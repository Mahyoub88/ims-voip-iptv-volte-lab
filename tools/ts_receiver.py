"""Minimal IPTV set-top receiver.

Receives an MPEG-TS stream over UDP (unicast, or multicast after an IGMP
join), writes every byte to a file and checks the MPEG-TS continuity counters
so lost transport packets can be counted.  Stops after `--idle` seconds
without data.

    python3 tools/ts_receiver.py --port 5000 --group 239.1.1.1 --ifaddr 10.0.0.22 --out tv2.ts
"""
import argparse
import json
import socket
import struct
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--group", help="multicast group to join (omit for unicast)")
    ap.add_argument("--ifaddr", default="0.0.0.0", help="local interface address for the join")
    ap.add_argument("--out", required=True)
    ap.add_argument("--idle", type=float, default=3.0)
    ap.add_argument("--wait", type=float, default=30.0, help="max seconds to wait for the first packet")
    a = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.bind(("", a.port))
    if a.group:
        mreq = struct.pack("4s4s", socket.inet_aton(a.group), socket.inet_aton(a.ifaddr))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    cc = {}
    stats = {"datagrams": 0, "bytes": 0, "ts_packets": 0, "cc_errors": 0}
    first = last = None
    s.settimeout(a.wait)
    with open(a.out, "wb") as f:
        while True:
            try:
                data = s.recv(65535)
            except socket.timeout:
                break
            now = time.time()
            first = first or now
            last = now
            s.settimeout(a.idle)
            f.write(data)
            stats["datagrams"] += 1
            stats["bytes"] += len(data)
            for i in range(0, len(data) - 187, 188):
                pkt = data[i:i + 188]
                if pkt[0] != 0x47:
                    continue
                stats["ts_packets"] += 1
                pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
                if pid == 0x1FFF or not (pkt[3] & 0x10):      # null packet / no payload
                    continue
                c = pkt[3] & 0x0F
                if pid in cc and c != (cc[pid] + 1) % 16:
                    stats["cc_errors"] += 1
                cc[pid] = c
    stats["duration_s"] = round((last - first), 2) if first else 0
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
