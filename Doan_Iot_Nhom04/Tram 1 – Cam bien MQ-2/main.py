import network
import time
import machine
import json
import os
import binascii
from machine import ADC, Pin
from umqtt.simple import MQTTClient
from config import *
from mq2_measurement import read_measurement
from gas_profile import ALARM_PPM

FEED_SENSOR = "{}/feeds/sensor-data".format(AIO_USER)
FEED_ALERT  = "{}/feeds/alert-status".format(AIO_USER)
FEED_RESET = "{}/feeds/system-reset".format(AIO_USER)
reset_requested = False


def on_message(topic, msg):
    global reset_requested
    if topic == FEED_RESET.encode() and msg.strip().upper() == b"RESET":
        reset_requested = True


def process_reset():
    global reset_requested
    if reset_requested:
        reset_requested = False
        print("TRAM1: nhan RESET, khoi dong lai")
        machine.reset()

PUBLISH_INTERVAL  = 6   


gas = ADC(Pin(34))
gas.atten(ADC.ATTN_11DB)
gas.width(ADC.WIDTH_12BIT)
led = Pin(2, Pin.OUT)
sensor_ready = Pin(32, Pin.IN, Pin.PULL_DOWN)
sensor_health = Pin(33, Pin.IN, Pin.PULL_DOWN)
BOOT_ID = binascii.hexlify(os.urandom(4)).decode()

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Dang ket noi WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASS)

        for i in range(30):
            if wlan.isconnected():
                break

            print(".", end="")
            time.sleep(0.5)

    if wlan.isconnected():
        print("\nWiFi OK:", wlan.ifconfig()[0])
    else:
        print("\nWiFi FAIL")
        print("WiFi status:", wlan.status())
        raise OSError("Khong ket noi duoc WiFi")

def connect_mqtt():
    c = MQTTClient("esp32_tv1_sensor", AIO_HOST,
                   user=AIO_USER, password=AIO_KEY, keepalive=60)
    c.set_callback(on_message)
    c.connect()
    c.subscribe(FEED_RESET.encode())  
    print("MQTT da ket noi Adafruit IO")
    return c

def main():
    client = None
    last_status = ""
    last_publish = None
    last_alert_publish = None
    sequence = 0
    print("TRAM1 LPG v2 | MQ2 propane custom model | KHONG HIEU CHUAN THAT")
    print("Vc=5V, RL=4.7k, conditioner=0.4; nguong de xuat 2100 ppm")
    while True:
        try:
            if client is None:
                connect_wifi()
                client = connect_mqtt()
                last_publish = None
                last_alert_publish = None
                last_status = ""
            client.check_msg()
            process_reset()
            measurement = read_measurement(gas, time.sleep_ms,
                                           ready_pin=sensor_ready, health_pin=sensor_health)
            status = measurement["sensor_state"]
            if status == "OK":
                status = "ALARM" if measurement["ppm_high"] >= ALARM_PPM else "NORMAL"
            now = time.ticks_ms()
            led.value(1 if status == "ALARM" else 0 if status == "NORMAL" else (now // 1000) % 2)
            print("ADC:", measurement["raw_adc"], "| PPM model:", measurement["ppm_estimated"],
                  "| SENSOR:", status, "| Rs:", measurement.get("sensor_resistance_ohm"))
            if last_publish is None or time.ticks_diff(now, last_publish) >= PUBLISH_INTERVAL * 1000:
                sequence += 1
                measurement["boot_id"] = BOOT_ID
                measurement["seq"] = sequence
                payload = json.dumps(measurement).encode()
                client.publish(FEED_SENSOR.encode(), payload)
                print("sensor-data: schema 3 |", status, "| seq:", sequence)
                # Derived compatibility feed is throttled; receivers use sensor-data.
                if status != last_status and (last_alert_publish is None or time.ticks_diff(now, last_alert_publish) >= 12000):
                    client.publish(FEED_ALERT.encode(), status.encode())
                    print("alert-status:", status)
                    last_status = status
                    last_alert_publish = now
                last_publish = now
            time.sleep(1)
        except OSError as e:
            print("Mat ket noi, thu lai...", e)
            if client is not None:
                try:
                    client.disconnect()
                except OSError:
                    pass
            client = None
            time.sleep(3)


if __name__ == "__main__":
    main()
