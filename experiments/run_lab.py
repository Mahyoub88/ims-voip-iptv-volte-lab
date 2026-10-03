"""Run every experiment of the IMS / VoIP / IPTV lab and write results/results.json.

    sudo python3 experiments/run_lab.py            # all experiments
    sudo python3 experiments/run_lab.py --only 3   # one experiment, merged into results.json

Experiment 1 - IMS signalling
    * four UEs register through the P-CSCF; the S-CSCF challenges them with
      HTTP digest (401) and stores the binding with the P-CSCF Path
    * negative checks: wrong password, unknown subscriber, call to a user that
      is not registered
    * UE-to-UE call (1001 -> 1003) routed P-CSCF -> S-CSCF -> P-CSCF -> UE
    * AS services selected by the S-CSCF filter: 600 echo, 700 announcement
    * every SIP message is captured on the sending host -> ladder diagram

Experiment 2 - VoIP QoS on a congested trunk
    The s2 -> s3 trunk is an HTB queue limited to 10 Mbit/s.  A 20 s G.711 call
    (1001 -> 1003; media marked DSCP EF, SIP marked CS3) is set up and carried
    while a 12 Mbit/s UDP flow from "bg" to "sink" overloads the same trunk.
      baseline       : no background traffic, single FIFO class
      congested_fifo : background traffic, single FIFO class (best effort)
      congested_qos  : background traffic, EF + CS3 in a priority class
    Call-setup time, RTP loss, one-way delay, RFC 3550 jitter and E-model MOS
    are computed from captures at the caller and the callee; each case is
    repeated REPS times.

Experiment 3 - IPTV delivery
    A 2 Mbit/s H.264 channel is sent from the head-end to three set-top hosts
    (tv1 behind s1, tv2 and tv3 behind s3), first as three unicast streams,
    then as one multicast group (239.1.1.1) with IGMP snooping on the switches.
    Bytes on each trunk, bytes leaking to a non-member port and received
    frame-by-frame integrity of every recording (decoded frames that are
    bit-identical to the transmitted programme, MPEG-TS continuity errors)
    are measured.
"""
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "topology"))
sys.path.insert(0, HERE)

from mininet.log import setLogLevel  # noqa: E402

import pcap_tools as pt  # noqa: E402
from ims_topo import build_network, prepare_hosts, trunk_intf  # noqa: E402

RUN = "/tmp/ims-lab-run"
RES = os.path.join(ROOT, "results")
LOGS = os.path.join(RES, "logs")
SIPP = os.path.join(ROOT, "sipp")
PCAP_VOICE = os.path.join(SIPP, "voice_g711a_20s.pcap")
PCSCF = "10.0.0.10:5060"
USERS = {"ue1": "1001", "ue2": "1002", "ue3": "1003", "ue4": "1004"}

TRUNK_RATE = "10mbit"
BG_RATE = "12M"
QUEUE_PKTS = 50
REPS = 3          # calls per QoS case


# --------------------------------------------------------------------------- helpers
def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def start_core(net):
    os.makedirs(f"{RUN}/ast/etc", exist_ok=True)
    os.makedirs(f"{RUN}/ast/log", exist_ok=True)
    os.makedirs(f"{RUN}/ast/spool", exist_ok=True)
    for f in glob.glob(os.path.join(ROOT, "ims/asterisk/*.conf")):
        txt = open(f).read().replace("@RUN@", f"{RUN}/ast").replace("@ETC@", f"{RUN}/ast/etc")
        open(f"{RUN}/ast/etc/{os.path.basename(f)}", "w").write(txt)
    kam = os.path.join(ROOT, "ims/kamailio")
    net.get("pcscf").cmd(f"kamailio -f {kam}/pcscf.cfg -P {RUN}/pcscf.pid -Y {RUN} -E > {RUN}/pcscf.log 2>&1 &")
    net.get("scscf").cmd(f"kamailio -f {kam}/scscf.cfg -P {RUN}/scscf.pid -Y {RUN} -E > {RUN}/scscf.log 2>&1 &")
    net.get("as").cmd(f"asterisk -C {RUN}/ast/etc/asterisk.conf -f -U root > {RUN}/asterisk.out 2>&1 &")
    for _ in range(60):
        if "Asterisk Ready" in open(f"{RUN}/ast/log/messages").read() if os.path.exists(f"{RUN}/ast/log/messages") else "":
            break
        time.sleep(0.5)
    time.sleep(1)


