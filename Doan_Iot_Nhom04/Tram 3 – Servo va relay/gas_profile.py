"""Ho so propane cho DO AN MO PHONG, khong phai chung nhan thiet bi.

LEL: https://www.cdc.gov/niosh/npg/npgd0524.html
10% LEL: muc tham khao HF500, khong phai ket qua hieu chuan MQ-2.
HF500LPG dung butane hieu chuan va cam bien xuc tac, khac MQ-2.
"""
import math

PROFILE_ID = "propane-reference-v1"
LEL_PPM = 21000
ALARM_PERCENT_LEL = 10
ALARM_PPM = LEL_PPM * ALARM_PERCENT_LEL / 100
MODEL_MIN_PPM = 300
MODEL_MAX_PPM = 10000


def classify(ppm, model_verified=False, warmup_complete=False, quality="OK"):
    """Chi so sanh nong do khi ben do da xac nhan mo hinh va chat luong.

    model_verified mac dinh False: khong bien ADC hoac nhan P 400 thanh ppm.
    Dai 300..10000 la dai khao sat, khong phai cam ket do chinh xac.
    """
    if warmup_complete is not True:
        return "WARMUP"
    if model_verified is not True:
        return "MODEL_UNVERIFIED"
    if quality != "OK":
        return "SENSOR_FAULT"
    if isinstance(ppm, bool) or not isinstance(ppm, (int, float)):
        return "SENSOR_FAULT"
    if not math.isfinite(ppm) or ppm < 0:
        return "SENSOR_FAULT"
    if ppm < MODEL_MIN_PPM:
        return "BELOW_RANGE"
    if ppm > MODEL_MAX_PPM:
        return "OVER_RANGE"
    return "ALARM" if ppm >= ALARM_PPM else "NORMAL"


def percent_lel(ppm):
    if classify(ppm, True, True) not in ("NORMAL", "ALARM"):
        return None
    return ppm * 100 / LEL_PPM
