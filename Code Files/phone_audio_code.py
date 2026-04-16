import threading
import queue
import time
import requests
import datetime
import uuid
import pytz
import io
import wave
import signal
import sys
import atexit
import pyaudio

from google.cloud import speech
from google.oauth2 import service_account

# ======= GOOGLE CLOUD SPEECH CONFIG =======
SERVICE_ACCOUNT_PATH = ""
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH)
speech_client = speech.SpeechClient(credentials=credentials)

# ======= AUDIO SETTINGS =======
SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # 16-bit PCM
CHUNK_SIZE = 1024
ACCUMULATION_TIME = 5  # seconds of audio per API call

# ======= ASTRA DB REST API CONFIG =======
API_ENDPOINT = ""
ASTRA_TOKEN = ""
KEYSPACE = "iot"
TABLE = "truth"
URL = f"{API_ENDPOINT}/api/rest/v2/keyspaces/{KEYSPACE}/{TABLE}"

headers = {
    "X-Cassandra-Token": ASTRA_TOKEN,
    "Content-Type": "application/json"
}

IST = pytz.timezone("Asia/Kolkata")
DEVICE_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000000"))

# ======= GLOBAL RESOURCES =======
audio_queue = queue.Queue()
audio_interface = None
audio_stream = None
shutdown_flag = False

# ======= CLEANUP HANDLER =======
def cleanup_resources():
    """Clean up all resources on shutdown."""
    global audio_stream, audio_interface, shutdown_flag
    
    print("\n🧹 Cleaning up resources...")
    shutdown_flag = True
    
    # Close audio stream
    if audio_stream:
        try:
            audio_stream.stop_stream()
            audio_stream.close()
            print("✅ Audio stream closed")
        except Exception as e:
            print(f"⚠️ Error closing audio stream: {e}")
    
    # Terminate PyAudio
    if audio_interface:
        try:
            audio_interface.terminate()
            print("✅ PyAudio terminated")
        except Exception as e:
            print(f"⚠️ Error terminating PyAudio: {e}")
    
    print("✅ Cleanup complete")

def signal_handler(signum, frame):
    """Handle CTRL+C and other termination signals."""
    print("\n🛑 Shutdown signal received...")
    cleanup_resources()
    sys.exit(0)

# ======= ASTRA DB UPDATER =======
def update_db(mode, status):
    now_ist = datetime.datetime.now(IST)
    iso_time = now_ist.isoformat()
    row = {
        "device_id": DEVICE_ID,
        "mode": mode,
        "status": status,
        "last_update": iso_time
    }
    try:
        resp = requests.post(URL, headers=headers, json=row, timeout=5)
        if resp.status_code in (200, 201):
            print(f"✅ DB Updated: mode={mode}, status={status}, time={iso_time}")
        else:
            print(f"❌ DB Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print("❌ DB update failed:", e)

# ======= PC MIC AUDIO RECEIVER THREAD =======
def mic_receiver():
    """Capture audio from PC microphone and enqueue it."""
    global audio_interface, audio_stream, shutdown_flag
    
    audio_interface = pyaudio.PyAudio()
    
    # List available devices
    print("\n🎤 Available audio input devices:")
    for i in range(audio_interface.get_device_count()):
        info = audio_interface.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            print(f"  [{i}] {info['name']} (Channels: {info['maxInputChannels']})")
    
    # Open default microphone
    try:
        audio_stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        print(f"\n✅ PC Microphone opened (Rate: {SAMPLE_RATE}Hz, Channels: {CHANNELS})")
    except Exception as e:
        print(f"❌ Failed to open microphone: {e}")
        return
    
    print(f"🎤 Listening to PC microphone...")
    
    while not shutdown_flag:
        try:
            data = audio_stream.read(CHUNK_SIZE, exception_on_overflow=False)
            audio_queue.put(data)
        except Exception as e:
            if not shutdown_flag:
                print(f"Microphone Error: {e}")
            break
    
    print("🎤 Microphone receiver stopped")

# ======= GOOGLE SPEECH PROCESSOR (5-sec accumulation) =======
def audio_processor():
    print(f"🧠 Speech Processor running ({ACCUMULATION_TIME}s accumulation)...")

    buffer = bytearray()
    last_send_time = time.time()

    while not shutdown_flag:
        try:
            try:
                data = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
                
            if not data:
                continue

            buffer.extend(data)

            # If ACCUMULATION_TIME seconds have passed → send to Google
            if time.time() - last_send_time >= ACCUMULATION_TIME:
                if len(buffer) == 0:
                    last_send_time = time.time()
                    continue

                # Convert PCM16 bytes → WAV in memory
                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(BYTES_PER_SAMPLE)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(buffer)
                wav_buf.seek(0)

                # Google Speech config
                audio = speech.RecognitionAudio(content=wav_buf.read())
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=SAMPLE_RATE,
                    language_code="en-US"
                )

                print(f"🎧 Sending {ACCUMULATION_TIME}s audio chunk to Google STT...")
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

                # Reset buffer and timer
                buffer.clear()
                last_send_time = time.time()

        except Exception as e:
            if not shutdown_flag:
                print(f"Processor Error: {e}")
            buffer.clear()
            last_send_time = time.time()
    
    print("🧠 Speech processor stopped")

# ======= MAIN STARTUP =======
if __name__ == "__main__":
    # Register cleanup handlers
    atexit.register(cleanup_resources)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🎙️ Starting Voice Control Service (PC Microphone)...")
    
    # ======= THREADS =======
    receiver_thread = threading.Thread(target=mic_receiver, daemon=True)
    processor_thread = threading.Thread(target=audio_processor, daemon=True)
    receiver_thread.start()
    processor_thread.start()

    print("🚀 All systems online: PC Mic + Voice Control active.\n")

    # ======= KEEP MAIN ALIVE =======
    try:
        while not shutdown_flag:
            time.sleep(1)
    except KeyboardInterrupt:
        pass  # Handled by signal handler
    finally:
        cleanup_resources()