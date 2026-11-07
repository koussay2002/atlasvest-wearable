#!/usr/bin/env python3
"""Enregistre la télémétrie MQTT du Smart Vest (Wokwi) dans data/telemetry_live.csv.

Usage :  pip install paho-mqtt
         python tools/mqtt_logger.py --id atlasvest-koussay-01
Option  : --cmd "hr_max=150"  envoie une commande de seuil personnalisé à l'ESP32 simulé.
"""
import argparse, csv, json, os, time
import paho.mqtt.client as mqtt

ap = argparse.ArgumentParser()
ap.add_argument("--id", default="atlasvest-koussay-01", help="DEVICE_ID du sketch")
ap.add_argument("--host", default="broker.hivemq.com")
ap.add_argument("--out", default="data/telemetry_live.csv")
ap.add_argument("--cmd", default=None, help='commande à publier, ex. "hr_max=150" ou "mute=0"')
a = ap.parse_args()
base = f"esprim/wearable/{a.id}"
FIELDS = ["ts", "uptime_s", "hr", "temp", "hum", "level", "state", "sensor_ok", "hr_max"]
os.makedirs(os.path.dirname(a.out), exist_ok=True)
new = not os.path.exists(a.out)
f = open(a.out, "a", newline="", encoding="utf-8")
w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
if new: w.writeheader()

def on_connect(c, *args):
    c.subscribe(base + "/#")
    print("Connecté, abonné à", base + "/#")
    if a.cmd: c.publish(base + "/cmd", a.cmd); print("Commande envoyée :", a.cmd)

def on_message(c, userdata, msg):
    p = msg.payload.decode(errors="replace")
    if msg.topic.endswith("/telemetry"):
        try:
            d = json.loads(p); d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            w.writerow(d); f.flush(); print(f"{d['ts']}  HR={d['hr']}  T={d['temp']}  niveau={d['state']}")
        except json.JSONDecodeError:
            print("JSON invalide :", p)
    else:
        print(msg.topic.split("/")[-1].upper(), "->", p)

try:   # paho-mqtt >= 2.0
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:   # paho-mqtt 1.x
    c = mqtt.Client()
c.on_connect, c.on_message = on_connect, on_message
c.connect(a.host, 1883, 60)
c.loop_forever()
