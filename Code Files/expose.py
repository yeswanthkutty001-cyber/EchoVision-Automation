from pyngrok import ngrok
import requests

# === USER CONFIGURATION ===
NGROK_AUTH_TOKEN = "33eFhguMPB6U0W3VKsVC1Phm9ov_5UxYtBf1ELBr3UBt6QGA6"   # Replace with your token
ESP32_LOCAL_IP = "192.168.1.16"              # Your ESP32-CAM local IP
ESP32_PORT = 81                              # Default camera web server port
ESP32_STREAM_PATH = "/stream"                # Stream path

# ==========================

def main():
    print("🚀 Setting up ngrok tunnel...")
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)

    # Start ngrok tunnel to ESP32-CAM web server
    public_tunnel = ngrok.connect(f"{ESP32_LOCAL_IP}:{ESP32_PORT}", "http")
    public_url = public_tunnel.public_url
    print(f"\n🌍 Public base URL: {public_url}")

    # Construct the stream URL
    stream_url = f"{public_url}{ESP32_STREAM_PATH}"
    print(f"🎥 ESP32-CAM Stream Public URL: {stream_url}")

    # Optional: test local camera stream availability
    esp32_local_url = f"http://{ESP32_LOCAL_IP}{ESP32_STREAM_PATH}"
    try:
        print("\n🔍 Checking local camera stream...")
        r = requests.get(esp32_local_url, stream=True, timeout=5)
        if r.status_code == 200:
            print(f"✅ ESP32-CAM stream reachable at {esp32_local_url}")
        else:
            print(f"⚠️ ESP32-CAM responded with status: {r.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Could not reach ESP32-CAM locally: {e}")

    print("\n🟢 Tunnel active! View your live stream here:")
    print(stream_url)

    print("\nPress CTRL+C to stop the tunnel and exit.")
    try:
        ngrok_process = ngrok.get_ngrok_process()
        ngrok_process.proc.wait()
    except KeyboardInterrupt:
        print("🛑 Tunnel closed by user.")
    except Exception as e:
        print(f"❗ ngrok error: {e}")

if __name__ == "__main__":
    main()