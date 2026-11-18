# Test data

Real output of the tools Wolf reads, scrubbed. Tests map these records, so a change to a parser is
checked against what the tools really write, not against hand-written JSON.

| File | Captured from |
|---|---|
| `suricata_eve.json` | Suricata 7 with ET Open in front of a Frappe bench: an sqlmap probe and a rule on the server's 403 answer |
| `suricata_eve_et_open.json` | Suricata 7.0 (`jasonish/suricata`) with ET Open on an nginx container's interface. A client sent log4j, Shellshock, Fortinet traversal, `.env`, masscan and a password in a POST body; the server itself made DNS, TLS and HTTP calls to IP lookup services, a `.onion` name, a tunnel and a file transfer service. One record per rule or record type |
| `wazuh_alerts.json` | a Wazuh manager: SSH, sudo, CIS assessment and Wolf's own export |
| `wazuh_alerts_lab.json` | a Wazuh 4.9.2 manager reading syslog relayed from `bench-01` and an nginx access log, with real-time integrity on a bench folder, and a real Wazuh agent (`bench-02`) under an IPv6 SSH brute force. Repeated alerts and the CIS assessment are cut to a few |

Scrubbing:

- container and public addresses become documentation ones: the server `192.0.2.10`, the web
  client `198.51.100.23`, the public services and the SSH attacker `203.0.113.x`, IPv6
  `2001:db8::/32`;
- the lab's host names become `erp.example.com`, `bench-01`, `bench-02`;
- Suricata's packet payloads and stats counters are dropped.

`test_real_fixtures.py` checks that every address in these files is a documentation, private or
multicast one.
