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
from google.oauth2 import service_account

# ====================================================
# ========== CONFIGURATION ===========================
# ====================================================

# ---- GOOGLE CLOUD SPEECH CONFIG ----
SERVICE_ACCOUNT_PATH = ""
LANGUAGE = "en-US"
SAMPLE_RATE = 16000
CHANNELS = 1

# ---- UDP AUDIO SETTINGS ----
UDP_IP = "0.0.0.0"
UDP_PORT = 3333
ACCUMULATION_TIME = 1.5  # Reduced for faster response

# ---- ASTRA DB CONFIG ----
API_ENDPOINT = ""
ASTRA_TOKEN = ""
KEYSPACE = "iot"
TABLE = "truth"
URL = f"{API_ENDPOINT}/api/rest/v2/keyspaces/{KEYSPACE}/{TABLE}"
HEADERS = {"X-Cassandra-Token": ASTRA_TOKEN, "Content-Type": "application/json"}

DEVICE_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000000"))
IST = pytz.timezone("Asia/Kolkata")

# ---- REPLIT SERVER CONFIG ----
REPLIT_URL = ""
REPLIT_RETRY_INTERVAL = 30  # seconds

# ====================================================
# ========== GLOBAL RESOURCES ========================
# ====================================================

udp_socket = None
audio_queue = queue.Queue()
recognition_queue = queue.Queue()  # For parallel recognition
speech_client = None
shutdown_flag = False
replit_available = True
last_replit_attempt = 0

# ====================================================
# ========== REPLIT LOGGING ==========================
# ====================================================

def send_to_replit(text):
    """Send console output to Replit server."""
    global replit_available, last_replit_attempt
    
    current_time = time.time()
    
    # Skip if recently failed and retry interval hasn't passed
    if not replit_available and (current_time - last_replit_attempt) < REPLIT_RETRY_INTERVAL:
        return
    
    try:
        payload = {
            "recognized_text": text,
            "timestamp": datetime.datetime.now(IST).isoformat()
        }
        # POST to root endpoint
        r = requests.post(REPLIT_URL, json=payload, timeout=5)
        if r.ok:
            if not replit_available:
                print(f"✅ Replit server reconnected")
            replit_available = True
        else:
            # Only print error once when it first fails
            if replit_available:
                print(f"⚠️ Replit server error {r.status_code} (will retry every {REPLIT_RETRY_INTERVAL}s)")
            replit_available = False
            last_replit_attempt = current_time
    except Exception as e:
        if replit_available:
            print(f"⚠️ Replit server unavailable: {e} (will retry every {REPLIT_RETRY_INTERVAL}s)")
        replit_available = False
        last_replit_attempt = current_time

def log_print(message):
    """Print to console and send to Replit server."""
    print(message)
    # Send to Replit in background thread to avoid blocking
    threading.Thread(target=send_to_replit, args=(message,), daemon=True).start()

# ====================================================
# ========== DATABASE WITH RETRY =====================
# ====================================================

def update_db(mode, status, max_retries=3):
    """Push voice command result to Astra DB with retry logic."""
    now_ist = datetime.datetime.now(IST)
    iso_time = now_ist.isoformat()
    row = {
        "device_id": DEVICE_ID,
        "mode": mode,
        "status": status,
        "last_update": iso_time
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(URL, headers=HEADERS, json=row, timeout=5)
            if resp.status_code in (200, 201):
                msg = f"✅ DB Updated: mode={mode}, status={status}, time={iso_time}"
                log_print(msg)
                return True
            else:
                msg = f"❌ DB Error {resp.status_code}: {resp.text}"
                log_print(msg)
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                else:
                    log_print("⚠️ Defaulting relay OFF (DB write issue).")
                    return False
        except Exception as e:
            msg = f"❌ DB update failed (attempt {attempt}/{max_retries}): {e}"
            log_print(msg)
            if attempt < max_retries:
                time.sleep(1)
            else:
                log_print("⚠️ Defaulting relay OFF (network/db offline).")
                return False
    
    return False

# ====================================================
# ========== CLEANUP =================================
# ====================================================

def cleanup_resources():
    """Clean up all resources on shutdown."""
    global udp_socket, shutdown_flag
    
    log_print("\n🧹 Cleaning up resources...")
    shutdown_flag = True
    
    if udp_socket:
        try:
            udp_socket.close()
            log_print("✅ UDP socket closed")
        except Exception as e:
            log_print(f"⚠️ Error closing UDP socket: {e}")
    
    log_print("✅ Cleanup complete")

def signal_handler(signum, frame):
    """Handle CTRL+C and other termination signals."""
    log_print("\n🛑 Shutdown signal received...")
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
    log_print(f"🎤 Listening for UDP audio on port {UDP_PORT}...")
    
    while not shutdown_flag:
        try:
            data, _ = udp_socket.recvfrom(4096)
            audio_queue.put(data)
        except socket.timeout:
            continue
        except Exception as e:
            if not shutdown_flag:
                log_print(f"UDP Error: {e}")
            break
    
    log_print("🎤 UDP receiver stopped")

# ====================================================
# ========== PARALLEL SPEECH RECOGNITION =============
# ====================================================

def recognize_speech_worker():
    """Worker thread for parallel speech recognition."""
    global speech_client, shutdown_flag
    
    # Initialize speech client with service account credentials
    if speech_client is None:
        try:
            credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH)
            speech_client = speech.SpeechClient(credentials=credentials)
            log_print("✅ Google Speech client initialized with service account")
        except Exception as e:
            log_print(f"❌ Failed to initialize Google Speech client: {e}")
            return
    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=SAMPLE_RATE,
        language_code=LANGUAGE,
        enable_automatic_punctuation=True,
    )
    
    log_print("🧠 Speech recognition worker ready")
    
    while not shutdown_flag:
        try:
            audio_data = recognition_queue.get(timeout=0.5)
            
            if audio_data is None:
                continue
            
            # Recognize in parallel
            audio = speech.RecognitionAudio(content=audio_data)
            
            try:
                response = speech_client.recognize(config=config, audio=audio)
                
                for result in response.results:
                    text = result.alternatives[0].transcript.lower().strip()
                    conf = result.alternatives[0].confidence
                    msg = f"🗣 Recognized: {text} (conf={conf:.2f})"
                    log_print(msg)
                    
                    # Process command immediately
                    process_voice_command(text)
                
                if not response.results:
                    log_print("🤔 No speech detected.")
                    
            except Exception as e:
                log_print(f"⚠️ Google Speech API error: {e}")
                
        except queue.Empty:
            continue
        except Exception as e:
            if not shutdown_flag:
                log_print(f"Recognition worker error: {e}")
    
    log_print("🧠 Speech recognition worker stopped")

