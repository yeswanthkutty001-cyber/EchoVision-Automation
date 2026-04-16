#include <WiFi.h>
#include <WiFiUdp.h>
#include <driver/i2s.h>

// ===== WiFi Credentials =====
const char* ssid = "YesPra";
const char* password = "always!95";

// ===== UDP Server (your phone/PC IP + port) =====
const char* udpAddress = "192.168.1.2";  // Change to your phone/PC IP
const int udpPort = 3333;

WiFiUDP udp;

// ===== I2S Microphone Pins =====
#define I2S_WS 25  // LRCLK
#define I2S_SCK 33 // BCLK
#define I2S_SD 32  // DOUT

void setup() {
  Serial.begin(115200);
  Serial.println("Connecting to WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\n✅ Connected! IP: " + WiFi.localIP().toString());

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

  Serial.println("🎤 I2S Microphone ready!");
}

void loop() {
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
  udp.beginPacket(udpAddress, udpPort);
  udp.write((uint8_t*)pcm16, count * sizeof(int16_t));
  udp.endPacket();
}