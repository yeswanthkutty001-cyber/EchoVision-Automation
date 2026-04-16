import time
import requests

URL = "https://677c562b-0436-440b-9454-1e39a4bd51d8-00-tkficnqryakd.pike.replit.dev/"

i = 1
while True:
    payload = {"text": f"Hello Replit! Message #{i}"}
    try:
        resp = requests.post(URL, json=payload, timeout=5)
        print(f"Sent #{i}, Response: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ Error sending data: {e}")
    i += 1
    time.sleep(5)
