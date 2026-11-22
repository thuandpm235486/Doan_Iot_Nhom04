# Tram 2 LPG: nong do UOC LUONG tu custom model, khong phai hieu chuan that.
import network
import time
import machine
import json
import os
import binascii
from machine import Pin, PWM, SoftI2C
from umqtt.simple import MQTTClient
from config import *
from lcd_i2c import LCD
from gas_profile import ALARM_PPM
from gas_protocol import decode_measurement, FrameGuard

FEED_SENSOR = "{}/feeds/sensor-data".format(AIO_USER)
FEED_STATE = "{}/feeds/control-valve".format(AIO_USER)
FEED_RESET = "{}/feeds/system-reset".format(AIO_USER)
TOPIC_ERRORS = "{}/errors".format(AIO_USER)
TOPIC_THROTTLE = "{}/throttle".format(AIO_USER)
DATA_TIMEOUT_MS = 20000
CLIENT_ID = "esp32_tv2_lpg-" + binascii.hexlify(os.urandom(4)).decode()
guard = FrameGuard()
reset_requested = False
last_received = None
waiting_since = None
gas_state = "WAIT"
ppm = None
lel = None
alarm_latched = False

led_red = Pin(26, Pin.OUT)
led_green = Pin(27, Pin.OUT)
buzzer = PWM(Pin(25), freq=2000, duty=0)
lcd = LCD(SoftI2C(scl=Pin(21), sda=Pin(22), freq=100000), 0x27)

def show():
    lcd.print_line(0, "Gas: {} ppm".format("---" if ppm is None else int(round(ppm))))
    label = "CHECK" if gas_state == "NORMAL" and alarm_latched else gas_state
    lcd.print_line(1, "{}{}".format(label, "" if lel is None else " {:.1f}%L".format(lel)))

def apply_alert(now):
    alarm = gas_state == "ALARM" or alarm_latched
    fault = gas_state not in ("NORMAL", "ALARM")
    led_green.value(1 if gas_state == "NORMAL" and not alarm else 0)
    led_red.value(1 if alarm else int((now // 500) % 2) if fault else 0)
    on = (now // 200) % 2 == 0 if alarm else now % 2000 < 150 if fault else False
    buzzer.duty(512 if on else 0)


def on_mqtt_connected(now):
    global gas_state, ppm, lel, last_received, waiting_since
    # A new connection is not a new measurement. Preserve alarm latch and seq guard.
    gas_state, ppm, lel = "WAIT", None, None
    last_received = None
    waiting_since = now
    show()
    apply_alert(now)


def mark_offline(now):
    global gas_state, ppm, lel, last_received, waiting_since
    gas_state, ppm, lel = "OFFLINE", None, None
    last_received = waiting_since = None
    show()
    apply_alert(now)


def check_data_timeout(now):
    global gas_state, ppm, lel
    reference = last_received if last_received is not None else waiting_since
    if reference is not None and time.ticks_diff(now, reference) >= DATA_TIMEOUT_MS:
        if gas_state != "NO DATA":
            print("TRAM2 | NO DATA: khong nhan ban tin MOI tu", FEED_SENSOR)
        gas_state, ppm, lel = "NO DATA", None, None
        show()

def on_message(topic, msg):
    global reset_requested, last_received, gas_state, ppm, lel, alarm_latched
    if topic in (TOPIC_ERRORS.encode(), TOPIC_THROTTLE.encode()):
        try:
            text = msg.decode()
        except UnicodeError:
            text = "Thong bao khong doc duoc"
        print("TRAM2 | AIO", "THROTTLE" if topic == TOPIC_THROTTLE.encode() else "ERROR", "|", text[:240])
        return
    if topic == FEED_RESET.encode():
        if msg.strip().upper() == b"RESET":
            reset_requested = True
        return
    if topic == FEED_STATE.encode():
        try:
            state = json.loads(msg.decode())
            if (state.get("schema") == 3 and state.get("sensor_boot_id") == guard.boot_id
                    and isinstance(state.get("sensor_seq"), int) and state["sensor_seq"] >= guard.seq
                    and isinstance(state.get("alarm_on"), bool)):
                alarm_latched = state["alarm_on"]
        except (ValueError, UnicodeError, AttributeError):
            pass
        show()
        apply_alert(time.ticks_ms())
        return
    if topic != FEED_SENSOR.encode():
        return
    print("TRAM2 RX:", FEED_SENSOR, "|", len(msg), "bytes")
    try:
        data = decode_measurement(msg)
        if not guard.accept(data):
            print("TRAM2 | bo qua seq trung/cu:", data["seq"])
            return
        last_received = time.ticks_ms()
        if data["sensor_state"] == "OK":
            ppm = data["ppm_estimated"]
            lel = data.get("percent_lel")
            gas_state = "ALARM" if data["ppm_high"] >= ALARM_PPM else "NORMAL"
            if gas_state == "ALARM":
                alarm_latched = True
        else:
            ppm, lel = None, None
            if data["sensor_state"] == "OVER_RANGE":
                alarm_latched = True
            gas_state = "WARMUP" if data["sensor_state"] == "WARMUP" else "FAULT"
        print("TRAM2 | PPM model:", ppm, "|", gas_state, "| seq:", guard.seq)
    except ValueError as error:
        gas_state, ppm, lel = "FAULT", None, None
        print("TRAM2 |", error)
    show()
    apply_alert(time.ticks_ms())

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(30):
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if not wlan.isconnected():
        raise OSError("WiFi FAIL")
    print("WiFi OK:", wlan.ifconfig()[0])

def connect_mqtt():
    client = MQTTClient(CLIENT_ID, AIO_HOST, user=AIO_USER, password=AIO_KEY, keepalive=60)
    client.set_callback(on_message)
    client.connect()
    on_mqtt_connected(time.ticks_ms())
    try:
        for feed in (FEED_SENSOR, FEED_STATE, FEED_RESET, TOPIC_ERRORS, TOPIC_THROTTLE):
            client.subscribe(feed.encode())
            print("TRAM2 SUB:", feed)
    except OSError:
        try:
            client.disconnect()
        except OSError:
            pass
        raise
    print("TRAM2 client:", CLIENT_ID)
    print("MQTT OK | cho ban tin MOI, khong lay lai lenh RESET")
    return client

def main():
    global gas_state, last_received, ppm, lel
    client = None
    last_ping = last_log = time.ticks_ms()
    print("TRAM2 LPG v3 | phuc hoi MQTT, theo doi ban tin moi")
    show()
    while True:
        try:
            if client is None:
                connect_wifi()
                client = connect_mqtt()
                last_ping = time.ticks_ms()
            client.check_msg()
            if reset_requested:
                print("TRAM2: nhan RESET, khoi dong lai")
                machine.reset()
            now = time.ticks_ms()
            check_data_timeout(now)
            apply_alert(now)
            if time.ticks_diff(now, last_log) >= 5000:
                print("TRAM2 |", gas_state, "| ppm:", ppm, "| last seq:", guard.seq)
                last_log = now
            if time.ticks_diff(now, last_ping) >= 30000:
                client.ping()
                last_ping = now
            time.sleep_ms(50)
        except OSError as error:
            print("TRAM2 | loi ket noi:", error)
            mark_offline(time.ticks_ms())
            if client is not None:
                try:
                    client.disconnect()
                except OSError:
                    pass
            client = None
            time.sleep(3)

if __name__ == "__main__":
    main()
