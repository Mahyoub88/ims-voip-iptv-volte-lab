"""Small dependency-free pcap reader plus the voice-quality maths used by the lab.

* read_udp(path)      -> list of UDP packets (time, src, dst, sport, dport, dscp, payload)
* sip_messages(...)   -> parsed SIP start lines / Call-IDs for the ladder diagram
* rtp_packets(...)    -> RTP header fields
* voice_metrics(...)  -> loss, one-way delay, RFC 3550 jitter and E-model MOS
"""
import socket
import struct


def read_udp(path):
    out = []
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return out
        magic = struct.unpack("<I", gh[:4])[0]
        endian = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
        nano = magic in (0xA1B23C4D, 0x4D3CB2A1)
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        while True:
            h = f.read(16)
            if len(h) < 16:
                break
            ts, tfrac, incl, _ = struct.unpack(endian + "IIII", h)
            data = f.read(incl)
            t = ts + tfrac / (1e9 if nano else 1e6)
            if linktype == 1:            # Ethernet
                if len(data) < 14 or data[12:14] != b"\x08\x00":
                    continue
                ip = data[14:]
            elif linktype == 113:        # Linux cooked (SLL)
                if data[14:16] != b"\x08\x00":
                    continue
                ip = data[16:]
            else:
                continue
            if len(ip) < 20 or ip[9] != 17:
                continue
            ihl = (ip[0] & 0x0F) * 4
            frag = struct.unpack("!H", ip[6:8])[0]
            if frag & 0x1FFF:
                continue
            udp = ip[ihl:]
            sport, dport, ulen = struct.unpack("!HHH", udp[:6])
            out.append({
                "t": t, "src": socket.inet_ntoa(ip[12:16]), "dst": socket.inet_ntoa(ip[16:20]),
                "sport": sport, "dport": dport, "dscp": ip[1] >> 2,
                "len": len(ip), "payload": udp[8:ulen],
            })
    return out


def sip_messages(pkts):
    msgs = []
    for p in pkts:
        if 5060 not in (p["sport"], p["dport"]):
            continue
        try:
            text = p["payload"].decode("utf-8", "replace")
        except Exception:
            continue
        first = text.split("\r\n", 1)[0]
        if not (first.startswith("SIP/2.0") or " sip:" in first):
            continue
        hdr = {}
        for line in text.split("\r\n")[1:]:
            if not line:
                break
            k, _, v = line.partition(":")
            hdr.setdefault(k.strip().lower(), v.strip())
        label = " ".join(first.split()[1:3]) if first.startswith("SIP/2.0") else first.split()[0]
        msgs.append({"t": p["t"], "src": p["src"], "dst": p["dst"], "label": label,
                     "call_id": hdr.get("call-id", hdr.get("i", "")),
                     "cseq": hdr.get("cseq", "")})
    return msgs


def rtp_packets(pkts, port_min=6000):
    out = []
    for p in pkts:
        b = p["payload"]
        if p["dport"] < port_min or p["dport"] == 5060 or len(b) < 12 or (b[0] >> 6) != 2:
            continue
        pt = b[1] & 0x7F
        if pt not in (0, 8):
            continue
        seq, ts, ssrc = struct.unpack("!HII", b[2:12])
        out.append({"t": p["t"], "seq": seq, "ts": ts, "ssrc": ssrc, "src": p["src"],
                    "dst": p["dst"], "dscp": p["dscp"], "len": p["len"]})
    return out


def emodel_mos(one_way_ms, loss_pct, bpl=25.1, ie=0.0, extra_ms=60.0):
    """ITU-T G.107 E-model, simplified (Cole & Rosenbluth delay term).

    `extra_ms` adds packetisation (20 ms) and a 40 ms de-jitter buffer to the
    measured network delay to approximate mouth-to-ear delay. G.711 with packet
    loss concealment: Ie = 0, Bpl = 25.1 (ITU-T G.113 Appendix I)."""
    d = one_way_ms + extra_ms
    i_d = 0.024 * d + (0.11 * (d - 177.3) if d > 177.3 else 0.0)
    ie_eff = ie + (95 - ie) * loss_pct / (loss_pct + bpl)
    r = max(0.0, min(100.0, 93.2 - i_d - ie_eff))
    mos = 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6
    return round(r, 1), round(max(1.0, min(4.5, mos)), 2)


def voice_metrics(sent, received, clock=8000):
    """Per-stream metrics from sender-side and receiver-side captures taken on
    the same host clock (Mininet namespaces share one clock)."""
    tx = {p["seq"]: p for p in sent}
    rx = {}
    for p in received:
        rx.setdefault(p["seq"], p)
    n_tx = len(tx)
    common = sorted(set(tx) & set(rx))
    delays = [(rx[s]["t"] - tx[s]["t"]) * 1000 for s in common]
    # RFC 3550 interarrival jitter, in arrival order
    j, prev = 0.0, None
    for p in sorted(rx.values(), key=lambda x: x["t"]):
        if prev is not None:
            d = (p["t"] - prev["t"]) - (p["ts"] - prev["ts"]) / clock
            j += (abs(d) - j) / 16
        prev = p
    loss = 100.0 * (n_tx - len(common)) / n_tx if n_tx else 0.0
    mean_d = sum(delays) / len(delays) if delays else float("nan")
    srt = sorted(delays)
    p95 = srt[int(0.95 * (len(srt) - 1))] if srt else float("nan")
    r, mos = emodel_mos(mean_d, loss)
    return {
        "packets_sent": n_tx, "packets_received": len(common),
        "loss_pct": round(loss, 2),
        "delay_mean_ms": round(mean_d, 2), "delay_p95_ms": round(p95, 2),
        "delay_max_ms": round(max(delays), 2) if delays else None,
        "jitter_ms": round(j * 1000, 2), "r_factor": r, "mos": mos,
        "dscp_seen_at_receiver": sorted({p["dscp"] for p in received}),
        "delay_series_ms": [round(x, 2) for x in delays],
    }
