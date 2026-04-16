import socket
import wave
import time

UDP_IP = "0.0.0.0"      # listen on all interfaces
UDP_PORT = 5005
DURATION = 5             # seconds
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2         # bytes (16-bit)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(2)

print(f"Listening on UDP {UDP_PORT} for {DURATION}s...")

frames = []
start = time.time()

while time.time() - start < DURATION:
    try:
        data, addr = sock.recvfrom(4096)
        frames.append(data)
    except socket.timeout:
        pass

sock.close()
print(f"Received {len(frames)} packets")

# Save as WAV
with wave.open("inmp441_recorded.wav", "wb") as wf:
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(SAMPLE_WIDTH)
    wf.setframerate(SAMPLE_RATE)
    wf.writeframes(b"".join(frames))

print("Saved to inmp441_recorded.wav ✅")