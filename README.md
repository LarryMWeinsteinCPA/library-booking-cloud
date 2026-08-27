# Walker Library Booking — Cloud Version

Cloud version of the study room booking automation. Runs on GitHub Actions every night instead
of relying on a Mac being awake. Booking data lives in Supabase; credentials live only in GitHub
Secrets.

- **Editor page**: hosted via GitHub Pages — a real URL you can open from any device
- **Automation**: `.github/workflows/nightly.yml`, a scheduled GitHub Actions workflow
- **Data**: Supabase table `library_bookings` (project: LW CPA Apps)

## Why it runs every 5 minutes, all day

GitHub explicitly documents that scheduled workflow triggers are best-effort, not precise — and
specifically calls out the top of the hour (like 12:00/12:01 AM) as their worst congestion
window. In practice this bit us twice: the very first scheduled run fired 22 minutes late, and
the night after that, it didn't fire at all.

Rather than try to out-guess GitHub's scheduler by picking a "safer" minute, the workflow just
runs every 5 minutes, all day, every day (GitHub's shortest allowed interval). This means no
single missed or delayed trigger can cause a real miss — the next check 5 minutes later catches
it. It's also free (GitHub Actions minutes are unlimited on public repos) and cheap in practice:
`booking_automation.py --check-only` does a lightweight Supabase read and exits in a couple of
seconds when nothing is due, which is true for the vast majority of these runs — Chromium only
gets installed and a real browser only gets launched on the rare run that actually has a booking
to attempt. Each booking still only gets one real attempt per day no matter how many times the
check runs (enforced in the script, not just by the schedule).

**Bonus:** this also eliminates the twice-yearly Daylight Saving Time cron edit that a
specific-hour schedule would have needed — there's no particular hour to get wrong anymore.

## Testing

Go to the repo's **Actions** tab → **"Nightly library booking check"** → **"Run workflow"** to
trigger it manually anytime, without waiting for the schedule.

## Security notes

- The editor page uses Supabase's public "anon" key, scoped by row-level security to only the
  `library_bookings` table — it cannot read or write anything else in the Supabase project.
- Library card number and PIN are GitHub Secrets, used only inside the Actions runner. They are
  never sent to Supabase or exposed in the editor page.
- The editor page itself has no login — anyone with the URL can view/edit bookings (not
  credentials). Keep the URL private, same trust model as the original local version.
