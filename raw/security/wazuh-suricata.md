# Wazuh and Suricata

> Feed Suricata and Wazuh alerts into Dodock Wolf, through the agent or the Wazuh integration, and find every source's events for one IP, host, site or user.

Suricata (network IDS) and Wazuh (host IDS) are optional sources. When they run, Wolf reads their
alerts and puts them in the same incidents as its own signals. Wolf never depends on them: without
them, the agent's own [web and host detection](/security/detection) stays on.

<table>
<thead>
  <tr>
    <th>
      Source
    </th>
    
    <th>
      Event category
    </th>
    
    <th>
      Read by
    </th>
    
    <th>
      Preset
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Suricata
    </td>
    
    <td>
      <code>
        network_ids_alert
      </code>
    </td>
    
    <td>
      the Wolf Agent, from the EVE log
    </td>
    
    <td>
      <em>
        Network IDS alert (critical)
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      Wazuh
    </td>
    
    <td>
      <code>
        hids_alert
      </code>
    </td>
    
    <td>
      the Wolf Agent on the manager's host, from <code>
        alerts.json
      </code>
      
      , or the Wazuh integration
    </td>
    
    <td>
      <em>
        Host intrusion alert (critical)
      </em>
    </td>
  </tr>
</tbody>
</table>

## What each setup covers

With Wolf alone, a bench is covered. Suricata and Wazuh add what a log line cannot show:

<table>
<thead>
  <tr>
    <th>
      
    </th>
    
    <th>
      Wolf alone
    </th>
    
    <th>
      + Suricata
    </th>
    
    <th>
      + Wazuh
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Web attacks
    </td>
    
    <td>
      nginx access log: scanners, injections in the URL, CMS and edge appliance paths, secret files (and whether one was served), bursts on Frappe's account endpoints and 403 storms on its API
    </td>
    
    <td>
      signatures on the traffic itself: request bodies and headers (after TLS termination), every protocol, packet context
    </td>
    
    <td>
      the web server's access log through Wazuh's own web attack rules, when its agent reads it
    </td>
  </tr>
  
  <tr>
    <td>
      Outbound
    </td>
    
    <td>
      new destinations of the bench users and of their containers: sampled from <code>
        /proc
      </code>
      
       every minute; every new TCP connection with the optional <code>
        wolf-outbound-log
      </code>
      
       helper; every request through a Squid proxy
    </td>
    
    <td>
      command-and-control signatures, DNS, TLS fingerprints, UDP, the content of the flows
    </td>
    
    <td>
      —
    </td>
  </tr>
  
  <tr>
    <td>
      Exposure
    </td>
    
    <td>
      bench services listening beyond loopback, risky <code>
        site_config.json
      </code>
      
       settings
    </td>
    
    <td>
      the scans and exploits aimed at them
    </td>
    
    <td>
      —
    </td>
  </tr>
  
  <tr>
    <td>
      Host
    </td>
    
    <td>
      auth log or journal: SSH brute force then login, root logins, sudo failures, new accounts, admin groups; file integrity of the bench (app code, site configs, nginx and supervisor config)
    </td>
    
    <td>
      SSH brute force and scans seen on the wire
    </td>
    
    <td>
      a full HIDS: more log sources, file integrity across the OS, rootkits, configuration assessment, Windows and macOS endpoints
    </td>
  </tr>
  
  <tr>
    <td>
      Frappe application
    </td>
    
    <td>
      logins, roles, Server and Client Scripts, permissions, security settings, API keys, webhooks, exports, honeytokens: only Wolf sees inside a bench
    </td>
    
    <td>
      —
    </td>
    
    <td>
      —
    </td>
  </tr>
  
  <tr>
    <td>
      Posture and health
    </td>
    
    <td>
      security score, versions against advisories, TLS, SPF/DMARC; 5xx, crons, workers, backups, database
    </td>
    
    <td>
      —
    </td>
    
    <td>
      OS configuration assessment
    </td>
  </tr>
  
  <tr>
    <td>
      Response
    </td>
    
    <td>
      human-approved: block an IP (nftables or fail2ban), disable a user, log out sessions, revoke API keys; CrowdSec bans
    </td>
    
    <td>
      —
    </td>
    
    <td>
      Wazuh active response for approved blocks, instead of or with the Wolf Agent
    </td>
  </tr>
  
  <tr>
    <td>
      Correlation
    </td>
    
    <td>
      incidents, grouping by IP or user across sources, sequence rules, the timeline of related scopes, NIS2/GDPR deadlines, signed journal
    </td>
    
    <td>
      its alerts join Wolf's incidents and sequence rules
    </td>
    
    <td>
      its alerts join Wolf's incidents and sequence rules
    </td>
  </tr>
