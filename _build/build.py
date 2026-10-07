#!/usr/bin/env python3
"""
v2 of the Under Contract page builder (sample). Adds:
  - completed phases collapse into one line
  - per-date "Add to calendar" (Google + Apple/Outlook .ics)
  - one subscribe-able calendar feed per deal (calendar.ics)
  - live closing countdown
  - "?" explainer on each milestone
  - sticky Text / Call / Email bar on phones

Usage (from the repo root):
    python3 _build/build.py <slug>/data.json <slug>/ --base-url https://dunnrealestate.github.io/deals/<slug>/

Writes out_dir/index.html, out_dir/calendar.ics, out_dir/cal/<n>.ics

New optional data fields (on top of the v1 schema):
  "closing_date": "2026-10-16"                       # drives the countdown
  milestone "start": "2026-10-16T09:00" or "2026-10-16"  # makes it a calendar event
  milestone "minutes": 60                             # event length (timed events), default 60
  milestone "location": "..."                         # event location
  milestone "info": "..."                             # override the default explainer
"""
import base64
import html
import json
import sys
import urllib.parse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
TZID = "America/Chicago"

STATUS_TEXT = {"done": "Complete", "in_progress": "In progress",
               "scheduled": "Scheduled", "not_started": "Coming up"}

# Plain-English explainers, keyed by milestone label. Override per milestone with "info".
EXPLAINERS = {
    # buyer
    "Offer accepted": "Both sides signed the contract. Every other deadline counts from this day.",
    "Earnest money delivered": "Your good-faith deposit. The title company holds it, and it goes toward your costs at closing.",
    "Inspection period": "Your window to have the house inspected and ask the seller for repairs or credits.",
    "Inspections": "Your inspector goes through the house top to bottom so you know what you're buying.",
    "Inspection resolution signed": "The signed agreement on which repairs or credits the seller is giving you.",
    "Seller's agreed repairs completed": "The seller finishing the repairs from the inspection resolution. We confirm them at the walkthrough.",
    "Homeowners insurance secured": "Your lender won't fund the loan until a policy is in place starting on closing day.",
    "Appraisal": "An independent check that the house is worth what's being paid for it. When it's waived, the lender didn't require one.",
    "Loan approval": "Underwriting reviewed your file and approved the loan, usually with a few small conditions left.",
    "Title commitment": "The title company's report confirming the seller can legally hand the house over, and what gets paid off at closing.",
    "Clear to close": "The lender's final sign-off. Every condition is met and the loan is ready to fund.",
    "Review your closing disclosure": "Your final loan terms and cash to close. You'll get it at least 3 business days before closing.",
    "Utilities and mail forwarding set up": "Power, gas, water, trash, and internet in your name so the house works on day one.",
    "Utilities set up in your name": "Power, gas, water, trash, and internet in your name so the house works on day one.",
    "Final walkthrough": "A last look to make sure the house is in the shape you agreed to and any repairs are done.",
    "Closing": "You sign the paperwork at the title company. Bring a photo ID.",
    "Keys & possession": "Once the loan funds, the house is yours and you get the keys.",
    # seller
    "Buyer's earnest money deposited": "The buyer's good-faith deposit, held by the title company. It shows they're committed.",
    "Buyer's inspections": "The buyer's inspector goes through the house. You don't need to be there.",
    "Agreed repairs completed": "The repairs you agreed to in the inspection resolution. Keep receipts, the buyer may ask for them.",
    "Buyer's loan approval": "The buyer's lender approving their loan. Nothing for you to do here.",
    "Utilities transferred out of your name": "Set shutoff or transfer for closing day, not before, so the walkthrough has power and water.",
    "Move out": "Everything that isn't staying with the house needs to be out before the buyer's walkthrough.",
    "Buyer's final walkthrough": "The buyer's last look to confirm the house is in the agreed condition.",
    "Closing & possession": "You sign at the title company, the buyer's loan funds, and the keys change hands.",
}


def esc(s):
    return html.escape(str(s or ""), quote=True)


