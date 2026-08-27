#!/usr/bin/env python3
"""
Cloud version of the Walker Neighborhood Library (Houston Public Library) study room booking
automation. Runs on GitHub Actions on a nightly schedule instead of a local Mac.

Booking data lives in Supabase (table: library_bookings) instead of a local JSON file, so it can
be edited from the hosted web page at any time, from any device. Credentials (library card
number, PIN) come from environment variables (GitHub Secrets) — they are never stored in
Supabase, since the anon key used to read/write bookings is public-facing in the hosted page.

The library opens study room booking exactly 1 day ahead (e.g. a Saturday slot first becomes
bookable at 12:01 AM Friday). So target_date is the day you actually want to sit in the room —
this script works out on its own that it needs to fire the night before, and only acts on a
booking row when today is exactly one day before its target_date.
"""

import os
import re
import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
LIBRARY_CARD_NUMBER = os.environ["LIBRARY_CARD_NUMBER"]
LIBRARY_PIN = os.environ["LIBRARY_PIN"]

REST_URL = f"{SUPABASE_URL}/rest/v1/library_bookings"
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

BASE_URL = "https://calendar.houstonlibrary.org/reserve/spaces/walker"
STUDY_ROOM_GROUP_VALUE = "43296"   # "Reserve a free study room"
CAPACITY_1_2_VALUE = "1"           # "Space For 1-2 people"

CENTRAL_TZ = ZoneInfo("America/Chicago")

POSITIVE_CONFIRMATION_MARKERS = [
    "confirmed", "confirmation", "successfully booked", "booking is complete",
    "thank you for your reservation", "reservation confirmed",
]
NEGATIVE_CONFIRMATION_MARKERS = [
    "error", "unable to", "failed", "unavailable", "please correct",
    "something went wrong", "session has expired",
]
CAPTCHA_MARKERS = ["captcha", "recaptcha", "hcaptcha"]


def log(message: str) -> None:
    timestamp = datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{timestamp}] {message}", flush=True)


