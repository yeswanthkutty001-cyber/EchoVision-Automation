# main.py
# Replit-side controller: decoupled stream_worker (detection) and state_worker (DB logic)
# Implements: exponential backoff, conditional frame processing, watchdog, voice hold recheck
# ADDED: Log receiver endpoint for voice_control.py logs
import requests
import threading
import queue
import time
import datetime
import pytz
import uuid
import json
import re
import cv2
import numpy as np
import mediapipe as mp
import traceback
from flask import Flask, request, jsonify

# ------------------------
# CONFIG (edit as needed)
# ------------------------
API_ENDPOINT = ""
ASTRA_TOKEN = ""
KEYSPACE = "iot"
TABLE = "truth"
ASTRA_URL = f"{API_ENDPOINT}/api/rest/v2/keyspaces/{KEYSPACE}/{TABLE}"
HEADERS = {
    "X-Cassandra-Token": ASTRA_TOKEN,
    "Content-Type": "application/json"
}
DEVICE_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000000"))

STREAM_URL = ""
CHUNK = 4096
FRAME_QUEUE_MAX = 8  # increased
PROCESS_EVERY_N = 6  # process 1 in 6 frames (approx 5 FPS at 30fps source)
INITIAL_BACKOFF = 5  # seconds
MAX_BACKOFF = 60  # seconds

AUTO_NoFaceTimeout = 10  # seconds (AUTO off threshold)
VOICE_Timeout = 30  # seconds

FRAME_READ_TIMEOUT = 10  # requests timeout for stream connect

# ------------------------
# FLASK APP FOR LOG RECEIVER
# ------------------------
app = Flask(__name__)


@app.route('/', methods=['POST'])
def receive_log():
    """Endpoint to receive logs from voice_control.py"""
    try:
        data = request.get_json()
        if data:
            recognized_text = data.get('recognized_text', '')
            timestamp = data.get('timestamp', '')
            print(f"[VOICE_LOG] [{timestamp}] {recognized_text}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"[VOICE_LOG_ERROR] Failed to process log: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now(UTC).isoformat()
    }), 200


# ------------------------
# TIMEZONES & LOGGING
# ------------------------
UTC = pytz.utc
IST = pytz.timezone("Asia/Kolkata")


def utc_now_iso():
    return datetime.datetime.now(UTC).isoformat()


def log(msg):
    print(f"[{utc_now_iso()}] {msg}")


# ------------------------
# SHARED STATE (thread-safe with lock)
# ------------------------
state_lock = threading.Lock()
state = {
    "mode": "AUTO",  # "AUTO" or "VOICE"
    "status": "OFF",  # "ON" or "OFF"
    "last_update": None  # iso string in UTC (as stored in Astra)
}

# detection / stream status
shared = {
    "last_human_time": None,  # epoch seconds
    "stream_active": False,
    "pause_detection": False,  # set by state_worker when voice hold active
    "last_seen_frame": 0
}

# frame queue for optional buffering (if you want to reuse frames)
frame_q = queue.Queue(maxsize=FRAME_QUEUE_MAX)

# thread liveness
thread_alive = {}
thread_alive_lock = threading.Lock()


def mark_alive(name):
    with thread_alive_lock:
        thread_alive[name] = time.time()


def alive_age(name):
    with thread_alive_lock:
        return time.time() - thread_alive.get(name, 0)


# ------------------------
# ASTRA DB helpers
# ------------------------
def parse_db_row_response(resp_json):
    # Astra returns {"data": [...]} or {"data": {...}} depending on request or SDK
    data = resp_json.get("data", None)
    if isinstance(data, list) and len(data) > 0:
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def fetch_db_state():
    """
    Fetch record for DEVICE_ID from Astra.
    Returns dict with keys: mode, status, last_update (ISO string in UTC) or None on error.
    """
    try:
        params = {"where": json.dumps({"device_id": {"$eq": DEVICE_ID}})}
        r = requests.get(ASTRA_URL, headers=HEADERS, params=params, timeout=10)
        if r.status_code != 200:
            log(f"⚠ DB read failed ({r.status_code}): {r.text}")
            return None
        js = r.json()
        row = parse_db_row_response(js)
        if not row:
            log("⚠ DB read returned no row")
            return None
        return {
            "mode": row.get("mode", "AUTO"),
            "status": row.get("status", "OFF"),
            "last_update": row.get("last_update", None)
        }
    except Exception as e:
        log(f"❌ DB read error: {e}")
        # traceback.print_exc()
        return None


