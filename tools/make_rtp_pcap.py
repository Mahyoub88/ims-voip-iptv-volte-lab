"""Build the RTP test stream that SIPp plays during calls.

Takes an audio prompt shipped with Asterisk (demo-congrats), converts it with
FFmpeg to 8 kHz G.711 A-law, loops it to the requested length and writes it as
RTP (payload type 8, 20 ms / 160-byte frames, 50 packets/s) inside a pcap file.
SIPp rewrites the addresses and ports when it plays the file.

    python3 tools/make_rtp_pcap.py --seconds 20 --out sipp/voice_g711a_20s.pcap
"""
import argparse
import struct
import subprocess

FRAME = 160  # bytes = 20 ms at 8 kHz, 8 bit


def alaw_audio(src):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", src, "-ar", "8000", "-ac", "1", "-f", "alaw", "-"],
        check=True, capture_output=True).stdout


def ip_checksum(hdr):
    s = sum(struct.unpack("!10H", hdr))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return (~s) & 0xFFFF


def packet(payload, seq, ts, ssrc=0x1A2B3C4D, src="10.0.0.1", dst="10.0.0.2", sport=6000, dport=6000):
    rtp = struct.pack("!BBHII", 0x80, 8, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc) + payload
    udp = struct.pack("!HHHH", sport, dport, 8 + len(rtp), 0) + rtp
    s = bytes(map(int, src.split("."))); d = bytes(map(int, dst.split(".")))
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0xB8, 20 + len(udp), seq & 0xFFFF, 0, 64, 17, 0, s, d)
    ip = ip[:10] + struct.pack("!H", ip_checksum(ip)) + ip[12:]
    eth = b"\x00\x00\x00\x00\x00\x02" + b"\x00\x00\x00\x00\x00\x01" + b"\x08\x00"
    return eth + ip + udp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/usr/share/asterisk/sounds/en/demo-congrats.gsm")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    audio = alaw_audio(a.src)
    need = int(a.seconds * 8000)
    audio = (audio * (need // len(audio) + 1))[:need]
    with open(a.out, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for i in range(need // FRAME):
            pkt = packet(audio[i * FRAME:(i + 1) * FRAME], i, i * FRAME)
            t_us = i * 20000
            f.write(struct.pack("<IIII", t_us // 1_000_000, t_us % 1_000_000, len(pkt), len(pkt)))
            f.write(pkt)
    print(f"{a.out}: {need // FRAME} RTP packets, {a.seconds:g} s G.711 A-law")


if __name__ == "__main__":
    main()
