#!/usr/bin/env python3
"""Build the README figures (SVG) from results/results.json and the logs."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
from matplotlib.patches import FancyBboxPatch      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")
LOGS = os.path.join(ROOT, "results", "logs")
os.makedirs(OUT, exist_ok=True)
r = json.load(open(os.path.join(ROOT, "results", "results.json")))

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"          # categorical slots 1-3
INK, SEC, GRID, BG = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({"svg.fonttype": "none", "font.family": "DejaVu Sans", "axes.edgecolor": GRID,
                     "axes.labelcolor": SEC, "xtick.color": SEC, "ytick.color": SEC,
                     "figure.facecolor": BG, "axes.facecolor": BG})
CASES = [("baseline", "Idle trunk"), ("congested_fifo", "Congested,\nsingle FIFO"),
         ("congested_qos", "Congested,\nEF + CS3 priority class")]


def style(ax, title, ylabel):
    ax.set_title(title, color=INK, loc="left", fontsize=11)
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)


def save(fig, fn, note=None):
    if note:
        fig.text(0.01, 0.01, note, color=SEC, fontsize=7.5)
        fig.tight_layout(rect=(0, 0.05, 1, 1))
    else:
        fig.tight_layout()
    fig.savefig(os.path.join(OUT, fn))
    plt.close(fig)


# ------------------------------------------------------------------ topology
def box(ax, x, y, t, w=1.3, h=0.62, fc="#ffffff", ec=BLUE):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=1.2))
    ax.text(x, y, t, ha="center", va="center", fontsize=7.6, color=INK)


fig, ax = plt.subplots(figsize=(9.6, 4.6))
ax.set_xlim(-0.2, 12.3)
ax.set_ylim(0, 6)
ax.axis("off")
sw = {"s1": (2, 3), "s2": (6, 3), "s3": (10, 3)}
ax.plot([2, 10], [3, 3], color=BLUE, lw=3, zorder=0)
ax.text(4, 3.18, "trunk", ha="center", fontsize=7, color=SEC)
ax.text(8, 3.18, "trunk  (10 Mbit/s HTB in exp. 2)", ha="center", fontsize=7, color=SEC)
for n, (x, y) in sw.items():
    box(ax, x, y, f"{n}\nOpen vSwitch", w=1.3, h=0.7, fc="#cde2fb")
left = [("ue1\n10.0.0.1", 0.9, 5.0), ("ue2\n10.0.0.2", 2.2, 5.0), ("tv1\n10.0.0.21", 1.5, 1.0)]
core = [("P-CSCF\nKamailio .10", 4.1, 5.0), ("S-CSCF\nKamailio .11", 5.6, 5.0),
        ("AS\nAsterisk .12", 7.1, 5.0), ("IPTV head-end\n.20", 5.0, 1.0), ("bg (load)\n.30", 6.9, 1.0)]
right = [("ue3\n10.0.0.3", 9.6, 5.0), ("ue4\n10.0.0.4", 10.9, 5.0), ("tv2\n10.0.0.22", 8.9, 1.0),
         ("tv3\n10.0.0.23", 10.25, 1.0), ("sink\n.31", 11.6, 1.0)]
for group, s in ((left, "s1"), (core, "s2"), (right, "s3")):
    sx, sy = sw[s]
    for t, x, y in group:
        ax.plot([x, sx], [y + (-0.3 if y > 3 else 0.3), sy + (0.35 if y > 3 else -0.35)], color=GRID, lw=1.2, zorder=0)
        box(ax, x, y, t, w=1.25 if "\n" in t else 1.1)
ax.text(0.1, 5.85, "IMS / VoIP / IPTV lab — Mininet, Open vSwitch, Kamailio, Asterisk, SIPp, FFmpeg",
        fontsize=10, color=INK)
fig.savefig(os.path.join(OUT, "topology.svg"))
plt.close(fig)

# ------------------------------------------------------------------ SIP ladder (exp 1 call)
msgs = json.load(open(os.path.join(LOGS, "e1_sip_messages.json")))
cid = r["experiment1"]["calls"]["1001_to_1003"]["call_id"]
call = [m for m in msgs if m["call_id"] == cid]
# drop retransmissions (same src/dst/label/cseq)
seen, flow = set(), []
for m in call:
    k = (m["src"], m["dst"], m["label"], m["cseq"])
    if k not in seen:
        seen.add(k)
        flow.append(m)
cols = {"10.0.0.1": ("UE 1001\n10.0.0.1", 0), "10.0.0.10": ("P-CSCF\n10.0.0.10", 1),
        "10.0.0.11": ("S-CSCF\n10.0.0.11", 2), "10.0.0.3": ("UE 1003\n10.0.0.3", 3)}
flow = [m for m in flow if m["src"] in cols and m["dst"] in cols]
t0 = flow[0]["t"]
n = len(flow)
fig, ax = plt.subplots(figsize=(8.6, 0.32 * n + 1.6))
ax.set_xlim(-0.6, 3.6)
ax.set_ylim(n + 0.6, -1.2)
ax.axis("off")
for ip, (lbl, x) in cols.items():
    ax.text(x, -0.75, lbl, ha="center", va="center", fontsize=8.5, color=INK,
            bbox=dict(boxstyle="round,pad=0.3", fc="#cde2fb", ec=BLUE, lw=1))
    ax.plot([x, x], [-0.3, n + 0.4], color=GRID, lw=1.2, zorder=0)
for i, m in enumerate(flow):
    xa, xb = cols[m["src"]][1], cols[m["dst"]][1]
    color = BLUE if not m["label"][:1].isdigit() else SEC
    ax.annotate("", xy=(xb, i + 0.3), xytext=(xa, i + 0.3),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.1))
    ax.text((xa + xb) / 2, i + 0.18, m["label"], ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.text(-0.55, i + 0.3, f"{(m['t'] - t0) * 1000:7.1f} ms", va="center", fontsize=6.8, color=SEC)
ax.set_title("Experiment 1 — captured SIP flow of call 1001 → 1003 (timestamps relative to INVITE)",
             loc="left", fontsize=10, color=INK)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "exp1_sip_call_flow.svg"))
plt.close(fig)

# ------------------------------------------------------------------ exp 2
e2 = r["experiment2"]
labels = [lbl for _, lbl in CASES]


def summary_bars(metric, title, ylabel, fn, fmt, ymax=None, note=None):
    fig, ax = plt.subplots(figsize=(7, 3.6))
    means = [e2[k]["summary"][metric]["mean"] for k, _ in CASES]
    lo = [e2[k]["summary"][metric]["min"] for k, _ in CASES]
    hi = [e2[k]["summary"][metric]["max"] for k, _ in CASES]
    b = ax.bar(labels, means, color=BLUE, width=0.5)
    if ymax:
        ax.set_ylim(0, ymax)
    else:
        ax.set_ylim(0, max(hi) * 1.25)
    ax.errorbar(range(3), means, yerr=[[m - lmin for m, lmin in zip(means, lo)],
                                        [h - m for m, h in zip(means, hi)]],
                fmt="none", ecolor=INK, elinewidth=1, capsize=4)
    for rect, v, a, z in zip(b, means, lo, hi):
        txt = fmt.format(v) + ("" if a == z else f"\n({fmt.format(a)}–{fmt.format(z)})")
        top = ax.get_ylim()[1]
        ax.text(rect.get_x() + rect.get_width() / 2, z + 0.015 * top, txt, ha="center", va="bottom",
                color=INK, fontsize=8.5)
    style(ax, title, ylabel)
    save(fig, fn, note)


n_runs = r["meta"]["qos_repetitions"]
note = (f"Mean of {n_runs} calls per case (range in brackets). G.711 A-law, 20 ms packets; "
        f"trunk 10 Mbit/s, background UDP 12 Mbit/s.")
summary_bars("mos", "Experiment 2 — voice quality (E-model MOS) at the callee", "MOS (1–4.5)",
             "exp2_mos.svg", "{:.2f}", 5.2, note)
summary_bars("loss_pct", "Experiment 2 — RTP packet loss, 1001 → 1003", "Packet loss (%)",
             "exp2_loss.svg", "{:.1f}%", None, note)
summary_bars("delay_mean_ms", "Experiment 2 — mean one-way network delay", "Delay (ms)",
             "exp2_delay.svg", "{:.1f}", None, note)

fig, ax = plt.subplots(figsize=(8, 3.8))
for (k, lbl), c in zip(CASES, (BLUE, ORANGE, AQUA)):
    s = json.load(open(os.path.join(LOGS, f"e2_{k}_r1_delay_series.json")))
    ax.plot([i * 0.02 for i in range(len(s))], s, color=c, lw=2, label=lbl.replace("\n", " "))
style(ax, "Experiment 2 — one-way delay of each received RTP packet (run 1)", "Delay (ms)")
ax.set_xlabel("Received packet number × 20 ms (s)")
ax.set_xlim(0, 21)
ax.legend(frameon=False, fontsize=8, loc="center right", bbox_to_anchor=(1.0, 0.6))
save(fig, "exp2_delay_series.svg",
     "With the single FIFO, lost packets are missing from the series, so its x-axis is shorter.")

# ------------------------------------------------------------------ exp 3
e3 = r["experiment3"]
links = [("s2_to_s1", "Trunk s2 → s1\n(1 receiver)"), ("s2_to_s3", "Trunk s2 → s3\n(2 receivers)"),
         ("to_ue4_non_member", "Port to ue4\n(not a viewer)")]
fig, ax = plt.subplots(figsize=(7.2, 3.8))
w = 0.34
for j, (mode, c) in enumerate((("unicast", BLUE), ("multicast", ORANGE))):
    vals = [e3[mode]["link_MB"][k] for k, _ in links]
    xs = [i + (j - 0.5) * (w + 0.02) for i in range(len(links))]
    b = ax.bar(xs, vals, width=w, color=c, label=mode.capitalize())
    for rect, v in zip(b, vals):
        ax.text(rect.get_x() + w / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8.5, color=INK)
ax.set_xticks(range(len(links)))
ax.set_xticklabels([lbl for _, lbl in links])
style(ax, "Experiment 3 — bytes carried for one 15 s, 2 Mbit/s IPTV channel", "MB sent on link")
ax.legend(frameon=False, fontsize=8.5)
src = e3["source"]["frames"]
rx = ", ".join(f"{k} {v['frames_bit_exact']}/{src}" for k, v in e3["multicast"]["receivers"].items())
save(fig, "exp3_iptv_link_bytes.svg", f"Multicast with IGMP snooping. Bit-exact frames received: {rx}.")
print("figures written to docs/images/")
