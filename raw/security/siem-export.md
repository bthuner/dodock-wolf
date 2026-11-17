# SIEM export

> Send Wolf's security events and signed journal to a syslog collector in OCSF or CEF, with the settings that work for rsyslog, Wazuh and Graylog.

**Wolf Settings → SIEM export (syslog)** (off by default) sends Wolf's security events and its
signed journal to a syslog collector. Every minute, the events that match the filters, and every
signed journal entry, go out as RFC 5424 syslog (facility `local0`) carrying OCSF JSON or CEF.

## Settings

<table>
<thead>
  <tr>
    <th>
      Setting
    </th>
    
    <th>
      Values
    </th>
    
    <th>
      Default
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        Export to a SIEM
      </strong>
    </td>
    
    <td>
      on / off
    </td>
    
    <td>
      off
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Collector host
      </strong>
    </td>
    
    <td>
      a host name or address. With TLS, it must be in the collector's certificate
    </td>
    
    <td>
      
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Port
      </strong>
    </td>
    
    <td>
      
    </td>
    
    <td>
      <code>
        514
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Transport
      </strong>
    </td>
    
    <td>
      <code>
        tcp
      </code>
      
      , <code>
        tls
      </code>
      
       (RFC 5425), <code>
        udp
      </code>
      
       (RFC 5426)
    </td>
    
    <td>
      <code>
        tcp
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Verify the collector's certificate
      </strong>
    </td>
    
    <td>
      on / off (TLS)
    </td>
    
    <td>
      on
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Collector CA file
      </strong>
    </td>
    
    <td>
      a PEM file of a private CA, absolute or relative to the site (<code>
        private/files/collector-ca.pem
      </code>
      
      ). Empty: the system CAs
    </td>
    
    <td>
      
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Framing
      </strong>
    </td>
    
    <td>
      <code>
        octet-counting
      </code>
      
       or <code>
        newline
      </code>
      
       (TCP and TLS, RFC 6587)
    </td>
    
    <td>
      <code>
        octet-counting
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Message header
      </strong>
    </td>
    
    <td>
      <code>
        rfc5424
      </code>
      
       or <code>
        none
      </code>
    </td>
    
    <td>
      <code>
        rfc5424
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Format
      </strong>
    </td>
    
    <td>
      <code>
        ocsf
      </code>
      
       or <code>
        cef
      </code>
    </td>
    
    <td>
      <code>
        ocsf
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Minimum severity
      </strong>
    </td>
    
    <td>
      <code>
        info
      </code>
      
      , <code>
        warning
      </code>
      
      , <code>
        critical
      </code>
    </td>
    
    <td>
      <code>
        warning
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Event types
      </strong>
    </td>
    
    <td>
      comma-separated: <code>
        security
      </code>
      
      , <code>
        error
      </code>
      
      , <code>
        cron_failure
      </code>
      
      , <code>
        worker_failure
      </code>
      
      , <code>
        host_metric_alert
      </code>
      
      , <code>
        deployment
      </code>
    </td>
    
    <td>
      <code>
        security
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Send the journal
      </strong>
    </td>
    
    <td>
      also send every signed journal entry (seq, digest, mac)
    </td>
    
    <td>
      on
    </td>
  </tr>
</tbody>
</table>

To check a collector, a Wolf Manager can POST to `dodock_wolf.api.siem.send_test`. It sends one
`wolf_test` message with the current settings, even while **Export to a SIEM** is off:

```bash
curl -X POST -H "Authorization: token <api_key>:<api_secret>" \
  https://wolf.example.com/api/method/dodock_wolf.api.siem.send_test
```

### Format

