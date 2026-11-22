// Irigasi Cerdas AIoT
// Sensor (tanah, DHT22, LDR) -> ESP32 -> Decision Tree (model.h) -> pompa, LED, LCD -> MQTT -> dashboard.
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "model.h"

const char *WIFI_SSID = "Wokwi-GUEST";
const char *WIFI_PASS = "";
const char *MQTT_HOST = "broker.hivemq.com";
// Harus sama dengan topik di dashboard/index.html.
const char *TOPIK = "litdih-aiot/irigasi-cerdas/data";

const int PIN_DHT = 32, PIN_LDR = 34, PIN_TANAH = 35;
const int PIN_HIJAU = 19, PIN_KUNING = 18, PIN_MERAH = 5, PIN_POMPA = 23;
const unsigned long INTERVAL_MS = 2000;

// Bacaan sensor tanah (fraksi 0-1 dari skala ADC) saat kering dan basah. Di simulasi sensornya potensiometer.
// Sensor kapasitif asli terbalik (kering sekitar 0,85, basah sekitar 0,35): ukur lalu ganti dua angka ini.
const float TANAH_KERING = 0.0, TANAH_BASAH = 1.0;

DHT dht(PIN_DHT, DHT22);
LiquidCrystal_I2C lcd(0x27, 16, 2);
WiFiClient net;
PubSubClient mqtt(net);

// Rasiometrik: Wokwi memberi potensiometer dan modul LDR skala ini apa pun pin catunya,
// dan di ESP32 asli sensor dicatu 3,3 V sehingga hasilnya sama.
float bacaFraksi(int pin) { return analogRead(pin) / 4095.0; }

float bacaTanah() {
  float persen = (bacaFraksi(PIN_TANAH) - TANAH_KERING) / (TANAH_BASAH - TANAH_KERING) * 100;
  return constrain(persen, 0, 100);
}

// Modul LDR: LDR di sisi bawah pembagi tegangan 10 kOhm. Rumus lux dari dokumentasi Wokwi (gamma 0,7, RL10 50 kOhm).
float bacaLux() {
  float f = bacaFraksi(PIN_LDR);
  if (f >= 0.999) return 0;
  if (f <= 0.0003) return 100000;
  float r = 10000 * f / (1 - f);
  return pow(50000 * pow(10, 0.7) / r, 1 / 0.7);
}

// Vapor Pressure Deficit (kPa), fitur yang sama dengan saat model dilatih.
float hitungVpd(float suhu, float lembap) { return 0.6108 * exp(17.27 * suhu / (suhu + 237.3)) * (1 - lembap / 100); }

void tampilLcd(const char *baris1, const char *baris2) {
  char buf[17];
  snprintf(buf, sizeof buf, "%-16s", baris1);
  lcd.setCursor(0, 0);
  lcd.print(buf);
  snprintf(buf, sizeof buf, "%-16s", baris2);
  lcd.setCursor(0, 1);
  lcd.print(buf);
}

void aturOutput(int keputusan) {
  digitalWrite(PIN_HIJAU, keputusan == 0);
  digitalWrite(PIN_MERAH, keputusan == 1);
  digitalWrite(PIN_KUNING, keputusan == 2);
  digitalWrite(PIN_POMPA, keputusan == 1);
}

void sambungMqtt() {
  static unsigned long coba = 0;
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED || (coba && millis() - coba < 5000)) return;
  coba = millis();
  // ID acak agar beberapa simulasi yang berjalan bersamaan tidak saling memutus di broker.
  String id = "irigasi-" + String(esp_random(), HEX);
  Serial.println(mqtt.connect(id.c_str()) ? "MQTT tersambung" : "MQTT gagal, coba lagi 5 detik");
}

void setup() {
  Serial.begin(115200);
  for (int pin : {PIN_HIJAU, PIN_KUNING, PIN_MERAH, PIN_POMPA}) pinMode(pin, OUTPUT);
  dht.begin();
  lcd.init();
  lcd.backlight();
  tampilLcd("Irigasi Cerdas", "AIoT memulai...");
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  mqtt.setServer(MQTT_HOST, 1883);
}

void loop() {
  sambungMqtt();
  mqtt.loop();

  static unsigned long terakhir = 0;
  if (terakhir && millis() - terakhir < INTERVAL_MS) return;
  terakhir = millis();

  float suhu = dht.readTemperature(), lembap = dht.readHumidity();
  if (isnan(suhu) || isnan(lembap)) {
    // Tanpa data suhu, keputusan tidak bisa dipercaya: pompa dimatikan agar tidak membanjiri lahan.
    aturOutput(-1);
    tampilLcd("DHT22 error", "Pompa OFF");
    Serial.println("{\"error\":\"DHT22 gagal dibaca\",\"pompa\":false}");
    return;
  }
  float tanah = bacaTanah(), lux = bacaLux(), vpd = hitungVpd(suhu, lembap);
  int keputusan = prediksi(tanah, suhu, lembap, lux, vpd);
  aturOutput(keputusan);

  char baris1[17], baris2[17];
  snprintf(baris1, sizeof baris1, "Tanah%3.0f%% %4.1fC", tanah, suhu);
  snprintf(baris2, sizeof baris2, "AI: %s", KELAS[keputusan]);
  tampilLcd(baris1, baris2);

  char json[192];
  snprintf(json, sizeof json,
           "{\"tanah\":%.1f,\"suhu\":%.1f,\"kelembapan\":%.1f,\"lux\":%.0f,\"vpd\":%.2f,\"keputusan\":\"%s\",\"pompa\":%s}",
           tanah, suhu, lembap, lux, vpd, KELAS[keputusan], keputusan == 1 ? "true" : "false");
  Serial.println(json);
  if (mqtt.connected()) mqtt.publish(TOPIK, json);
}