</tbody>
</table>

What Wolf alone does not see:

- request bodies and headers (an injection in a POST body, or in a header such as
`X-Frappe-Request-Id`), and protocols other than HTTP: Suricata does;
- the content of outbound flows and UDP; without the helper, connections shorter than a minute;
- file changes outside the bench and its web and process config, rootkits, and hosts other than
Linux: Wazuh does.

## Suricata

### Turn it on

The agent reads Suricata when it finds an EVE log: `suricata.eve_log`, else
`/var/log/suricata/eve.json` if it exists. Nothing else to set.

```json [config.json]
"suricata": {"enabled": true, "eve_log": null, "max_priority": 3}
```

<table>
<thead>
  <tr>
    <th>
      Key
    </th>
    
    <th>
      Meaning
    </th>
    
    <th>
      Default
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        enabled
      </code>
    </td>
    
    <td>
      read Suricata's EVE log
    </td>
    
    <td>
      <code>
        true
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        eve_log
      </code>
    </td>
    
    <td>
      path of the EVE log. <code>
        null
      </code>
      
       uses <code>
        /var/log/suricata/eve.json
      </code>
      
       when it exists
    </td>
    
    <td>
      <code>
        null
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        max_priority
      </code>
    </td>
    
    <td>
      skip alerts whose priority is above this
    </td>
    
    <td>
      <code>
        3
      </code>
    </td>
  </tr>
</tbody>
</table>

`"suricata": false` turns it off. See [Configuration](/agent/configuration).

### What it sends

- Only `alert` records are read.
- Each (signature, remote address) pair gives one `network_ids_alert` event per minute of log time,
with a count. Past 500 pairs in an interval, alerts are only counted.
- Severity follows the rule's priority: 1 is critical, 2 warning, 3 info.
- The payload keeps the rule (SID, signature, category, ATT&CK techniques from its
`mitre_technique_id` metadata), the flow (`flow_id`, `community_id`, ports) and the app-layer
fields Suricata puts on alerts: HTTP host, URL, user agent, TLS SNI, DNS query.
- The remote address is the rule's `source` when set. Otherwise it is the end of the flow that is
not one of this host's addresses. A rule on the server's answer still names the client; an
outbound connection names the remote server.
- The HTTP host or SNI maps the alert to a site.

**Preset**: *Network IDS alert (critical)* fires on any priority 1 alert, per host.

Tried against Suricata 7 with ET Open: sqlmap, Zmap and path traversal probes against nginx came
out as events with the client address, the site and the rule's ATT&CK technique.

## Wazuh

Two ways in. Use the agent route when a Wolf Agent runs on the Wazuh manager's host; otherwise
use the integration route. Both map alerts the same way.

### What is kept

