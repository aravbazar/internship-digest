# Daily Internship Digest

Emails the tech internships that appeared on the community GitHub lists in the
last 24 hours. Runs on GitHub Actions - no laptop required.

**Sources:** `SimplifyJobs/Summer2027-Internships`, `vanshb03/Summer2027-Internships`
**Delivery:** 7:45 AM CT daily
**Coverage:** all tech categories - SWE, Data/AI/ML, Quant, Hardware, Security, Product

---

## Remaining setup (~5 minutes)

The code is already here. Three steps left, all requiring your credentials.

### 1. Generate a Gmail app password

A regular Gmail password will not work - Google blocks SMTP logins with it.

1. Turn on 2-Step Verification at https://myaccount.google.com/security
   (required; the app-password page will not appear without it)
2. Go to https://myaccount.google.com/apppasswords
3. Name it `internship-digest`, create it, copy the 16-character string

### 2. Add three repo secrets

Settings -> Secrets and variables -> Actions -> New repository secret

| Name | Value |
|---|---|
| `SMTP_USER` | your Gmail address |
| `SMTP_APP_PASSWORD` | the 16-character app password from step 1 |
| `MAIL_TO` | where the digest goes (can be the same address) |

### 3. Seed the state

Actions -> Daily Internship Digest -> Run workflow, tick **seed_only**, run it.

This records the ~2,000 currently-live roles as "already seen" so your first
real digest contains only genuinely new postings instead of a 2,000-row email.

Then run it once more with `seed_only` unticked. You should get an email within
a minute - probably "nothing new," which is the correct result immediately
after seeding. After that it runs itself.

---

## How it works

1. Fetches `.github/scripts/listings.json` from each source repo - structured
   JSON, not scraped README markdown, so it does not break when the maintainers
   restyle their tables.
2. Filters to `active` and `is_visible` roles. Simplify's file carries ~14,800
   historical entries; roughly 2,000 are live at any time.
3. Dedupes on normalized company + title, so a role listed in both repos emails
   once rather than twice.
4. Diffs against `state/seen.json`, emails the difference, commits the updated
   state back to this repo.

State is a union, not a replacement - a role that briefly flips inactive and
returns will not be re-reported as new.

## Tuning

- **Time:** edit the `cron` line in the workflow. It is UTC. `45 12` = 7:45 AM
  CDT. In November, change to `45 13` to hold 7:45 AM local through CST.
- **Add a source:** drop another raw `listings.json` URL into the `SOURCES`
  dict in `digest.py`. Same schema means no other changes needed.
- **Narrow the roles:** `CATEGORY_RULES` drives grouping. To filter rather than
  just group, add a check inside `collect()`.

## If it goes quiet

GitHub emails you automatically when a workflow run fails, so silence means
either no new roles or no run at all. Check the Actions tab.

One caveat: GitHub disables scheduled workflows in repos with no activity for
60 days. The daily state commit counts as activity, so this should not trigger -
but if the digest ever stops cold, check that first.

## Known gap

These repos aggregate public postings. UT-specific pipelines and anything that
only appears on Handshake will not show up here. Worth checking those separately
during peak season.
