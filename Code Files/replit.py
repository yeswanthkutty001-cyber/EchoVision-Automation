import cv2

# Replace with your ngrok-exposed stream URL
url = "https://babara-unconnived-carman.ngrok-free.dev/stream"

# OpenCV VideoCapture can directly open MJPEG streams
cap = cv2.VideoCapture(url)

if not cap.isOpened():
    print("❌ Failed to open stream")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("⚠️ Failed to grab frame")
        break

    cv2.imshow("ESP32-CAM Stream", frame)

    # Press 'q' to exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()