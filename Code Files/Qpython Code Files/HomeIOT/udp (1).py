from pyngrok import ngrok, conf
import os, certifi, ssl

NGROK_AUTH_TOKEN = ""
ESP32_LOCAL_IP = ""
ESP32_PORT = 81
ESP32_STREAM_PATH = "/stream"

# Fix Termux DNS & TLS issues
os.environ["SSL_CERT_FILE"] = certifi.where()
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["NGROK_REGION"] = "ap"
os.environ["DNS_SERVER"] = "8.8.8.8"

pyngrok_config = conf.PyngrokConfig(
    auth_token=NGROK_AUTH_TOKEN,
    region="ap"
)

print("🚀 Starting ngrok tunnel...")
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

try:
    tunnel = ngrok.connect(f"{ESP32_LOCAL_IP}:{ESP32_PORT}", "http", pyngrok_config=pyngrok_config)
    print(f"🌍 Public URL: {tunnel.public_url}{ESP32_STREAM_PATH}")
    print("\n🟢 Ngrok tunnel active. Press CTRL+C to exit.")

    while True:
        pass  # Keep alive
except KeyboardInterrupt:
    print("\n🛑 Stopping tunnel...")
    ngrok.disconnect(tunnel.public_url)
    ngrok.kill()
except Exception as e:
    print(f"❌ Ngrok error: {e}")