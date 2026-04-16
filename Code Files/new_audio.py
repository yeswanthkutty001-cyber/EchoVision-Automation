import socket
import queue
import time
import datetime
import uuid
import pytz
import requests
import signal
import sys
import atexit
import threading
from google.cloud import speech

# ====================================================
# ========== CONFIGURATION ===========================
# ====================================================

# ---- GOOGLE CLOUD SPEECH CONFIG ----
# Make sure GOOGLE_APPLICATION_CREDENTIALS env var is set
# export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
LANGUAGE = "en-US"
SAMPLE_RATE = 16000
CHANNELS = 1

# ---- UDP AUDIO SETTINGS ----
UDP_IP = "0.0.0.0"
UDP_PORT = 3333
ACCUMULATION_TIME = 1.5  # Reduced for faster response (was 3s)

# ---- ASTRA DB CONFIG ----
API_ENDPOINT = ""
ASTRA_TOKEN = ""
KEYSPACE = "iot"
TABLE = "truth"
URL = f"{API_ENDPOINT}/api/rest/v2/keyspaces/{KEYSPACE}/{TABLE}"
HEADERS = {"X-Cassandra-Token": ASTRA_TOKEN, "Content-Type": "application/json"}

# ---- REPLIT SERVER CONFIG ----
REPLIT_URL = "https://677c562b-0436-440b-9454-1e39a4bd51d8-00-tkficnqryakd.pike.replit.dev/"

DEVICE_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000000"))
IST = pytz.timezone("Asia/Kolkata")

# ====================================================
# ========== GLOBAL RESOURCES ========================
# ====================================================

udp_socket = None
audio_queue = queue.Queue()
recognition_queue = queue.Queue()  # Queue for parallel recognition
speech_client = None
shutdown_flag = False

# ====================================================
# ========== LOGGING TO REPLIT =======================
# ====================================================

def log_to_replit(log_type, message, extra_data=None):
    """Send logs to Replit server in background thread."""
    def _send():
        try:
            payload = {
                "log_type": log_type,
                "message": message,
                "timestamp": datetime.datetime.now(IST).isoformat(),
                "device_id": DEVICE_ID
            }
            if extra_data:
                payload.update(extra_data)
            
            r = requests.post(REPLIT_URL, json=payload, timeout=3)
            if not r.ok:
                print(f"⚠️ Replit server error {r.status_code}")
        except Exception as e:
            print(f"⚠️ Failed to send to Replit: {e}")
    
    # Send in background thread to not block
    threading.Thread(target=_send, daemon=True).start()

def print_and_log(message, log_type="info", extra_data=None):
    """Print to console and send to Replit."""
    print(message)
    log_to_replit(log_type, message, extra_data)

# ====================================================
# ========== SHARED UTILITIES ========================
# ====================================================

def update_db(mode, status, retry=True):
    """Push voice command result to Astra DB with retry logic."""
    now_ist = datetime.datetime.now(IST)
    iso_time = now_ist.isoformat()
    row = {
        "device_id": DEVICE_ID,
        "mode": mode,
        "status": status,
        "last_update": iso_time
    }
    
    attempts = 2 if retry else 1
    
    for attempt in range(attempts):
        try:
            resp = requests.post(URL, headers=HEADERS, json=row, timeout=5)
            if resp.status_code in (200, 201):
                msg = f"✅ DB Updated: mode={mode}, status={status}, time={iso_time}"
                print_and_log(msg, "db_success", {"mode": mode, "status": status})
                return True
            else:
                error_msg = f"❌ DB Error {resp.status_code}: {resp.text}"
                if attempt < attempts - 1:
                    print(f"{error_msg} - Retrying...")
                    time.sleep(0.5)
                else:
                    print_and_log(error_msg, "db_error", {
                        "mode": mode, 
                        "status": status,
                        "status_code": resp.status_code,
                        "response": resp.text
                    })
                    print_and_log("⚠️ Defaulting relay OFF (DB write issue).", "warning")
        except Exception as e:
            error_msg = f"❌ DB update failed: {e}"
            if attempt < attempts - 1:
                print(f"{error_msg} - Retrying...")
                time.sleep(0.5)
            else:
                print_and_log(error_msg, "db_error", {
                    "mode": mode,
                    "status": status,
                    "error": str(e)
                })
                print_and_log("⚠️ Defaulting relay OFF (network/db offline).", "warning")
    
    return False

def cleanup_resources():
    """Clean up all resources on shutdown."""
    global udp_socket, shutdown_flag
    
    msg = "\n🧹 Cleaning up resources..."
    print_and_log(msg, "shutdown")
    shutdown_flag = True
    
    # Close UDP socket
    if udp_socket:
        try:
            udp_socket.close()
            print_and_log("✅ UDP socket closed", "shutdown")
        except Exception as e:
            print_and_log(f"⚠️ Error closing UDP socket: {e}", "error")
    
    print_and_log("✅ Cleanup complete", "shutdown")

def signal_handler(signum, frame):
    """Handle CTRL+C and other termination signals."""
    print_and_log("\n🛑 Shutdown signal received...", "shutdown")
    cleanup_resources()
    sys.exit(0)

