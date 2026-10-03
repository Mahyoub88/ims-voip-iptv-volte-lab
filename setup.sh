#!/usr/bin/env bash
# One-time setup on Ubuntu 24.04 (VM, WSL2 or container). Run as root:  sudo bash setup.sh
set -euo pipefail
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y mininet openvswitch-switch iproute2 iptables \
    ethtool tcpdump iperf3 ffmpeg kamailio asterisk sip-tester python3-matplotlib
# Asterisk and Kamailio are started inside Mininet hosts by the experiment script,
# so stop the system services the packages may have started.
systemctl disable --now asterisk kamailio 2>/dev/null || true
# Open vSwitch daemons (the userspace datapath works without the kernel module)
/usr/share/openvswitch/scripts/ovs-ctl start --system-id=random || true
echo "Setup complete. Next: sudo python3 experiments/run_lab.py && python3 experiments/make_figures.py"
