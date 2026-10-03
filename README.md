# IMS Multimedia Services — VoIP, IPTV & VoLTE

End-to-end IP multimedia environment covering **enterprise VoIP**, **IPTV streaming**, and **Voice over LTE (VoLTE)** over an **IP Multimedia Subsystem (IMS)** core — plus a study of how an IMS core could interconnect a fixed-line operator and a mobile operator.

> Team project. I worked across all workstreams: the VoIP / Cisco UC deployment, the VoLTE performance analysis, IPTV streaming, the operator-integration study, and the technical documentation.

**Stack:** IMS · SIP · H.323 · VoIP · Cisco CUCM 8.6 · Cisco CME · GNS3 · VMware · VoLTE · LTE / EPC · OPNET Modeler 14.5 · IPTV · VLC · QoS

---

## 1. VoIP — Cisco Unified Communications

**Platform**

- Cisco Unified Communications Manager (CUCM 8.6), deployed on VMware Workstation and managed from the CLI and the web admin GUI.
- A GNS3 topology with three routers, bridged to the CUCM server:

| Node | Role | Addressing |
|---|---|---|
| VGW | Voice gateway (HQ), H.323 toward CUCM | 192.168.154.1/24 |
| BR1 | Branch router running **CME** | WAN link 10.10.10.1 · LAN 192.168.20.0/24 |
| PSTN | PSTN side | 192.168.30.1/24 |

**Configuration**

- **Dial-peers:** POTS and VoIP dial-peers with destination patterns that route calls between CUCM, the branch, and the PSTN.
- **Codec and signalling:** `voice class codec` with G.711 µ-law; H.323 signalling toward CUCM; `allow-connections` for H.323↔H.323, H.323↔SIP, and SIP↔SIP interworking; DTMF relay over H.245.
- **Branch survivability:** BR1 runs as a standalone CME (`telephony-service`). Branch phones keep internal calling if the WAN link to CUCM fails, and branch calls are routed into the CUCM directory when the link is up.
- **CUCM:** NTP (Windows Time service as the phone NTP source) and Date/Time Groups; phone provisioning over TFTP.
- **Endpoints:** Cisco IP Communicator (SCCP), X-Lite and Media5-fone on Android (SIP).
- **Extension Mobility:** service activation, service parameters, phone service URL, default and user device profiles, user association, and phone subscription.

**Result:** calls completed end-to-end with low delay and good voice quality.

---

## 2. IPTV

- LAN video streaming with VLC over HTTP and UDP, including optional transcoding to save bandwidth.
- The stream was received on laptops and on mobile phones on the same network as the voice gateway.

---

## 3. VoLTE — OPNET Modeler 14.5

OPNET 14.5 has no native VoLTE model, so the LTE access network was built from the WiMAX (802.16e) model and its parameters were tuned to behave like LTE.

| Component | Value |
|---|---|
| Cells / base stations | 4 (eNodeB role) |
| Cell radius | 1 km |
| PHY | OFDMA 20 MHz profile, 2048 subcarriers, FDD |
| Frequency band | 10 GHz base, 50 MHz |
| Antenna | STC 2×1 MIMO |
| QoS class | "Gold", UGS scheduling, 5 Mbps max / 1 Mbps min sustained, 30 ms max latency |
| Classifier | IP ToS = Interactive Voice (6) |
| Application | Voice, PCM-quality speech |
| IMS core | P-CSCF, I-CSCF, S-CSCF (SIP proxies), HSS |
| Interworking | ASN gateway, IP cloud, PSTN switch with two phones |
| Mobility | Mobile UE following a multi-cell trajectory (~46 min) |

**Metrics:** voice traffic sent/received, jitter, packet-delay variation, end-to-end delay, WiMAX/LTE access delay, throughput, and MOS.

**Observations**

- Voice-traffic dips line up with cell handovers along the UE trajectory.
- Jitter stayed close to zero.
- Packet-delay variation was in the order of 10⁻⁵ s and fell as the session stabilised.
- Access delay was a few milliseconds, with higher values only at the start of movement.
- Throughput stayed around 180 kbps between handovers.
- PSTN-side phones sent and received voice traffic through the IMS core successfully.

---

## 4. Operator integration study (IMS)

This study compared three ways for a fixed-line operator and a mobile operator to adopt IMS, including interconnection with other operators over SIP and SS7:

1. **NGN → IMS upgrade:** reuse some NGN components and replace the rest. Estimated at about 70% of the cost of a new IMS.
2. **Converged core:** one core with two domains.
   - HSS and SLF: one per operator, or a shared HSS with two domains.
   - SBC with firewall: one per operator, or one with two domains.
   - PCRF: one per operator, or shared.
   - MGCF / AGCF / IM-MGW and MSAN (H.248) on the fixed side.
   - A single EPC, with the mobile RAN upgraded to eNodeB.
3. **Two new IMS cores**, each with its own application servers, plus MVNO/VNO gateways and an eNodeB upgrade.

---

## Topics covered

IMS architecture (transport, control, and application layers), CSCF roles, HSS, SLF, PDF/PCRF, MRF, BGCF, MGCF/MGW, SGW, and IM-SSF. Protocols: SIP, SDP, RTP/RTCP, Diameter, RADIUS, H.323, H.248/Megaco, MGCP, COPS, SigComp, SIGTRAN, SCTP, XCAP, and TLS. LTE/EPC: MME, S-GW, P-GW, HSS, and PCRF. Voice-over-LTE options: CSFB, SVLTE, VoLTE (GSMA IR.92), and SRVCC.

---

**Author:** Mohammed Mahyoub · [Portfolio](https://mahyoub88.github.io/) · [LinkedIn](https://www.linkedin.com/in/mohammed-mahyoub/) · [ORCID](https://orcid.org/0009-0003-5640-352X)
