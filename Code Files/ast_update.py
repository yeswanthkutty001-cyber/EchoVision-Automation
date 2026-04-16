import requests
import datetime
import uuid
import json
import pytz   # install in Pydroid: pip install pytz

# === Astra DB REST API connection ===
API_ENDPOINT = ""
ASTRA_TOKEN = ""   # paste your token

KEYSPACE = "iot"
TABLE = "truth"
URL = f"{API_ENDPOINT}/api/rest/v2/keyspaces/{KEYSPACE}/{TABLE}"

headers = {
    "X-Cassandra-Token": ASTRA_TOKEN,
    "Content-Type": "application/json"
}

# --- Local timezone for Chennai ---
IST = pytz.timezone("Asia/Kolkata")

def update_db(mode, status):
    now_ist = datetime.datetime.now(IST)
    iso_time = now_ist.isoformat()      # example: 2025-11-01T21:05:30.123+05:30
    device_id = str(uuid.UUID("00000000-0000-0000-0000-000000000000"))

    row = {
        "device_id": device_id,
        "mode": mode,
        "status": status,
        "last_update": iso_time
    }

    try:
        response = requests.post(URL, headers=headers, json=row)
        print(f"📡 DB Updated → mode={mode}, status={status}, time={iso_time}")
        print("Response:", response.text)
    except Exception as e:
        print("❌ DB update failed:", e)


# ---- Example test ----
if __name__ == "__main__":
    update_db("AUTO", "OFF")