def stop_core():
    for p in ("sipp", "kamailio", "asterisk", "iperf3", "ffmpeg", "tcpdump"):
        sh(f"pkill -INT {p}; sleep 0.3; pkill -9 {p}")


def capture(host, name, flt="udp"):
    path = f"{RUN}/{name}.pcap"
    host.cmd(f"tcpdump -i {host.defaultIntf()} -U -s 0 -w {path} '{flt}' > /dev/null 2>&1 &")
    return path, host.lastPid


def stop_capture(host, pid):
    host.cmd(f"kill -INT {pid}")
    time.sleep(0.5)


def sipp(host, args, timeout=60):
    out = host.cmd(f"cd {RUN} && timeout {timeout} sipp {args} -i {host.IP()} -p 5060 "
                   f"-mi {host.IP()} -m 1 -nostdin -trace_err > /dev/null 2>&1; echo rc=$?")
    return int(re.search(r"rc=(\d+)", out).group(1))


def register(host, user, password):
    return sipp(host, f"-sf {SIPP}/register.xml -s {user} -au {user} -ap {password} "
                      f"-timeout 10 {PCSCF}", timeout=15)


def first_response(msgs, call_filter):
    for m in msgs:
        if call_filter(m) and m["label"][:1].isdigit():
            yield m


