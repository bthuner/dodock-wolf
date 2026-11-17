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
      one event per (site, client) and push interval, with the rules hit, the statuses, up to 10 targets and the ATT&CK IDs
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
      failed SSH logins, aggregated per source IP
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
</tbody>
</table>

Web attack detection follows the nginx logs: it stops for a bench whose nginx log the agent does
not tail.
