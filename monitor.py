import os, time, json, pathlib, subprocess, threading, logging, requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from requests.auth import HTTPDigestAuth
from onvif import ONVIFCamera
from lxml import etree

# ── Camera configs ────────────────────────────────────────────────────────────
CAMERAS = [
    {
        "name":  "camera-0",
        "ip":    "10.0.0.10",
        "port":  80,
        "user":  "username",
        "pass":  "password",
    },
    {
        "name":  "camera-1",
        "ip":    "10.0.0.11",
        "port":  80,
        "user":  "username",
        "pass":  "password",
    },
]

CAMERAS[0]['name'] = os.environ.get("BOSCH_CAM0_NAME")
CAMERAS[0]['ip']   = os.environ.get("BOSCH_CAM0_IP")
CAMERAS[0]['port'] = os.environ.get("BOSCH_CAM0_PORT")
CAMERAS[0]['user'] = os.environ.get("BOSCH_CAM0_USER")
CAMERAS[0]['pass'] = os.environ.get("BOSCH_CAM0_PASS")

CAMERAS[1]['name'] = os.environ.get("BOSCH_CAM1_NAME")
CAMERAS[1]['ip']   = os.environ.get("BOSCH_CAM1_IP")
CAMERAS[1]['port'] = os.environ.get("BOSCH_CAM1_PORT")
CAMERAS[1]['user'] = os.environ.get("BOSCH_CAM1_USER")
CAMERAS[1]['pass'] = os.environ.get("BOSCH_CAM1_PASS")

# ── Shared config ─────────────────────────────────────────────────────────────
CAMERA_UTC_OFFSET = -7
POST_EVENT_WAIT   = 35
CLIP_DURATION     = 40
PRE_BUFFER        = 10
COOLDOWN_SECS     = 10
BOSCH_EPOCH       = datetime(2000, 1, 1, tzinfo=timezone.utc)

# ── Schedule ──────────────────────────────────────────────────────────────────
MONITOR_END_HOUR = 6
MONITOR_END_MIN  = 30

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE            = pathlib.Path.home() / "loitering-monitor"
CLIPS_LOITERING = BASE / "clips" / "loitering"
CLIPS_WARNING   = BASE / "clips" / "front-warning"
LOG             = BASE / "logs" / "events.jsonl"
BASE.mkdir(exist_ok=True)
CLIPS_LOITERING.mkdir(parents=True, exist_ok=True)
CLIPS_WARNING.mkdir(parents=True, exist_ok=True)
(BASE / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE / "logs" / "monitor.log")
    ]
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_rule(xml: str) -> str:
    try:
        start = xml.index('Name="Rule" Value="') + len('Name="Rule" Value="')
        return xml[start:xml.index('"', start)]
    except Exception:
        return "Unknown"


