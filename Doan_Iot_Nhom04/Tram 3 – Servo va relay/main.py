# Tram 3 LPG: van + khoa su co + HOME/AWAY. LED relay chi bao van dong.
import network
import time
import machine
import json
import os
import binascii
from machine import Pin, PWM
from umqtt.simple import MQTTClient
from config import *
from gas_protocol import decode_measurement, FrameGuard
from controller import Controller
from state_store import StateStore

FEED_SENSOR = "{}/feeds/sensor-data".format(AIO_USER)
FEED_STATE = "{}/feeds/control-valve".format(AIO_USER)
FEED_COMMAND = "{}/feeds/valve-command".format(AIO_USER)
FEED_RESET = "{}/feeds/system-reset".format(AIO_USER)
FEED_EVENTS = "{}/feeds/alarm-events".format(AIO_USER)

servo = PWM(Pin(18), freq=50, duty=0)
indicator = Pin(19, Pin.OUT)
guard = FrameGuard()
store = StateStore()
control = None
storage_error = False
last_saved = None
last_angle = None
pending_report = True
reset_requested = False
events = []
device_boot = binascii.hexlify(os.urandom(4)).decode()
last_command = "NONE"
last_command_ok = False

def apply_outputs(now):
    global last_angle
    output = control.outputs(now)
    if storage_error:
        output["valve"] = "CLOSED"
        output["servo_angle"] = 90
        output["state_fault"] = True
    angle = output["servo_angle"]
    if angle != last_angle:
        servo.duty_ns(500000 + angle * 2000000 // 180)
        last_angle = angle
        print("VAN:", output["valve"], "|", angle, "do")
    indicator.value(1 if output["valve"] == "CLOSED" else 0)
    return output

def save_if_changed():
    global last_saved, storage_error
    if storage_error or not control.state_valid:
        return False
    snapshot = control.snapshot()
    if snapshot == last_saved:
        return True
    try:
        store.save(snapshot)
        last_saved = snapshot
        return True
    except (OSError, ValueError) as error:
        storage_error = True
        print("LOI LUU TRANG THAI, GIU VAN DONG:", error)
        return False

def initialize():
    global control, last_saved, storage_error, pending_report
    try:
        saved = store.load()
        if saved is None:
            control = Controller.new_installation(time.ticks_diff)
            control.inspection_required = True
            control.manual_closed = True
        else:
            control = Controller(saved, time.ticks_diff)
            last_saved = saved
        if not control.state_valid:
            raise ValueError("Trang thai luu sai cau truc")
        save_if_changed()
    except (OSError, ValueError) as error:
        control = Controller(None, time.ticks_diff)
        storage_error = True
        print("KHOI PHUC TRANG THAI THAT BAI:", error)
    apply_outputs(time.ticks_ms())
    pending_report = True

def queue_event(name):
    event = {"event": name, "gas_state": control.gas_state, "mode": control.mode,
             "ppm": control.ppm, "device_boot": device_boot, "uptime_ms": time.ticks_ms()}
    if events and events[-1]["event"] == name:
        return
    if len(events) >= 8:
        if name != "ALARM":
            return
        events.pop(0)
    events.append(event)
    print("EVENT:", name)

def finish_change(event=None):
    global pending_report
    apply_outputs(time.ticks_ms())
    save_if_changed()
    apply_outputs(time.ticks_ms())
    pending_report = True
    if event is not None:
        queue_event(event)

def on_message(topic, msg):
    global reset_requested, last_command, last_command_ok
    if topic == FEED_RESET.encode():
        if msg.strip().upper() == b"RESET":
            reset_requested = True
        return
    if control is None:
        return
    now = time.ticks_ms()
    if topic == FEED_SENSOR.encode():
        previous_alarm = control.alarm_latched
        previous_state = control.gas_state
        try:
            data = decode_measurement(msg)
            if not guard.accept(data):
                return
            state = data["sensor_state"]
            if state == "OK":
                control.receive(data["ppm_estimated"], now, True, True, "OK", data["ppm_high"])
            elif state == "WARMUP":
                control.receive(None, now, True, False)
            elif state == "OVER_RANGE":
                control.receive(10001, now, True, True)
            elif state == "BELOW_RANGE":
                control.receive(299, now, True, True)
            elif state == "MODEL_UNVERIFIED":
                control.receive(None, now, False, True)
            else:
                control.receive(None, now, True, True, "BAD")
        except ValueError as error:
            print("LOI GOI DO:", error)
            control.sensor_fault()
        event = "ALARM" if control.alarm_latched and not previous_alarm else (
            "SENSOR_FAULT" if control.gas_state not in ("NORMAL", "ALARM", "WARMUP") and control.gas_state != previous_state else None)
        finish_change(event)
        print("TRAM3 |", control.gas_state, "| ppm model:", control.ppm)
    elif topic == FEED_COMMAND.encode():
        try:
            command = msg.decode().strip().upper()
        except UnicodeError:
            return
        if command not in ("CLOSE", "CLOSED", "OPEN", "ACK", "HOME", "AWAY"):
            return
        last_command = command
        if command in ("CLOSE", "CLOSED"):
            control.close()
            last_command_ok = True
        elif command == "OPEN":
            last_command_ok = False if storage_error else control.request_open(now)
        elif command == "ACK":
            last_command_ok = False if storage_error else control.acknowledge_inspection(now)
        else:
            last_command_ok = control.set_mode(command)
        finish_change()
        if storage_error and command in ("ACK", "OPEN", "HOME", "AWAY"):
            last_command_ok = False
        queue_event(command if last_command_ok else command + "_REJECTED")
        print("LENH:", command, "|", "OK" if last_command_ok else "TU CHOI")

def state_packet(now):
    result = apply_outputs(now)
    result.update({"schema": 3, "sensor_boot_id": guard.boot_id, "sensor_seq": guard.seq,
                   "sensor_age_ms": None if control.last_received_ms is None else time.ticks_diff(now, control.last_received_ms),
                   "last_command": last_command, "last_command_ok": last_command_ok})
    return result

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
    client = MQTTClient("esp32_tv3_lpg", AIO_HOST, user=AIO_USER, password=AIO_KEY, keepalive=60)
    client.set_callback(on_message)
    client.connect()
    for feed in (FEED_SENSOR, FEED_COMMAND, FEED_RESET):
        client.subscribe(feed.encode())
    print("MQTT OK | cho du lieu moi, khong /get lenh cu")
    return client

def main():
    global pending_report, reset_requested
    initialize()
    queue_event("BOOT")
    client = None
    last_report = last_event = None
    last_ping = time.ticks_ms()
    print("TRAM3 LPG v3 | Dong va giu van sau su co | relay LED = VAN DONG")
    while True:
        now = time.ticks_ms()
        before = control.gas_state
        apply_outputs(now)
        save_if_changed()
        apply_outputs(now)
        if control.gas_state == "NO DATA" and before != "NO DATA":
            pending_report = True
            queue_event("NO_DATA")
        try:
            if client is None:
                connect_wifi()
                client = connect_mqtt()
                last_ping = time.ticks_ms()
                last_report = None
                pending_report = True
            client.check_msg()
            if reset_requested:
                control.reset_requested()
                finish_change()
                if save_if_changed():
                    print("TRAM3: da luu khoa, nhan RESET, khoi dong lai")
                    machine.reset()
                else:
                    print("TU CHOI RESET: khong luu duoc khoa su co")
                    reset_requested = False
            now = time.ticks_ms()
            since_report = 15000 if last_report is None else time.ticks_diff(now, last_report)
            if last_report is None or (pending_report and since_report >= 10000) or since_report >= 15000:
                client.publish(FEED_STATE.encode(), json.dumps(state_packet(now)).encode())
                last_report = now
                pending_report = False
            if events and (last_event is None or time.ticks_diff(now, last_event) >= 10000):
                client.publish(FEED_EVENTS.encode(), json.dumps(events[0]).encode())
                events.pop(0)
                last_event = now
            if time.ticks_diff(now, last_ping) >= 30000:
                client.ping()
                last_ping = now
            time.sleep_ms(50)
        except OSError as error:
            print("TRAM3 | loi ket noi:", error)
            control.sensor_fault()
            finish_change("OFFLINE")
            if client is not None:
                try:
                    client.disconnect()
                except OSError:
                    pass
            client = None
            time.sleep(3)

if __name__ == "__main__":
    main()