def b64_of(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def status_of(m):
    s = m.get("status", "not_started")
    return s if s in STATUS_TEXT else "not_started"


def all_milestones(phases):
    return [m for p in phases for m in p.get("milestones", [])]


# ---------- calendar ----------

def event_times(m):
    """Return (start_dt, end_dt, all_day) or None."""
    start = m.get("start")
    if not start:
        return None
    if "T" in start:
        s = datetime.fromisoformat(start)
        return s, s + timedelta(minutes=int(m.get("minutes", 60))), False
    d = datetime.fromisoformat(start)
    return d, d + timedelta(days=1), True


VTIMEZONE = [
    "BEGIN:VTIMEZONE", "TZID:America/Chicago",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0600", "TZOFFSETTO:-0500", "TZNAME:CDT",
    "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:-0500", "TZOFFSETTO:-0600", "TZNAME:CST",
    "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
    "END:VTIMEZONE",
]


def slugify(t):
    return re.sub(r"[^a-z0-9]+", "-", str(t).lower()).strip("-")


def ics_escape(t):
    return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def vevent(m, data, uid):
    s, e, all_day = event_times(m)
    title = f'{m["label"]} ({data["property_address"].split(",")[0]})'
    desc = m.get("note", "") or ""
    lines = ["BEGIN:VEVENT", f"UID:{uid}@dunnrealestate",
             "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")]
    if all_day:
        lines += [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{e:%Y%m%d}"]
    else:
        lines += [f"DTSTART;TZID={TZID}:{s:%Y%m%dT%H%M%S}", f"DTEND;TZID={TZID}:{e:%Y%m%dT%H%M%S}"]
    lines += [f"SUMMARY:{ics_escape(title)}"]
    if desc:
        lines.append(f"DESCRIPTION:{ics_escape(desc)}")
    if m.get("location"):
        lines.append(f"LOCATION:{ics_escape(m['location'])}")
    lines.append("END:VEVENT")
    return lines


def ics_doc(events_lines, name):
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Dunn Real Estate//Under Contract//EN",
           "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(name)}",
           f"X-WR-TIMEZONE:{TZID}", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
           "X-PUBLISHED-TTL:PT6H"] + VTIMEZONE
    for ev in events_lines:
        out += ev
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def google_link(m, data):
    s, e, all_day = event_times(m)
    if all_day:
        dates = f"{s:%Y%m%d}/{e:%Y%m%d}"
    else:
        dates = f"{s:%Y%m%dT%H%M%S}/{e:%Y%m%dT%H%M%S}"
    q = {"action": "TEMPLATE", "text": f'{m["label"]} ({data["property_address"].split(",")[0]})',
         "dates": dates, "ctz": TZID, "details": m.get("note", "")}
    if m.get("location"):
        q["location"] = m["location"]
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(q)


# ---------- rendering ----------

def render_keydates(key_dates, closing_date):
    cells = []
    for k in key_dates:
        sub = f'<p class="keydate-sub">{esc(k["sub"])}</p>' if k.get("sub") else ""
        cells.append(f'<div class="keydate"><p class="keydate-label">{esc(k.get("label"))}</p>'
                     f'<p class="keydate-value">{esc(k.get("value"))}</p>{sub}</div>')
    if closing_date:
        cells.insert(0, f'<div class="keydate keydate-countdown" id="countdown" data-date="{esc(closing_date)}">'
                        f'<p class="keydate-label">Countdown</p><p class="keydate-value">&nbsp;</p>'
                        f'<p class="keydate-sub">&nbsp;</p></div>')
    return f'<div class="keydates">{"".join(cells)}</div>' if cells else ""


def render_calsub(base_url):
    if not base_url:
        return ""
    feed = base_url.rstrip("/") + "/calendar.ics"
    webcal = "webcal://" + feed.split("://", 1)[1]
    gsub = "https://calendar.google.com/calendar/r?cid=" + urllib.parse.quote(webcal, safe="")
    return ('<div class="cal-sub"><p class="cal-sub-text">Put these dates in your calendar. They update automatically when I update this page.</p>'
            f'<div class="cal-sub-btns"><a class="btn btn-solid" href="{esc(webcal)}">Add to Apple / Outlook</a>'
            f'<a class="btn" href="{esc(gsub)}" target="_blank" rel="noopener">Add to Google Calendar</a></div></div>')


