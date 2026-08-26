# Walker Library Booking — Cloud Version

Cloud version of the study room booking automation. Runs on GitHub Actions every night instead
of relying on a Mac being awake. Booking data lives in Supabase; credentials live only in GitHub
Secrets.

- **Editor page**: hosted via GitHub Pages — a real URL you can open from any device
- **Automation**: `.github/workflows/nightly.yml`, a scheduled GitHub Actions workflow
- **Data**: Supabase table `library_bookings` (project: LW CPA Apps)

## Daylight Saving Time

GitHub Actions cron schedules are UTC-only and do not auto-adjust for DST. The workflow has
**two** scheduled triggers (00:01 and 00:03 AM Central — see "Two scheduled triggers" below),
both currently set for **Central Daylight Time (CDT, UTC-5)**. When Central time changes, both
lines need the same edit:

- **Fall back to CST (UTC-6)**, typically early November: edit `.github/workflows/nightly.yml`,
  change both `cron: "1 5 * * *"` → `"1 6 * * *"` and `cron: "3 5 * * *"` → `"3 6 * * *"`.
- **Spring forward to CDT (UTC-5)**, typically mid-March: change both back to `"1 5 * * *"` and
  `"3 5 * * *"`.

Commit and push the change — no other steps needed.

## Two scheduled triggers

GitHub documents that scheduled workflows can be delayed, and calls out the top of the hour as
the worst-case congestion window — exactly where a 00:01 AM trigger sits. So the workflow fires
twice, two minutes apart (00:01 and 00:03 Central), as a safety net. This is safe: the script
skips any booking already marked `"success"`, so if the first trigger ran fine, the second is a
harmless no-op. It only does real work if the first one got delayed or dropped — which is exactly
what happened the first night this went live (00:01 didn't fire for ~18 minutes; a manual trigger
was used that night before this backup schedule existed).

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