def process_voice_command(text):
    """Process recognized text and update DB."""
    on_phrases = ["turn on", "switch on", "light on", "activate light"]
    off_phrases = ["turn off", "switch off", "light off", "deactivate light"]
    auto_phrases = ["switch to auto", "go to auto", "enable auto", "automatic mode"]

    if any(p in text for p in on_phrases):
        update_db("VOICE", "ON")
    elif any(p in text for p in off_phrases):
        update_db("VOICE", "OFF")
    elif any(p in text for p in auto_phrases):
        update_db("AUTO", "OFF")

# ====================================================
# ========== AUDIO ACCUMULATOR =======================
# ====================================================

def audio_accumulator():
    """Accumulate audio and send to recognition workers."""
    global shutdown_flag
    
    log_print("🎙️ Audio accumulator running (1.5s chunks for faster response)...")
    buffer = bytearray()
    last_send_time = time.time()

    while not shutdown_flag:
        try:
            try:
                data = audio_queue.get(timeout=0.1)
                buffer.extend(data)
            except queue.Empty:
                pass
            
            # Send accumulated audio for recognition
            current_time = time.time()
            if len(buffer) > 0 and (current_time - last_send_time) >= ACCUMULATION_TIME:
                # Send to recognition queue (non-blocking)
                recognition_queue.put(bytes(buffer))
                buffer.clear()
                last_send_time = current_time

        except Exception as e:
            if not shutdown_flag:
                log_print(f"Accumulator Error: {e}")
                log_print("⚠️ Defaulting relay OFF due to processing error.")
                update_db("VOICE", "OFF")
            buffer.clear()
            last_send_time = time.time()
    
    log_print("🎙️ Audio accumulator stopped")

# ====================================================
# ========== MAIN STARTUP ============================
# ====================================================

if __name__ == "__main__":
    # Register cleanup handlers
    atexit.register(cleanup_resources)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🎙️ Starting Optimized Voice Control Service...")
    print(f"🔑 Using service account: {SERVICE_ACCOUNT_PATH}")
    
    # Test Replit server connection
    print(f"🌐 Testing Replit server connection: {REPLIT_URL}")
    try:
        test_resp = requests.get(f"{REPLIT_URL}/health", timeout=5)
        if test_resp.ok:
            print("✅ Replit server is reachable")
            replit_available = True
        else:
            print(f"⚠️ Replit server returned {test_resp.status_code} (logs will be local only, retrying every {REPLIT_RETRY_INTERVAL}s)")
            replit_available = False
    except Exception as e:
        print(f"⚠️ Replit server not reachable: {e}")
        print(f"   Logs will be local only. Will retry every {REPLIT_RETRY_INTERVAL}s")
        replit_available = False
        last_replit_attempt = time.time()
    
    try:
        # Start UDP receiver thread
        recv_thread = threading.Thread(target=udp_receiver, daemon=True)
        recv_thread.start()
        
        # Start multiple recognition workers for parallel processing
        num_workers = 3  # Process up to 3 recognitions in parallel
        recognition_threads = []
        for i in range(num_workers):
            worker = threading.Thread(target=recognize_speech_worker, daemon=True)
            worker.start()
            recognition_threads.append(worker)
            print(f"✅ Started recognition worker {i+1}/{num_workers}")
        
        # Run audio accumulator in main thread
        audio_accumulator()
        
    except KeyboardInterrupt:
        pass  # Handled by signal handler
    finally:
        cleanup_resources()