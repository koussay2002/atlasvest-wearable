/*
  AtlasVest — Smart Vest (simulation Wokwi) — Wearable Technology, ESPRIM 2026/2027
  ESP32 + DHT22 (température/humidité) + potentiomètre (= rythme cardiaque) + buzzer + 2 LED
  + bouton d'acquittement + publication MQTT (JSON) vers un broker cloud public.
  Règles du sujet : buzzer si pouls > 140 bpm ou température anormale.
*/
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include "alert_logic.h"

#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 2
#endif

// ---------- Configuration (à adapter) ----------
const char* WIFI_SSID  = "Wokwi-GUEST";       // réseau Wi-Fi simulé par Wokwi (sans mot de passe)
const char* WIFI_PASS  = "";
const char* MQTT_HOST  = "broker.hivemq.com"; // broker public (aucune donnée sensible !)
const uint16_t MQTT_PORT = 1883;
const char* DEVICE_ID  = "atlasvest-koussay-01"; // rendre unique : le broker est partagé

// ---------- Broches ----------
#define PIN_DHT   15   // DHT22 (SDA)
#define PIN_HR    34   // potentiomètre = capteur de pouls (ADC1)
#define PIN_BUZ   4    // buzzer
#define PIN_LED_G 26   // LED verte  : niveau OK
#define PIN_LED_R 2    // LED rouge  : ORANGE / ROUGE
#define PIN_ACK   14   // bouton d'acquittement (INPUT_PULLUP)

DHT dht(PIN_DHT, DHT22);
WiFiClient net;
PubSubClient mqtt(net);
AlertEngine engine;

float hrF = 70.0f;            // pouls filtré (EMA) — mini filtrage "Edge"
float tempC = 36.5f, hum = 50.0f; bool tempOk = true;
unsigned long tHR = 0, tDHT = 0, tPub = 0, tMqtt = 0, muteUntil = 0;
bool buzOn = false;
char tTele[96], tAlert[96], tStatus[96], tCmd[96];

void buzzer(bool on) {
  if (on == buzOn) return;
  buzOn = on;
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWriteTone(PIN_BUZ, on ? 2000 : 0);
#else
  ledcWriteTone(0, on ? 2000 : 0);
#endif
}

void publishAlert() {
  char msg[160];
  snprintf(msg, sizeof(msg), "{\"id\":\"%s\",\"level\":%d,\"state\":\"%s\",\"hr\":%.1f,\"temp\":%.1f,\"sensor_ok\":%s}",
           DEVICE_ID, (int)engine.level, levelName(engine.level), hrF, tempC, tempOk ? "true" : "false");
  if (mqtt.connected()) mqtt.publish(tAlert, msg, true);   // retenu : le dernier état reste lisible
  Serial.printf("[ALERTE] %s\n", msg);
}

void publishTelemetry() {
  char msg[220];
  snprintf(msg, sizeof(msg),
    "{\"id\":\"%s\",\"uptime_s\":%lu,\"hr\":%.1f,\"temp\":%.1f,\"hum\":%.0f,\"level\":%d,\"state\":\"%s\",\"sensor_ok\":%s,\"hr_max\":%.0f}",
    DEVICE_ID, millis() / 1000UL, hrF, tempC, hum, (int)engine.level, levelName(engine.level),
    tempOk ? "true" : "false", engine.th.hr_orange);
  mqtt.publish(tTele, msg);
  Serial.println(msg);
}

// Commandes distantes : "hr_max=150" (seuil personnalisé de l'athlète), "mute=0" (lève l'acquittement)
void onMessage(char* topic, byte* payload, unsigned int len) {
  char buf[32]; len = min(len, (unsigned int)31); memcpy(buf, payload, len); buf[len] = 0;
  if (strncmp(buf, "hr_max=", 7) == 0) {
    float v = atof(buf + 7);
    if (v >= 100 && v <= 200) { engine.th.hr_orange = v; Serial.printf("[CMD] hr_max=%.0f\n", v); }
  } else if (strncmp(buf, "mute=0", 6) == 0) muteUntil = 0;
}

void mqttMaintain(unsigned long now) {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected() || now - tMqtt < 3000) return;
  tMqtt = now;
  if (mqtt.connect(DEVICE_ID, nullptr, nullptr, tStatus, 1, true, "offline")) {   // testament (LWT)
    mqtt.publish(tStatus, "online", true);
    mqtt.subscribe(tCmd);
    Serial.println("[MQTT] connecté");
  }
}

