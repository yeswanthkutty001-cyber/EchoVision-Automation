#include <WiFi.h>
#include <WiFiUdp.h>
#include <driver/i2s.h>

// ===== WiFi Credentials =====
const char* ssid = "Satishbalaji_4G";
const char* password = "Satrohi1";

// ===== UDP Server (your phone/PC IP + port) =====
const char* udpAddress = "192.168.1.163";  // Change to your phone/PC IP
const int udpPort = 3333;

WiFiUDP udp;

// ===== I2S Microphone Pins =====
#define I2S_WS 25  // LRCLK
#define I2S_SCK 33 // BCLK
#define I2S_SD 32  // DOUT

// ====== Helper functions ======
void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 40) { // ~12s timeout
    delay(300);
    Serial.print(".");
    retry++;
  }
  if (WiFi.status() == WL_CONNECTED)
    Serial.println("\n✅ Connected! IP: " + WiFi.localIP().toString());
  else {
    Serial.println("\n⚠ WiFi failed, retrying in 5s...");
    delay(5000);
    connectWiFi();
  }
}

bool micSelfTest() {
  const int samples = 256;
  int32_t buffer[samples];
  size_t bytesRead;
  i2s_read(I2S_NUM_0, (void*)buffer, sizeof(buffer), &bytesRead, portMAX_DELAY);
  int count = bytesRead / sizeof(int32_t);

  long sum = 0;
  int32_t prev = buffer[0];
  int stableCount = 0;
  for (int i = 0; i < count; i++) {
    sum += abs(buffer[i]);
    if (buffer[i] == prev) stableCount++;
    prev = buffer[i];
  }

  long avg = sum / count;
  if (avg < 100 || stableCount > count * 0.9) {
    Serial.println("❌ Mic test failed (silent or stuck values)");
    return false;
  }
  return true;
}

void safeShutdown() {
  Serial.println("\n🧹 Cleaning up resources...");
  udp.stop();
  i2s_driver_uninstall(I2S_NUM_0);
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  Serial.println("✅ UDP + I2S + WiFi safely closed.");
}

// ===== Main =====
void setup() {
  Serial.begin(115200);
  Serial.println("Connecting to WiFi...");
  connectWiFi();

  // ===== I2S Config =====
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = 0,
    .dma_buf_count = 4,
    .dma_buf_len = 256,
    .use_apll = true,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
  i2s_zero_dma_buffer(I2S_NUM_0);

  // ===== Mic validation =====
  Serial.println("🔍 Running mic self-test...");
  bool ok = micSelfTest();
  if (ok) Serial.println("🎤 I2S Microphone ready!");
  else {
    Serial.println("⚠ Retrying mic init in 3s...");
    delay(3000);
    ESP.restart();
  }
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠ WiFi disconnected, reconnecting...");
    connectWiFi();
  }

  const int samples = 512;
  int32_t rawBuffer[samples];
  int16_t pcm16[samples];
  size_t bytesRead;

  // Read from I2S
  i2s_read(I2S_NUM_0, (void*)rawBuffer, sizeof(rawBuffer), &bytesRead, portMAX_DELAY);
  int count = bytesRead / sizeof(int32_t);

  // Convert to 16-bit PCM
  for (int i = 0; i < count; i++) {
    pcm16[i] = rawBuffer[i] >> 14;
  }

  // Send via UDP
  if (WiFi.status() == WL_CONNECTED) {
    if (!udp.beginPacket(udpAddress, udpPort)) {
      Serial.println("⚠ UDP connection error, retrying...");
      udp.stop();
      delay(2000);
      udp.begin(WiFi.localIP(), udpPort);
    } else {
      udp.write((uint8_t*)pcm16, count * sizeof(int16_t));
      udp.endPacket();
    }
  } else {
    Serial.println("⚠ Skipping UDP send (no WiFi)");
    delay(1000);
  }

  // Optional: Safe shutdown on serial command
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'q' || c == 'Q') {
      safeShutdown();
      Serial.println("👋 Stopping program.");
      while (true);
    }
  }
}