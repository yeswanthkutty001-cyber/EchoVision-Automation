#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// === WiFi Credentials ===
const char* ssid = "";
const char* password = "";

// === Astra DB REST API ===
const char* API_URL = "";
const char* AUTH_TOKEN = "";

#define RELAY_PIN 23
#define LED_PIN   2     // Built-in LED for most ESP32 boards
#define DEVICE_ID "00000000-0000-0000-0000-000000000000"

unsigned long lastCheck = 0;
const unsigned long CHECK_INTERVAL = 2000; // every 2 sec
bool relayState = false;

bool previouslyConnected = false;
unsigned long lastReconnectAttempt = 0;
const unsigned long RECONNECT_INTERVAL = 10000; // attempt reconnect every 10 sec
unsigned long lastBlink = 0;
const unsigned long BLINK_INTERVAL = 500; // blink every 500ms

// === Helper: Convert string to lowercase ===
String toLowerCaseStr(const char* input) {
  String s = String(input);
  s.toLowerCase();
  return s;
}

// === Helper: Determine if string means ON ===
bool isOnCommand(String val) {
  val.toLowerCase();
  return (val == "on" || val == "activate" || val == "activated" ||
          val == "enabled" || val == "start" || val == "1" || val == "true");
}

// === Helper: Determine if string means OFF ===
bool isOffCommand(String val) {
  val.toLowerCase();
  return (val == "off" || val == "deactivate" || val == "disabled" ||
          val == "stop" || val == "0" || val == "false");
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH);
  digitalWrite(LED_PIN, LOW);

  WiFi.begin(ssid, password);
  Serial.print("🔌 Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi Connected");
  Serial.print("📶 IP: ");
  Serial.println(WiFi.localIP());
  previouslyConnected = true;
}

void loop() {
  bool isConnected = (WiFi.status() == WL_CONNECTED);
  unsigned long now = millis();

  if (!isConnected) {
    previouslyConnected = false;

    // Blink LED to indicate disconnection
    if (now - lastBlink >= BLINK_INTERVAL) {
      lastBlink = now;
      digitalWrite(LED_PIN, digitalRead(LED_PIN) == LOW ? HIGH : LOW);
    }

    // Attempt to reconnect periodically
    if (now - lastReconnectAttempt >= RECONNECT_INTERVAL) {
      lastReconnectAttempt = now;
      Serial.println("🔄 Attempting WiFi reconnect...");
      WiFi.begin(ssid, password);
    }

    return; // Skip sync while disconnected; keep relay in last state
  }

  // WiFi is connected
  if (!previouslyConnected) {
    // Just reconnected - sync immediately
    previouslyConnected = true;
    Serial.println("✅ WiFi Reconnected!");
    syncRelayWithDB();
    lastCheck = now;
  } else {
    // Normal operation
    if (now - lastCheck > CHECK_INTERVAL) {
      lastCheck = now;
      syncRelayWithDB();
    }
  }
}

// === Function: Read DB and control relay + LED ===
void syncRelayWithDB() {
  HTTPClient http;
  String url = String(API_URL) + "/" + DEVICE_ID;
  http.begin(url);
  http.addHeader("X-Cassandra-Token", AUTH_TOKEN);
  http.addHeader("Content-Type", "application/json");

  Serial.println("🌐 Requesting DB data...");
  int httpCode = http.GET();

  if (httpCode == 200) {
    String payload = http.getString();
    Serial.println("📦 DB Response: " + payload);

    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, payload);

    if (error) {
      Serial.print("❌ JSON parse error: ");
      Serial.println(error.c_str());
      setRelayOff();
      return;
    }

    JsonArray rows = doc["data"].as<JsonArray>();
    if (rows.size() == 0) {
      Serial.println("⚠️ No rows in DB!");
      setRelayOff();
      return;
    }

    JsonObject row = rows[0];

    const char* mode_c = row.containsKey("mode") ? row["mode"].as<const char*>() : "AUTO";
    const char* status_c = row.containsKey("status") ? row["status"].as<const char*>() : "OFF";
    const char* ts_c = row.containsKey("last_update") ? row["last_update"].as<const char*>() : "N/A";

    String status_str = toLowerCaseStr(status_c);
    Serial.printf("🗄 DB → mode=%s | status=%s | last_update=%s\n", mode_c, status_c, ts_c);

    // === Relay Logic with flexible keyword matching ===
    if (isOnCommand(status_str)) {
      if (!relayState) {
        setRelayOn();
        relayState = true;
        Serial.println("⚡ Relay → ON | 💡 LED → ON");
      }
    } else if (isOffCommand(status_str)) {
      if (relayState) {
        setRelayOff();
        relayState = false;
        Serial.println("💤 Relay → OFF | 💡 LED → OFF");
      }
    } else {
      Serial.printf("⚠️ Unknown status keyword: '%s' → Defaulting OFF\n", status_c);
      setRelayOff();
      relayState = false;
    }
  } 
  else {
    Serial.printf("❌ HTTP Error: %d\n", httpCode);
    Serial.println("Defaulting Relay & LED → OFF");
    setRelayOff();
    relayState = false;
  }

  http.end();
}

// === Helper: Set relay ON (LOW for reverse relay) ===
void setRelayOn() {
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(LED_PIN, HIGH);
}

// === Helper: Set relay OFF (HIGH for reverse relay) ===
void setRelayOff() {
  digitalWrite(RELAY_PIN, HIGH);
  digitalWrite(LED_PIN, LOW);
}