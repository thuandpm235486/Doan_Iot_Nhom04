import network
import time
from machine import Pin
from umqtt.simple import MQTTClient
from config import *

FEED_RESET = "{}/feeds/system-reset".format(AIO_USER)
DEBOUNCE_MS = 50
RESET_COOLDOWN_MS = 10000

button = Pin(4, Pin.IN)  
led = Pin(2, Pin.OUT)
last_sent = None
blink_started = None


class DebouncedButton:
    def __init__(self):
        self.raw = 0
        self.stable = 0
        self.changed_at = time.ticks_ms()

    def update(self, value, now):
        if value != self.raw:
            self.raw = value
            self.changed_at = now
        if value != self.stable and time.ticks_diff(now, self.changed_at) >= DEBOUNCE_MS:
            self.stable = value
            return value == 1
        return False


def update_led(now):
    global blink_started
    if blink_started is None:
        led.value(0)
        return
    elapsed = time.ticks_diff(now, blink_started)
    if elapsed >= 900:
        blink_started = None
        led.value(0)
    else:
        led.value(1 if (elapsed // 150) % 2 == 0 else 0)


def send_reset(client):
    global last_sent, blink_started
    now = time.ticks_ms()
    if last_sent is not None and time.ticks_diff(now, last_sent) < RESET_COOLDOWN_MS:
        print("Vui long doi 10 giay giua hai lan RESET")
        return False
    client.publish(FEED_RESET.encode(), b"RESET", qos=1)
    last_sent = time.ticks_ms()
    blink_started = last_sent
    print("TRAM4: da gui RESET; tram 1-3 dang ket noi se khoi dong lai")
    print("LED chi bao gui thanh cong, khong phai xac nhan tung tram da reset")
    return True


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Dang ket noi WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(30):
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if not wlan.isconnected():
        raise OSError("Khong ket noi duoc WiFi")
    print("WiFi OK:", wlan.ifconfig()[0])


def connect_mqtt():
    client = MQTTClient("esp32_tv4_reset", AIO_HOST,
                        user=AIO_USER, password=AIO_KEY, keepalive=60)
    client.connect()
    print("MQTT OK | lenh: system-reset")
    return client


def main():
    client = None
    debounce = DebouncedButton()
    last_ping = time.ticks_ms()
    led.value(0)
    print("TRAM4 v2 | Nhan va tha nut de khoi dong lai tram 1-3")
    while True:
        try:
            if client is None:
                connect_wifi()
                client = connect_mqtt()
                last_ping = time.ticks_ms()
            client.check_msg()
            now = time.ticks_ms()
            if debounce.update(button.value(), now):
                send_reset(client)
            update_led(now)
            if time.ticks_diff(now, last_ping) >= 30000:
                client.ping()
                last_ping = now
            time.sleep_ms(10)
        except OSError as exc:
            print("Loi ket noi WiFi/MQTT, thu lai...", exc)
            if client is not None:
                try:
                    client.disconnect()
                except OSError:
                    pass
            client = None
            time.sleep(3)


if __name__ == "__main__":
    main()