# --------------------------------------------------------------------------- experiment 1
def experiment1(net):
    hosts = {n: net.get(n) for n in ("ue1", "ue2", "ue3", "ue4", "pcscf", "scscf", "as")}
    caps = {n: capture(h, f"e1_{n}", f"udp and src host {h.IP()}") for n, h in hosts.items()}
    time.sleep(1.5)
    res = {"registrations": {}, "negative": {}, "calls": {}}

    for name in ("ue1", "ue2", "ue3", "ue4"):
        u = USERS[name]
        res["registrations"][u] = {"host": name, "sipp_rc": register(hosts[name], u, f"pw{u}")}
    # negative checks
    res["negative"]["wrong_password_1002"] = {"sipp_rc": register(hosts["ue2"], "1002", "bad-pass")}
    res["negative"]["unknown_subscriber_1999"] = {"sipp_rc": register(hosts["ue2"], "1999", "x")}
    # re-register 1002 correctly (the failed attempt does not remove the binding)
    register(hosts["ue2"], "1002", "pw1002")

    # call to a non-registered user -> 404 expected (scenario fails by design)
    rc = sipp(hosts["ue1"], f"-sf {SIPP}/uac_call.xml -s 1777 -key caller 1001 "
                            f"-key pcap {PCAP_VOICE} -d 1000 {PCSCF}", timeout=15)
    res["negative"]["call_unregistered_1777"] = {"sipp_rc": rc}

    # UE -> UE call
    uas = hosts["ue3"]
    uas.cmd(f"cd {RUN} && sipp -sf {SIPP}/uas_answer.xml -i {uas.IP()} -p 5060 -mi {uas.IP()} "
            f"-m 1 -nostdin -trace_err > /dev/null 2>&1 &")
    time.sleep(1)
    rc = sipp(hosts["ue1"], f"-sf {SIPP}/uac_call.xml -s 1003 -key caller 1001 "
                            f"-key pcap {PCAP_VOICE} -d 8000 {PCSCF}", timeout=40)
    res["calls"]["1001_to_1003"] = {"sipp_rc": rc}
    time.sleep(1)
    # AS echo service
    rc = sipp(hosts["ue2"], f"-sf {SIPP}/uac_call.xml -s 600 -key caller 1002 "
                            f"-key pcap {PCAP_VOICE} -d 6000 {PCSCF}", timeout=40)
    res["calls"]["1002_to_600_echo"] = {"sipp_rc": rc}
    # AS announcement service
    rc = sipp(hosts["ue4"], f"-sf {SIPP}/uac_announce.xml -s 700 -key caller 1004 {PCSCF}", timeout=70)
    res["calls"]["1004_to_700_announcement"] = {"sipp_rc": rc}
    time.sleep(1)

    for n, (path, pid) in caps.items():
        stop_capture(hosts[n], pid)
    pkts = []
    for n, (path, _) in caps.items():
        pkts += pt.read_udp(path)
        shutil.copy(path, os.path.join(LOGS, os.path.basename(path)))
    pkts.sort(key=lambda p: p["t"])
    msgs = pt.sip_messages(pkts)

    # registration timing: first REGISTER sent by the UE -> final response at the UE
    for u, r in res["registrations"].items():
        ip = hosts[r["host"]].IP()
        reg = [m for m in msgs if m["cseq"].endswith("REGISTER") and ip in (m["src"], m["dst"])
               and f"@{ip}" in m["call_id"]]
        cid = next((m["call_id"] for m in reg if m["src"] == ip), None)
        reg = [m for m in reg if m["call_id"] == cid]
        reqs = [m for m in reg if m["src"] == ip]
        resp = [m for m in reg if m["dst"] == ip]
        if reqs and resp:
            r["responses"] = [m["label"] for m in resp]
            r["register_to_200_ms"] = (round((resp[-1]["t"] - reqs[0]["t"]) * 1000, 2)
                                       if resp[-1]["label"].startswith("200") else None)

    # per-call SIP timing: INVITE leaves the UE -> 180 / 200 arrive at the UE
    for key, (caller, callee) in {"1001_to_1003": ("ue1", "1003"), "1002_to_600_echo": ("ue2", "600"),
                                  "1004_to_700_announcement": ("ue4", "700")}.items():
        ip = hosts[caller].IP()
        inv = [m for m in msgs if m["label"] == "INVITE" and m["src"] == ip]
        if not inv:
            continue
        cid = inv[-1]["call_id"]
        call = [m for m in msgs if m["call_id"] == cid]
        t0 = min(m["t"] for m in call if m["label"] == "INVITE" and m["src"] == ip)
        r180 = [m for m in call if m["label"].startswith("180") and m["dst"] == ip]
        r200 = [m for m in call if m["label"].startswith("200") and m["dst"] == ip and "INVITE" in m["cseq"]]
        c = res["calls"][key]
        c["post_dial_delay_ms"] = round((r180[0]["t"] - t0) * 1000, 2) if r180 else None
        c["invite_to_200_ms"] = round((r200[0]["t"] - t0) * 1000, 2) if r200 else None
        c["sip_messages_in_dialog"] = len(call)
        c["call_id"] = cid
    # error responses delivered to the UEs in the negative checks
    seen = {}
    for m in msgs:
        if m["dst"] in ("10.0.0.1", "10.0.0.2") and m["label"][:1] == "4":
            seen.setdefault(m["label"], set()).add(m["cseq"].split()[-1])
    res["negative"]["error_responses_seen"] = {k: sorted(v) for k, v in sorted(seen.items())}

    # RTP counts for the AS services, as seen by the callers
    for key, host in (("1002_to_600_echo", "ue2"), ("1004_to_700_announcement", "ue4")):
        ip = hosts[host].IP()
        rtp_in = [p for p in pt.rtp_packets([p for p in pkts if p["dst"] == ip], port_min=6000)]
        res["calls"][key]["rtp_packets_from_as"] = len(rtp_in)
        res["calls"][key]["rtp_seconds_from_as"] = round(len(rtp_in) * 0.02, 1)

    with open(os.path.join(LOGS, "e1_sip_messages.json"), "w") as f:
        json.dump([{k: v for k, v in m.items()} for m in msgs], f, indent=1)
    return res


