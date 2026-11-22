"""Loi logic thuan Python/MicroPython, chua noi GPIO, MQTT hay phep do ADC.

snapshot() la du lieu de buoc tich hop luu vao bo nho ben vung. Lop nay
khong tu ghi flash. Thieu/hong snapshot luc khoi dong => khong cho mo van.
"""
from gas_profile import PROFILE_ID, ALARM_PPM, classify, percent_lel
import math

DATA_TIMEOUT_MS = 20000  # Tham so do tre du lieu, khong phai nguong nong do


class Controller:
    def __init__(self, saved_state=None, ticks_diff=None):
        self._diff = ticks_diff if ticks_diff is not None else lambda a, b: a - b
        self.state_valid = self._valid_saved_state(saved_state)
        state = saved_state if self.state_valid else {}
        self.mode = state.get("mode", "HOME")
        self.alarm_latched = state.get("alarm_latched", True)
        self.inspection_required = state.get("inspection_required", True)
        self.manual_closed = state.get("manual_closed", True)
        self.open_requested = False  # Reset khong tu khoi phuc lenh mo van
        self.gas_state = "NO DATA"
        self.ppm = None
        self.last_received_ms = None

    @staticmethod
    def _valid_saved_state(state):
        return (isinstance(state, dict) and state.get("version") == 1
                and state.get("profile_id") == PROFILE_ID
                and state.get("mode") in ("HOME", "AWAY")
                and all(isinstance(state.get(key), bool) for key in
                        ("alarm_latched", "inspection_required", "manual_closed")))

    @classmethod
    def new_installation(cls, ticks_diff=None):
        """Chi danh cho khoi tao lan dau co chu dich / bai test.

        Khong duoc tu goi khi doc file luu that bai de vuot khoa su co.
        """
        return cls({"version": 1, "profile_id": PROFILE_ID, "mode": "HOME",
                    "alarm_latched": False, "inspection_required": False,
                    "manual_closed": False}, ticks_diff)

    def snapshot(self):
        if not self.state_valid:
            raise ValueError("Can khoi phuc trang thai luu hop le")
        return {"version": 1, "profile_id": PROFILE_ID, "mode": self.mode,
                "alarm_latched": self.alarm_latched,
                "inspection_required": self.inspection_required,
                "manual_closed": self.manual_closed}

    def receive(self, ppm, now_ms, model_verified=False,
                warmup_complete=False, quality="OK", ppm_upper=None):
        self.gas_state = classify(ppm, model_verified, warmup_complete, quality)
        if ppm_upper is not None and self.gas_state in ("NORMAL", "ALARM"):
            if (isinstance(ppm_upper, bool) or not isinstance(ppm_upper, (int, float))
                    or not math.isfinite(ppm_upper) or ppm_upper < ppm):
                self.gas_state = "SENSOR_FAULT"
            elif ppm_upper >= ALARM_PPM:
                self.gas_state = "ALARM"  # Chon bao dong khi can tren cua mo hinh cham nguong
        self.last_received_ms = now_ms
        self.ppm = ppm if self.gas_state in ("NORMAL", "ALARM") else None
        if self.gas_state in ("ALARM", "OVER_RANGE"):
            self.alarm_latched = True
            self.inspection_required = True
            self.open_requested = False
        elif self.gas_state != "NORMAL":
            self.inspection_required = True
            self.open_requested = False
        return self.gas_state

    def tick(self, now_ms):
        if self.last_received_ms is not None and self._diff(now_ms, self.last_received_ms) >= DATA_TIMEOUT_MS:
            self.gas_state = "NO DATA"
            self.ppm = None
            self.inspection_required = True
            self.open_requested = False

    def set_mode(self, mode):
        if mode not in ("HOME", "AWAY"):
            return False
        self.mode = mode
        if mode == "AWAY":
            self.open_requested = False
            self.inspection_required = True
        return True

    def close(self):
        self.manual_closed = True
        self.open_requested = False

    def sensor_fault(self):
        self.gas_state = "SENSOR_FAULT"
        self.ppm = None
        self.inspection_required = True
        self.open_requested = False

    def reset_requested(self):
        # Luu yeu cau kiem tra truoc khi khoi dong lai, khong dung reset de vuot khoa.
        self.inspection_required = True
        self.open_requested = False

    def acknowledge_inspection(self, now_ms):
        """Xac nhan cua nguoi dung trong mo hinh, KHONG tu mo van."""
        self.tick(now_ms)
        if not self.state_valid or self.mode != "HOME" or self.gas_state != "NORMAL":
            return False
        self.alarm_latched = False
        self.inspection_required = False
        return True

    def request_open(self, now_ms):
        self.tick(now_ms)
        if (not self.state_valid or self.mode != "HOME" or self.gas_state != "NORMAL"
                or self.alarm_latched or self.inspection_required):
            return False
        self.manual_closed = False
        self.open_requested = True
        return True

    def outputs(self, now_ms):
        self.tick(now_ms)
        can_open = (self.state_valid and self.mode == "HOME" and self.gas_state == "NORMAL"
                    and not self.alarm_latched and not self.inspection_required
                    and not self.manual_closed and self.open_requested)
        return {"gas_state": self.gas_state, "mode": self.mode,
                "ppm_estimated": self.ppm,
                "percent_lel": percent_lel(self.ppm) if self.ppm is not None else None,
                "valve": "OPEN" if can_open else "CLOSED",
                "servo_angle": 0 if can_open else 90,
                "alarm_on": self.alarm_latched,
                "sensor_fault": self.gas_state not in ("NORMAL", "ALARM"),
                "state_fault": not self.state_valid,
                "inspection_required": self.inspection_required}
