from flask import Flask, request
import wave
import time
import os

app = Flask(__name__)

# WAV parameters
SAMPLE_RATE = 16000  # Try 44100 if audio is fast-forwarded
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
DURATION = 5.0  # Save after 5 seconds
OUTPUT_FILE = "inmp441_recorded.wav"

# Buffer and timing
frames = []
start_time = None
last_packet_time = None

@app.route('/upload', methods=['POST'])
def upload():
    global frames, start_time, last_packet_time
    try:
        data = request.get_data()
        if not data:
            return {"status": "error", "message": "No data received"}, 400

        # Validate data size
        if len(data) % SAMPLE_WIDTH != 0:
            return {"status": "error", "message": f"Invalid data size: {len(data)} bytes"}, 400

        # Track packet timing
        current_time = time.time()
        if last_packet_time is not None:
            packet_gap = (current_time - last_packet_time) * 1000  # ms
            print(f"Packet gap: {packet_gap:.2f}ms")
        last_packet_time = current_time

        # Initialize start time
        if start_time is None:
            start_time = current_time

        # Append data
        frames.append(data)
        total_bytes = sum(len(chunk) for chunk in frames)
        duration = total_bytes / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)
        print(f"Received {len(data)} bytes, total: {total_bytes} bytes, duration: {duration:.2f}s")

        # Save after 5 seconds
        if duration >= DURATION:
            with wave.open(OUTPUT_FILE, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b''.join(frames))
            print(f"Saved {total_bytes} bytes ({duration:.2f}s) to {OUTPUT_FILE}")
            frames = []  # Clear buffer
            start_time = None
            last_packet_time = None

        return {"status": "success"}, 200
    except Exception as e:
        print(f"Error: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

if __name__ == '__main__':
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    print(f"Listening on /upload for {DURATION}s...")
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=False)