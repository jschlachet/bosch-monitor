#
# kill start and end, its kicked off from a job so just
# configure a DURATION at which it'll kill itself.
#
#
import json, pathlib, smtplib, subprocess, base64, os
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# ── Config ────────────────────────────────────────────────────────────────────
RUN_DURATION_MINS = 2 # 60*10 10 hours

SMTP_HOST  = "smtp.gmail.com"
SMTP_PORT  = 587
EMAIL_FROM = os.environ.get("BOSCH_EMAIL_FROM")
EMAIL_PASS = os.environ.get("BOSCH_EMAIL_FROM_PASS")
EMAIL_TO   = os.environ.get("BOSCH_EMAIL_TO")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE            = pathlib.Path.home() / "loitering-monitor"
CLIPS_LOITERING = BASE / "clips" / "loitering"
CLIPS_WARNING   = BASE / "clips" / "front-warning"
LOG             = BASE / "logs" / "events.jsonl"
OUT             = BASE / "digest.html"

now = datetime.now()

# ── Load last night's events ──────────────────────────────────────────────────
def load_events() -> list:

    events = []
    if not LOG.exists():
        return events
    with LOG.open() as f:
        for line in f:
            try:
                e = json.loads(line)
                t = datetime.fromisoformat(e["time"])
                if t >= start:
                    events.append(e)
            except Exception:
                continue
    LOG.unlink()
    return events


# ── Find files for event ──────────────────────────────────────────────────────
def clip_dir_for(rule: str) -> pathlib.Path:
    return CLIPS_WARNING if "warning" in rule.lower() else CLIPS_LOITERING


def find_clip(event: dict) -> pathlib.Path | None:
    safe_ts = event["time"][:19].replace(":", "-")
    clip    = clip_dir_for(event.get("rule", "")) / f"event_{event['camera']}_{safe_ts}.mp4"
    return clip if clip.exists() else None


def find_snapshot(event: dict) -> pathlib.Path | None:
    safe_ts = event["time"][:19].replace(":", "-")
    snap    = clip_dir_for(event.get("rule", "")) / f"snap_{event['camera']}_{safe_ts}.jpg"
    return snap if snap.exists() else None


def snapshot_to_base64(snap: pathlib.Path) -> str | None:
    try:
        data = base64.b64encode(snap.read_bytes()).decode()
        return f"data:image/jpeg;base64,{data}"
    except Exception:
        return None


# ── Build table rows ──────────────────────────────────────────────────────────
def build_rows(events: list) -> str:
    if not events:
        return '<tr><td colspan="5" style="text-align:center;color:#999;padding:16px">No events recorded</td></tr>'

    rows = ""
    for e in events:
        clip = find_clip(e)
        snap = find_snapshot(e)

        clip_cell = f'<a href="file:///{clip}" style="color:#2471a3;text-decoration:none;font-size:12px">&#9654; View</a>' if clip else "—"

        if snap:
            b64 = snapshot_to_base64(snap)
            thumb_cell = f'<img src="{b64}" style="width:120px;height:68px;object-fit:cover;border-radius:6px;border:0.5px solid #ddd;display:block">' if b64 else '<span style="color:#999;font-size:12px">—</span>'
        else:
            thumb_cell = '<span style="color:#999;font-size:12px">—</span>'

        rows += f"""
        <tr>
            <td style="font-family:monospace;font-size:12px;color:#666;white-space:nowrap">{e['time'][11:19]}</td>
            <td><span style="font-size:11px;padding:2px 7px;border-radius:20px;background:#f5f5f5;color:#666;border:0.5px solid #ddd">{e['camera']}</span></td>
            <td>{thumb_cell}</td>
            <td style="font-size:13px">{e.get('rule', '—')}</td>
            <td>{clip_cell}</td>
        </tr>"""
    return rows


