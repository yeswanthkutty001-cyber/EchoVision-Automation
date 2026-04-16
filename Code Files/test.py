import socket
import pyaudio
import speech_recognition as sr
import requests
import threading
import time
import queue

# ===== UDP Settings =====
UDP_IP = "0.0.0.0"
UDP_PORT = 3333
CHUNK = 512
SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16

# ===== Replit Endpoint =====
REPLIT_URL = "https://677c562b-0436-440b-9454-1e39a4bd51d8-00-tkficnqryakd.pike.replit.dev/"

# ===== Shared Queue for Audio =====
audio_queue = queue.Queue()

# ===== PyAudio Playback =====
p = pyaudio.PyAudio()
stream = p.open(format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=CHUNK)

recognizer = sr.Recognizer()

# ===== Helper: Send to Replit =====
def send_to_replit(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = {"message": message, "timestamp": timestamp}
    try:
        requests.post(REPLIT_URL, json=payload, timeout=2)
        print(f"📤 Sent to Replit: {payload}")
    except Exception as e:
        print(f"❌ Failed to send: {e}")

# ===== Thread 1: Receive UDP Audio =====
def udp_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(0.5)
    print(f"🎤 Listening on UDP {UDP_PORT}...")
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            stream.write(data)              # Play immediately
            audio_queue.put(data)           # Queue for recognition
        except socket.timeout:
            continue
        except Exception as e:
            print(f"UDP Receiver error: {e}")

# ===== Thread 2: Process Audio & Recognize Commands =====
def audio_processor():
    buffer = []
    BUFFER_CHUNKS = int(SAMPLE_RATE * 1 / CHUNK)  # ~1 second chunks
    while True:
        try:
            data = audio_queue.get()
            buffer.append(data)
            if len(buffer) >= BUFFER_CHUNKS:
                audio_bytes = b"".join(buffer)
                audio_data = sr.AudioData(audio_bytes, SAMPLE_RATE, 2)
                try:
                    text = recognizer.recognize_google(audio_data).lower()
                    print(f"🗣 Recognized: {text}")
                    # Command detection
                    on_keywords = ["on", "up", "activate", "enable", "bright"]
                    off_keywords = ["off", "out", "deactivate", "disable", "dark", "down"]
                    if any(k in text for k in on_keywords):
                        send_to_replit("VOICE:ON")
                    elif any(k in text for k in off_keywords):
                        send_to_replit("VOICE:OFF")
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    print(f"Speech Recognition error: {e}")
                buffer = []  # Reset after processing
        except Exception as e:
            print(f"Processor error: {e}")

# ===== Start Threads =====
receiver_thread = threading.Thread(target=udp_receiver, daemon=True)
processor_thread = threading.Thread(target=audio_processor, daemon=True)
receiver_thread.start()
processor_thread.start()

# Keep main thread alive
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping...")
    stream.stop_stream()
    stream.close()
    p.terminate()