def render_progress(phases):
    ms = all_milestones(phases)
    if not ms:
        return ""
    done = sum(1 for m in ms if status_of(m) == "done")
    pct = round(100 * done / len(ms))
    nxt = None
    for wanted in ("in_progress", "scheduled", "not_started"):
        nxt = next((m for m in ms if status_of(m) == wanted), None)
        if nxt:
            break
    next_html = ""
    if nxt:
        label = "Happening now" if status_of(nxt) == "in_progress" else "Next up"
        note = f'<p class="nextup-note">{esc(nxt["note"])}</p>' if nxt.get("note") else ""
        next_html = (f'<div class="nextup"><p class="nextup-label">{label}</p>'
                     f'<p class="nextup-title">{esc(nxt.get("label"))}</p>'
                     f'<p class="nextup-when">{esc(nxt.get("date"))}</p>{note}</div>')
    return (f'<div class="progress-wrap"><div class="progress-head">'
            f'<span><strong>{done} of {len(ms)}</strong> steps complete</span><span>{pct}%</span></div>'
            f'<div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>'
            f'{next_html}</div>')


def render_milestone(m, data, idx, cal_links):
    s = status_of(m)
    note = f'<div class="milestone-note">{esc(m["note"])}</div>' if m.get("note") else ""
    info = m.get("info") or EXPLAINERS.get(m.get("label", ""), "")
    info_btn = (f'<button class="info-btn" type="button" aria-label="What is this?" aria-expanded="false">?</button>'
                if info else "")
    info_html = f'<div class="info-text">{esc(info)}</div>' if info else ""
    add = ""
    if s != "done" and idx in cal_links:
        g, f = cal_links[idx]
        add = (f'<div class="add-cal"><a href="{esc(g)}" target="_blank" rel="noopener">+ Google Calendar</a>'
               f'<a href="{esc(f)}">+ Apple / Outlook</a></div>')
    return (f'<div class="milestone {s}"><span class="marker"></span>'
            f'<div class="milestone-row"><div class="milestone-label">{esc(m.get("label"))}'
            f'<span class="status-chip">{STATUS_TEXT[s]}</span>{info_btn}</div>'
            f'<div class="milestone-date">{esc(m.get("date"))}</div></div>{note}{info_html}{add}</div>')


def render_phases(phases, data, cal_links):
    blocks, idx = [], 0
    for phase in phases:
        rows = []
        for m in phase.get("milestones", []):
            rows.append(render_milestone(m, data, idx, cal_links))
            idx += 1
        ms = phase.get("milestones", [])
        body = f'<div class="milestones">{"".join(rows)}</div>'
        if ms and all(status_of(m) == "done" for m in ms):
            blocks.append(
                f'<details class="phase-done"><summary><span class="phase-title">{esc(phase.get("name"))}</span>'
                f'<span class="done-summary">All {len(ms)} done</span>'
                f'<span class="done-toggle"><span class="show">Show</span><span class="hide">Hide</span></span>'
                f'</summary>{body}</details>')
        else:
            blocks.append(f'<div class="phase"><div class="phase-title">{esc(phase.get("name"))}</div>{body}</div>')
    return "".join(blocks)


def render_checklist(title, items):
    if not items:
        return ""
    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
    return f'<div class="checklist"><h2>{esc(title)}</h2><ul>{lis}</ul></div>'


def render_team(team):
    if not team:
        return ""
    cards = []
    for t in team:
        contact = f'<div class="team-contact">{esc(t["contact"])}</div>' if t.get("contact") else ""
        cards.append(f'<div class="team-card"><div class="team-role">{esc(t.get("role"))}</div>'
                     f'<div class="team-name">{esc(t.get("name"))}</div>{contact}</div>')
    return f'<div class="team"><h2>Who\'s Involved</h2><div class="team-grid">{"".join(cards)}</div></div>'


def render_vendors(vendors):
    if not vendors:
        return ""
    items = []
    for v in vendors:
        contact = f'<div>{esc(v["contact"])}</div>' if v.get("contact") else ""
        name = esc(v.get("name"))
        if v.get("url"):
            name = f'<a href="{esc(v["url"])}" target="_blank" rel="noopener">{name}</a>'
        items.append(f'<div class="footer-vendor"><div class="vendor-role">{esc(v.get("role"))}</div>'
                     f'<div class="vendor-name">{name}</div>{contact}</div>')
    return ('<div class="footer-vendors"><p class="footer-vendors-label">Recommended Vendors</p>'
            f'<div class="footer-vendors-list">{"".join(items)}</div></div>')


