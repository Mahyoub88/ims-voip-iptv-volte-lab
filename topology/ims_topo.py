r"""
IMS / VoIP / IPTV lab topology (Mininet + Open vSwitch).

      access A (s1)                 IMS core (s2)                  access B (s3)
  ue1 10.0.0.1  --+          pcscf 10.0.0.10  (Kamailio P-CSCF)    +-- ue3  10.0.0.3
  ue2 10.0.0.2  --+-- s1 ==== scscf 10.0.0.11 (Kamailio S-CSCF) ==== s3 -+-- ue4  10.0.0.4
  tv1 10.0.0.21 --+          as    10.0.0.12  (Asterisk AS)         +-- tv2  10.0.0.22
                             iptv  10.0.0.20  (IPTV head-end)       +-- tv3  10.0.0.23
                             bg    10.0.0.30  (background load)     +-- sink 10.0.0.31

The switches are plain L2 learning switches (OVS fail-mode standalone, no
controller).  Access links run at 100 Mbit/s; the two trunks (====) are left
unshaped here because the experiments install their own HTB queueing on the
s2 -> s3 trunk (with or without a priority class for voice).
"""
from functools import partial

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.topo import Topo

ACCESS_BW = 100  # Mbit/s

HOSTS = {
    # name: (ip, switch)
    "ue1": ("10.0.0.1", "s1"), "ue2": ("10.0.0.2", "s1"), "tv1": ("10.0.0.21", "s1"),
    "pcscf": ("10.0.0.10", "s2"), "scscf": ("10.0.0.11", "s2"), "as": ("10.0.0.12", "s2"),
    "iptv": ("10.0.0.20", "s2"), "bg": ("10.0.0.30", "s2"),
    "ue3": ("10.0.0.3", "s3"), "ue4": ("10.0.0.4", "s3"),
    "tv2": ("10.0.0.22", "s3"), "tv3": ("10.0.0.23", "s3"), "sink": ("10.0.0.31", "s3"),
}


class IMSTopo(Topo):
    def build(self):
        sw = {n: self.addSwitch(n, failMode="standalone") for n in ("s1", "s2", "s3")}
        for name, (ip, s) in HOSTS.items():
            h = self.addHost(name, ip=f"{ip}/24")
            self.addLink(h, sw[s], bw=ACCESS_BW)
        self.addLink(sw["s1"], sw["s2"])
        self.addLink(sw["s2"], sw["s3"])


def build_network():
    """`datapath="user"` runs Open vSwitch in userspace so the lab also works
    where the openvswitch kernel module is unavailable (containers, WSL, VMs)."""
    switch = partial(OVSSwitch, datapath="user", failMode="standalone")
    return Mininet(topo=IMSTopo(), switch=switch, controller=None, link=TCLink,
                   autoSetMacs=True)


def prepare_hosts(net):
    """Disable checksum offload (the userspace datapath does not complete it)
    and add a multicast route so IPTV receivers can join groups."""
    for h in net.hosts:
        for intf in h.intfNames():
            h.cmd(f"ethtool -K {intf} tx off rx off >/dev/null 2>&1")
        h.cmd(f"ip route add 224.0.0.0/4 dev {h.defaultIntf()} 2>/dev/null")


def trunk_intf(net, a="s2", b="s3"):
    """Return the interface on switch `a` that faces switch `b`."""
    sa, sb = net.get(a), net.get(b)
    return sa.connectionsTo(sb)[0][0]


if __name__ == "__main__":
    from mininet.cli import CLI
    from mininet.log import setLogLevel

    setLogLevel("info")
    net = build_network()
    net.start()
    prepare_hosts(net)
    CLI(net)
    net.stop()
