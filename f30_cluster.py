import ctypes
import os
import struct
import time

import libusb_package
os.environ["PATH"] = os.path.dirname(libusb_package.get_library_path()) + os.pathsep + os.environ["PATH"]
import can

# fuel % -> raw, gauge isnt linear. table from fatihcesur/bmw-f30-cluster-simhub
FUEL_TABLE = [(0, 37), (25, 27), (50, 18), (60, 11), (75, 8), (100, 4)]
IDLE = (0, 0, 1, None, 50, False, False, False)  # speed, rpm, gear, fuel L, fuel %, left, right, lights

# id, crc xor, first byte, rest. "all good" msgs so no warning lights
# message layouts here and below are from r00li/CarCluster
OK_MSGS = [
    (0x36E, 0xD8, 0xF0, [0xFE, 0xFF, 0x14]),                    # abs
    (0x36F, 0x17, 0xF0, [0x38, 0x00, 0x14]),                    # park brake off
    (0x2A7, 0x9E, 0xF0, [0xFE, 0xFF, 0x14]),                    # steering
    (0x289, 0x82, 0xF0, [0xE0, 0xE0, 0xE1, 0x00, 0xEC, 0x01]),  # cruise
    (0x19B, 0xFF, 0x40, [0x40, 0x55, 0xFD, 0xFF, 0xFF, 0xFF]),  # airbag
    (0x297, 0x28, 0xE0, [0xF1, 0xF0, 0xF2, 0xF2, 0xFE]),        # seatbelt
    (0x369, 0xC5, 0xF0, [0xA2, 0xA0, 0xA0]),                    # tyres
    (0x3F9, 0xF1, 0x10, [0x82, 0x4E, 0x7E, 140, 0x05, 0x89]),   # engine
    (0x3A7, 0x4A, 0xF0, [0x00, 0x00, 4, 0x11, 0xC0]),           # sport mode
]


# bmw crc8 from r00li/CarCluster
def crc8(data, xor):
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc ^ xor


def crc(xor, *data):
    return [crc8(data, xor)] + list(data)


def fuel_raw(pct):
    pct = max(0, min(100, pct))
    for (p0, r0), (p1, r1) in zip(FUEL_TABLE, FUEL_TABLE[1:]):
        if pct <= p1:
            return round(r0 + (r1 - r0) * (pct - p0) / (p1 - p0))


# ac shared memory
k32 = ctypes.WinDLL("kernel32")
k32.OpenFileMappingW.restype = ctypes.c_void_p
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]


def shm(name):
    h = k32.OpenFileMappingW(4, False, name)
    return k32.MapViewOfFile(h, 4, 0, 0, 0) if h else None


def open_ac():
    mem = [shm("Local\\acpmf_" + name) for name in ("physics", "graphics", "static")]
    return mem if all(mem) else None


def read(ptr, offset, fmt):
    return struct.unpack_from(fmt, ctypes.string_at(ptr + offset, struct.calcsize(fmt)))


def game_state(mem, lua):
    physics, graphics, static = mem
    if read(graphics, 4, "<i")[0] not in (1, 2, 3):  # not on track
        return IDLE
    fuel, gear, rpm = read(physics, 12, "<fii")
    speed = read(physics, 28, "<f")[0]
    max_fuel = read(static, 416, "<f")[0] or 60
    left = right = lights = 0
    if lua:  # blinkers + headlights
        l, r, hazard, phase, lights = read(lua, 0, "<5B")
        left, right = phase and (l or hazard), phase and (r or hazard)  # blink in sync with the game
    return speed, rpm, gear, fuel, 100 * fuel / max_fuel, bool(left), bool(right), bool(lights)


