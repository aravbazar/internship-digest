#!/usr/bin/env python3
"""
Daily internship digest.

Pulls structured listings from community internship repos, diffs against the
roles seen on previous runs, and emails only what's new.

State lives in state/seen.json and is committed back to the repo by the
workflow, so "new" survives across runs.

Stdlib only - no pip install, so CI cold-start is a few seconds.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

SOURCES = {
    "Simplify / Pitt CSC": (
        "https://raw.githubusercontent.com/SimplifyJobs/"
        "Summer2027-Internships/dev/.github/scripts/listings.json"
    ),
    "vanshb03 / CSCareers": (
        "https://raw.githubusercontent.com/vanshb03/"
        "Summer2027-Internships/dev/.github/scripts/listings.json"
    ),
    # Add more raw listings.json URLs here. Same schema = zero code changes.
}

STATE_PATH = Path("state/seen.json")
MAX_ROLES_IN_EMAIL = 100
TIMEZONE = timezone(timedelta(hours=-5))  # US Central, for display only

# Title keyword -> category label. First match wins, so order matters.
CATEGORY_RULES = [
    ("Quant", ("quant", "trading", "trader", "systematic")),
    ("Data / AI / ML", ("data", "machine learning", " ml ", "ai ", "analytics",
                        "scientist", "nlp", "deep learning", "research")),
    ("Hardware", ("hardware", "electrical", "asic", "fpga", "embedded",
                  "silicon", "chip", "rf ", "mechanical")),
    ("Security", ("security", "cyber", "infosec", "appsec")),
    ("Product / Design", ("product manager", "product management", "apm",
                          "designer", "ux ", "ui ")),
    ("Software Engineering", ("software", "swe", "engineer", "developer",
                              "backend", "frontend", "full stack", "full-stack",
                              "devops", "sre", "platform", "infrastructure",
                              "mobile", "ios", "android")),
]

CATEGORY_ORDER = [
    "Software Engineering",
    "Data / AI / ML",
    "Quant",
    "Security",
    "Hardware",
    "Product / Design",
    "Other Tech",
]


# --------------------------------------------------------------------------
# FETCH
# --------------------------------------------------------------------------

def fetch_json(url: str) -> list[dict]:
    """GET a raw JSON file. Raises on failure so the workflow goes red."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "internship-digest/1.0"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array from {url}")
    return data


def normalize(text: str) -> str:
    """Collapse a string to a comparable token."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def role_key(listing: dict) -> str:
    """
    Dedupe key. Deliberately company+title rather than the repo's own id -
    the same role appears in both repos under different ids, and we only
    want to be told about it once.
    """
    return f"{normalize(listing.get('company_name'))}|{normalize(listing.get('title'))}"


def categorize(title: str) -> str:
    lowered = f" {(title or '').lower()} "
    for label, keywords in CATEGORY_RULES:
        if any(kw in lowered for kw in keywords):
            return label
    return "Other Tech"


def collect() -> dict[str, dict]:
    """Fetch every source, filter to live roles, dedupe. Returns key -> role."""
    roles: dict[str, dict] = {}
    for source_name, url in SOURCES.items():
        try:
            listings = fetch_json(url)
        except (urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            # One dead source shouldn't kill the whole digest.
            print(f"WARN: {source_name} failed: {exc}", file=sys.stderr)
            continue

        kept = 0
        for item in listings:
            # Defaults are permissive: if a repo drops a field, keep the role
            # rather than silently filtering out everything.
            if not item.get("active", True):
                continue
            if not item.get("is_visible", True):
                continue
            if not item.get("title") or not item.get("company_name"):
                continue

            key = role_key(item)
            if key in roles:
                # Already have it from an earlier source; keep whichever has
                # a usable apply link.
                if not roles[key].get("url") and item.get("url"):
                    roles[key]["url"] = item["url"]
                continue

            roles[key] = {
                "company": item.get("company_name", "").strip(),
                "title": item.get("title", "").strip(),
                "locations": item.get("locations") or [],
                "url": item.get("url") or item.get("company_url") or "",
                "date_posted": item.get("date_posted") or 0,
                "terms": item.get("terms") or [],
                # Newer schemas carry this; older ones don't. Read defensively.
                "sponsorship": item.get("sponsorship") or "",
                "source": source_name,
                "category": categorize(item.get("title", "")),
            }
            kept += 1

        print(f"{source_name}: {len(listings)} listings, {kept} new to this run")

    return roles


# --------------------------------------------------------------------------
# STATE
# --------------------------------------------------------------------------

def load_seen() -> set[str] | None:
    """Returns None if we've never run before (triggers seed mode)."""
    if not STATE_PATH.exists():
        return None
    try:
        payload = json.loads(STATE_PATH.read_text())
        return set(payload.get("keys", []))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARN: unreadable state file ({exc}) - treating as first run",
              file=sys.stderr)
        return None


def save_seen(keys: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(
        {
            "last_run": datetime.now(timezone.utc).isoformat(),
            "count": len(keys),
            "keys": sorted(keys),
        },
        indent=1,
    ))


# --------------------------------------------------------------------------
# RENDER
# --------------------------------------------------------------------------

def format_date(ts: int) -> str:
    if not ts:
        return "\u2014"
    try:
        return datetime.fromtimestamp(int(ts), TIMEZONE).strftime("%b %-d")
    except (ValueError, OSError):
        return "\u2014"


def format_locations(locations: list[str]) -> str:
    if not locations:
        return "\u2014"
    if len(locations) <= 2:
        return " \u00b7 ".join(locations)
    return f"{locations[0]} +{len(locations) - 1} more"


