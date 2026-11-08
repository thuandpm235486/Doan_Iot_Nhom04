import network
import time
import machine
from machine import ADC, Pin
from umqtt.simple import MQTTClient
from config import *
from alert_logic import get_status

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

def read_gas(samples=10):
    total = 0
    for _ in range(samples):
        total += gas.read()
        time.sleep_ms(10)
    return total // samples


def main():
    client = None
    last_status = ""
    last_publish = None
    while True:
        try:
            if client is None:
                connect_wifi()
                client = connect_mqtt()
                last_publish = None
                last_status = ""
            client.check_msg()
            process_reset()
            value = read_gas()
            status = get_status(value)
            led.value(0 if status == "SAFE" else 1)
            print("ADC:", value, "| STATUS:", status, "| LED:", led.value())
            now = time.ticks_ms()
            if last_publish is None or time.ticks_diff(now, last_publish) >= PUBLISH_INTERVAL * 1000:
                client.publish(FEED_SENSOR.encode(), str(value).encode())
                print("sensor-data:", value)
                if status != last_status:
                    client.publish(FEED_ALERT.encode(), status.encode())
                    print("alert-status:", status)
                    last_status = status
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