# --------------------------------------------------------------------------- experiment 2
def trunk_queue(sw, intf, qos):
    sw.cmd(f"tc qdisc del dev {intf} root 2>/dev/null")
    sw.cmd(f"tc qdisc add dev {intf} root handle 1: htb default 20")
    sw.cmd(f"tc class add dev {intf} parent 1: classid 1:1 htb rate {TRUNK_RATE} ceil {TRUNK_RATE}")
    if qos:
        sw.cmd(f"tc class add dev {intf} parent 1:1 classid 1:10 htb rate 1mbit ceil {TRUNK_RATE} prio 0")
        sw.cmd(f"tc class add dev {intf} parent 1:1 classid 1:20 htb rate 9mbit ceil {TRUNK_RATE} prio 1")
        sw.cmd(f"tc qdisc add dev {intf} parent 1:10 handle 10: pfifo limit {QUEUE_PKTS}")
        sw.cmd(f"tc qdisc add dev {intf} parent 1:20 handle 20: pfifo limit {QUEUE_PKTS}")
        # DSCP EF (46, voice media) and CS3 (24, SIP signalling) -> priority class
        sw.cmd(f"tc filter add dev {intf} parent 1: protocol ip prio 1 u32 match ip dsfield 0xb8 0xfc flowid 1:10")
        sw.cmd(f"tc filter add dev {intf} parent 1: protocol ip prio 2 u32 match ip dsfield 0x60 0xfc flowid 1:10")
    else:
        sw.cmd(f"tc class add dev {intf} parent 1:1 classid 1:20 htb rate {TRUNK_RATE} ceil {TRUNK_RATE}")
        sw.cmd(f"tc qdisc add dev {intf} parent 1:20 handle 20: pfifo limit {QUEUE_PKTS}")
    return sw.cmd(f"tc -s qdisc show dev {intf}")