# ── Build HTML ────────────────────────────────────────────────────────────────
def build_html(events: list) -> str:
    date_str  = now.strftime("%B %d, %Y")
    warnings  = [e for e in events if "warning" in e.get("rule", "").lower()]
    loitering = [e for e in events if "warning" not in e.get("rule", "").lower()]

    table_style = "width:100%;border-collapse:collapse;font-size:13px"
    th_style    = "text-align:left;padding:8px 10px;color:#888;font-weight:500;border-bottom:1px solid #eee"
    td_style    = "padding:8px 10px;border-bottom:1px solid #f5f5f5;vertical-align:middle"

    def table(rows: str) -> str:
        return f"""
        <table style="{table_style}">
            <thead><tr>
                <th style="{th_style};width:80px">Time</th>
                <th style="{th_style};width:140px">Camera</th>
                <th style="{th_style};width:135px">Snapshot</th>
                <th style="{th_style}">Rule</th>
                <th style="{th_style};width:70px">Clip</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, sans-serif; padding: 2rem; color: #222; max-width: 900px; margin: 0 auto; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 1.5rem; }}
  .metric {{ background: #f8f8f8; border-radius: 8px; padding: 12px 14px; }}
  .metric-label {{ font-size: 12px; color: #888; margin: 0 0 4px; }}
  .metric-value {{ font-size: 22px; font-weight: 500; margin: 0; }}
  .section {{ margin-bottom: 2rem; }}
  .section-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #eee; }}
  .section-title {{ font-size: 14px; font-weight: 500; margin: 0; }}
  .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 6px; }}
  tr:hover td {{ background: #fafafa; }}
</style>
</head><body>

<p style="font-size:13px;color:#888;margin:0 0 4px">{date_str} &nbsp;·&nbsp; 9pm – 6:30am</p>
<h2 style="font-size:20px;font-weight:500;margin:0 0 1.5rem">Overnight security digest</h2>

<div class="metrics">
  <div class="metric"><p class="metric-label">Front warnings</p><p class="metric-value" style="color:#c0392b">{len(warnings)}</p></div>
  <div class="metric"><p class="metric-label">Loitering events</p><p class="metric-value" style="color:#2471a3">{len(loitering)}</p></div>
  <div class="metric"><p class="metric-label">Cameras active</p><p class="metric-value">2</p></div>
  <div class="metric"><p class="metric-label">Clips saved</p><p class="metric-value">{len(events)}</p></div>
</div>

<div class="section">
  <div class="section-header">
    <p class="section-title">&#9888; Front warning</p>
    <span class="badge" style="background:#fdecea;color:#c0392b">{len(warnings)} event{'s' if len(warnings) != 1 else ''}</span>
  </div>
  {table(build_rows(warnings))}
</div>

<div class="section">
  <div class="section-header">
    <p class="section-title">&#128694; Loitering</p>
    <span class="badge" style="background:#eaf2fb;color:#2471a3">{len(loitering)} event{'s' if len(loitering) != 1 else ''}</span>
  </div>
  {table(build_rows(loitering))}
</div>

</body></html>"""


# ── Send email ────────────────────────────────────────────────────────────────
def send_email(html: str, events: list):
    warnings  = sum(1 for e in events if "warning" in e.get("rule", "").lower())
    loitering = len(events) - warnings
    subject   = f"Overnight Security Digest — {warnings} warnings, {loitering} loitering"

    msg            = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    # Replace base64 src with cid: references in HTML
    email_html = html
    for e in events:
        snap = find_snapshot(e)
        if snap:
            safe_ts = e["time"][:19].replace(":", "-")
            cid     = f"{e['camera']}_{safe_ts}".replace("-", "_")
            # Replace the base64 data URI with cid reference
            email_html = email_html.replace(
                f"data:image/jpeg;base64,{base64.b64encode(snap.read_bytes()).decode()}",
                f"cid:{cid}"
            )

    msg.attach(MIMEText(email_html, "html"))

    # Attach each snapshot as inline image
    for e in events:
        snap = find_snapshot(e)
        if snap:
            safe_ts = e["time"][:19].replace(":", "-")
            cid     = f"{e['camera']}_{safe_ts}".replace("-", "_")
            img     = MIMEImage(snap.read_bytes(), _subtype="jpeg")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline")
            msg.attach(img)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(EMAIL_FROM, EMAIL_PASS)
        s.send_message(msg)
    print("✓ Email sent")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    events   = load_events()
    warnings = sum(1 for e in events if "warning" in e.get("rule", "").lower())
    loitering = len(events) - warnings

    print(f"Events loaded: {len(events)} ({warnings} warnings, {loitering} loitering)")

    html = build_html(events)
    OUT.write_text(html, encoding="utf-8")
    print(f"✓ Digest written → {OUT}")

    #subprocess.run(["cmd", "/c", "start", str(OUT)], shell=False)

    send_email(html, events)