- Alerts at or above the minimum level become `hids_alert` events: `wazuh.min_level` on the
agent route, the `<level>` of the integration block on the integration route (7 in both
examples below). Level 12 and above is critical, 7 to 11 warning, below 7 info.
- One event per rule and subject (source IP, else host), with a count.
- The `sca` group (configuration assessment) is left out by default.
- The `dodock_wolf` group is always left out. Those are Wazuh's alerts on Wolf's own
[SIEM export](/security/siem-export), so nothing loops back.
- The event's host is the Wazuh agent's name. For logs the manager received by syslog (agent
`000`), it is the host name in the log line, where it happened.
- The payload keeps the rule (id, level, description, groups, `rule.mitre.id` as ATT&CK), the
Wazuh agent, the source IP and user, and the first log line, scrubbed like every event.

**Preset**: *Host intrusion alert (critical)* fires on any level 12+ alert, per host.

### Agent route

On the Wazuh manager's host, the agent tails `wazuh.alerts_log`, else
`/var/ossec/logs/alerts/alerts.json` if it exists.

```json [config.json]
"wazuh": {"enabled": true, "alerts_log": null, "min_level": 7, "exclude_groups": ["sca"]}
```

<table>
<thead>
  <tr>
    <th>
      Key
    </th>
    
    <th>
      Meaning
    </th>
    
    <th>
      Default
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        enabled
      </code>
    </td>
    
    <td>
      read Wazuh's alerts log
    </td>
    
    <td>
      <code>
        true
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        alerts_log
      </code>
    </td>
    
    <td>
      path of <code>
        alerts.json
      </code>
      
      . <code>
        null
      </code>
      
       uses <code>
        /var/ossec/logs/alerts/alerts.json
      </code>
      
       when it exists
    </td>
    
    <td>
      <code>
        null
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        min_level
      </code>
    </td>
    
    <td>
      lowest rule level sent
    </td>
    
    <td>
      <code>
        7
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        exclude_groups
      </code>
    </td>
    
    <td>
      Wazuh rule groups left out (<code>
        dodock_wolf
      </code>
      
       is always left out)
    </td>
    
    <td>
      <code>
        ["sca"]
      </code>
    </td>
  </tr>
</tbody>
</table>

The agent's user must be able to read the alerts log: add `wolf-agent` to the `wazuh` group.

```bash
sudo usermod -aG wazuh wolf-agent
sudo systemctl restart wolf-agent
```

Events are one per rule and subject per minute of log time.

### Wazuh integration route

Without a Wolf Agent on the manager's host, Wazuh's integration daemon posts its alerts to Wolf
itself.

<steps level="4">

#### Register a source of kind `integration`

```bash
curl -X POST -H 'Content-Type: application/json' \
  -d '{"registration_token": "...", "hostname": "wazuh-manager", "kind": "integration"}' \
  https://wolf.example.com/api/method/dodock_wolf.api.agent.register
```

