import cv2
import time
import threading
import numpy as np
import mediapipe as mp

# -------- CONFIG --------
STREAM_URL = "https://babara-unconnived-carman.ngrok-free.dev/stream"   # ESP32 MJPEG stream
DETECTION_SIZE = (320, 240)                   # inference resolution
SKIP_IF_PROCESSING = True
# ------------------------

mp_drawing = mp.solutions.drawing_utils
mp_holistic = mp.solutions.holistic

# Shared data
_latest_frame = None
_processed_frame = None
_latest_frame_lock = threading.Lock()
_processed_frame_lock = threading.Lock()
_should_stop = threading.Event()

class CaptureThread(threading.Thread):
    def run(self):
        global _latest_frame
        cap = cv2.VideoCapture(STREAM_URL, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            print("[CAPTURE] Could not open stream.")
            _should_stop.set()
            return
        print("[CAPTURE] Stream opened.")

        while not _should_stop.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            with _latest_frame_lock:
                _latest_frame = frame
        cap.release()

class ProcessThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.holistic = mp_holistic.Holistic(
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            model_complexity=1
        )

    def run(self):
        global _latest_frame, _processed_frame
        while not _should_stop.is_set():
            with _latest_frame_lock:
                frame = None if _latest_frame is None else _latest_frame.copy()

            if frame is None:
                time.sleep(0.01)
                continue

            # Resize for inference
            resized = cv2.resize(frame, DETECTION_SIZE)
            rgb_small = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

            results = self.holistic.process(rgb_small)

            # Draw landmarks directly on full frame
            draw_frame = frame.copy()

            if results.pose_landmarks:
                mp_drawing.draw_landmarks(draw_frame, results.pose_landmarks, mp_holistic.POSE_CONNECTIONS)
            if results.face_landmarks:
                mp_drawing.draw_landmarks(draw_frame, results.face_landmarks, mp_holistic.FACEMESH_CONTOURS)
            if results.left_hand_landmarks:
                mp_drawing.draw_landmarks(draw_frame, results.left_hand_landmarks, mp_holistic.HAND_CONNECTIONS)
            if results.right_hand_landmarks:
                mp_drawing.draw_landmarks(draw_frame, results.right_hand_landmarks, mp_holistic.HAND_CONNECTIONS)

            with _processed_frame_lock:
                _processed_frame = draw_frame

        self.holistic.close()

def main():
    global _processed_frame
    cap_thread = CaptureThread()
    proc_thread = ProcessThread()
    cap_thread.start()
    proc_thread.start()

    fps_counter, last_time = 0, time.time()
    fps = 0

    print("[MAIN] Press ESC to quit.")
    while not _should_stop.is_set():
        with _processed_frame_lock:
            frame = None if _processed_frame is None else _processed_frame.copy()

        if frame is not None:
            fps_counter += 1
            now = time.time()
            if now - last_time >= 1.0:
                fps = fps_counter / (now - last_time)
                fps_counter, last_time = 0, now
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            cv2.imshow("ESP32 + Mediapipe", frame)
        else:
            blank = np.zeros((480,640,3), dtype=np.uint8)
            cv2.putText(blank, "Waiting for frames...", (50,250),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
            cv2.imshow("ESP32 + Mediapipe", blank)

        if cv2.waitKey(1) == 27:  # ESC
            _should_stop.set()
            break

    cap_thread.join()
    proc_thread.join()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()