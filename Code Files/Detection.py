import cv2
import asyncio
import time
from kasa.iot import IotBulb
import speech_recognition as sr
import threading
import queue
import mediapipe as mp

# TP-Link bulb IP
BULB_IP = "192.168.1.8"

# Settings
NO_FACE_TIMEOUT = 5              # seconds after last seen face -> OFF
VOICE_SUPPRESS_WINDOW = 10       # seconds, ignore auto after voice cmd
ABSOLUTE_OVERRIDE_TIMEOUT = 15   # 30 minutes max override
FACE_REAPPEAR_GRACE = 5          # 5 sec grace after face disappears (for "light off")

# Initialize webcam
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# Speech recognizer
recognizer = sr.Recognizer()

# MediaPipe Pose
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

# State tracking
last_seen = time.time()
light_on = False
last_voice_command_time = 0
override_start_time = None
voice_override_mode = None  # "on" or "off"
face_gone_time = None
command_queue = queue.Queue()

async def turn_on(bulb):
    await bulb.update()
    if bulb.is_off:
        print("Turning light ON")
        await bulb.turn_on()
        return True
    return False

async def turn_off(bulb):
    await bulb.update()
    if bulb.is_on:
        print("Turning light OFF")
        await bulb.turn_off()
        return True
    return False

def voice_control_thread():
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source)
        while True:
            try:
                print("Listening for voice commands...")
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=3)
                command = recognizer.recognize_google(audio).lower()
                print(f"Voice command: {command}")
                light_words = ["light", "lights", "lamp"]
                if any(word in command for word in light_words):
                    command_queue.put(command)
            except (sr.WaitTimeoutError, sr.UnknownValueError, sr.RequestError):
                pass
            time.sleep(0.1)

async def process_voice_commands(bulb):
    global light_on, last_voice_command_time, override_start_time
    global voice_override_mode, face_gone_time
    try:
        command = command_queue.get_nowait()
        off_keywords = ["off", "out", "deactivate", "disable", "down", "dark"]
        on_keywords = ["on", "up", "activate", "enable", "bright"]
        if any(k in command for k in off_keywords):
            if await turn_off(bulb):
                light_on = False
            last_voice_command_time = time.time()
            override_start_time = None  # No timeout for "light off"
            voice_override_mode = "off"
            face_gone_time = None
        elif any(k in command for k in on_keywords):
            if await turn_on(bulb):
                light_on = True
            last_voice_command_time = time.time()
            override_start_time = time.time()
            voice_override_mode = "on"
            face_gone_time = None
    except queue.Empty:
        pass

async def main():
    global last_seen, light_on, last_voice_command_time, override_start_time
    global voice_override_mode, face_gone_time

    bulb = IotBulb(BULB_IP)
    await bulb.update()

    # Voice recognition thread
    threading.Thread(target=voice_control_thread, daemon=True).start()

    last_bulb_update = time.time()
    while True:
        start_time = time.time()

        ret, frame = cap.read()
        if not ret:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)
        human_detected = results.pose_landmarks is not None
        if human_detected:
            mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

        now = time.time()

        # Voice override logic
        override_active = False
        if override_start_time is not None:
            if now - override_start_time < ABSOLUTE_OVERRIDE_TIMEOUT:
                override_active = True
            else:
                print("Override expired (absolute timeout)")
                override_start_time = None
                voice_override_mode = None

        # Special case: Light OFF voice override
        if voice_override_mode == "off":
            if human_detected:
                face_gone_time = None  # reset grace timer
            else:
                if face_gone_time is None:
                    face_gone_time = now
                elif now - face_gone_time > FACE_REAPPEAR_GRACE:
                    # grace expired, revert to normal logic
                    voice_override_mode = None
                    override_start_time = None

        # Apply control logic
        if voice_override_mode == "on" and override_active:
            if not light_on:
                await turn_on(bulb)
                light_on = True
        elif voice_override_mode == "off":
            if light_on:
                await turn_off(bulb)
                light_on = False
        else:
            # Default auto logic
            if human_detected:
                last_seen = now
                if not light_on:
                    await turn_on(bulb)
                    light_on = True
            else:
                if light_on and (now - last_seen > NO_FACE_TIMEOUT):
                    print("No face long enough -> OFF")
                    await turn_off(bulb)
                    light_on = False

        # Update bulb state every 2s
        if now - last_bulb_update > 2:
            await bulb.update()
            last_bulb_update = now

        # Overlay
        status_text = f"Light: {'ON' if light_on else 'OFF'}"
        cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    1, (0, 255, 0) if light_on else (0, 0, 255), 2)

        mode_text = f"Mode: {voice_override_mode or 'AUTO'}"
        cv2.putText(frame, mode_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        fps = 1 / (now - start_time) if (now - start_time) > 0 else 0
        cv2.putText(frame, f"FPS: {int(fps)}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.imshow("Human Detection & Light Control", frame)

        # Process any queued voice commands
        await process_voice_commands(bulb)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

asyncio.run(main())