import network
import time
import machine
from machine import Pin, PWM, SoftI2C
from umqtt.simple import MQTTClient
from config import *
from lcd_i2c import LCD
from alert_logic import get_status

FEED_SENSOR = "{}/feeds/sensor-data".format(AIO_USER)
FEED_RESET = "{}/feeds/system-reset".format(AIO_USER)
reset_requested = False


def process_reset():
    global reset_requested
    if reset_requested:
        reset_requested = False
        print("TRAM2: nhan RESET, khoi dong lai")
        machine.reset()
DATA_TIMEOUT_MS = 20000  

led_red   = Pin(26, Pin.OUT)
led_green = Pin(27, Pin.OUT)
buzzer    = PWM(Pin(25), freq=2000, duty=0)  

i2c = SoftI2C(scl=Pin(21, Pin.OPEN_DRAIN, Pin.PULL_UP), sda=Pin(22, Pin.OPEN_DRAIN, Pin.PULL_UP), freq=100000)
lcd = LCD(i2c, 0x27)

gas_value = "---"
status = "WAIT"
alert_status = "WAIT"
beep_on = False
last_toggle = 0
last_received = None

def show():
    lcd.print_line(0, "Gas: {}".format(gas_value))
    lcd.print_line(1, "Status: {}".format(status))

def set_buzzer(on):
    buzzer.duty(512 if on else 0)

def apply_alert(now):
    """Dieu khien LED + coi theo trang thai (khong chan chuong trinh)."""
    global beep_on, last_toggle
    led_green.value(1 if status == "SAFE" else 0)
    led_red.value(1 if alert_status in ("WARNING", "DANGER") else 0)
    if alert_status == "SAFE":
        set_buzzer(False)
        beep_on = False
    elif alert_status in ("WARNING", "DANGER"):
        interval = 800 if alert_status == "WARNING" else 200
        if time.ticks_diff(now, last_toggle) >= interval:
            beep_on = not beep_on
            last_toggle = now
        set_buzzer(beep_on)
    else:
        set_buzzer(False)
        beep_on = False

def update_status(new_status, now):
    global status, alert_status, beep_on, last_toggle
    status = new_status
    if new_status in ("SAFE", "WARNING", "DANGER", "WAIT") and new_status != alert_status:
        alert_status = new_status
        beep_on = alert_status in ("WARNING", "DANGER")
        last_toggle = now
    apply_alert(now)

def reset_data(new_status="WAIT"):
    global gas_value, last_received
    gas_value = "---"
    last_received = None
    update_status(new_status, time.ticks_ms())
    if new_status in ("NO DATA", "OFFLINE"):
        print("TRAM2 |", new_status, "| Canh bao giu lai:", alert_status)
    show()

def check_data_timeout(now):
    if last_received is not None and time.ticks_diff(now, last_received) >= DATA_TIMEOUT_MS:
        reset_data("NO DATA")

def on_message(topic, msg):
    global gas_value, last_received, reset_requested
    if topic == FEED_RESET.encode():
        if msg.strip().upper() == b"RESET":
            reset_requested = True
        return
    if topic != FEED_SENSOR.encode():
        return
    try:
        value = int(msg.decode().strip())
    except (ValueError, UnicodeError):
        print("Bo qua sensor-data khong hop le")
        return
    if not 0 <= value <= 4095:
        print("Bo qua ADC ngoai khoang 0..4095:", value)
        return
    gas_value = value
    last_received = time.ticks_ms()
    update_status(get_status(value), last_received)
    print("ADC:", value, "| STATUS:", status, "| LED:", led_red.value())
    show()

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
        return wlan
    else:
        print("\nWiFi FAIL")
        print("WiFi status:", wlan.status())
        raise OSError("Khong ket noi duoc WiFi")

def connect_mqtt():
    c = MQTTClient("esp32_tv2_display", AIO_HOST,
                   user=AIO_USER, password=AIO_KEY, keepalive=60)
    c.set_callback(on_message)
    c.connect()
    c.subscribe(FEED_SENSOR.encode())
    c.subscribe(FEED_RESET.encode())  
    c.publish((FEED_SENSOR + "/get").encode(), b"\0")
    print("MQTT OK - da subscribe sensor-data")
    return c

def main():
    client = None
    wlan = None
    operation = "Khoi tao"
    last_ping = time.ticks_ms()
    reset_data()
    while True:
        try:
            if client is None:
                operation = "LCD"
                lcd.print_line(0, "Dang ket noi...")
                operation = "Ket noi WiFi"
                wlan = connect_wifi()
                operation = "Ket noi MQTT"
                client = connect_mqtt()
                last_ping = time.ticks_ms()
                operation = "LCD"
                show()

            operation = "Kiem tra WiFi"
            if not wlan.isconnected():
                raise OSError("WiFi da ngat")
            operation = "Nhan MQTT / cap nhat LCD"
            client.check_msg()
            process_reset()
            now = time.ticks_ms()
            operation = "Cap nhat canh bao / LCD"
            check_data_timeout(now)
            apply_alert(now)
            if time.ticks_diff(now, last_ping) >= 30000:
                operation = "MQTT ping"
                client.ping()
                last_ping = now
            time.sleep_ms(50)
        except OSError as e:
            print("TRAM2 | Loi tai:", operation, "|", repr(e))
            if wlan is not None:
                print("WiFi connected:", wlan.isconnected(), "| status:", wlan.status())
            reset_data("OFFLINE")
            if client is not None:
                try:
                    client.disconnect()
                except OSError:
                    pass
            client = None
            time.sleep(3)


if __name__ == "__main__":
    main()