def experiment2(net):
    s2 = net.get("s2")
    intf = str(trunk_intf(net, "s2", "s3"))
    ue1, ue3, bg, sink = net.get("ue1", "ue3", "bg", "sink")
    # UEs mark media DSCP EF (46) and SIP DSCP CS3 (24); the CSCFs mark the
    # SIP they relay CS3 as well (tos=0x60 in the Kamailio configs)
    for ue in (ue1, ue3):
        ue.cmd("iptables -t mangle -F OUTPUT; "
               "iptables -t mangle -A OUTPUT -p udp ! --dport 5060 ! --sport 5060 -j DSCP --set-dscp 46; "
               "iptables -t mangle -A OUTPUT -p udp --dport 5060 -j DSCP --set-dscp 24; "
               "iptables -t mangle -A OUTPUT -p udp --sport 5060 -j DSCP --set-dscp 24")
    sink.cmd("iperf3 -s -D -p 5201")
    results = {}
    for case, (bg_on, qos) in {"baseline": (False, False), "congested_fifo": (True, False),
                               "congested_qos": (True, True)}.items():
        runs = []
        for rep in range(1, REPS + 1):
            tag = f"e2_{case}_r{rep}"
            trunk_queue(s2, intf, qos)
            c_tx, p_tx = capture(ue1, f"{tag}_ue1", "udp and host 10.0.0.1")
            c_rx, p_rx = capture(ue3, f"{tag}_ue3", "udp and dst host 10.0.0.3 and not port 5060")
            ue3.cmd(f"cd {RUN} && sipp -sf {SIPP}/uas_answer.xml -i {ue3.IP()} -p 5060 -mi {ue3.IP()} "
                    f"-m 1 -nostdin -trace_err > /dev/null 2>&1 &")
            time.sleep(1.5)
            if bg_on:
                bg.cmd(f"iperf3 -c {sink.IP()} -u -b {BG_RATE} -l 1400 -t 120 > {RUN}/{tag}_iperf.txt 2>&1 &")
                bg_pid = bg.lastPid
                time.sleep(3)
            rc = sipp(ue1, f"-sf {SIPP}/uac_call.xml -s 1003 -key caller 1001 -key pcap {PCAP_VOICE} "
                           f"-d 21000 {PCSCF}", timeout=60)
            time.sleep(1)
            stop_capture(ue1, p_tx)
            stop_capture(ue3, p_rx)
            qstats = s2.cmd(f"tc -s qdisc show dev {intf}")
            if bg_on:
                bg.cmd(f"kill -INT {bg_pid}; wait {bg_pid}")
                time.sleep(3)
            ue1_pkts = pt.read_udp(c_tx)
            sent = pt.rtp_packets([p for p in ue1_pkts if p["src"] == "10.0.0.1"])
            m = pt.voice_metrics(sent, pt.rtp_packets(pt.read_udp(c_rx)))
            m["sipp_rc"] = rc
            sip = pt.sip_messages(ue1_pkts)
            inv = [x for x in sip if x["label"] == "INVITE" and x["src"] == "10.0.0.1"]
            ok = [x for x in sip if x["label"].startswith("200") and x["dst"] == "10.0.0.1" and "INVITE" in x["cseq"]]
            m["invite_to_200_ms"] = round((ok[0]["t"] - inv[0]["t"]) * 1000, 1) if inv and ok else None
            m["invite_transmissions"] = len(inv)
            # per-queue counters on the trunk for this call
            m["trunk_queues"] = {
                q: {"sent_pkts": int(sp), "dropped_pkts": int(dp)}
                for q, sp, dp in re.findall(r"qdisc pfifo (\d+):.*?\n Sent \d+ bytes (\d+) pkt \(dropped (\d+)",
                                            qstats, re.S)}
            with open(os.path.join(LOGS, f"{tag}_tc.txt"), "w") as f:
                f.write(qstats)
            if rep == 1:
                for p in (c_tx, c_rx):
                    shutil.copy(p, os.path.join(LOGS, os.path.basename(p)))
                with open(os.path.join(LOGS, f"{tag}_delay_series.json"), "w") as f:
                    json.dump(m["delay_series_ms"], f)
            m.pop("delay_series_ms")
            runs.append(m)
            print(f"  {case:15s} run {rep}: loss {m['loss_pct']:6.2f} %  delay {m['delay_mean_ms']:7.2f} ms  "
                  f"jitter {m['jitter_ms']:6.2f} ms  MOS {m['mos']}  setup {m['invite_to_200_ms']} ms "
                  f"({m['invite_transmissions']} INVITE)")
            sh("pkill sipp")
            time.sleep(1)
        summary = {}
        for k in ("loss_pct", "delay_mean_ms", "delay_p95_ms", "jitter_ms", "mos", "invite_to_200_ms"):
            vals = [r[k] for r in runs if r.get(k) is not None]
            if vals:
                summary[k] = {"mean": round(sum(vals) / len(vals), 2), "min": min(vals), "max": max(vals)}
        results[case] = {"summary": summary, "runs": runs}
    sink.cmd("pkill iperf3")
    for ue in (ue1, ue3):
        ue.cmd("iptables -t mangle -F OUTPUT")
    s2.cmd(f"tc qdisc del dev {intf} root")
    return results


# --------------------------------------------------------------------------- experiment 3
def intf_bytes(intf, direction="tx"):
    return int(open(f"/sys/class/net/{intf}/statistics/{direction}_bytes").read())


