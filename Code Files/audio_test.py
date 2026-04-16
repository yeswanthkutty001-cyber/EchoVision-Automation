import base64, requests, json

with open("esp32_audio_5s.wav", "rb") as f:
    audio = base64.b64encode(f.read()).decode()

url = "https://speech.googleapis.com/v1/speech:recognize?key=AIzaSyAsQL-hWG2B4uaoXPgQyzntQWvDuL4IPP0"
payload = {
  "config": {"encoding": "LINEAR16", "languageCode": "en-US"},
  "audio": {"content": audio}
}
resp = requests.post(url, json=payload)
print(json.dumps(resp.json(), indent=2))
