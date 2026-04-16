# Smart Vision & Voice-Based Automation System

## Overview

This project is an advanced IoT-based automation system that integrates computer vision and speech recognition to control electronic appliances in real time. It combines ESP32 hardware modules for data acquisition and actuation with a distributed AI processing system running on a laptop/server.

The system is designed to detect human presence using video input and interpret voice commands using audio input, enabling intelligent, hands-free control of devices through wireless communication.



## System Architecture

The system follows a distributed architecture consisting of three layers:

### 1. Edge Layer (Data Capture & Actuation)

* ESP32-CAM captures real-time video frames
* INMP441 I²S Microphone (ESP32) captures audio signals
* Relay Module (3V) controls external appliances
* ESP32 modules communicate with the server over WiFi using HTTP/WebSockets

### 2. Processing Layer (AI Server)

* Runs on a local machine (laptop/server)
* Handles:

  * Video stream processing
  * Audio transcription
  * Command inference
* Uses multiple scripts and services to process data pipelines in parallel

### 3. Communication Layer

* Bi-directional communication between ESP32 and server
* Protocols used:

  * HTTP (for API-based communication)
  * WebSockets (for real-time streaming and control)



## Technical Implementation

### Video Processing Pipeline

1. ESP32-CAM streams frames over WiFi
2. Frames are received by the server
3. Processed using:

   * OpenCV for frame handling
   * MediaPipe / YOLO models (in testing) for detection
4. Face detection triggers event-based actions (e.g., presence detection)



### Audio Processing Pipeline

1. INMP441 microphone captures audio via ESP32
2. Audio is transmitted or recorded locally
3. Processed using:

   * SpeechRecognition library
   * Vosk offline speech-to-text model
4. Extracted text is passed to command handler



### Command Processing Logic

* Combines outputs from:

  * Vision system (face detection)
  * Audio system (voice commands)
* Uses rule-based or script-based logic to determine actions
* Example:

  * If face detected → system active
  * If command = "turn on light" → send ON signal



### Control Execution

1. Server sends command to ESP32 via WebSocket/HTTP
2. ESP32 interprets command
3. Relay module switches appliance ON/OFF



## Project Structure

```id="h7e4xv"
Project Root/
│
├── Arduino_ESP32 Code Files/
│   ├── CameraTest/
│   ├── ESP32-CAM/
│   ├── Mic/
│   ├── Relay/
│   └── Websockets/
│
├── Code Files/
│   ├── Replit Code Files/
│   ├── Qpython Code Files/
│   │
│   ├── ast_update/
│   ├── audio_test/
│   ├── audio-transcribe-47691/
│   ├── correct/
│   ├── Detection/
│   ├── expose/
│   ├── HomelOT-token/
│   ├── local-server/
│   ├── mail/
│   ├── mic/
│   ├── new_audio/
│   ├── phone_audio_code/
│   ├── receive_mic/
│   ├── replit/
│   ├── sender/
│   ├── server/
│   ├── sleep/
│   ├── test/
│   ├── test_mic/
│   └── text_sender/
│
├── Libs/                            # External libraries and dependencies
│
├── Testing/
│   ├── audio outputs
│   ├── testing videos
│   ├── logs
│   └── YOLO model files
│
├── Vosk Model/
│   └── (offline speech recognition model files)
│
└── README.md
```



## Technologies Used

### Hardware

* ESP32-CAM
* INMP441 I²S Microphone
* Relay Module

### Software & Libraries

* Python
* OpenCV
* MediaPipe
* YOLO (for object detection testing)
* SpeechRecognition
* Vosk (offline speech recognition)

### Communication

* WiFi
* HTTP APIs
* WebSockets



## How It Works (End-to-End Flow)

1. ESP32-CAM streams video → Server
2. Microphone captures audio → Server
3. Server processes:

   * Video → Face detection
   * Audio → Speech-to-text
4. Command engine interprets results
5. Control signal sent back to ESP32
6. Relay module activates/deactivates appliance

## Demo Video
[Testing Demo](https://drive.google.com/file/d/1bOfJCe1qBDnQK8SXByHbNH3_Korwtrig/view?usp=sharing)

[Audio_Output](https://drive.google.com/file/d/14Ou6jSrwt7Zl8uW8i5zo_ePjKNm3YymJ/view?usp=sharing)

## Installation & Setup

### Prerequisites

* Python 3.8+
* Arduino IDE (ESP32 support installed)

### Install Dependencies

```bash id="3rqj9z"
pip install opencv-python mediapipe SpeechRecognition vosk numpy
```



## Running the System

### Step 1: Upload ESP32 Code

* Open Arduino IDE
* Upload respective modules:

  * Camera
  * Mic
  * Relay
  * WebSocket handler

### Step 2: Start Server

```bash id="llg0pm"
python server/main.py
```

### Step 3: Ensure Connectivity

* Connect ESP32 and server to same WiFi network

### Step 4: Run System

* Start video stream
* Speak commands
* Observe automated control via relay



## Testing & Development

* Testing folder includes:

  * Audio samples
  * Video recordings
  * Logs for debugging
  * YOLO models for experimentation

* Vosk Model folder enables offline speech recognition without internet dependency



## Use Cases

* Smart home automation
* Touchless control systems
* Assistive technologies
* Security monitoring
* IoT-based intelligent environments



## Future Enhancements

* Face recognition (identity-based control)
* Mobile app integration
* Cloud deployment
* Multi-device orchestration
* Advanced NLP for contextual commands



## Limitations

* Requires stable WiFi connectivity
* Audio accuracy depends on noise conditions
* Vision accuracy depends on lighting and camera quality



## License

This project is developed for educational and experimental purposes.



## Conclusion

This project demonstrates a complete integration of embedded systems, real-time communication, and AI-based processing. It showcases how vision and voice interfaces can be combined to build scalable, intelligent automation systems for modern IoT environments.
