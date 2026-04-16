import cv2
import numpy as np
import requests
import re
import threading
import queue
import time
import mediapipe as mp

# ======================================
# CONFIG
# ======================================
URL = "http://192.168.1.20:81/stream"   # or your ngrok URL
CHUNK = 4096
MAX_FPS = 30
frame_queue = queue.Queue(maxsize=2)

# ======================================
# MEDIAPIPE SETUP
# ======================================
mp_drawing = mp.solutions.drawing_utils
mp_pose = mp.solutions.pose

# Optimized for partial-body detection
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    enable_segmentation=False,
    smooth_landmarks=True,
    min_detection_confidence=0.4,   # lower to catch partial humans
    min_tracking_confidence=0.3
)

# ======================================
# MJPEG STREAM READER (THREAD)
# ======================================
def mjpeg_reader(url):
    try:
        print(f"Connecting to {url}")
        r = requests.get(url, stream=True)
        ct = r.headers.get('Content-Type', '')
        print("Headers:", ct)
        m = re.search('boundary=(.*)', ct)
        boundary = ('--' + m.group(1).strip()).encode() if m else b'--frame'
        print("Using boundary:", boundary)

        buffer = b""
        for chunk in r.iter_content(chunk_size=CHUNK):
            buffer += chunk

            while True:
                start = buffer.find(boundary)
                if start == -1:
                    break

                header_end = buffer.find(b'\r\n\r\n', start)
                if header_end == -1:
                    break

                header = buffer[start:header_end].decode(errors='ignore')
                mlen = re.search(r'Content-Length:\s*(\d+)', header, re.IGNORECASE)
                if not mlen:
                    break

                length = int(mlen.group(1))
                image_start = header_end + 4
                image_end = image_start + length
                if len(buffer) < image_end:
                    break

                jpg = buffer[image_start:image_end]
                buffer = buffer[image_end:]  # ✅ keep remainder only

                frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    if frame_queue.full():
                        try:
                            frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    frame_queue.put(frame)
    except Exception as e:
        print(f"❌ Stream error: {e}")


# ======================================
# START THREAD
# ======================================
threading.Thread(target=mjpeg_reader, args=(URL,), daemon=True).start()
print("🔄 Reader thread started.")


# ======================================
# MAIN LOOP: PROCESS + DISPLAY
# ======================================
prev_time = time.time()
fps_list = []

while True:
    if not frame_queue.empty():
        frame = frame_queue.get()
        h, w, _ = frame.shape

        # Convert to RGB for MediaPipe
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(frame_rgb)

        # Human detection logic
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(
                frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                mp_drawing.DrawingSpec(color=(0,255,0), thickness=2, circle_radius=2),
                mp_drawing.DrawingSpec(color=(255,0,0), thickness=2)
            )
            cv2.putText(frame, "Human Detected", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
        else:
            cv2.putText(frame, "No Human", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)

        # Compute FPS
        now = time.time()
        fps = 1.0 / (now - prev_time)
        prev_time = now
        fps_list.append(fps)
        if len(fps_list) > 30:
            fps_list.pop(0)
        avg_fps = sum(fps_list) / len(fps_list)

        cv2.putText(frame, f"FPS: {avg_fps:.1f}", (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,0), 2)

        cv2.imshow("ESP32-CAM Human Detection (Optimized)", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

    # Keep GUI responsive and CPU low
    time.sleep(max(0, 1.0 / MAX_FPS))

cv2.destroyAllWindows()