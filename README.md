# Walker Library Booking — Cloud Version

Cloud version of the study room booking automation. Runs on GitHub Actions every night instead
of relying on a Mac being awake. Booking data lives in Supabase; credentials live only in GitHub
Secrets.

- **Editor page**: hosted via GitHub Pages — a real URL you can open from any device
- **Automation**: `.github/workflows/nightly.yml`, a scheduled GitHub Actions workflow
- **Data**: Supabase table `library_bookings` (project: LW CPA Apps)

## Why an external scheduler (cron-job.org), not GitHub's own `schedule:` trigger

GitHub's `schedule:` trigger is documented as best-effort, not precise. We tried it at several
intervals, ending with every 5 minutes all day. It initially looked fine, but a two-week gap
analysis of actual run timestamps (Aug 26 – Sep 8) showed it was *never* really running every 5
minutes — real gaps between runs were consistently 2-5+ hours, every single night. That silently
caused a missed booking window on 2026-09-08: the check that should have caught a newly-opened
slot didn't run until 4:44 AM, by which time the rooms were already taken.

The fix: a free external cron service, [cron-job.org](https://cron-job.org), calls this
workflow's `workflow_dispatch` API endpoint directly — every 5 minutes, 12:01-2:56 AM, in the
`America/Chicago` timezone. Because the job is scheduled in that named timezone rather than UTC,
it also self-adjusts for Daylight Saving Time automatically — no twice-yearly manual edit needed.

The workflow itself stays cheap regardless of trigger source: `booking_automation.py
--check-only` does a lightweight Supabase read and exits in a couple of seconds when nothing is
due, which is true for the vast majority of runs — Chromium only gets installed and a real
browser only gets launched on the rare run that actually has a booking to attempt. Each booking
still only gets one real attempt per day no matter how many times the check runs (enforced in
the script itself).

## Testing

Go to the repo's **Actions** tab → **"Nightly library booking check"** → **"Run workflow"** to
trigger it manually anytime. cron-job.org's dashboard (cron-job.org → your account → this job)
also shows execution history and lets you trigger a test run from there.

## Security notes

- The editor page uses Supabase's public "anon" key, scoped by row-level security to only the
  `library_bookings` table — it cannot read or write anything else in the Supabase project.
- Library card number and PIN are GitHub Secrets, used only inside the Actions runner. They are
  never sent to Supabase or exposed in the editor page.
- The editor page itself has no login — anyone with the URL can view/edit bookings (not
  credentials). Keep the URL private, same trust model as the original local version.
