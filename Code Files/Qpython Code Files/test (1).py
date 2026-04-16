import threading
import requests
import socket
import queue
import time
import json
import datetime
import uuid
import pytz
import io
import wave
from pyngrok import ngrok, conf
from google.cloud import speech
from google.oauth2 import service_account

# ====================================================
# ========== CONFIGURATION ===========================
# ====================================================

# ---- NGROK + ESP32 CAM CONFIG ----
NGROK_AUTH_TOKEN = ""
ESP32_LOCAL_IP = ""
ESP32_PORT = 81
ESP32_STREAM_PATH = "/stream"

# ---- GOOGLE SPEECH CONFIG ----
SERVICE_ACCOUNT_PATH = ""
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH)
speech_client = speech.SpeechClient(credentials=credentials)

# ---- UDP AUDIO SETTINGS ----
UDP_IP = "0.0.0.0"
UDP_PORT = 3333
SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2
ACCUMULATION_TIME = 3  # seconds

# ---- ASTRA DB CONFIG ----
API_ENDPOINT = ""
ASTRA_TOKEN = ""
KEYSPACE = "iot"
TABLE = "truth"
URL = f"{API_ENDPOINT}/api/rest/v2/keyspaces/{KEYSPACE}/{TABLE}"
HEADERS = {"X-Cassandra-Token": ASTRA_TOKEN, "Content-Type": "application/json"}

DEVICE_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000000"))
IST = pytz.timezone("Asia/Kolkata")

# ====================================================
# ========== SHARED UTILITIES ========================
# ====================================================

def update_db(mode, status):
    """Push voice command result to Astra DB (failsafe: relay off on error)."""
    now_ist = datetime.datetime.now(IST)
    iso_time = now_ist.isoformat()
    row = {
        "device_id": DEVICE_ID,
        "mode": mode,
        "status": status,
        "last_update": iso_time
    }
    try:
        resp = requests.post(URL, headers=HEADERS, json=row, timeout=5)
        if resp.status_code in (200, 201):
            print(f"✅ DB Updated: mode={mode}, status={status}, time={iso_time}")
        else:
            print(f"❌ DB Error {resp.status_code}: {resp.text}")
            print("⚠️ Defaulting relay OFF (DB write issue).")
    except Exception as e:
        print(f"❌ DB update failed: {e}")
        print("⚠️ Defaulting relay OFF (network/db offline).")

# ====================================================
# ========== THREAD 1: NGROK CAMERA STREAM ===========
# ====================================================

def start_ngrok_tunnel():
    """Expose ESP32-CAM stream publicly via ngrok."""
    print("🚀 Setting up ngrok tunnel...")
    pyngrok_config = conf.PyngrokConfig(auth_token=NGROK_AUTH_TOKEN, region="ap")
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)

    try:
        tunnel = ngrok.connect(f"{ESP32_LOCAL_IP}:{ESP32_PORT}", "http", pyngrok_config=pyngrok_config)
        public_url = tunnel.public_url
        stream_url = f"{public_url}{ESP32_STREAM_PATH}"

        print(f"\n🌍 Public Stream URL: {stream_url}")
        print("✅ Tunnel active! Press Ctrl+C to stop.\n")

        # Optional: Check local reachability
        try:
            r = requests.get(f"http://{ESP32_LOCAL_IP}{ESP32_STREAM_PATH}", stream=True, timeout=5)
            if r.status_code == 200:
                print("✅ ESP32-CAM reachable locally.")
            else:
                print(f"⚠️ ESP32 returned status {r.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Local ESP32 check failed: {e}")

        # Keep tunnel alive
        ngrok_process = ngrok.get_ngrok_process()
        while True:
            time.sleep(1)
            if ngrok_process.proc.poll() is not None:
                print("❌ ngrok process exited unexpectedly. Restarting soon...")
                break

    except KeyboardInterrupt:
        print("\n🛑 Tunnel closed by user.")
    except Exception as e:
        print(f"❌ ngrok error: {e}")
        print("⚠️ Defaulting relay OFF due to ngrok failure.")
        update_db("VOICE", "OFF")

# ====================================================
# ========== THREAD 2: VOICE COMMAND HANDLER =========
# ====================================================

audio_queue = queue.Queue()

def udp_receiver():
    """Receive audio data over UDP and enqueue it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(0.5)
    print(f"🎤 Listening for UDP audio on port {UDP_PORT}...")
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            audio_queue.put(data)
        except socket.timeout:
            continue
        except Exception as e:
            print(f"UDP Error: {e}")

def audio_processor():
    """Process audio queue and send to Google Speech every few seconds."""
    print("🧠 Speech Processor running (3s accumulation)...")
    buffer = bytearray()
    last_send_time = time.time()

    while True:
        try:
            data = audio_queue.get()
            if not data:
                continue
            buffer.extend(data)

            if time.time() - last_send_time >= ACCUMULATION_TIME:
                if len(buffer) == 0:
                    last_send_time = time.time()
                    continue

                # Convert to WAV
                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(BYTES_PER_SAMPLE)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(buffer)
                wav_buf.seek(0)

                # Send to Google Speech
                audio = speech.RecognitionAudio(content=wav_buf.read())
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=SAMPLE_RATE,
                    language_code="en-US"
                )

                print("🎧 Sending 3s audio chunk to Google STT...")
                response = speech_client.recognize(config=config, audio=audio)

                for result in response.results:
                    text = result.alternatives[0].transcript.lower().strip()
                    if text:
                        print(f"🗣 Recognized: {text}")

                        on_phrases = ["turn on", "switch on", "light on", "activate light"]
                        off_phrases = ["turn off", "switch off", "light off", "deactivate light"]
                        auto_phrases = ["switch to auto", "go to auto", "enable auto", "automatic mode"]

                        if any(p in text for p in on_phrases):
                            update_db("VOICE", "ON")
                        elif any(p in text for p in off_phrases):
                            update_db("VOICE", "OFF")
                        elif any(p in text for p in auto_phrases):
                            update_db("AUTO", "OFF")

                buffer.clear()
                last_send_time = time.time()

        except Exception as e:
            print(f"Processor Error: {e}")
            buffer.clear()
            last_send_time = time.time()
            print("⚠️ Defaulting relay OFF due to processing error.")
            update_db("VOICE", "OFF")

# ====================================================
# ========== MAIN STARTUP ============================
# ====================================================

if __name__ == "__main__":
    print("🧩 Starting unified control system...")

    # --- Thread 1: Camera Tunnel ---
    tunnel_thread = threading.Thread(target=start_ngrok_tunnel, daemon=True)
    tunnel_thread.start()

    # --- Thread 2a: UDP Audio Receiver ---
    recv_thread = threading.Thread(target=udp_receiver, daemon=True)
    recv_thread.start()

    # --- Thread 2b: Speech Processor ---
    proc_thread = threading.Thread(target=audio_processor, daemon=True)
    proc_thread.start()

    print("🚀 All systems online: Ngrok + Voice Control active.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 System stopped.")