- **OCSF**: JSON, Detection Finding (class 2004). ATT&CK techniques in `finding_info.attacks`;
Wolf's site, bench and payload under `unmapped`. The mapping is Wolf's reading of the schema,
not a certified profile.
- **CEF**: ATT&CK in `cs4`, [IP reputation](/security/journal#ip-reputation-lists) lists in `cs5`.

### Message header

- `rfc5424`: a syslog header before each message: priority, timestamp, the site as host name,
`dodock-wolf` as application, the event category as MSGID.
- `none`: the bare JSON or CEF, for collectors that decode the message themselves, such as
Wazuh's JSON decoder and Graylog's CEF input.

### Transport and framing

- Prefer TCP or TLS. UDP sends one datagram per message, cut at 8 KB. Wolf cannot tell whether
the collector got anything, so the cursor moves anyway.
- `octet-counting` precedes each message with its length. rsyslog, syslog-ng and Graylog's Syslog
input read it.
- `newline` sends one message per line; a line break inside a message becomes a space. Wazuh and
Graylog's CEF input need it.

### TLS

- The collector's certificate is checked against the system CAs, or **Collector CA file**.
- Python 3.13 and later verify strictly: the CA needs `basicConstraints=CA:TRUE` and
`keyUsage=keyCertSign`, and the server certificate needs an Authority Key Identifier.

<caution>

Turning certificate verification off works, but anyone on the path can then read the export.

</caution>

## Delivery

- A cursor moves only after a batch is sent. A collector that is down delays the export; nothing
is skipped.
- A failure mid-batch can send a message twice: delivery is at least once.
- Events younger than 2 minutes wait for the next run, so a transaction that commits a little
after it inserted is not skipped.
- Payloads go out as they are stored (already [scrubbed](/agent/scrubbing) by the agent), cut at
4 KB.
- Journal entries give the SIEM an external copy of the chain: an anchor Wolf cannot rewrite. See
[Tamper-evident journal](/security/journal#tamper-evident-journal).

## Collectors

Each recipe was tried against the real collector (November 2026).

<table>
<thead>
  <tr>
    <th>
      Collector
    </th>
    
    <th>
      Format
    </th>
    
    <th>
      Message header
    </th>
    
    <th>
      Transport
    </th>
    
    <th>
      Framing
    </th>
    
    <th>
      What you get
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      rsyslog 8.2404
    </td>
    
    <td>
      OCSF or CEF
    </td>
    
    <td>
      <code>
        rfc5424
      </code>
    </td>
    
    <td>
      UDP, TCP or TLS
    </td>
    
    <td>
      <code>
        octet-counting
      </code>
      
       (TCP/TLS)
    </td>
    
    <td>
      messages written as sent; MSGID is the event category
    </td>
  </tr>
  
  <tr>
    <td>
      Wazuh 4.9.2 manager
    </td>
    
    <td>
      OCSF
    </td>
    
    <td>
      <code>
        none
      </code>
    </td>
    
    <td>
      TCP
    </td>
    
    <td>
      <code>
        newline
      </code>
    </td>
    
    <td>
      one Wazuh alert per finding, level by severity
    </td>
  </tr>
  
  <tr>
    <td>
      Graylog 6.1, CEF input
    </td>
    
    <td>
      CEF
    </td>
    
    <td>
      <code>
        none
      </code>
    </td>
    
    <td>
      TCP
    </td>
    
    <td>
      <code>
        newline
      </code>
    </td>
    
    <td>
      every field extracted (source address, ATT&CK, site, severity)
    </td>
  </tr>
  
  <tr>
    <td>
      Graylog 6.1, Syslog input
    </td>
    
    <td>
      OCSF or CEF
    </td>
    
    <td>
      <code>
        rfc5424
      </code>
    </td>
    
    <td>
      UDP, TCP or TLS
    </td>
    
    <td>
      <code>
        octet-counting
      </code>
    </td>
    
    <td>
      messages stored, JSON not split into fields
    </td>
  </tr>
</tbody>
</table>

<tabs>
<tabs-item label="rsyslog">

```text [rsyslog.conf]
module(load="imptcp")                     # TCP, octet-counted or newline
input(type="imptcp" port="514")
module(load="imtcp" StreamDriver.Name="gtls" StreamDriver.Mode="1" StreamDriver.AuthMode="anon")
input(type="imtcp" port="6514")           # TLS (global DefaultNetstreamDriver* point at the cert)
module(load="imudp")
input(type="imudp" port="514")
```

The default Wolf settings work: `rfc5424`, `octet-counting`, OCSF or CEF.

</tabs-item>

<tabs-item label="Wazuh">

1. On the manager, add a syslog input to `/var/ossec/etc/ossec.conf`:```xml [ossec.conf]
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>tcp</protocol>
  <allowed-ips>WOLF_SITE_ADDRESS/32</allowed-ips>
</remote>
```
2. Copy the [rules file](https://github.com/bthuner/dodock-wolf/blob/main/docs/siem/wazuh_dodock_wolf_rules.xml)
to `/var/ossec/etc/rules/` and restart the manager. It needs Wazuh 4.6 or later.
3. Set Wolf to: format `ocsf`, message header `none`, transport `tcp`, framing `newline`.

<table>
<thead>
  <tr>
    <th>
      Wolf finding
    </th>
    
    <th>
      Wazuh rule
    </th>
    
    <th>
      Level
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      info
    </td>
    
    <td>
      100901
    </td>
    
    <td>
      3
    </td>
  </tr>
  
  <tr>
    <td>
      warning
    </td>
    
    <td>
      100902
    </td>
    
    <td>
      7
    </td>
  </tr>
  
  <tr>
    <td>
      critical
    </td>
    
    <td>
      100903
    </td>
    
    <td>
      12
    </td>
  </tr>
  
  <tr>
    <td>
      journal entry
    </td>
    
    <td>
      100910
    </td>
    
    <td>
      3
    </td>
  </tr>
</tbody>
</table>

The OCSF fields become Wazuh fields: `src_endpoint.ip`, `finding_info.title`,
`finding_info.attacks`, `unmapped.site`, and so on.

Does not work with Wazuh:

- the RFC 5424 header: Wazuh does not parse it, so only a generic rule fires;
- CEF: Wazuh has no decoder for it;
- octet-counted frames: they are dropped;
- TLS: Wazuh's syslog input has none. Put a local relay (rsyslog, stunnel) in front when the
network between Wolf and Wazuh is not trusted.

</tabs-item>

<tabs-item label="Graylog">

**To get fields**: create a **CEF TCP** input, then set Wolf to: format `cef`, message header
`none`, transport `tcp`, framing `newline`.

- The input extracts `sourceAddress`, `deviceHostName` (the site), `mitre_attack`, `site`,
`severity`, `event_class_id` (the category) and the journal's `digest` / `mac`.
- `source` is the address of the Wolf site.
- The RFC 5424 header confuses this input: `source` becomes `-`.

**To store only**: the Syslog TCP, UDP or TLS inputs accept the default settings (`rfc5424`,
`octet-counting`). Graylog keeps MSGID and the structured-data dash at the start of `message`
and does not split the JSON. Add a JSON extractor or a pipeline rule if you take this road.

</tabs-item>

<tabs-item label="UniSOC and others">

UniSOC has not been tried, for lack of an instance. Any collector that takes syslog with
RFC 5424, CEF or JSON lines should work with one of the combinations above.

</tabs-item>
</tabs>

<note>

When Wolf exports to a Wazuh manager that the Wolf Agent also reads, Wazuh's alerts on Wolf's own
export (group `dodock_wolf`) are always left out, so nothing loops back. See
[Wazuh and Suricata](/security/wazuh-suricata).

</note>