def parse_utc_time(msg_el) -> datetime:
    try:
        return datetime.fromisoformat(msg_el.get("UtcTime").replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def utc_to_bosch_seek(event_utc: datetime) -> str:
    event_local = event_utc + timedelta(hours=CAMERA_UTC_OFFSET)
    start_local = event_local - timedelta(seconds=PRE_BUFFER)
    seek_secs   = int((start_local.replace(tzinfo=timezone.utc) - BOSCH_EPOCH).total_seconds())
    return hex(seek_secs)


def clip_dir_for(rule: str) -> pathlib.Path:
    return CLIPS_WARNING if "warning" in rule.lower() else CLIPS_LOITERING


# ── Snapshot capture ──────────────────────────────────────────────────────────
def capture_snapshot(cam: dict, local_time: str, rule: str):
    safe_ts = local_time[:19].replace(":", "-")
    out     = clip_dir_for(rule) / f"snap_{cam['name']}_{safe_ts}.jpg"
    url     = f"http://{cam['ip']}/snap.jpg"
    try:
        r = requests.get(url, auth=HTTPDigestAuth(cam["user"], cam["pass"]), timeout=5)
        if r.status_code == 200 and "image" in r.headers.get("Content-Type", ""):
            out.write_bytes(r.content)
            print(f"[{cam['name']}] ✓ Snapshot saved → {out.name}")
        else:
            print(f"[{cam['name']}] ✗ Snapshot failed — HTTP {r.status_code}")
    except Exception as e:
        print(f"[{cam['name']}] ✗ Snapshot error: {e}")


# ── Clip capture ──────────────────────────────────────────────────────────────
def capture_clip(cam: dict, event_utc: datetime, local_time: str, rule: str):
    print(f"[{cam['name']}] Waiting {POST_EVENT_WAIT}s for post-event footage...")
    time.sleep(POST_EVENT_WAIT)

    seek_hex = utc_to_bosch_seek(event_utc)
    safe_ts  = local_time[:19].replace(":", "-")
    out      = clip_dir_for(rule) / f"event_{cam['name']}_{safe_ts}.mp4"
    encoded  = quote(cam["pass"], safe="")

    rtsp = (
        f"rtsp://{cam['user']}:{encoded}@{cam['ip']}"
        f"/rtsp_tunnel?rec=1&rnd=42&seek={seek_hex}"
    )

    print(f"[{cam['name']}] Pulling clip → {clip_dir_for(rule).name}/{out.name}")
    result = subprocess.run([
        "ffmpeg", "-rtsp_transport", "tcp",
        "-i", rtsp,
        "-t", str(CLIP_DURATION),
        "-c", "copy", str(out)
    ], capture_output=True)

    if out.exists() and out.stat().st_size > 0:
        print(f"[{cam['name']}] ✓ Saved → {clip_dir_for(rule).name}/{out.name} ({out.stat().st_size // 1024}KB)")
    else:
        print(f"[{cam['name']}] ✗ Clip capture failed")
        print(result.stderr.decode(errors="ignore")[-500:])


# ── Event logging ─────────────────────────────────────────────────────────────
def log_event(cam: dict, event_utc: datetime, rule: str, local_time: str):
    entry = {
        "camera":   cam["name"],
        "time":     local_time,
        "utc_time": event_utc.isoformat(),
        "rule":     rule
    }
    with LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[{cam['name']}] ✓ Event logged — {rule} at {local_time}")


# ── Shutdown watcher ──────────────────────────────────────────────────────────
def watch_for_shutdown():
    while True:
        now = datetime.now()
        if now.hour == MONITOR_END_HOUR and now.minute >= MONITOR_END_MIN:
            print(f"\n[monitor] Reached {MONITOR_END_HOUR}:{MONITOR_END_MIN:02d} — launching digest and shutting down...")
            import sys
            subprocess.Popen([sys.executable, str(pathlib.Path(__file__).parent / "digest.py")])
            time.sleep(2)
            os._exit(0)
        time.sleep(30)  # check every 30 seconds


# ── Per-camera monitor loop ───────────────────────────────────────────────────
def monitor_camera(cam: dict):
    last_event_time = 0

    while True:
        try:
            print(f"[{cam['name']}] Connecting to {cam['ip']}...")
            onvif_cam = ONVIFCamera(cam["ip"], cam["port"], cam["user"], cam["pass"])
            pullpoint = onvif_cam.create_pullpoint_service()
            print(f"[{cam['name']}] Connected. Listening for events...")

            while True:
                response = pullpoint.PullMessages({
                    "MessageLimit": 10,
                    "Timeout": "PT20S"
                })

                for notification in response.NotificationMessage:
                    msg_el = notification.Message._value_1
                    xml    = etree.tostring(msg_el, encoding="unicode")

                    is_loitering     = "Loitering" in xml
                    is_front_warning = "Front warning" in xml
                    if (not is_loitering and not is_front_warning) or 'Value="true"' not in xml:
                        continue

                    now_ts = time.time()
                    if now_ts - last_event_time < COOLDOWN_SECS:
                        print(f"[{cam['name']}] Within cooldown — skipping")
                        continue
                    last_event_time = now_ts

                    event_utc  = parse_utc_time(msg_el)
                    local_time = datetime.now().isoformat()
                    rule       = parse_rule(xml)

                    log_event(cam, event_utc, rule, local_time)

                    # Snapshot immediately at event time
                    capture_snapshot(cam, local_time, rule)

                    # Clip pulled in background after post-event buffer
                    threading.Thread(
                        target=capture_clip,
                        args=(cam, event_utc, local_time, rule),
                        daemon=True
                    ).start()

        except Exception as e:
            print(f"[{cam['name']}] Error: {e} — reconnecting in 15s")
            import traceback
            traceback.print_exc()
            time.sleep(15)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting loitering monitor...")
    print(f"Clips → {BASE / 'clips'}")
    print(f"Log   → {LOG}")
    print(f"Runs until {MONITOR_END_HOUR}:{MONITOR_END_MIN:02d}")
    print()

    # Start shutdown watcher
    threading.Thread(target=watch_for_shutdown, daemon=True).start()

    # Start camera threads
    threads = []
    for cam in CAMERAS:
        t = threading.Thread(target=monitor_camera, args=(cam,), daemon=True)
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping monitor.")