def frame_hashes(path):
    """MD5 of every decoded video frame, in decode order."""
    out = sh(f"ffmpeg -v quiet -i {path} -map 0:v -f framemd5 -")
    return [ln.split(",")[-1].strip() for ln in out.splitlines() if ln and not ln.startswith("#")]


def video_check(ref_hashes, path):
    """Compare a received recording with the transmitted programme frame by
    frame: decoded frames, frames bit-identical to the source, missing frames."""
    rx = frame_hashes(path)
    if not rx:
        return {"frames_decoded": 0, "frames_bit_exact": 0, "frames_missing": len(ref_hashes)}
    # every test-pattern frame is unique (it carries a running clock), so a
    # received frame is correct exactly when its hash occurs in the source
    ref = set(ref_hashes)
    exact = len({h for h in rx if h in ref})
    return {"frames_decoded": len(rx), "frames_bit_exact": exact,
            "frames_damaged_or_missing": len(ref_hashes) - exact}


def experiment3(net):
    src = f"{RUN}/iptv_src.ts"
    sh(f"ffmpeg -y -v error -f lavfi -i testsrc2=size=1280x720:rate=25 -f lavfi "
       f"-i sine=frequency=440:sample_rate=48000 -t 15 -c:v libx264 -preset veryfast "
       f"-b:v 2000k -maxrate 2000k -bufsize 1000k -g 25 -c:a aac -b:a 96k -f mpegts {src}")
    ref = frame_hashes(src)
    head = net.get("iptv")
    tvs = [net.get(n) for n in ("tv1", "tv2", "tv3")]
    t21, t23 = str(trunk_intf(net, "s2", "s1")), str(trunk_intf(net, "s2", "s3"))
    ue4_port = str(net.get("ue4").connectionsTo(net.get("s3"))[0][1])
    # IGMP snooping on every switch; access switches forward IGMP reports
    # up their trunk so the core switch learns which trunks have members
    for s in ("s1", "s2", "s3"):
        sh(f"ovs-vsctl set Bridge {s} mcast_snooping_enable=true "
           f"other_config:mcast-snooping-disable-flood-unregistered=true")
    for a, b in (("s1", "s2"), ("s3", "s2")):
        sh(f"ovs-vsctl set Port {trunk_intf(net, a, b)} other_config:mcast-snooping-flood-reports=true")
    results = {"source": {"frames": len(ref), "MB": round(os.path.getsize(src) / 1e6, 2),
                          "video": "H.264 1280x720 25 fps, 2 Mbit/s + AAC, 15 s, MPEG-TS"}}
    rx_tool = os.path.join(ROOT, "tools", "ts_receiver.py")
    for mode in ("unicast", "multicast"):
        counters = (("s2_to_s1", t21), ("s2_to_s3", t23), ("to_ue4_non_member", ue4_port))
        b0 = {k: intf_bytes(v) for k, v in counters}
        for tv in tvs:
            grp = f"--group 239.1.1.1 --ifaddr {tv.IP()}" if mode == "multicast" else ""
            tv.cmd(f"python3 {rx_tool} --port 5000 {grp} --out {RUN}/e3_{mode}_{tv.name}.ts "
                   f"> {RUN}/e3_{mode}_{tv.name}.json 2>&1 &")
        time.sleep(2)
        if mode == "multicast":
            head.cmd(f"ffmpeg -v error -re -i {src} -c copy -f mpegts "
                     f"'udp://239.1.1.1:5000?ttl=4&pkt_size=1316&localaddr={head.IP()}' > {RUN}/e3_head.log 2>&1")
            # group membership learned by each switch (receivers still joined)
            snoop = sh("for s in s1 s2 s3; do echo \"== $s\"; ovs-appctl mdb/show $s; done")
            with open(os.path.join(LOGS, "e3_igmp_snooping_tables.txt"), "w") as f:
                f.write(snoop)
        else:
            procs = " & ".join(
                f"ffmpeg -v error -re -i {src} -c copy -f mpegts 'udp://{tv.IP()}:5000?pkt_size=1316'"
                for tv in tvs)
            head.cmd(f"({procs} & wait) > {RUN}/e3_head.log 2>&1")
        time.sleep(5)
        b1 = {k: intf_bytes(v) for k, v in counters}
        r = {"link_MB": {k: round((b1[k] - b0[k]) / 1e6, 2) for k, _ in counters}, "receivers": {}}
        for tv in tvs:
            try:
                st = json.loads(open(f"{RUN}/e3_{mode}_{tv.name}.json").read().strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                st = {}
            st.update(video_check(ref, f"{RUN}/e3_{mode}_{tv.name}.ts"))
            r["receivers"][tv.name] = st
        results[mode] = r
        print(f"  {mode:9s} s2->s1 {r['link_MB']['s2_to_s1']} MB, s2->s3 {r['link_MB']['s2_to_s3']} MB, "
              f"ue4 {r['link_MB']['to_ue4_non_member']} MB | " +
              ", ".join(f"{k} {v['frames_bit_exact']}/{len(ref)} cc_err {v.get('cc_errors')}"
                        for k, v in r["receivers"].items()))
    return results


# --------------------------------------------------------------------------- main
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, nargs="*", choices=(1, 2, 3),
                    help="run only these experiments and merge them into results.json")
    only = set(ap.parse_args().only or (1, 2, 3))
    setLogLevel("warning")
    shutil.rmtree(RUN, ignore_errors=True)
    os.makedirs(RUN)
    os.makedirs(LOGS, exist_ok=True)
    if only == {1, 2, 3}:
        for f in glob.glob(os.path.join(LOGS, "*")):
            os.remove(f)
    if not os.path.exists(PCAP_VOICE):
        sh(f"python3 {ROOT}/tools/make_rtp_pcap.py --seconds 20 --out {PCAP_VOICE}")
    sh("mn -c")
    sh("sysctl -qw net.core.rmem_max=8388608 net.core.rmem_default=1048576")
    net = build_network()
    net.start()
    prepare_hosts(net)
    results = {"meta": {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "kamailio": sh("kamailio -v | head -1").strip(),
                        "asterisk": sh("asterisk -V").strip(),
                        "sipp": sh("sipp -v 2>&1 | grep -m1 SIPp").strip(),
                        "ovs": sh("ovs-vsctl --version | head -1").strip(),
                        "ffmpeg": sh("ffmpeg -version | head -1").strip(),
                        "trunk_rate": TRUNK_RATE, "background_rate": BG_RATE, "queue_pkts": QUEUE_PKTS,
                        "qos_repetitions": REPS}}
    try:
        start_core(net)
        if 1 in only:
            print("Experiment 1: IMS registration, routing and AS services")
            results["experiment1"] = e1 = experiment1(net)
            print(json.dumps(e1["calls"], indent=1))
        if 2 in only:
            print("Experiment 2: VoIP QoS on a congested trunk")
            if 1 not in only:
                for u, name in USERS.items():
                    register(net.get(u), name, f"pw{name}")
            results["experiment2"] = experiment2(net)
        if 3 in only:
            print("Experiment 3: IPTV unicast vs multicast")
            results["experiment3"] = experiment3(net)
    finally:
        for f in ("pcscf.log", "scscf.log"):
            if os.path.exists(f"{RUN}/{f}"):
                shutil.copy(f"{RUN}/{f}", os.path.join(LOGS, f))
        if os.path.exists(f"{RUN}/ast/log/messages"):
            shutil.copy(f"{RUN}/ast/log/messages", os.path.join(LOGS, "asterisk_messages.log"))
        stop_core()
        net.stop()
    path = os.path.join(RES, "results.json")
    if only != {1, 2, 3} and os.path.exists(path):
        merged = json.load(open(path))
        merged.update({k: v for k, v in results.items() if k != "meta"})
        results = merged
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print("results written to results/results.json")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    main()
