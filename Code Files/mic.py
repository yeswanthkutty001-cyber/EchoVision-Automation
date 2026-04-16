import serial
import numpy as np
import soundfile as sf
import time

# === CONFIG ===
PORT = "COM3"           # change to your ESP32 port
BAUD = 921600
DURATION = 10            # seconds
SAMPLE_RATE = 8000

# === SETUP SERIAL ===
ser = serial.Serial(PORT, BAUD, timeout=1)
print("Listening to ESP32...")

audio_data = bytearray()
start_time = time.time()

while time.time() - start_time < DURATION:
    data = ser.read(1024)
    if data:
        audio_data.extend(data)

ser.close()

print(f"Received {len(audio_data)} bytes")

# === CONVERT TO NUMPY ARRAY ===
samples = np.frombuffer(audio_data, dtype=np.int16)

# === SAVE AS WAV ===
sf.write("esp32_inmp441_recording.wav", samples, SAMPLE_RATE)
print("✅ Saved as esp32_inmp441_recording.wav")