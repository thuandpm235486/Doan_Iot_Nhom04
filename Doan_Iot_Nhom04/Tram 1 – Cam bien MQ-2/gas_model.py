"""Mo hinh giao duc MQ-2/propane, KHONG phai hieu chuan cam bien that.

Nguon: Winsen MQ-2 v1.5 (2018), Fig.5, trang PDF 5, RL=4.7 kohm.
Cac diem dien ap la doc XAP XI tu do thi, khong phai bang so lieu cua hang.
SHA256 PDF: 073fa45f5a1051b37453df5a1c8d475e8254ac0302b1730a6b74ffde82a81ba9
Gia dinh: Vc=5V, RL=4700 ohm, dieu kien tham chieu cua datasheet;
khong mo phong nhiet do, do am, lao hoa hoac do nhay cheo.
"""
import math

MODEL_ID = "mq2-propane-winsen15-fig5-v1"
VC_V = 5.0
RL_OHM = 4700.0
CONDITIONING_GAIN = 0.4  # Khoi dem ly tuong + chia ap 15k/10k: 5V -> toi da 2V
WOKWI_ADC_REFERENCE_V = 5.0  # Analog API Wokwi, khong phai ADC ESP32 that
ADC_MAX = 4095
GRAPH_READING_ALLOWANCE_V = 0.05  # Gia dinh doc do thi, KHONG la sai so duoc chung nhan
MIN_PPM = 300.0
MAX_PPM = 10000.0
POINTS = ((300.0, 1.70), (500.0, 2.50), (1000.0, 3.10),
          (2000.0, 3.55), (3000.0, 3.85), (4000.0, 4.10),
          (5000.0, 4.22), (6000.0, 4.30), (7000.0, 4.42), (10000.0, 4.46))


def resistance_from_voltage(voltage):
    if not isinstance(voltage, (int, float)) or isinstance(voltage, bool):
        raise ValueError("Dien ap phai la so")
    if not math.isfinite(voltage) or not 0 < voltage < VC_V:
        raise ValueError("Dien ap ngoai mien mach Rs-RL")
    return RL_OHM * (VC_V / voltage - 1.0)


def _resistance_points():
    return tuple((ppm, resistance_from_voltage(voltage)) for ppm, voltage in POINTS)


def sensor_voltage_from_ppm(ppm):
    if isinstance(ppm, bool) or not isinstance(ppm, (int, float)) or not math.isfinite(ppm):
        raise ValueError("Nong do khong hop le")
    if not MIN_PPM <= ppm <= MAX_PPM:
        raise ValueError("Ngoai dai mo hinh")
    points = _resistance_points()
    for (p1, r1), (p2, r2) in zip(points, points[1:]):
        if p1 <= ppm <= p2:
            t = math.log(ppm / p1) / math.log(p2 / p1)
            rs = math.exp(math.log(r1) + t * math.log(r2 / r1))
            return VC_V * RL_OHM / (rs + RL_OHM)
    return POINTS[-1][1]


def ppm_from_sensor_voltage(voltage, clamp=False):
    resistance_from_voltage(voltage)  # Reject NaN, booleans and invalid types before comparison.
    if voltage < POINTS[0][1]:
        if clamp:
            return MIN_PPM
        raise ValueError("BELOW_RANGE")
    if voltage > POINTS[-1][1]:
        if clamp:
            return MAX_PPM
        raise ValueError("OVER_RANGE")
    rs = resistance_from_voltage(voltage)
    points = _resistance_points()
    for (p1, r1), (p2, r2) in zip(points, points[1:]):
        if r2 <= rs <= r1:
            t = math.log(rs / r1) / math.log(r2 / r1)
            return math.exp(math.log(p1) + t * math.log(p2 / p1))
    return MAX_PPM


def estimate_from_adc(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not 0 <= raw <= ADC_MAX:
        raise ValueError("ADC_INVALID")
    v_adc = raw * WOKWI_ADC_REFERENCE_V / ADC_MAX
    v_sensor = v_adc / CONDITIONING_GAIN
    # Chi bu sai so luong tu o hai dau bang mo hinh, khong ngoai suy duong cong.
    lsb_sensor = WOKWI_ADC_REFERENCE_V / ADC_MAX / CONDITIONING_GAIN
    if v_sensor < POINTS[0][1] - lsb_sensor:
        raise ValueError("BELOW_RANGE")
    if v_sensor > POINTS[-1][1] + lsb_sensor:
        raise ValueError("OVER_RANGE")
    bounded_v = min(POINTS[-1][1], max(POINTS[0][1], v_sensor))
    ppm = ppm_from_sensor_voltage(bounded_v)
    allowance = GRAPH_READING_ALLOWANCE_V + lsb_sensor
    low = ppm_from_sensor_voltage(bounded_v - allowance, clamp=True)
    high = ppm_from_sensor_voltage(bounded_v + allowance, clamp=True)
    return {"ppm_estimated": round(ppm, 1), "ppm_low": round(low, 1),
            "ppm_high": round(high, 1), "adc_voltage_v": round(v_adc, 4),
            "sensor_voltage_v": round(v_sensor, 4),
            "sensor_resistance_ohm": round(resistance_from_voltage(bounded_v), 1)}