# ====================================================
# ========== UDP AUDIO RECEIVER ======================
# ====================================================

def udp_receiver():
    """Receive audio data over UDP and enqueue it."""
    global udp_socket, shutdown_flag
    
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.bind((UDP_IP, UDP_PORT))
    udp_socket.settimeout(0.5)
    print_and_log(f"🎤 Listening for UDP audio on port {UDP_PORT}...", "startup")
    
    while not shutdown_flag:
        try:
            data, _ = udp_socket.recvfrom(4096)
            audio_queue.put(data)
        except socket.timeout:
            continue
        except Exception as e:
            if not shutdown_flag:
                print_and_log(f"UDP Error: {e}", "error")
            break
    
    print_and_log("🎤 UDP receiver stopped", "shutdown")

# ====================================================
# ========== SPEECH RECOGNITION (PARALLEL) ===========
# ====================================================

def recognize_speech_worker():
    """Worker thread that processes recognition requests in parallel."""
    global speech_client, shutdown_flag
    
    if speech_client is None:
        speech_client = speech.SpeechClient()
    
    print_and_log("🧠 Speech recognition worker started", "startup")
    
    while not shutdown_flag:
        try:
            audio_data = recognition_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        
        if audio_data is None:  # Shutdown signal
            break
        
        # Perform recognition
        audio = speech.RecognitionAudio(content=audio_data)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            language_code=LANGUAGE,
            enable_automatic_punctuation=True,
        )
        
        try:
            response = speech_client.recognize(config=config, audio=audio)
            
            for result in response.results:
                text = result.alternatives[0].transcript.lower().strip()
                conf = result.alternatives[0].confidence
                
                msg = f"🗣 Recognized: {text} (conf={conf:.2f})"
                print_and_log(msg, "recognition", {
                    "recognized_text": text,
                    "confidence": conf
                })
                
                # Process commands
                process_voice_command(text)
                
            if not response.results:
                print("🤔 No speech detected.")
                
        except Exception as e:
            print_and_log(f"⚠️ Google Speech API error: {e}", "error", {"error": str(e)})
    
    print_and_log("🧠 Speech recognition worker stopped", "shutdown")

def process_voice_command(text):
    """Process recognized text and update DB accordingly."""
    on_phrases = ["turn on", "switch on", "light on", "activate light"]
    off_phrases = ["turn off", "switch off", "light off", "deactivate light"]
    auto_phrases = ["switch to auto", "go to auto", "enable auto", "automatic mode"]

    if any(p in text for p in on_phrases):
        update_db("VOICE", "ON")
    elif any(p in text for p in off_phrases):
        update_db("VOICE", "OFF")
    elif any(p in text for p in auto_phrases):
        update_db("AUTO", "OFF")

def audio_accumulator():
    """Accumulate audio and send to recognition queue for parallel processing."""
    global shutdown_flag
    
    print_and_log("🎙️ Audio accumulator running (1.5s chunks for faster response)...", "startup")
    buffer = bytearray()
    last_send_time = time.time()

    while not shutdown_flag:
        try:
            # Try to get audio data
            try:
                data = audio_queue.get(timeout=0.1)
                if data:
                    buffer.extend(data)
            except queue.Empty:
                pass
            
            # Check if it's time to send accumulated audio for recognition
            current_time = time.time()
            if current_time - last_send_time >= ACCUMULATION_TIME:
                if len(buffer) > 0:
                    # Send to recognition queue (non-blocking, parallel processing)
                    recognition_queue.put(bytes(buffer))
                    buffer.clear()
                
                last_send_time = current_time

        except Exception as e:
            if not shutdown_flag:
                print_and_log(f"Accumulator Error: {e}", "error", {"error": str(e)})
                print_and_log("⚠️ Defaulting relay OFF due to processing error.", "warning")
                update_db("VOICE", "OFF")
            buffer.clear()
            last_send_time = time.time()
    
    # Send shutdown signal to recognition worker
    recognition_queue.put(None)
    print_and_log("🎙️ Audio accumulator stopped", "shutdown")

# ====================================================
# ========== MAIN STARTUP ============================
# ====================================================

if __name__ == "__main__":
    # Register cleanup handlers
    atexit.register(cleanup_resources)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print_and_log("🎙️ Starting Voice Control Service...", "startup")
    print_and_log("⚠️ Make sure GOOGLE_APPLICATION_CREDENTIALS is set!", "startup")
    
    try:
        # Start UDP receiver thread
        recv_thread = threading.Thread(target=udp_receiver, daemon=True)
        recv_thread.start()
        
        # Start multiple recognition workers for parallel processing
        num_workers = 2  # Run 2 workers in parallel for faster recognition
        recognition_threads = []
        for i in range(num_workers):
            t = threading.Thread(target=recognize_speech_worker, daemon=True)
            t.start()
            recognition_threads.append(t)
        
        # Run audio accumulator in main thread
        audio_accumulator()
        
    except KeyboardInterrupt:
        pass  # Handled by signal handler
    except Exception as e:
        print_and_log(f"Fatal error: {e}", "error", {"error": str(e)})
    finally:
        cleanup_resources()