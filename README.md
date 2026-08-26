# Walker Library Booking — Cloud Version

Cloud version of the study room booking automation. Runs on GitHub Actions every night instead
of relying on a Mac being awake. Booking data lives in Supabase; credentials live only in GitHub
Secrets.

- **Editor page**: hosted via GitHub Pages — a real URL you can open from any device
- **Automation**: `.github/workflows/nightly.yml`, a scheduled GitHub Actions workflow
- **Data**: Supabase table `library_bookings` (project: LW CPA Apps)

## Daylight Saving Time

GitHub Actions cron schedules are UTC-only and do not auto-adjust for DST. The workflow is set
for **00:01 AM Central Daylight Time (CDT, UTC-5)**. When Central time changes:

- **Fall back to CST (UTC-6)**, typically early November: edit `.github/workflows/nightly.yml`,
  change `cron: "1 5 * * *"` to `cron: "1 6 * * *"`.
- **Spring forward to CDT (UTC-5)**, typically mid-March: change it back to `"1 5 * * *"`.

Commit and push the change — no other steps needed.

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
