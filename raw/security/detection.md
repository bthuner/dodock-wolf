# Web and host detection

> What the Wolf Agent detects in nginx access logs and the auth log, which bench services and site settings it reports as exposed, and which presets alert on them.

The Wolf Agent runs its own web and host detection from logs it already tails. It needs no
Wazuh, Suricata or extra package. All findings are `security` events, scrubbed on the host
before they are sent (see [Scrubbing](/agent/scrubbing)).

## Web attacks from nginx

The agent reads the same nginx access logs it uses for `http_5xx` and `http_502`. Nothing to turn
on: when the agent tails a bench's nginx log, web attack detection runs. Log paths are set per
bench in `nginx_access_log` (see [Configuration](/agent/configuration)).

### What counts as a probe

A request is a probe when it:

- looks for secrets: `.env`, `.git/`, `site_config.json`, keys, dumps;
- looks for CMS and admin panels (`wp-login.php`, `phpmyadmin`…);
- tries path traversal, SQL, command or template injection, or XSS;
- comes from a scanner User-Agent (sqlmap, nuclei…).

URL-encoded targets are decoded twice before matching.

### Events

<table>
<thead>
  <tr>
    <th>
      Category
    </th>
    
    <th>
      Severity
    </th>
    
    <th>
      What it means
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        web_attack_probe
      </code>
    </td>
    
    <td>
      warning, critical once a client sends 50+ probes
    </td>
    
    <td>
      one event per (site, client) and minute of log time, with the rules hit, the statuses, up to 10 targets and the ATT&CK IDs
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        web_sensitive_file_exposed
      </code>
    </td>
    
    <td>
      critical
    </td>
    
    <td>
      a secret-bearing file was answered with a 2xx. The file was probably leaked
    </td>
  </tr>
</tbody>
</table>

### What is not a probe

- Attachments (`/files`, `/private/files`) and authorized backup downloads (`/backups`).
- A 2xx under a route that answers any sub-path with a page (`/app/`, `/wolf/`, `/api/`…) is not
counted as a served file.

### The client address

The client is `$remote_addr`. When `$remote_addr` is a loopback or private proxy, the agent takes
the right-most public address of the `X-Forwarded-For` list logged after it: the one your proxy
appended. The left-most entries are written by the client and are not trusted.

### Presets

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <em>
        Web attack scan
      </em>
    </td>
    
    <td>
      100+ <code>
        web_attack_probe
      </code>
      
       requests in 10 min, per site (warning)
    </td>
  </tr>
  
  <tr>
    <td>
      <em>
        Sensitive file served
      </em>
    </td>
    
    <td>
      any <code>
        web_sensitive_file_exposed
      </code>
      
       (critical). Rotate the secrets
    </td>
  </tr>
</tbody>
</table>

## Host intrusion signals

The agent reads `/var/log/auth.log`, `/var/log/secure`, or the journal:

```bash
journalctl -o short-iso -t sshd -t sshd-session -t sudo -t useradd -t usermod -t gpasswd
```

`sshd-session` covers OpenSSH 9.8 and later. The `short-iso` format keeps each line's real
timestamp.

The `auth_log` setting picks the source: `null` auto-detects, a path forces a file, `"journal"`
forces journalctl, `false` turns it off. The installer adds the `wolf-agent` user to the `adm` and
`systemd-journal` groups when they exist, so it can read these logs without root.

<table>
<thead>
  <tr>
    <th>
      Category
    </th>
    
    <th>
      What it means
    </th>
    
    <th>
      Severity
    </th>
    
    <th>
      Preset
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        ssh_failed_login
      </code>
    </td>
    
    <td>
      failed SSH logins, aggregated per source IP and minute of log time
    </td>
    
    <td>
      warning, critical at 20+ in one event
    </td>
    
    <td>
      <em>
        SSH brute force
      </em>
      
      : 20+ in 10 min, per host (critical)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ssh_root_login
      </code>
    </td>
    
    <td>
      a root login
    </td>
    
    <td>
      warning
    </td>
    
    <td>
      none
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ssh_login_after_failures
      </code>
    </td>
    
    <td>
      a successful login from an address that failed 5+ times in the hour before. Failure counts survive push intervals
    </td>
    
    <td>
      critical
    </td>
    
    <td>
      <em>
        SSH login after brute force
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sudo_failure
      </code>
    </td>
    
    <td>
      wrong sudo passwords, users outside sudoers
    </td>
    
    <td>
      warning
    </td>
    
    <td>
      <em>
        Repeated sudo failures
      </em>
      
      : 3+ in 10 min, per host
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        account_created
      </code>
    </td>
    
    <td>
      <code>
        useradd
      </code>
      
       creates a local account
    </td>
    
    <td>
      warning
    </td>
    
    <td>
      <em>
        New system account
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        admin_group_change
      </code>
    </td>
    
    <td>
      a user is added to <code>
        sudo
      </code>
      
      , <code>
        wheel
      </code>
      
      , <code>
        admin
      </code>
      
      , <code>
        root
      </code>
      
      , <code>
        adm
      </code>
      
      , <code>
        docker
      </code>
      
       or <code>
        lxd
      </code>
    </td>
    
    <td>
      critical
    </td>
    
    <td>
      <em>
        User added to admin group
      </em>
    </td>
  </tr>
