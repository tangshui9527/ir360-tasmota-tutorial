#!/usr/bin/env python3
"""Gree YAP0F IR frame generator + MQTT sender.
Builds the exact double-frame (A+B) used by YAPOF10 remotes and publishes it
to Tasmota IR-360 (cmnd/tasmota_C78A82/IRsend) as compact RAW timings.
Usage: yap0f_send.py <Power:On|Off> <Mode:Cool|Heat|Fan|Dry|Auto> <Fan:Auto|Low|Medium|High> <Temp:16-30> <Swing:On|Off>
"""
import socket, struct, random, sys

BROKER = ("192.168.31.230", 1883)
TOPIC = "cmnd/tasmota_C78A82/IRsend"

MODE = {"Auto": 0x00, "Cool": 0x01, "Dry": 0x02, "Fan": 0x03, "Heat": 0x04}
FAN = {"Auto": 0x00, "Silent": 0x10, "Low": 0x20, "Medium": 0x30, "High": 0x40, "Max": 0x50}


def checksum(b):
    return (((b[0] & 0x0F) + (b[1] & 0x0F) + (b[2] & 0x0F) + (b[3] & 0x0F) +
             ((b[4] & 0xF0) >> 4) + ((b[5] & 0xF0) >> 4) + ((b[6] & 0xF0) >> 4) + 0x0A) & 0x0F) << 4


def frame(msg_type, power, mode, fan, temp, swing, swing_h=False, light=True, sleep=False):
    b = [0] * 8
    b[0] = MODE[mode] | FAN[fan] | (0x08 if power else 0) | (0x40 if (swing or swing_h) else 0) | (0x80 if sleep else 0)
    b[1] = temp & 0x0F
    b[2] = 0x20 if light else 0  # LIGHT bit (byte2 0x20)
    b[3] = msg_type  # 0x50 frame A / 0x70 frame B
    if swing:
        b[4] |= 0x01
    if swing_h:
        b[4] |= 0x10  # horizontal swing
    if msg_type == 0x70:
        b[6] |= FAN[fan]
    b[7] = checksum(b)
    return b


def timings(state, end_gap):
    out = [9000, 4500]

    def block(rng):
        seq = []
        for i in rng:
            for bit in range(8):
                seq += [620, 1600 if (state[i] >> bit) & 1 else 540]
        return seq

    out += block(range(4))
    out += [620, 540, 620, 1600, 620, 540]  # footer 0b010
    out += [620, 19980]
    out += block(range(4, 8))
    out.append(620)
    if end_gap:
        out.append(end_gap)
    return out


def build_payload(power_on, mode, fan, temp, swing_on, swing_h=False, light=True, sleep=False):
    A = frame(0x50, power_on, mode, fan, temp, swing_on, swing_h, light, sleep)
    B = frame(0x70, power_on, mode, fan, temp, swing_on, swing_h, light, sleep)
    t = timings(A, 7300) + timings(B, 0)
    return "0," + "".join(("+" if i % 2 == 0 else "-") + str(v) for i, v in enumerate(t))


def mqtt_publish(topic, payload):
    s = socket.create_connection(BROKER, timeout=6)
    cid = b"ha-yap0f-%d" % random.randint(1000, 9999)
    vh = struct.pack(">H", 4) + b"MQTT" + bytes([4, 0x02]) + struct.pack(">H", 60)
    body = struct.pack(">H", len(cid)) + cid
    s.sendall(bytes([0x10, len(vh) + len(body)]) + vh + body)
    s.recv(4)  # CONNACK
    tp = topic.encode()
    pb = payload.encode()
    rem = 2 + len(tp) + len(pb)
    lenb = b""
    while True:
        d = rem % 128
        rem //= 128
        if rem:
            d |= 0x80
        lenb += bytes([d])
        if not rem:
            break
    s.sendall(bytes([0x30]) + lenb + struct.pack(">H", len(tp)) + tp + pb)
    s.sendall(bytes([0xE0, 0x00]))  # DISCONNECT
    s.close()


def main():
    argv = list(sys.argv[1:6]) + [sys.argv[6] if len(sys.argv) > 6 else "On"] + [sys.argv[7] if len(sys.argv) > 7 else "Off"] + [sys.argv[8] if len(sys.argv) > 8 else "Off"]
    power, mode, fan, temp, swing, light, sleep, swing_h = argv
    if power not in ("On", "Off") or mode not in MODE or fan not in FAN or swing not in ("On", "Off", "Auto") or light not in ("On", "Off") or sleep not in ("On", "Off") or swing_h not in ("On", "Off"):
        print("bad args"); sys.exit(1)
    temp = max(16, min(30, int(temp)))
    payload = build_payload(power == "On", mode, fan, temp, swing in ("On", "Auto"), light == "On", sleep == "On", swing_h == "On")
    mqtt_publish(TOPIC, payload)
    print("sent", power, mode, fan, temp, swing)


if __name__ == "__main__":
    main()