The answer gives `agent_id` and `agent_secret`. The secret is shown once (see
[Agent secrets](/security/access#agent-secrets)). An `integration` source is never reported
silent, since it only speaks when Wazuh has an alert.

#### Install the integration

Copy `agent/wazuh/custom-dodock-wolf` and `agent/wazuh/custom-dodock-wolf.py` from the repository
to `/var/ossec/integrations/`, owned by `root:wazuh`, mode 750. The launcher runs the script with
Wazuh's own Python.

#### Configure the manager

Add this to `/var/ossec/etc/ossec.conf`, then restart the manager:

```xml [ossec.conf]
<integration>
  <name>custom-dodock-wolf</name>
  <hook_url>https://wolf.example.com</hook_url>
  <api_key>AGENT_ID:AGENT_SECRET</api_key>
  <level>7</level>
  <alert_format>json</alert_format>
</integration>
```

</steps>

Wazuh runs the script for each alert at or above `<level>`. It posts the alert to
`dodock_wolf.api.wazuh.alert`.

- Wolf maps it like the agent route (`sca` and `dodock_wolf` left out; the answer gives the
reason when an alert is skipped).
- The same rule and subject within 10 minutes bump one event's count.
- The endpoint accepts up to 600 calls per minute per integration, since Wazuh sends one call per
alert.
- Errors go to `/var/ossec/logs/integrations.log`.

Tried against a Wazuh 4.9.2 manager, both routes: sshd and sudo lines it received by syslog came
out under the host that logged them, with Wazuh's ATT&CK techniques. Three alerts sent by its
integration daemon became one event with a count of 3.

## Entities shared across sources

Wolf, Suricata and Wazuh name the same things differently: an address in `ip`, `src_ip` or
`dest_ip`, a host by its Wolf hostname, its Wazuh agent name or one of its addresses, a site by its
name or one of its domains. At ingest, Wolf resolves them to one set of entities.

### Extraction

Each `security` event's entities go in `payload.entities` and in **Wolf Event Entity**:

<table>
<thead>
  <tr>
    <th>
      Kind
    </th>
    
    <th>
      Taken from
    </th>
    
    <th>
      Normalised
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        ip
      </code>
    </td>
    
    <td>
      <code>
        ip
      </code>
      
      , <code>
        src_ip
      </code>
      
      , <code>
        dest_ip
      </code>
    </td>
    
    <td>
      canonical form (<code>
        ::ffff:1.2.3.4
      </code>
      
       is <code>
        1.2.3.4
      </code>
      
      , IPv6 compressed). An address that belongs to a known host becomes that host: the IP entity is the other party. A Suricata <code>
        dest_ip
      </code>
      
       on the server is the host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        host
      </code>
    </td>
    
    <td>
      the event's host, the Wazuh agent's name
    </td>
    
    <td>
      lowercased, resolved through aliases. A Wazuh agent name or an FQDN resolves to its host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        site
      </code>
    </td>
    
    <td>
      the event's site, the HTTP host or TLS SNI
    </td>
    
    <td>
      lowercased, resolved through aliases to the site
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        user
      </code>
    </td>
    
    <td>
      <code>
        user
      </code>
      
      , <code>
        suser
      </code>
      
      , <code>
        username
      </code>
      
      , <code>
        srcuser
      </code>
      
      , <code>
        dstuser
      </code>
      
      , <code>
        users
      </code>
    </td>
    
    <td>
      lowercased. Placeholders (<code>
        -
      </code>
      
      , <code>
        unknown
      </code>
      
      , <code>
        none
      </code>
      
      , <code>
        guest
      </code>
      
      …) are dropped
    </td>
  </tr>
</tbody>
</table>

At most 10 values per kind and event.

### Aliases

**Wolf Entity Alias** maps a name to a host or site:

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Meaning
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Kind
    </td>
    
    <td>
      <code>
        host
      </code>
      
       or <code>
        site
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Alias
    </td>
    
    <td>
      the other name: an address, a Wazuh agent name, an FQDN, a domain
    </td>
  </tr>
  
  <tr>
    <td>
      Is
    </td>
    
    <td>
      the canonical host or site
    </td>
  </tr>
  
  <tr>
    <td>
      Source
    </td>
    
    <td>
      <code>
        Auto
      </code>
      
       (learnt) or <code>
        Manual
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Learnt from
    </td>
    
    <td>
      what taught Wolf the alias
    </td>
  </tr>
</tbody>
</table>

Wolf learns `Auto` aliases from:

- agent registrations: the agent's address, and its benches' site domains;
- pushes from a new address;
- Wazuh alerts about other Wazuh agents: that agent's address.

When two tools name a host differently, add a `Manual` alias in Desk. Wolf never overwrites a
manual alias. Wolf Managers can edit aliases; Wolf Users can read them.

### Search by entity

The event list API takes an `entity` filter, `kind:value`:

```text
ip:203.0.113.5
host:erp-01
site:erp.example.com
user:jane@example.com
```

It finds Wolf's, Suricata's and Wazuh's events together. Call
`dodock_wolf.api.explore.list_events` with `entity=…`, or `dodock_wolf.api.entities.find`.

Entity rows are purged daily with the events they belong to.

## When detectors overlap

Wolf's own detectors and these sources overlap: the agent's nginx web probes and Suricata, its
auth log signals and Wazuh. **Wolf Settings → Overlapping detectors** has one mode for each:

<table>
<thead>
  <tr>
    <th>
      Setting
    </th>
    
    <th>
      Wolf's own detector
    </th>
    
    <th>
      Other source
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        Web Attacks
      </strong>
    </td>
    
    <td>
      <code>
        web_attack_probe
      </code>
    </td>
    
    <td>
      Suricata, <code>
        network_ids_alert
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Host Logins and Accounts
      </strong>
    </td>
    
    <td>
      <code>
        ssh_failed_login
      </code>
      
      , <code>
        ssh_root_login
      </code>
      
      , <code>
        ssh_login_after_failures
      </code>
      
      , <code>
        sudo_failure
      </code>
      
      , <code>
        account_created
      </code>
      
      , <code>
        admin_group_change
      </code>
    </td>
    
    <td>
      Wazuh, <code>
        hids_alert
      </code>
    </td>
  </tr>
</tbody>
</table>

<table>
<thead>
  <tr>
    <th>
      Mode
    </th>
    
    <th>
      What happens
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        own
      </code>
    </td>
    
    <td>
      The default, as when Wolf works alone: both raise their own events.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        both
      </code>
    </td>
    
    <td>
      A Wolf event and the other source's alert are one finding when they name the same remote IP, share an ATT&CK technique (or one of them names none), and fall within <strong>
        Detector Match Minutes
      </strong>
      
       (10).
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        external
      </code>
    </td>
    
    <td>
      Wolf's own events of that detector are dropped at ingest while the other source covers the host.
    </td>
  </tr>
</tbody>
</table>

### Both: one finding, two sources

Both events are kept, and each still counts in its own alert rules. The later one is stored with
**Same Finding As** set to the first:

- the timeline shows it with "same finding as …", linked to the first source's row;
- CrowdSec and the [SIEM export](/security/siem-export) skip it when the first was sent. A critical
alert linked to a warning one still goes to a collector that takes critical only.

`sudo_failure`, `account_created` and `admin_group_change` carry no IP, so they are never linked.

### External: Wolf gives way, then comes back

Wolf's own events of that detector are dropped while the other source has sent, in the last hour,
an alert about the same host (under any of its names, see [Aliases](#aliases)) that watches the
same thing:

- Wazuh: an authentication, SSH, sudo or account rule, or an ATT&CK technique of the auth signals
(T1110, T1078, T1548, T1136, T1098). A file-integrity alert does not stand in for SSH detection.
- Suricata: an alert with HTTP context (`app_proto` `http`, an HTTP host or URL) or a web
technique (T1595, T1190, T1189, T1552). A Suricata sensor on another machine counts for a host
when its alert's `dest_ip` is one of that host's addresses.

When the other source goes quiet for an hour, Wolf's own detection comes back by itself. Each
**Wolf Agent** counts the events it sent that gave way, in **Own Events Given Way**, with the last
time.

<warning>

In `external` mode, Wolf's own detection depends on Suricata or Wazuh covering the host. Check
**Own Events Given Way** on the Wolf Agent to see what it handed over.

</warning>

Blocking is not part of these modes: an approved block can run through the Wolf Agent, [Wazuh active response](/agent/response-actions#wazuh-active-response), or both.

Whatever the mode, [grouping by IP or user](/alerts/incidents#grouping-by-ip-or-user) puts the
events of both sources in one incident, and [sequence rules](/alerts/rules#sequence-rules) chain
them: a scan, then a login from the same IP.

## Planned

Without Wazuh or Suricata, the agent still watches [file integrity on the bench](/security/detection#file-integrity)
and the bench users' [outbound connections](/security/detection#outbound-connections).