def fetch_bookings() -> list:
    resp = requests.get(REST_URL, headers=SUPABASE_HEADERS, params={"select": "*"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def update_booking(row_id: str, status: str, note: str) -> None:
    resp = requests.patch(
        REST_URL,
        headers=SUPABASE_HEADERS,
        params={"id": f"eq.{row_id}"},
        json={
            "status": status,
            "last_run_at": datetime.now(CENTRAL_TZ).isoformat(),
            "last_run_note": note,
        },
        timeout=15,
    )
    resp.raise_for_status()


def to_24h(time_str: str) -> str:
    """Convert '10:00 AM' -> '10:00' (24h, as required by <input type=time>)."""
    return datetime.strptime(time_str.strip(), "%I:%M %p").strftime("%H:%M")


def page_has_captcha(page) -> bool:
    try:
        text = page.content().lower()
    except Exception:
        return False
    return any(marker in text for marker in CAPTCHA_MARKERS)


def safe_filename_part(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")


def booking_file_tag(booking: dict) -> str:
    return safe_filename_part(f"{booking['label']}_{booking['from_time']}")


def click_and_wait(page, click_fn, timeout=10000, settle_ms=1500):
    """Click, then wait tolerantly for the page to settle. Some steps on this site don't fire a
    real navigation event (look AJAX-driven), so wrapping clicks in expect_navigation() caused
    false-negative timeouts on real, successful clicks in production. This waits for a load
    event if one happens, but doesn't treat its absence as failure."""
    click_fn()
    try:
        page.wait_for_load_state("load", timeout=timeout)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(settle_ms)


class BookingFailed(Exception):
    pass


def run_booking(page, booking: dict, date_tag: str) -> str:
    label = booking["label"]

    log(f"  [{label}] Navigating to search page")
    page.goto(BASE_URL, wait_until="load")

    if page_has_captcha(page):
        raise BookingFailed("CAPTCHA detected on search page — stopping (no auto-solve).")

    page.select_option("#s-lc-group", STUDY_ROOM_GROUP_VALUE)
    page.select_option("#s-lc-type", CAPACITY_1_2_VALUE)
    page.fill("#s-lc-date", booking["target_date"])
    page.fill("#s-lc-time-start", to_24h(booking["from_time"]))
    page.fill("#s-lc-time-end", to_24h(booking["until_time"]))

    log(f"  [{label}] Searching: {booking['target_date']} {booking['from_time']}-{booking['until_time']}")
    page.click("#s-lc-go")
    page.wait_for_load_state("load")
    page.wait_for_selector("#s-lc-eq-search-results", timeout=15000)

    if page_has_captcha(page):
        raise BookingFailed("CAPTCHA detected on results page — stopping (no auto-solve).")

    suggestions = page.query_selector_all("#s-lc-eq-search-results .s-lc-booking-suggestion")
    room_names = []
    suggestion_by_name = {}
    for suggestion in suggestions:
        heading = suggestion.query_selector(".s-lc-suggestion-heading")
        name = heading.inner_text().strip() if heading else ""
        room_names.append(name)
        if name.lower() not in suggestion_by_name:
            suggestion_by_name[name.lower()] = (suggestion, name)

    preferences = [p.strip() for p in booking["room_preference"].split(",") if p.strip()]
    target_suggestion = None
    matched_name = None
    for pref in preferences:
        hit = suggestion_by_name.get(pref.lower())
        if hit:
            target_suggestion, matched_name = hit
            break

    if target_suggestion is None:
        available = ", ".join(room_names) if room_names else "(no rooms available at all for this search)"
        raise BookingFailed(
            f"None of the preferred rooms ({', '.join(preferences)}) were available. "
            f"Available rooms for this search: {available}. No other substitute room was booked."
        )

    log(f"  [{label}] '{matched_name}' is available — clicking Book Now")
    book_button = target_suggestion.query_selector(".s-lc-suggestion-book-now")
    if book_button is None:
        raise BookingFailed(f"'{matched_name}' found in results but has no Book Now button (already booked?).")

    click_and_wait(page, book_button.click)

    if page_has_captcha(page):
        raise BookingFailed("CAPTCHA detected after Book Now — stopping (no auto-solve).")

    username_field = page.query_selector("#username")
    if username_field:
        log(f"  [{label}] Login prompt appeared — logging in")
        page.fill("#username", LIBRARY_CARD_NUMBER)
        page.fill("#password", LIBRARY_PIN)
        click_and_wait(page, lambda: page.click("#s-libapps-login-button"))

        if page.query_selector("#username"):
            raise BookingFailed("Login did not succeed — still on login page after submitting credentials.")

    if page_has_captcha(page):
        raise BookingFailed("CAPTCHA detected after login — stopping (no auto-solve).")

    try:
        page.wait_for_selector("#nick", timeout=15000)
    except PlaywrightTimeoutError:
        raise BookingFailed("Booking details form ('nick' field) did not appear after login/Book Now.")

    log(f"  [{label}] Filling booking form")
    page.fill("#nick", booking["attendee_name"])

    attendance_field = page.query_selector("#q2632") or page.query_selector(
        "xpath=//label[contains(., 'Estimated attendance')]/following::input[1]"
    )
    if attendance_field is None:
        raise BookingFailed("Could not find the 'Estimated attendance' field.")
    attendance_field.fill(str(booking["estimated_attendance"]))

    terms_checkbox = page.query_selector("#terms")
    if terms_checkbox is None:
        raise BookingFailed("Could not find the Terms & Conditions checkbox.")
    if not terms_checkbox.is_checked():
        terms_checkbox.check()

    if page_has_captcha(page):
        raise BookingFailed("CAPTCHA detected on booking form — stopping (no auto-solve).")

    log(f"  [{label}] Submitting booking (single attempt, no retry)")
    click_and_wait(page, lambda: page.click("#btn-form-submit"), settle_ms=2000)

    if page_has_captcha(page):
        raise BookingFailed("CAPTCHA detected after submit — stopping (no auto-solve).")

    body_text = page.inner_text("body").lower()
    negative_hit = next((m for m in NEGATIVE_CONFIRMATION_MARKERS if m in body_text), None)
    positive_hit = next((m for m in POSITIVE_CONFIRMATION_MARKERS if m in body_text), None)

    if negative_hit and not positive_hit:
        raise BookingFailed(f"Page showed an error/negative indicator after submit (matched: '{negative_hit}').")
    if not positive_hit:
        raise BookingFailed(
            "Could not positively confirm the booking succeeded (no known confirmation text found)."
        )

    return f"Booked '{matched_name}' for {booking['target_date']} {booking['from_time']}-{booking['until_time']}."


def process_booking(browser, booking: dict, today_str: str) -> None:
    label = booking["label"]

    if booking.get("status") == "success":
        log(f"[{label}] status already 'success' — skipping (safety check).")
        return

    # This check now runs every 5 minutes (see nightly.yml), so it's essential that a booking
    # only gets ONE real attempt per day even if that attempt failed (e.g. room genuinely
    # unavailable) — otherwise a failure would get silently retried every 5 minutes for the rest
    # of the day, hammering the real site and violating the one-attempt-per-run rule.
    last_run_at = booking.get("last_run_at")
    if last_run_at and last_run_at[:10] == today_str:
        log(f"[{label}] already attempted today ({last_run_at}) — skipping (no same-day retries).")
        return

    target_date = datetime.strptime(booking["target_date"], "%Y-%m-%d").date()
    fire_date = target_date - timedelta(days=1)
    fire_date_str = fire_date.isoformat()

    if fire_date_str != today_str:
        return

    log(f"[{label}] Today ({today_str}) is the day before target_date {booking['target_date']} — "
        f"the booking window just opened. Running booking flow.")
    context = browser.new_context()
    page = context.new_page()
    try:
        note = run_booking(page, booking, today_str)
        update_booking(booking["id"], "success", note)
        log(f"[{label}] SUCCESS — {note}")
    except BookingFailed as e:
        update_booking(booking["id"], "failed", str(e))
        log(f"[{label}] FAILED — {e}")
    except Exception as e:
        update_booking(booking["id"], "failed", f"Unexpected error: {e}")
        log(f"[{label}] FAILED (unexpected error) — {e}")
        log("  " + traceback.format_exc().replace("\n", "\n  "))
    finally:
        context.close()


def is_actionable(booking: dict, today_str: str) -> bool:
    if booking.get("status") == "success":
        return False
    last_run_at = booking.get("last_run_at")
    if last_run_at and last_run_at[:10] == today_str:
        return False
    target_date = datetime.strptime(booking["target_date"], "%Y-%m-%d").date()
    fire_date = target_date - timedelta(days=1)
    return fire_date.isoformat() == today_str


def main(check_only: bool = False):
    # Runs every 5 minutes (see nightly.yml) so GitHub's own schedule-trigger imprecision can
    # never cause a missed window — but that means the overwhelming majority of runs (~99%) have
    # nothing to do. Check that cheaply via the Supabase fetch alone, and only pay the cost of
    # installing/launching a real browser on the rare run that actually has a booking to attempt
    # (see --check-only below, used by nightly.yml to decide whether to even install Chromium).
    today_str = datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d")
    bookings = fetch_bookings()
    actionable = [b for b in bookings if is_actionable(b, today_str)]

    if check_only:
        print(f"actionable={'true' if actionable else 'false'}")
        return

    if not actionable:
        return

    log(f"=== Run started (today = {today_str} Central) ===")
    log(f"Fetched {len(bookings)} booking row(s) from Supabase — {len(actionable)} actionable.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for booking in actionable:
                process_booking(browser, booking, today_str)
        finally:
            browser.close()

    log("=== Run finished ===")


if __name__ == "__main__":
    main(check_only="--check-only" in sys.argv)
