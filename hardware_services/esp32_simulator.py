import paho.mqtt.client as mqtt
import json
import time
import random
from datetime import datetime, timezone
import threading

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_PREFIX = "echonet/sensors"

# This list of MAC addresses should match the sensors you register via the API.
SENSORS = {
    "11:2A:00:3B:4D:22", # Delhi 1
    "11:22:33:44:55:66", # Delhi 2
    "AA:BB:CC:DD:EE:F2", # Delhi 3
    "AA:BB:CC:D1:EE:FF"  # Mumbai
}

def sensor_thread(mac_address):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"sensor_{mac_address}")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    
    topic = f"{MQTT_TOPIC_PREFIX}/{mac_address}"
    
    while True:
        # The payload now conforms to the new, simplified SensorData format.
        # It no longer sends location or sound_features.
        payload = {
            "device_id": mac_address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decibel": random.uniform(20.0, 95.0)
        }
        json_payload = json.dumps(payload)
        client.publish(topic, json_payload)
        print(f"Sensor {mac_address} published simplified data to {topic}")
        
        time.sleep(random.uniform(8, 12))

if __name__ == "__main__":
    threads = []
    for mac in SENSORS:
        thread = threading.Thread(target=sensor_thread, args=(mac,))
        threads.append(thread)
        thread.start()