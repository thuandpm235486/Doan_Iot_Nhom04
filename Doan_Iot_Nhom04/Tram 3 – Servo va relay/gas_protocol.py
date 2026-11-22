"""Kiem tra goi mo phong co phien ban, khong nhan ADC cu nhu ppm."""
import json
import math
from gas_profile import PROFILE_ID, LEL_PPM, ALARM_PPM

MODEL_ID = "mq2-propane-winsen15-fig5-v1"
SENSOR_STATES = ("OK", "WARMUP", "SENSOR_FAULT", "MODEL_UNVERIFIED", "BELOW_RANGE", "OVER_RANGE")


def finite_number(value):
    try:
        return (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value))
    except OverflowError:
        return False


def decode_measurement(payload):
    try:
        data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
        if not isinstance(data, dict) or data.get("schema") != 3:
            raise ValueError("SCHEMA")
        if data.get("profile_id") != PROFILE_ID or data.get("model_id") != MODEL_ID:
            raise ValueError("PROFILE")
        if data.get("source") != "CUSTOM_DATASHEET_SIMULATION" or data.get("model_validated") is not True:
            raise ValueError("MODEL")
        if data.get("hardware_calibrated") is not False or data.get("sensor_state") not in SENSOR_STATES:
            raise ValueError("QUALITY")
        if not isinstance(data.get("boot_id"), str) or not 1 <= len(data["boot_id"]) <= 32:
            raise ValueError("BOOT")
        if isinstance(data.get("seq"), bool) or not isinstance(data.get("seq"), int) or data["seq"] < 0:
            raise ValueError("SEQUENCE")
        if data["sensor_state"] == "OK":
            p, low, high = data.get("ppm_estimated"), data.get("ppm_low"), data.get("ppm_high")
            if not all(finite_number(v) for v in (p, low, high)) or not 300 <= low <= p <= high <= 10000:
                raise ValueError("PPM")
            if data.get("adc_quality") != "OK":
                raise ValueError("ADC")
            data["percent_lel"] = round(p * 100 / LEL_PPM, 2)
        data["alarm_setpoint_ppm"] = ALARM_PPM
        return data
    except (ValueError, TypeError, UnicodeError, KeyError) as error:
        raise ValueError("Goi do khong hop le: " + str(error))


class FrameGuard:
    def __init__(self):
        self.boot_id = None
        self.seq = -1

    def accept(self, data):
        if data["boot_id"] == self.boot_id and data["seq"] <= self.seq:
            return False
        self.boot_id, self.seq = data["boot_id"], data["seq"]
        return True
