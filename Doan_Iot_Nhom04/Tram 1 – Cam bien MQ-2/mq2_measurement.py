"""ADC -> dien ap -> Rs -> ppm uoc luong cua CUSTOM MODEL, khong hieu chuan that."""
from gas_profile import PROFILE_ID, ALARM_PPM, LEL_PPM
from gas_model import MODEL_ID, estimate_from_adc

def read_measurement(adc, sleep_ms, samples=16, ready_pin=None, health_pin=None):
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 128:
        raise ValueError("samples phai la so nguyen 1..128")
    report = {"schema": 3, "profile_id": PROFILE_ID, "model_id": MODEL_ID,
              "source": "CUSTOM_DATASHEET_SIMULATION", "model_validated": True,
              "hardware_calibrated": False, "sensor_state": "SENSOR_FAULT",
              "raw_adc": None, "adc_quality": "READ_ERROR", "ppm_estimated": None,
              "ppm_low": None, "ppm_high": None, "percent_lel": None,
              "alarm_setpoint_ppm": ALARM_PPM}
    if ready_pin is None or health_pin is None:
        report["sensor_state"] = "MODEL_UNVERIFIED"
        return report
    if not health_pin.value():
        return report
    if not ready_pin.value():
        report["sensor_state"] = "WARMUP"
        report["adc_quality"] = "WARMUP"
        return report
    values = []
    try:
        for _ in range(samples):
            value = adc.read()
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4095:
                raise ValueError("ADC_INVALID")
            values.append(value)
            sleep_ms(5)
        if not health_pin.value() or not ready_pin.value():
            return report
    except (OSError, ValueError):
        return report
    average = sum(values) / len(values)
    report["raw_adc"] = round(average, 2)
    if min(values) == 0 or max(values) == 4095:
        report["adc_quality"] = "ADC_LIMIT"
        return report
    try:
        report.update(estimate_from_adc(average))
    except ValueError as error:
        code = str(error)
        report["sensor_state"] = code if code in ("BELOW_RANGE", "OVER_RANGE") else "SENSOR_FAULT"
        report["adc_quality"] = "OUT_OF_MODEL_RANGE"
        return report
    report["sensor_state"] = "OK"
    report["adc_quality"] = "OK"
    report["percent_lel"] = round(report["ppm_estimated"] * 100 / LEL_PPM, 2)
    return report
