import socket
import pyaudio
import vosk
import threading
import queue
import json
from datetime import datetime
import time
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
import uuid

# ========== Astra DB Connection ==========
cloud_config = {
    'secure_connect_bundle': 'secure-connect-homeiot.zip'
}

with open("HomeIOT-token.json") as f:
    secrets = json.load(f)

CLIENT_ID = secrets["clientId"]
CLIENT_SECRET = secrets["secret"]

auth_provider = PlainTextAuthProvider(CLIENT_ID, CLIENT_SECRET)
cluster = Cluster(cloud=cloud_config, auth_provider=auth_provider)
session = cluster.connect()

print("✅ Connected to Astra DB")

DEVICE_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")  # fixed device ID

# Ensure table exists
session.execute("""
CREATE TABLE IF NOT EXISTS iot.truth (
    device_id uuid PRIMARY KEY,
    mode text,
    status text,
    last_update timestamp
);
""")

# ========== Audio + Recognition Setup ==========
UDP_IP = "0.0.0.0"
UDP_PORT = 3333
CHUNK = 512
SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16

audio_queue = queue.Queue()

p = pyaudio.PyAudio()
stream = p.open(format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE, output=True, frames_per_buffer=CHUNK)

model = vosk.Model("vosk-model-small-en-us-0.15")
rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)

# ========== Helper: Update DB ==========
def update_db(mode, status):
    now = datetime.utcnow()
    try:
        session.execute(
            """
            INSERT INTO iot.truth (device_id, mode, status, last_update)
            VALUES (%s, %s, %s, %s)
            """,
            (DEVICE_ID, mode, status, now)
        )
        print(f"📡 DB Updated → mode={mode}, status={status}, time={now}")
    except Exception as e:
        print(f"❌ DB update failed: {e}")

# ========== UDP Receiver ==========
def udp_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(0.5)
    print(f"🎤 Listening for UDP audio on {UDP_PORT}...")
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            stream.write(data)
            audio_queue.put(data)
        except socket.timeout:
            continue
        except Exception as e:
            print(f"UDP error: {e}")

# ========== Speech Processor ==========
def audio_processor():
    while True:
        try:
            data = audio_queue.get()
            if rec.AcceptWaveform(data):
                result = rec.Result()
                result_json = json.loads(result)
                text = result_json.get("text", "").lower()
                if not text:
                    continue

                print(f"🗣 Recognized: {text}")

                # Voice ON/OFF phrases
                on_phrases = ["turn on", "switch on", "light on", "activate light"]
                off_phrases = ["turn off", "switch off", "light off", "deactivate light"]
                auto_phrases = ["switch to auto", "go to auto", "enable auto mode"]

                if any(p in text for p in on_phrases):
                    update_db("VOICE", "ON")
                elif any(p in text for p in off_phrases):
                    update_db("VOICE", "OFF")
                elif any(p in text for p in auto_phrases):
                    update_db("AUTO", "OFF")
        except Exception as e:
            print(f"Processor error: {e}")

# ========== Start Threads ==========
receiver_thread = threading.Thread(target=udp_receiver, daemon=True)
processor_thread = threading.Thread(target=audio_processor, daemon=True)
receiver_thread.start()
processor_thread.start()

# ========== Keep Main Alive ==========
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("🛑 Stopping...")
    stream.stop_stream()
    stream.close()
    p.terminate()
    cluster.shutdown()