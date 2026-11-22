import time

class LCD:
    RS = 0x01
    EN = 0x04
    BL = 0x08

    def __init__(self, i2c, addr=0x27, cols=16, rows=2):
        self.i2c = i2c
        self.addr = addr
        self.cols = cols
        self.rows = rows
        time.sleep_ms(50)
        for _ in range(3):
            self._write4(0x03, 0)
            time.sleep_ms(5)
        self._write4(0x02, 0)      
        self._cmd(0x28)          
        self._cmd(0x0C)             
        self._cmd(0x06)           
        self.clear()

    def _write4(self, nibble, mode):
        data = (nibble << 4) | mode | self.BL
        self.i2c.writeto(self.addr, bytes([data | self.EN]))
        time.sleep_us(50)
        self.i2c.writeto(self.addr, bytes([data & ~self.EN]))
        time.sleep_us(50)

    def _send(self, byte, mode):
        self._write4(byte >> 4, mode)
        self._write4(byte & 0x0F, mode)

    def _cmd(self, byte):
        self._send(byte, 0)

    def clear(self):
        self._cmd(0x01)
        time.sleep_ms(3)

    def move_to(self, col, row):
        offset = (0x00, 0x40)[row]
        self._cmd(0x80 | (offset + col))

    def putstr(self, s):
        for ch in s:
            self._send(ord(ch), self.RS)

    def print_line(self, row, text):
        self.move_to(0, row)
        self.putstr("{:<16}".format(text)[:16])