def render_contact_bar(phone, email):
    digits = "".join(c for c in (phone or "") if c.isdigit())
    links = []
    if digits:
        links += [f'<a href="sms:+1{digits}">Text Jared</a>', f'<a href="tel:+1{digits}">Call</a>']
    links.append(f'<a href="mailto:{esc(email)}">Email</a>')
    return f'<nav class="contact-bar">{"".join(links)}</nav>'


def build(data, out_dir, base_url=""):
    out_dir = Path(out_dir)
    (out_dir / "cal").mkdir(parents=True, exist_ok=True)
    phases = data.get("phases", [])
    ms = all_milestones(phases)

    # calendar files
    feed_events, cal_links = [], {}
    for i, m in enumerate(ms):
        if not event_times(m):
            continue
        # UID from deal folder + label, so a moved date updates the same event instead of adding a new one
        key = slugify(m["label"])
        ev = vevent(m, data, f"{Path(out_dir).name}-{key}")
        feed_events.append(ev)
        (out_dir / "cal" / f"{key}.ics").write_text(ics_doc([ev], m["label"]))
        cal_links[i] = (google_link(m, data), f"cal/{key}.ics")
    street = data["property_address"].split(",")[0]
    (out_dir / "calendar.ics").write_text(ics_doc(feed_events, f"{street} closing timeline"))

    template = (ASSETS_DIR / "template.html").read_text()
    side = data.get("side", "seller")
    phone = data.get("agent_phone", "")
    intro = data.get("intro_text", "")
    notes = data.get("agent_notes", "")
    email = data.get("agent_email", "jared@jareddunn.com")
    rep = {
        "{{LOGO_WORDMARK_B64}}": b64_of(ASSETS_DIR / "dunn-logo-wordmark-v2.png"),
        "{{LOGO_ICON_B64}}": b64_of(ASSETS_DIR / "dunn-logo-icon-v2.png"),
        "{{EYEBROW}}": "Under Contract | Seller" if side == "seller" else "Under Contract | Buyer",
        "{{PROPERTY_ADDRESS}}": esc(data.get("property_address")),
        "{{CLIENT_NAMES}}": esc(data.get("client_names")),
        "{{GENERATED_DATE}}": esc(data.get("generated_date")),
        "{{INTRO_HTML}}": f'<p class="intro">{esc(intro)}</p>' if intro else "",
        "{{KEYDATES_HTML}}": render_keydates(data.get("key_dates", []), data.get("closing_date")),
        "{{CALSUB_HTML}}": render_calsub(base_url),
        "{{PROGRESS_HTML}}": render_progress(phases),
        "{{PHASES_HTML}}": render_phases(phases, data, cal_links),
        "{{AGENT_NOTES_HTML}}": ('<div class="agent-notes"><p class="agent-notes-label">Notes from Jared</p>'
                                 f'<p class="agent-notes-text">{esc(notes)}</p></div>' if notes else ""),
        "{{CHECKLIST_HTML}}": render_checklist(data.get("checklist_title", "Before Closing Day"),
                                               data.get("checklist_items", [])),
        "{{TEAM_HTML}}": render_team(data.get("team", [])),
        "{{NOTE_TEXT}}": esc(data.get("note_text",
            "Dates are estimates and can shift with lender, appraisal, and title timelines. "
            "I'll update this page as things move, so there's no need to track any of this yourself.")),
        "{{AGENT_NAME}}": esc(data.get("agent_name", "Jared Dunn")),
        "{{BROKERAGE}}": esc(data.get("brokerage", "Real Broker")),
        "{{AGENT_EMAIL}}": esc(email),
        "{{AGENT_PHONE_LINE}}": f" · {esc(phone)}" if phone else "",
        "{{VENDORS_HTML}}": render_vendors(data.get("vendors", [])),
        "{{CONTACT_BAR_HTML}}": render_contact_bar(phone, email),
    }
    out = template
    for k, v in rep.items():
        out = out.replace(k, v)
    (out_dir / "index.html").write_text(out)


def main():
    args = sys.argv[1:]
    base = ""
    if "--base-url" in args:
        i = args.index("--base-url")
        base = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    build(json.loads(Path(args[0]).read_text()), args[1], base)
    print(f"Wrote {args[1]}")


if __name__ == "__main__":
    main()