def build_html(new_roles: list[dict], total_tracked: int) -> str:
    today = datetime.now(TIMEZONE).strftime("%A, %B %-d")

    if not new_roles:
        return f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
color:#1a1a1a;max-width:680px;margin:0 auto;padding:24px">
<h2 style="margin:0 0 4px">Internship digest \u2014 {today}</h2>
<p style="color:#666;margin:0 0 20px">No new postings since yesterday.</p>
<p style="color:#888;font-size:13px">Tracking {total_tracked} live roles across
{len(SOURCES)} repos. The job ran fine \u2014 quiet days are normal, especially on
weekends.</p></body></html>"""

    grouped: dict[str, list[dict]] = {}
    for role in new_roles:
        grouped.setdefault(role["category"], []).append(role)

    sections = []
    for category in CATEGORY_ORDER:
        bucket = grouped.get(category)
        if not bucket:
            continue
        bucket.sort(key=lambda r: r["date_posted"], reverse=True)

        rows = []
        for role in bucket:
            link = role["url"]
            title_cell = (
                f'<a href="{link}" style="color:#0645ad;text-decoration:none">'
                f'{role["title"]}</a>' if link else role["title"]
            )
            terms = ", ".join(role["terms"]) if role["terms"] else "\u2014"
            # "Other" is the schema's default and appears on ~everything;
            # only surface genuinely restrictive flags.
            sponsor = role["sponsorship"]
            if sponsor.strip().lower() in ("", "other", "unknown"):
                sponsor = ""
            sponsor_flag = (
                f'<div style="color:#b45309;font-size:12px;margin-top:2px">'
                f'{sponsor}</div>' if sponsor else ""
            )
            rows.append(f"""<tr style="border-bottom:1px solid #eee">
<td style="padding:10px 8px 10px 0;vertical-align:top">
  <strong>{role["company"]}</strong>
  <div style="font-size:14px;margin-top:2px">{title_cell}</div>
  {sponsor_flag}
</td>
<td style="padding:10px 8px;vertical-align:top;font-size:13px;color:#555;white-space:nowrap">
  {format_locations(role["locations"])}
</td>
<td style="padding:10px 0 10px 8px;vertical-align:top;font-size:13px;color:#555;white-space:nowrap">
  {terms}<br><span style="color:#999">{format_date(role["date_posted"])}</span>
</td>
</tr>""")

        sections.append(f"""<h3 style="margin:28px 0 8px;font-size:15px;
text-transform:uppercase;letter-spacing:.04em;color:#444">
{category} <span style="color:#999;font-weight:normal">({len(bucket)})</span></h3>
<table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>""")

    truncated = ""
    if len(new_roles) >= MAX_ROLES_IN_EMAIL:
        truncated = (f'<p style="color:#b45309;font-size:13px">Showing the '
                     f'{MAX_ROLES_IN_EMAIL} most recent of a larger batch.</p>')

    return f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
color:#1a1a1a;max-width:680px;margin:0 auto;padding:24px">
<h2 style="margin:0 0 4px">Internship digest \u2014 {today}</h2>
<p style="color:#666;margin:0 0 4px"><strong>{len(new_roles)} new</strong>
since yesterday \u00b7 {total_tracked} live roles tracked</p>
{truncated}
{"".join(sections)}
<p style="color:#999;font-size:12px;margin-top:32px;border-top:1px solid #eee;
padding-top:12px">Rolling review \u2014 same-day applications get seen first.</p>
</body></html>"""


def build_text(new_roles: list[dict], total_tracked: int) -> str:
    if not new_roles:
        return f"No new postings. Tracking {total_tracked} live roles."
    lines = [f"{len(new_roles)} new postings ({total_tracked} tracked)", ""]
    for role in new_roles:
        lines.append(f"[{role['category']}] {role['company']} \u2014 {role['title']}")
        lines.append(f"  {format_locations(role['locations'])} \u00b7 "
                     f"{format_date(role['date_posted'])}")
        if role["url"]:
            lines.append(f"  {role['url']}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# SEND
# --------------------------------------------------------------------------

def send_email(subject: str, html: str, text: str) -> None:
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_APP_PASSWORD"]
    recipient = os.environ.get("MAIL_TO", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(user, password)
        server.send_message(msg)
    print(f"Sent to {recipient}")


# --------------------------------------------------------------------------

def main() -> int:
    roles = collect()
    if not roles:
        print("ERROR: every source failed", file=sys.stderr)
        return 1

    current_keys = set(roles)
    seen = load_seen()

    # First run (or wiped state): record everything, don't email 500 roles.
    if seen is None or os.environ.get("SEED_ONLY") == "true":
        save_seen(current_keys)
        print(f"Seeded state with {len(current_keys)} roles. No email sent.")
        return 0

    new_keys = current_keys - seen
    new_roles = sorted(
        (roles[k] for k in new_keys),
        key=lambda r: r["date_posted"],
        reverse=True,
    )[:MAX_ROLES_IN_EMAIL]

    count = len(new_keys)
    subject = (f"{count} new internship{'s' if count != 1 else ''} \u2014 "
               f"{datetime.now(TIMEZONE).strftime('%b %-d')}"
               ) if count else "Internship digest \u2014 nothing new"

    send_email(subject, build_html(new_roles, len(current_keys)),
               build_text(new_roles, len(current_keys)))

    # Union, not replacement: a role that briefly goes inactive and comes back
    # shouldn't get re-reported as new.
    save_seen(seen | current_keys)
    print(f"{count} new roles reported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