def update_db(mode, status):
    """
    Upsert the device state into Astra. last_update is written in UTC ISO.
    """
    now_utc = datetime.datetime.now(UTC).isoformat()
    row = {
        "device_id": DEVICE_ID,
        "mode": mode,
        "status": status,
        "last_update": now_utc
    }
    try:
        r = requests.post(ASTRA_URL, headers=HEADERS, json=row, timeout=10)
        if r.status_code not in (200, 201):
            log(f"⚠ DB write returned {r.status_code}: {r.text}")
        log(f"📡 DB Updated → mode={mode} status={status} last_update={now_utc}"
            )
    except Exception as e:
        log(f"❌ DB update error: {e}")


# ------------------------
# Helper: ISO time parse to UTC datetime
# ------------------------
def parse_iso_to_utc(iso_str):
    if not iso_str:
        return None
    try:
        # handle "Z"
        if iso_str.endswith("Z"):
            iso_str = iso_str.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        try:
            # last resort: parse naive
            dt = datetime.datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.replace(tzinfo=UTC)
        except Exception:
            return None


# ------------------------
# STREAM + DETECTION WORKER
# stream_worker connects, reads MJPEG chunks, and runs detection every Nth frame
# It honors shared['pause_detection'] to skip detection during voice hold
# ------------------------
def stream_worker():
    thread_name = "stream_worker"
    mark_alive(thread_name)
    log("stream_worker starting")
    backoff = INITIAL_BACKOFF

    # mediapipe detector init (face detection or pose? using lightweight detection for presence)
    mp_face = mp.solutions.face_detection
    detector = mp_face.FaceDetection(model_selection=0,
                                     min_detection_confidence=0.4)

    frame_counter = 0

    while True:
        try:
            log(f"🔌 Attempt connecting to stream {STREAM_URL}")
            r = requests.get(STREAM_URL,
                             stream=True,
                             timeout=FRAME_READ_TIMEOUT)
            if r.status_code != 200:
                log(f"⚠ Stream returned HTTP {r.status_code}. Backoff {backoff}s"
                    )
                shared["stream_active"] = False
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                mark_alive(thread_name)
                continue

            # success
            log("✅ Stream connected")
            shared["stream_active"] = True
            backoff = INITIAL_BACKOFF
            buffer = b""
            content_type = r.headers.get("Content-Type", "")
            m = re.search("boundary=(.*)", content_type)
            boundary = ("--" +
                        m.group(1).strip()).encode() if m else b"--frame"

            for chunk in r.iter_content(chunk_size=CHUNK):
                mark_alive(thread_name)
                buffer += chunk
                # find frame(s) in buffer
                while True:
                    start = buffer.find(boundary)
                    if start == -1:
                        break
                    header_end = buffer.find(b"\r\n\r\n", start)
                    if header_end == -1:
                        break
                    header = buffer[start:header_end].decode(errors="ignore")
                    mlen = re.search(r"Content-Length:\s*(\d+)", header,
                                     re.IGNORECASE)
                    if not mlen:
                        # can't parse content-length; skip
                        break
                    length = int(mlen.group(1))
                    image_start = header_end + 4
                    image_end = image_start + length
                    if len(buffer) < image_end:
                        break
                    jpg = buffer[image_start:image_end]
                    buffer = buffer[image_end:]

                    # decode frame
                    frame = cv2.imdecode(np.frombuffer(jpg, np.uint8),
                                         cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    # put to queue (non-blocking)
                    try:
                        if frame_q.full():
                            _ = frame_q.get_nowait()
                        frame_q.put_nowait(frame)
                    except Exception:
                        pass

                    # detection: skip if pause_detection set
                    if shared["pause_detection"]:
                        # skip detection while paused (but keep connection alive)
                        continue

                    # process only every Nth frame
                    frame_counter += 1
                    if frame_counter % PROCESS_EVERY_N != 0:
                        continue

                    # convert and run lightweight detector
                    try:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        results = detector.process(rgb)
                        human_here = results.detections is not None and len(
                            results.detections) > 0
                        if human_here:
                            shared["last_human_time"] = time.time()
                        # log detection event every now and then
                        log(f"detected_human={human_here}")
                    except Exception as e:
                        log(f"❌ Detection error: {e}")
                        # don't crash the worker; continue
            # end for
        except Exception as ex:
            shared["stream_active"] = False
            log(f"⚠ Stream error: {ex}. backing off {backoff}s")
            # optional: print traceback for debugging once
            # traceback.print_exc()
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            mark_alive(thread_name)


# ------------------------
# STATE WORKER
# - Syncs DB periodically (unless VOICE hold active)
# - Applies mode logic
# - When VOICE is active, pauses detection for the remaining time; before switching to AUTO re-checks DB to catch new voice commands
# ------------------------
def state_worker():
    thread_name = "state_worker"
    mark_alive(thread_name)
    log("state_worker starting")
    DB_POLL_INTERVAL = 3  # seconds when not paused

    while True:
        try:
            mark_alive(thread_name)
            with state_lock:
                current_mode = state["mode"]
                current_status = state["status"]
                last_update_iso = state["last_update"]

            # If VOICE active -> compute remaining
            if current_mode == "VOICE" and last_update_iso:
                last_update_dt = parse_iso_to_utc(last_update_iso)
                if last_update_dt is None:
                    # if parse fails, treat as expired
                    remaining = -1
                else:
                    elapsed = (datetime.datetime.now(UTC) -
                               last_update_dt).total_seconds()
                    remaining = VOICE_Timeout - elapsed

                if remaining > 0:
                    # Enter hold: pause detection + DB reads for 'remaining' seconds,
                    # but before final expiry re-check DB to see if last_update changed (dynamic extension)
                    log(f"🔇 VOICE mode active for {remaining:.1f}s more → pausing detection and DB polling"
                        )
                    # set pause flag
                    shared["pause_detection"] = True

                    # We'll sleep in small intervals and re-check DB last_update near end
                    sleep_step = min(3, remaining)
                    slept = 0.0
                    while slept < remaining:
                        time.sleep(sleep_step)
                        slept += sleep_step
                        mark_alive(thread_name)
                        # near the end (last 3s) re-check DB to handle dynamic extension
                        time_left = remaining - slept
                        if time_left <= 3:
                            db_state = fetch_db_state()
                            if db_state and db_state.get(
                                    "last_update") != last_update_iso:
                                # updated by phone — extend hold accordingly: reload variables
                                log("🔁 New voice update detected in DB — extend hold dynamically"
                                    )
                                with state_lock:
                                    state["mode"] = db_state["mode"]
                                    state["status"] = db_state["status"]
                                    state["last_update"] = db_state[
                                        "last_update"]
                                # recompute remaining from new last_update
                                last_update_iso = state["last_update"]
                                last_update_dt = parse_iso_to_utc(
                                    last_update_iso)
                                if last_update_dt:
                                    elapsed = (datetime.datetime.now(UTC) -
                                               last_update_dt).total_seconds()
                                    remaining = VOICE_Timeout - elapsed
                                    slept = 0.0
                                    sleep_step = min(3,
                                                     max(0.5, remaining / 4))
                                    log(f"🔁 Extended voice hold, new remaining {remaining:.1f}s"
                                        )
                                else:
                                    break
                    # hold finished: clear pause flag
                    shared["pause_detection"] = False
                    # after hold ends, re-evaluate loop to perform expiry handling
                    continue
                else:
                    # voice expired — before switching to AUTO, re-check DB once more
                    db_state = fetch_db_state()
                    if db_state and db_state.get(
                            "last_update") and db_state.get(
                                "last_update") != last_update_iso:
                        # new voice update came in meanwhile; update in-memory state and continue holding
                        log("🔁 Found new voice update at expiry check; reloading state and continuing"
                            )
                        with state_lock:
                            state["mode"] = db_state["mode"]
                            state["status"] = db_state["status"]
                            state["last_update"] = db_state["last_update"]
                        continue

                    # switch to AUTO
                    log("⏱ VOICE timeout -> switching to AUTO")
                    with state_lock:
                        state["mode"] = "AUTO"
                        # determine new status from human detection if stream active, else OFF
                        if shared["stream_active"] and shared[
                                "last_human_time"] and (
                                    time.time() - shared["last_human_time"]
                                    < AUTO_NoFaceTimeout):
                            new_status = "ON"
                        else:
                            new_status = "OFF"
                        state["status"] = new_status
                        state["last_update"] = datetime.datetime.now(
                            UTC).isoformat()
                    # commit to DB
                    update_db("AUTO", state["status"])
                    # continue to loop
                    continue

            # If not in voice hold, poll DB periodically to sync possible phone writes
            db_state = fetch_db_state()
            if db_state:
                with state_lock:
                    if db_state.get("mode") != state["mode"] or db_state.get(
                            "status") != state["status"]:
                        log(f"🗄 DB → mode={db_state.get('mode')} status={db_state.get('status')}"
                            )
                        state["mode"] = db_state.get("mode")
                        state["status"] = db_state.get("status")
                        state["last_update"] = db_state.get("last_update")

            # AUTO logic (runs irrespective of DB sync)
            with state_lock:
                if state["mode"] == "AUTO":
                    # decide based on last_human_time and stream availability
                    if shared["stream_active"] and shared[
                            "last_human_time"] and (time.time() -
                                                    shared["last_human_time"]
                                                    < AUTO_NoFaceTimeout):
                        desired = "ON"
                    else:
                        desired = "OFF"

                    if desired != state["status"]:
                        state["status"] = desired
                        state["last_update"] = datetime.datetime.now(
                            UTC).isoformat()
                        update_db(state["mode"], state["status"])

            # sleep small while not paused
            time.sleep(DB_POLL_INTERVAL)
        except Exception as e:
            log(f"❌ state_worker exception: {e}")
            # traceback.print_exc()
            time.sleep(2)
            mark_alive(thread_name)


# ------------------------
# WATCHDOG: restarts workers if dead
# ------------------------
def start_thread(name, target, args=()):
    t = threading.Thread(target=target, args=args, name=name, daemon=True)
    t.start()
    return t


def watchdog():
    """
    Ensure stream_worker and state_worker are running. If not alive for >30s, restart.
    """
    THREADS = {"stream_worker": stream_worker, "state_worker": state_worker}
    running = {}
    for name, fn in THREADS.items():
        running[name] = start_thread(name, fn)
        time.sleep(0.2)

    while True:
        for name, fn in THREADS.items():
            age = alive_age(name)
            if age > 30:
                log(f"⚠ Watchdog: {name} not responsive for {age:.1f}s — restarting"
                    )
                # attempt restart by launching new thread
                running[name] = start_thread(name, fn)
                # reset alive timestamp
                mark_alive(name)
        time.sleep(5)


# ------------------------
# FLASK SERVER WORKER
# ------------------------
def flask_server():
    """Run Flask server in separate thread"""
    log("Flask log receiver starting on port 3000")
    # Disable Flask request logging for cleaner output
    import logging
    flask_log = logging.getLogger('werkzeug')
    flask_log.setLevel(logging.ERROR)

    # Use port 3000 - Replit auto-detects this
    app.run(host='0.0.0.0',
            port=3000,
            debug=False,
            use_reloader=False,
            threaded=True)


# ------------------------
# MAIN entry: start watchdog (which launches threads) + Flask server
# ------------------------
if __name__ == "__main__":
    log("Controller starting")
    mark_alive("main")

    # Start Flask server in background thread
    flask_thread = threading.Thread(target=flask_server,
                                    name="flask_server",
                                    daemon=True)
    flask_thread.start()
    log("✅ Flask log receiver started")

    # sync initial DB state once at startup
    dbs = fetch_db_state()
    if dbs:
        with state_lock:
            state["mode"] = dbs.get("mode", "AUTO")
            state["status"] = dbs.get("status", "OFF")
            state["last_update"] = dbs.get("last_update", None)
        log(f"Initial DB state -> mode={state['mode']} status={state['status']} last_update={state['last_update']}"
            )
    else:
        log("No DB state found at startup; using defaults")

    # launch watchdog which will spawn workers
    watchdog_thread = threading.Thread(target=watchdog,
                                       name="watchdog",
                                       daemon=True)
    watchdog_thread.start()

    # keep main alive
    while True:
        mark_alive("main")
        time.sleep(60)