</tbody>
</table>

<tip>

*New system account* fires on planned provisioning too. Open a **Wolf Silence** for the host
while you provision it.

</tip>

## Exposure and site-config risks

Every `exposure.interval` (default 600 s), the agent checks what a host and its sites expose.

### Exposed bench services

`exposed_services` per host counts bench ports listening on all interfaces or on a public address
in `/proc/net/tcp{,6}`:

<table>
<thead>
  <tr>
    <th>
      Service
    </th>
    
    <th>
      Port
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      MariaDB
    </td>
    
    <td>
      3306
    </td>
  </tr>
  
  <tr>
    <td>
      Postgres
    </td>
    
    <td>
      5432
    </td>
  </tr>
  
  <tr>
    <td>
      Redis
    </td>
    
    <td>
      6379, 11000, 12000, 13000, or the bench's own <code>
        redis_*
      </code>
      
       ports
    </td>
  </tr>
  
  <tr>
    <td>
      socket.io
    </td>
    
    <td>
      9000
    </td>
  </tr>
  
  <tr>
    <td>
      gunicorn
    </td>
    
    <td>
      8000 or <code>
        webserver_port
      </code>
    </td>
  </tr>
</tbody>
</table>

Add ports with `exposure.ports`, a map of port to service name. A LAN address is not counted.

<note>

A listening socket is not proof of reachability: a firewall may still block what is counted.

</note>

### Site config risks

`site_config_risks` per site counts these in `site_config.json`:

- `developer_mode`;
- `allow_tests`;
- a plain-HTTP `host_name`;
- `allow_cors: "*"`.

### Events and presets

The agent sends `service_exposed` and `insecure_site_config` events only when the set it finds
changes. Both are tagged T1190.

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <em>
        Bench service exposed
      </em>
    </td>
    
    <td>
      <code>
        exposed_services
      </code>
      
       above 0, per host (critical). Redis has no password by default
    </td>
  </tr>
  
  <tr>
    <td>
      <em>
        Development settings in production
      </em>
    </td>
    
    <td>
      <code>
        site_config_risks
      </code>
      
       above 0, per site (warning)
    </td>
  </tr>
</tbody>
</table>