class Cluster:
    def __init__(self):
        self.bus = can.Bus(interface="gs_usb", channel=0, index=0, bitrate=500000)
        self.bus.gs_usb.gs_usb.default_timeout = 100  # dont hang if the cluster is off
        self.c = self.count = self.acc = self.dist = 0
        self.speed = self.rpm = self.fuel_used = 0
        self.last_fuel = None

    def send(self, id, data):
        try:
            self.bus.send(can.Message(arbitration_id=id, data=data, is_extended_id=False))
        except can.CanError:
            pass

    def drain(self):
        # adapter echoes everything back, have to read it or it fills up
        while self.bus.recv(timeout=0.001):
            pass

    def needles(self, speed, rpm, gear):
        # smoothing
        self.speed += (speed - self.speed) * 0.4
        self.rpm += (rpm - self.rpm) / 3
        kmh = round(max(0, min(260, self.speed)))
        v = int(kmh * 64.01)
        self.send(0x1A1, crc(0xA9, 0xC0 | self.c, v & 0xFF, v >> 8, 0x91 if kmh else 0x81))
        g = {0: 2, 1: 1}.get(gear, min(gear - 1, 9) + 4)  # ac gears: 0 R, 1 N, 2 = 1st
        r = int(max(0, min(7000, self.rpm)) * 43 / 6900)
        self.send(0x0F3, crc(0x7A, 0x60 | self.c, r, 0xC0, 0xF0, g, 0xFF, 0xFF))

    def status(self, gear, fuel_l, fuel_pct, left, right, lights, ignition=True):
        c = self.c
        self.send(0x12F, crc(0x44, 0x80 | c, 0x8A if ignition else 0x08, 0xDD, 0xF1, 0x01, 0x30, 0x06))

        lever, num = (0x40, 0) if gear == 0 else (0x60, 0) if gear == 1 else (0x81, min(gear - 1, 9))
        # R / N / S1 S2.. gear number trick from fatihcesur/bmw-f30-cluster-simhub
        self.send(0x3FD, crc(0xD6, num << 4 | c, lever, 0xFC, 0xFF))

        # fuel level + fuel used counter. if they dont match the cluster thinks the tank is empty
        # counter rate from fatihcesur/bmw-f30-cluster-simhub
        raw = fuel_raw(fuel_pct)
        self.send(0x349, [0, raw, 0, raw, 0])
        if fuel_l is not None and self.last_fuel is not None and 0 < self.last_fuel - fuel_l < 1:
            self.fuel_used += (self.last_fuel - fuel_l) * 4100
        self.last_fuel = fuel_l
        self.send(0x2C4, crc(0xC6, int(self.fuel_used) & 0xFF, 0xFF, 0x64, 0x64, 0x64, 0x01, 0xF1))
        self.send(0x2BB, crc(0xDE, 0xF0 | c, self.dist & 0xFF, self.dist >> 8, 0xF2))
        self.dist = (self.dist + int(self.speed * 2.9)) & 0xFFFF

        blink = 0x81 | left << 4 | right << 5 if left or right else 0x80
        self.send(0x1F6, [blink, 0xF0])
        self.send(0x21A, [0x04 if lights else 0, 0xC0, 0xF7])  # headlights
        self.send(0x202, [0xFD if lights else 0xFE, 0xFF])  # backlight, FE = off
        for id, xor, first, rest in OK_MSGS:
            self.send(id, crc(xor, first | c, *rest))
        self.send(0x33B, crc(0x6B, 0xF0 | self.acc, 0x5C, 0x70, 0x00, 0x00))
        self.send(0x0D7, [self.count, 0xFF])

        self.c = (self.c + 1) % 14
        self.count = (self.count + 1) % 254
        self.acc = (self.acc + 4) % 15


def main():
    dash = Cluster()
    mem = lua = None

    # stay quiet for 7 seconds first, then the cluster wakes up fresh
    start = time.time()
    while time.time() - start < 7:
        dash.drain()

    print("running, ctrl+c to stop")
    state = IDLE
    next_fast = next_slow = time.time()
    try:
        while True:
            now = time.time()
            if now >= next_fast:  # speed + rpm 50x a sec
                mem = mem or open_ac()
                lua = lua or shm("Local\\F30Cluster")
                state = game_state(mem, lua) if mem else IDLE
                dash.needles(*state[:3])
                next_fast = max(next_fast + 0.02, now)
            if now >= next_slow:  # rest 10x a sec
                dash.status(*state[2:])
                next_slow = max(next_slow + 0.1, now)
            dash.drain()
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass

    print("ignition off")
    dash.speed = dash.rpm = 0  # make sure it goes to sleep at 0 km/h
    for _ in range(10):
        dash.needles(0, 0, 1)
        dash.status(*IDLE[2:], ignition=False)
        dash.drain()
        time.sleep(0.1)
    dash.bus.shutdown()


if __name__ == "__main__":
    main()
