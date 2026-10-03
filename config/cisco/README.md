# Cisco voice configuration (excerpts)

Transcribed from the router console screenshots in `docs/project/`
(04–07). They show the parts of the running configuration that carry
the call routing: dial-peers, codec class, H.323 settings, interworking
and the branch CME telephony service. Interface and IP-routing sections
are not shown in the screenshots and are therefore not reproduced here.

| File | Router | Role |
|---|---|---|
| `vgw.cfg` | VGW | HQ voice gateway, H.323 toward CUCM (192.168.154.10) |
| `br-cme.cfg` | BR1 | Branch router running Cisco Unified CME |
| `pstn.cfg` | PSTN | PSTN-side router |