Both metrics also feed the [security score](/security/compliance#security-score).

## File integrity

Every `integrity.interval` (default 900 s), the agent compares what a bench is made of with its
baseline:

<table>
<thead>
  <tr>
    <th>
      Watched
    </th>
    
    <th>
      What a change means
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      each app under <code>
        apps/<app>/
      </code>
      
       (not <code>
        .git
      </code>
      
      , <code>
        node_modules
      </code>
      
      , <code>
        public/dist
      </code>
      
       and other <code>
        dist
      </code>
      
      /<code>
        build
      </code>
      
       output, <code>
        *.egg-info
      </code>
      
      , caches, compiled <code>
        .pyc
      </code>
      
       and <code>
        .mo
      </code>
      
       files)
    </td>
    
    <td>
      with the app's git commit unchanged: code changed outside a deployment (a web shell, a patched file), <strong>
        critical
      </strong>
      
      . With a new commit: a deployment, <strong>
        info
      </strong>
      
      , with both commits, or <strong>
        warning
      </strong>
      
       when it added Python under a <code>
        www/
      </code>
      
       folder. Without a git checkout (an archive install, an image without <code>
        .git
      </code>
      
      ), Wolf cannot tell: <strong>
        warning
      </strong>
      
      , saying so
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sites/common_site_config.json
      </code>
      
      , each <code>
        sites/<site>/site_config.json
      </code>
    </td>
    
    <td>
      <strong>
        warning
      </strong>
      
      . Only the names of the keys added, changed or removed are sent, never their values
    </td>
  </tr>
  
  <tr>
    <td>
      the bench's <code>
        config/
      </code>
      
       (the nginx and supervisor files it generates, not <code>
        pids/
      </code>
      
      ), <code>
        /etc/nginx
      </code>
      
       and <code>
        /etc/supervisor
      </code>
    </td>
    
    <td>
      <strong>
        warning
      </strong>
      
      : someone may have redirected traffic or started a process
    </td>
  </tr>
</tbody>
</table>

- Each scan hashes only what changed size or modification time; every `integrity.full_scan_interval`
(24 h) it hashes everything again, so a file whose size and time were put back is still caught.
- While git holds a lock in an app (a pull or a checkout in progress), the app is judged at the
next scan, so a deployment is not read as tampering halfway through.
- Files over 32 MB are compared by size and time only, and a pass stops after 200,000 files; what
is left keeps its baseline until the next pass.
- The first scan of a path is its baseline and raises nothing. The baseline is kept in the spool
directory (`integrity-state.json`, mode 0600): a restart does not hide what changed meanwhile.
`wolf-agent check` never moves it. Site config values are kept as HMACs under a key of this
install (`integrity.key`, 0600).
- A bench or site discovery misses for a while keeps its baseline for 7 days. An app removed from
`apps/`, a site or a config path that is gone is reported once, as removed (warning).
- A file or folder the agent cannot read keeps its baseline instead of reading as deleted:
`integrity_unreadable` counts them.
- A site config rewritten with the same keys and values raises nothing.
- Events: `bench_code_changed` (per app) and `bench_config_changed` (per file or server path), with
up to 20 paths of each kind (added, modified, deleted). Tagged T1505.003 and T1565.001; a
deployment has no technique. `integrity_files` counts what is watched, per bench and for the
host's own paths.
- `integrity.server_paths` replaces `/etc/nginx` and `/etc/supervisor`, for example on a host
whose web server lives elsewhere. The agent's user must be able to read what it watches;
unreadable files are skipped.

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <em>
        Bench code changed outside a deployment
      </em>
    </td>
    
    <td>
      a <code>
        bench_code_changed
      </code>
      
       event at critical, per bench (critical)
    </td>
  </tr>
  
  <tr>
    <td>
      <em>
        Bench or server config changed
      </em>
    </td>
    
    <td>
      a <code>
        bench_config_changed
      </code>
      
       event, per host (warning)
    </td>
  </tr>
</tbody>
</table>

## Outbound connections

Without Suricata, the agent still notices a bench talking to somewhere new: a light hint of
command-and-control or exfiltration, not packet inspection. Every `outbound.interval` (60 s) it
reads `/proc/net/tcp` and `/proc/net/tcp6` and keeps the established connections that:

- belong to a bench's user, the owner of the bench folder. Knowing which process holds a socket
would need root, so benches sharing one user share one record, and anything else that user runs
(an SSH session, a `git push`) counts as the bench's. A bench owned by root is skipped;
- leave from a local port nothing listens on: the bench is the client, not answering a visitor;
- go to a public address. Private, loopback and link-local peers (MariaDB, Redis, a LAN API) are
left out unless `outbound.include_private`.

A destination is the remote network (/24 for IPv4, /48 for IPv6) and port, so a CDN's next
address is not new. For `outbound.learn_days` (7) after the agent first sees a bench's user, every
destination is learned silently. After that:

- a new destination on an unusual port is reported once as `bench_new_outbound` (**warning**), at
most 20 per scan; the rest come out at the next scans;
- one on a usual port (web, mail with 2525, IMAP and POP, DNS, NTP, SSH and git, LDAP; add yours
with `outbound.usual_ports`) is only counted in `bench_new_outbound_usual`, since clouds rotate
their addresses all day. `outbound.report_usual_ports` reports those too, at **info**.

A destination unseen for 30 days is forgotten. The record is in the spool directory
(`outbound-state.json`, 0600). `bench_outbound_destinations` counts the destinations seen at each
sample.

The event names the destination in `remote_ip` and `remote_port`, not `ip`: a partner the bench
calls is not the remote party of an attack. It is searchable by entity and checked against the
[IP reputation lists](/security/journal#ip-reputation-lists), which raise a known-bad
destination, but it never groups incidents by IP, feeds a sequence rule, goes to CrowdSec as an
attacker or gets a block proposal.

**Benches in containers** (Docker, Press, Podman) have their own network. The agent finds them
without root: each container's cgroup names it (`/proc/<pid>/cgroup`), the folder it mounts from
the host (`/proc/<pid>/mountinfo`, for example the bench's `sites/`, on the same filesystem) says
which bench it is, and the container's own TCP table (`/proc/<pid>/net/tcp`) gives its
connections. Several containers of one bench are one record, and a container on the host's
network is not counted twice. The event says `seen_by: container`.

**Behind an outbound proxy**, the connections go to the proxy, not to the real destinations: the
agent reads the proxy's access log instead. `/var/log/squid/access.log` is read when it exists;
`outbound.proxy_logs` sets others (a path, or `[{"path": "...", "format": "squid"}]`); for a
proxy running in a container, give its log's path on the host. Only Squid's native log format is
read. Each request names its destination host and port (`remote_host`), every one of them, not a
sample, and the client address says which bench made it: a container's address, or the host's own
(all its benches). Other clients of a shared proxy, such as machines of the LAN, are left out.
The event says `seen_by: proxy`.

<warning>

Squid's log folder is readable by the `proxy` group only on Debian and Ubuntu. The installer adds
the agent's user to it; on a host set up by hand, run `sudo usermod -aG proxy wolf-agent` and
restart the agent. Until then the agent logs that it cannot read the log.

</warning>

**Every new connection, not a sample.** Read from `/proc`, a connection that opened and closed
between two samples is missed: most webhook or API calls last under a second. No kernel interface
lists past connections without root, so this one step is privileged and optional. The helper
`wolf-outbound-log` adds an nftables table that logs every **new** outbound TCP connection of the
bench users (`output`, with their uid) and of the containers behind a Docker, Podman or CNI bridge
(`docker0`, `br-*`, `podman*`, `cni*`; `forward`, with their address). The agent reads those lines
from the kernel log (`journalctl -t kernel`, resuming after a restart, else `/var/log/kern.log`),
runs the helper again when the bench users change, and marks those events `seen_by: kernel`.

```bash [as root]
install -m 0755 -o root -g root agent/wolf-outbound-log.sh /usr/local/sbin/wolf-outbound-log
echo 'wolf-agent ALL=(root) NOPASSWD: /usr/local/sbin/wolf-outbound-log' > /etc/sudoers.d/wolf-outbound-log
chmod 0440 /etc/sudoers.d/wolf-outbound-log
systemctl restart wolf-agent
```

The agent uses it once it is there (`outbound.kernel_log`, `"auto"`). It refuses uid 0.

- Every rule shares one limit: 50 new connections a second for the whole host, so the journal
cannot be flooded; past it, only what a `/proc` sample sees is counted. UDP (DNS, NTP) is not
logged, nor are private, loopback and link-local destinations (`outbound.include_private` does
not apply here).
- Matching new connections turns connection tracking on for the host's traffic.
- Destinations only this log sees get a learning week of their own, from when the helper is first
applied: installing it on a host learned long ago does not raise a burst of alerts.
- `nft list table inet wolf_outbound` shows the rules and their counters. `"kernel_log": false`
makes the agent remove the table; to uninstall, run `wolf-outbound-log --off`. Without the
helper, or when sudo refuses, the agent says so once and keeps sampling `/proc`.

<table>
<thead>
  <tr>
    <th>
      Preset
    </th>
    
    <th>
      Fires when
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <em>
        Bench connects somewhere new
      </em>
    </td>
    
    <td>
      a <code>
        bench_new_outbound
      </code>
      
       event at warning (an unusual port), per host (warning)
    </td>
  </tr>
</tbody>
</table>

## Turning detection off

<table>
<thead>
  <tr>
    <th>
      To turn off
    </th>
    
    <th>
      Set in the agent config
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Auth log signals
    </td>
    
    <td>
      <code>
        "auth_log": false
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Exposure checks
    </td>
    
    <td>
      <code>
        "exposure": false
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      File integrity
    </td>
    
    <td>
      <code>
        "integrity": false
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Outbound connections
    </td>
    
    <td>
      <code>
        "outbound": false
      </code>
    </td>
  </tr>
</tbody>
</table>

Web attack detection follows the nginx logs: it stops for a bench whose nginx log the agent does
not tail.