// Autotest au démarrage : vérifie le câblage des LED et du buzzer (visible aussi dans le moniteur série)
void selfTest() {
  Serial.println("[TEST] LED verte ..."); digitalWrite(PIN_LED_G, HIGH); delay(500); digitalWrite(PIN_LED_G, LOW);
  Serial.println("[TEST] LED rouge ..."); digitalWrite(PIN_LED_R, HIGH); delay(500); digitalWrite(PIN_LED_R, LOW);
  Serial.println("[TEST] buzzer ...");    buzzer(true); delay(150); buzzer(false);
  Serial.println("[TEST] terminé");
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_G, OUTPUT); pinMode(PIN_LED_R, OUTPUT); pinMode(PIN_ACK, INPUT_PULLUP);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_BUZ, 2000, 8);
#else
  ledcSetup(0, 2000, 8); ledcAttachPin(PIN_BUZ, 0);
#endif
  analogReadResolution(12);
  dht.begin();
  snprintf(tTele,   sizeof(tTele),   "esprim/wearable/%s/telemetry", DEVICE_ID);
  snprintf(tAlert,  sizeof(tAlert),  "esprim/wearable/%s/alert",     DEVICE_ID);
  snprintf(tStatus, sizeof(tStatus), "esprim/wearable/%s/status",    DEVICE_ID);
  snprintf(tCmd,    sizeof(tCmd),    "esprim/wearable/%s/cmd",       DEVICE_ID);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  mqtt.setServer(MQTT_HOST, MQTT_PORT); mqtt.setCallback(onMessage); mqtt.setBufferSize(256);
  Serial.println("AtlasVest — démarrage");
  Serial.printf("Broches : DHT=%d HR=%d BUZ=%d LED_V=%d LED_R=%d ACK=%d\n", PIN_DHT, PIN_HR, PIN_BUZ, PIN_LED_G, PIN_LED_R, PIN_ACK);
  selfTest();
}

void loop() {
  const unsigned long now = millis();
  mqttMaintain(now); mqtt.loop();

  if (now - tDHT >= 2000) {                       // le DHT22 impose >= 2 s entre deux lectures
    tDHT = now;
    float t = dht.readTemperature(), h = dht.readHumidity();
    tempOk = !isnan(t);
    if (tempOk) { tempC = t; if (!isnan(h)) hum = h; }
  }

  if (now - tHR >= 1000) {                        // mesure + évaluation à 1 Hz
    tHR = now;
    float bpm = 40.0f + analogRead(PIN_HR) * (160.0f / 4095.0f);   // 40..200 bpm
    hrF = 0.3f * bpm + 0.7f * hrF;                                 // filtre EMA
    Level before = engine.level;
    engine.update(hrF, tempC, tempOk);
    if (engine.level != before) publishAlert();
  }

  // Bouton d'acquittement : coupe le buzzer ORANGE pendant 30 s (le ROUGE ne s'acquitte jamais)
  static bool ackPrev = false;
  const bool ack = (digitalRead(PIN_ACK) == LOW);
  if (ack && !ackPrev) {
    if (engine.level == LEVEL_ORANGE) { muteUntil = now + 30000UL; Serial.println("[ACK] buzzer ORANGE coupé 30 s"); }
    else if (engine.level == LEVEL_RED) Serial.println("[ACK] ignoré : le niveau ROUGE n'est pas acquittable");
    else Serial.println("[ACK] rien à acquitter (niveau OK)");
  }
  ackPrev = ack;

  // LED verte = OK ; LED rouge = clignote (ORANGE) ou fixe (ROUGE)
  digitalWrite(PIN_LED_G, engine.level == LEVEL_OK);
  digitalWrite(PIN_LED_R, engine.level == LEVEL_RED ? HIGH : (engine.level == LEVEL_ORANGE ? ((now / 500) % 2 == 0) : LOW));
  if (engine.level == LEVEL_RED) buzzer(true);                       // ROUGE : continu, non acquittable
  else if (engine.level == LEVEL_ORANGE) buzzer(now >= muteUntil && ((now / 500) % 2 == 0));
  else buzzer(false);

  if (now - tPub >= 2000) { tPub = now; if (mqtt.connected()) publishTelemetry(); }
}
