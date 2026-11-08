import network
import time
import machine
from machine import Pin, PWM
from umqtt.simple import MQTTClient
from config import *
from alert_logic import get_status

FEED_SENSOR = "{}/feeds/sensor-data".format(AIO_USER)
FEED_VALVE = "{}/feeds/control-valve".format(AIO_USER)
FEED_COMMAND = "{}/feeds/valve-command".format(AIO_USER)
FEED_RESET = "{}/feeds/system-reset".format(AIO_USER)
reset_requested = False


def process_reset():
    global reset_requested
    if reset_requested:
        reset_requested = False
        print("TRAM3: nhan RESET, khoi dong lai")
        machine.reset()
DATA_TIMEOUT_MS = 20000
ENABLE_MANUAL_CONTROL = True  
REPORT_INTERVAL_MS = 10000

RELAY_ACTIVE = 1  
ANGLE_OPEN = 0
ANGLE_CLOSED = 90

servo = PWM(Pin(18), freq=50, duty=0)
relay = Pin(19, Pin.OUT)

valve_state = ""
fan_state = None
status = "WAIT"
last_received = None
report_pending = False
connected_at = None
last_reported = None
connection_state = "WAIT"
data_stale = True
manual_closed = False


def set_servo(angle):
    angle = max(0, min(180, angle))
    servo.duty_ns(500000 + angle * 2000000 // 180)


def set_fan(on):
    global fan_state
    relay.value(RELAY_ACTIVE if on else 1 - RELAY_ACTIVE)
    fan_state = on


def set_valve(state):
    global valve_state, report_pending
    if state not in ("OPEN", "CLOSED") or state == valve_state:
        return
    angle = ANGLE_CLOSED if state == "CLOSED" else ANGLE_OPEN
    set_servo(angle)
    valve_state = state
    report_pending = True
    print("Van:", state, "| Servo:", angle, "do")


def handle_status(new_status):
    global status
    if new_status not in ("SAFE", "WARNING", "DANGER"):
        return
    status = new_status
    set_valve("CLOSED" if status == "DANGER" or manual_closed else "OPEN")
    set_fan(status != "SAFE")
    print("STATUS:", status, "| Quat:", "ON" if fan_state else "OFF")


def reset_data(new_status="WAIT"):
    global status, last_received, connection_state, data_stale, manual_closed
    status = new_status
    last_received = None
    connection_state = "WAIT"
    data_stale = True
    manual_closed = False
    set_valve("CLOSED")
    set_fan(True)
    print("STATUS:", status, "| Van: CLOSED | Quat: ON")


def mark_data_unavailable(reason):
    global connection_state, data_stale
    connection_state = reason
    data_stale = True
    print("DU LIEU:", reason, "| Giu STATUS:", status,
          "| Van:", valve_state, "| Quat:", "ON" if fan_state else "OFF")


def check_data_timeout(now):
    reference = last_received if last_received is not None else connected_at
    if reference is not None and connection_state != "NO DATA" and time.ticks_diff(now, reference) >= DATA_TIMEOUT_MS:
        print("Khong nhan ADC moi trong 20 giay; kiem tra tram 1 con gui sensor-data")
        mark_data_unavailable("NO DATA")


def print_diagnostics(now):
    if last_received is None:
        print("TRAM3 |", status, "| du lieu:", connection_state,
              "| chua nhan ADC tu sensor-data | van:", valve_state)
    else:
        print("TRAM3 |", status, "| du lieu:", connection_state, "| van:", valve_state,
              "| servo:", ANGLE_CLOSED if valve_state == "CLOSED" else ANGLE_OPEN,
              "| thoi gian nhan du lieu:", time.ticks_diff(now, last_received))


def on_message(topic, msg):
    global last_received, connection_state, data_stale, reset_requested, manual_closed
    if topic == FEED_RESET.encode():
        if msg.strip().upper() == b"RESET":
            reset_requested = True
        return
    if topic == FEED_SENSOR.encode():
        try:
            value = int(msg.decode().strip())
        except (ValueError, UnicodeError):
            print("Bo qua sensor-data khong hop le")
            return
        if not 0 <= value <= 4095:
            print("Bo qua ADC ngoai khoang 0..4095:", value)
            return
        last_received = time.ticks_ms()
        connection_state = "LIVE"
        data_stale = False
        print("ADC:", value)
        handle_status(get_status(value))
    elif ENABLE_MANUAL_CONTROL and topic == FEED_COMMAND.encode():
        try:
            command = msg.decode().strip().upper()
        except UnicodeError:
            return
        if command in ("CLOSE", "CLOSED"):
            manual_closed = True
            set_valve("CLOSED")
            print("DONG VAN BANG TAY: giu 90 do den khi nhan OPEN hop le")
        elif command == "OPEN":
            check_data_timeout(time.ticks_ms())
            if last_received is not None and not data_stale and status in ("SAFE", "WARNING"):
                manual_closed = False
                set_valve("OPEN")
                print("MO VAN: 0 do, tiep tuc bao ve tu dong theo gas")
            else:
                print("Bo qua OPEN khi DANGER hoac chua co du lieu moi")


def publish_valve(client):
    global report_pending, last_reported
    now = time.ticks_ms()
    if report_pending and (last_reported is None or time.ticks_diff(now, last_reported) >= REPORT_INTERVAL_MS):
        client.publish(FEED_VALVE.encode(), valve_state.encode())
        report_pending = False
        last_reported = time.ticks_ms()


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
        print("WiFi FAIL | status:", wlan.status())
        raise OSError("Khong ket noi duoc WiFi")
    print("WiFi OK:", wlan.ifconfig()[0])


def subscribe_feeds(c):
    c.subscribe(FEED_SENSOR.encode())
    c.subscribe(FEED_RESET.encode())  
    if ENABLE_MANUAL_CONTROL:
        c.subscribe(FEED_COMMAND.encode())


def connect_mqtt(request_latest=True):
    c = MQTTClient("esp32_tv3_actuator", AIO_HOST,
                   user=AIO_USER, password=AIO_KEY, keepalive=60)
    c.set_callback(on_message)
    c.connect()
    subscribe_feeds(c)
    if request_latest:
        c.publish((FEED_SENSOR + "/get").encode(), b"\0")
    print("MQTT OK - nhan sensor-data; gui control-valve")
    if ENABLE_MANUAL_CONTROL:
        print("Lenh dashboard: valve-command")
    return c


def main():
    global report_pending, connected_at, connection_state, data_stale
    client = None
    last_ping = time.ticks_ms()
    last_diagnostic = last_ping
    last_resubscribe = last_ping
    request_latest = True
    print("TRAM3 v6 | Servo GPIO18 | Relay GPIO19 | Nhan sensor-data + valve-command + system-reset")
    print("Khoi dong dong van 90 do; can ADC SAFE/WARNING de mo ve 0 do")
    print("Khi mat du lieu: giu nguyen servo/quat theo ADC cuoi cung")
    reset_data()
    while True:
        try:
            if client is None:
                connect_wifi()
                client = connect_mqtt(request_latest=request_latest)
                request_latest = False
                report_pending = True
                last_ping = time.ticks_ms()
                connected_at = last_ping
                last_resubscribe = last_ping
                connection_state = "WAIT DATA"
                data_stale = True
            client.check_msg()
            process_reset()
            now = time.ticks_ms()
            check_data_timeout(now)
            if connection_state == "NO DATA" and time.ticks_diff(now, last_resubscribe) >= DATA_TIMEOUT_MS:
                print("NO DATA: dang ky lai MQTT, cho ADC moi tu tram 1")
                subscribe_feeds(client)
                last_resubscribe = time.ticks_ms()
            publish_valve(client)
            if time.ticks_diff(now, last_diagnostic) >= 5000:
                print_diagnostics(now)
                last_diagnostic = now
            if time.ticks_diff(now, last_ping) >= 30000:
                client.ping()
                last_ping = now
            time.sleep_ms(50)
        except OSError as e:
            print("Loi ket noi WiFi/MQTT, thu lai...", e)
            mark_data_unavailable("OFFLINE")
            connected_at = None
            if client is not None:
                try:
                    client.disconnect()
                except OSError:
                    pass
            client = None
            time.sleep(3)


if __name__ == "__main__":
    main()
