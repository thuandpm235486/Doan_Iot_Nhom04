"""Luu hai slot + checksum cho mo hinh MicroPython.

Loi ghi/doc => dong van. Khong tu khoi tao lai neu co dau vet file hong.
Khong phai chung nhan kha nang chiu mat dien cua bo nho phan cung.
"""
import json
import os
import hashlib
import binascii


class StateStore:
    def __init__(self, prefix="lpg_state"):
        self.prefix = prefix
        self.sequence = 0

    @staticmethod
    def _digest(text):
        return binascii.hexlify(hashlib.sha256(text.encode()).digest()).decode()

    @staticmethod
    def _exists(path):
        try:
            os.stat(path)
            return True
        except OSError as error:
            if error.args and error.args[0] == 2:
                return False
            raise

    def load(self):
        records = []
        for slot in (0, 1):
            path = self.prefix + "." + str(slot) + ".json"
            if not self._exists(path):
                continue
            try:
                with open(path) as stream:
                    record = json.load(stream)
                if (not isinstance(record, dict) or not isinstance(record.get("payload"), str)
                        or type(record.get("sequence")) is not int or record["sequence"] < 1
                        or record.get("checksum") != self._digest(record["payload"])):
                    raise ValueError("Checksum/schema")
                records.append((record["sequence"], json.loads(record["payload"])))
            except (ValueError, TypeError, OSError):
                raise ValueError("Trang thai luu hong: " + path)
        if not records:
            if self._exists(self.prefix + ".initialized"):
                raise ValueError("Da khoi tao nhung mat trang thai")
            return None
        records.sort(key=lambda item: item[0])
        self.sequence = records[-1][0]
        return records[-1][1]

    def save(self, state):
        payload = json.dumps(state)
        sequence = self.sequence + 1
        record = {"sequence": sequence, "payload": payload, "checksum": self._digest(payload)}
        path = self.prefix + "." + str(sequence % 2) + ".json"
        temporary = self.prefix + ".tmp"
        with open(temporary, "w") as stream:
            json.dump(record, stream)
            stream.flush()
        getattr(os, "replace", os.rename)(temporary, path)
        with open(path) as stream:
            written = json.load(stream)
        if written != record:
            raise OSError("Kiem tra ghi trang thai that bai")
        with open(self.prefix + ".initialized", "w") as stream:
            stream.write("1")
            stream.flush()
        self.sequence = sequence
