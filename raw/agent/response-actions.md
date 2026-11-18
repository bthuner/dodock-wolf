# Response actions

> Block an attacking IP on the host, disable a user or revoke sessions, after a Wolf Manager approves. Off by default.

Wolf proposes, a Wolf Manager approves each action with a second click, and nothing runs on its
own. Every approval is a **Wolf Response Action** row (who, when, what, result; read-only for
everyone) and a comment on the incident.

<table>
<thead>
  <tr>
    <th>
      Action
    </th>
    
    <th>
      Proposed for
    </th>
    
    <th>
      Applied by
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        Block IP for N hours
      </strong>
      
       (1 to 168, default 24)
    </td>
    
    <td>
      the public addresses of the incident's security events, from any source (Wolf, Suricata, Wazuh), for the attacked host
    </td>
    
    <td>
      the Wolf Agent on that host, with its next push, when allowed there (below), and/or <a href="#wazuh-active-response">
        Wazuh active response
      </a>
      
      ; and <a href="#crowdsec">
        CrowdSec
      </a>
      
       when set up
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Disable user
      </strong>
      
      , <strong>
        log out all sessions
      </strong>
      
      , <strong>
        revoke API keys
      </strong>
    </td>
    
    <td>
      the users named by the site's own security events (failed logins, new IP or country, role granted, API key generated)
    </td>
    
    <td>
      the Wolf site, at once
    </td>
  </tr>
</tbody>
</table>

- Approve from the incident's **Response** panel in the Wolf UI, or from the signed link in the
alert (up to 5 per alert). The link only shows the proposal: a guest is sent to the login page,
only a logged-in Wolf Manager or System Manager gets the button, and only its POST acts. A
forwarded email alone cannot act, and a link opened again says the action was done.
- Only what Wolf proposed from the incident's own events can be approved: the API refuses any
other action, target or host.
- Administrator, Guest and the approver's own account are refused. Only a System Manager can act
on a System Manager. User actions apply to the Wolf site only.
- Blocks are marked *Expired* once their time is over (hourly).

## Blocking on the host

The agent does nothing unless you allow it on that host.

<caution>

The agent refuses private, loopback and reserved addresses, and durations over a week, whatever
the site sends. It runs the command as a list of arguments, never through a shell. Without
`response.enabled`, each action comes back *Failed* with the reason, so the manager knows it was
not applied.

</caution>

### Set up

<note>

An agent installed before this fix has `NoNewPrivileges=yes` in `/etc/systemd/system/wolf-agent.service`, which stops `sudo`: no block ever ran. Re-run `install.sh`, or delete that line, then `systemctl daemon-reload && systemctl restart wolf-agent`.

</note>

<tabs>
<tabs-item label="nftables">

```bash [host]
install -m 0755 -o root -g root agent/wolf-block.sh /usr/local/sbin/wolf-block
echo 'wolf-agent ALL=(root) NOPASSWD: /usr/local/sbin/wolf-block' > /etc/sudoers.d/wolf-block
chmod 0440 /etc/sudoers.d/wolf-block
```

In the agent config:

```json [/etc/wolf-agent/config.json]
"response": {"enabled": true}
```

Restart the agent. `wolf-block` adds the address to an nftables set (`inet wolf`, `blocked4` /
`blocked6`) whose entries expire by themselves. `nft list table inet wolf` shows them.

</tabs-item>

<tabs-item label="fail2ban">

Where fail2ban already manages the firewall, `wolf-block-fail2ban` bans in a jail of its own
(`wolf`), with your usual ban action:

```bash [host]
cp agent/fail2ban/wolf.local /etc/fail2ban/jail.d/wolf.local && fail2ban-client reload
install -m 0755 -o root -g root agent/wolf-block-fail2ban.sh /usr/local/sbin/wolf-block-fail2ban
install -d -m 0700 /var/lib/wolf-block   # the expiries; writable from the agent's unit
echo 'wolf-agent ALL=(root) NOPASSWD: /usr/local/sbin/wolf-block-fail2ban' > /etc/sudoers.d/wolf-block
chmod 0440 /etc/sudoers.d/wolf-block
# reboots lose the scheduled unbans: sweep the expired ones every 5 minutes
echo '*/5 * * * * root /usr/local/sbin/wolf-block-fail2ban --sweep >/dev/null' > /etc/cron.d/wolf-block-fail2ban
```

In the agent config:

```json [/etc/wolf-agent/config.json]
"response": {"enabled": true, "command": ["sudo", "-n", "/usr/local/sbin/wolf-block-fail2ban", "{ip}", "{seconds}"]}
```

`fail2ban-client get wolf banip` lists the addresses. `fail2ban-client set wolf unbanip IP` lifts
one early. Without the jail, the helper refuses and says so, and the action comes back *Failed*.

</tabs-item>
</tabs>

Paths are relative to a checkout of the repository.

### Custom command

`response.command` replaces the command. `{ip}` and `{seconds}` are filled in.

### How fail2ban durations work

fail2ban has no per-ban duration: every ban gets the jail's `bantime`. The jail's is the longest
block Wolf asks for (7 days), and the helper unbans each address when its own duration is over:

- a transient systemd timer (`wolf-unban-<ip>-<time>`) runs `fail2ban-client set wolf unbanip`;
- each expiry is also written to `/var/lib/wolf-block/fail2ban.state`, and `--sweep` unbans those
that are over.

Timers do not survive a reboot, and fail2ban restores its bans after one. Without the cron line, a
block could last up to the jail's 7 days. The helper also sweeps on each ban.

## Wazuh active response

With **Block With** set to `wazuh` or `both` (**Wolf Settings → Blocking**), an approved block runs
through Wazuh active response on the Wazuh agent of the attacked host, through the Wazuh manager's
API. It is the same approval, the same signed links, the same journal: only who applies the block
changes.

<table>
<thead>
  <tr>
    <th>
      Block With
    </th>
    
    <th>
      Who applies an approved block
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        wolf_agent
      </code>
      
       (default)
    </td>
    
    <td>
      the Wolf Agent on the attacked host, as above
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        wazuh
      </code>
    </td>
    
    <td>
      Wazuh active response on that host's Wazuh agent
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        both
      </code>
    </td>
    
    <td>
      each of them: two <strong>
        Wolf Response Action
      </strong>
      
       rows, one per executor
    </td>
  </tr>
</tbody>
</table>

A block is proposed for the host that was attacked, not for the agent that sent the alert: a Wazuh
or Suricata alert, read on the manager's or the sensor's host, or posted by the integration, is
about the host it names. Any other agent's event is about that agent's own host, whatever its
`host` says, so an agent cannot point a block at another machine. With
`wolf_agent`, a host without a Wolf Agent gets no block proposal; with `wazuh` or `both`, it does.

<steps level="3">

### Define a timed command on the Wazuh manager

Wolf runs a *named* command, which Wazuh removes by itself when its timeout runs out. Add an
`<active-response>` block for `firewall-drop` with the timeout you want, on a rule that never fires
so that it only runs when Wolf asks, then restart the manager:

```xml [ossec.conf]
<active-response>
  <disabled>no</disabled>
  <command>firewall-drop</command>
  <location>local</location>
  <rules_id>999999</rules_id>
  <timeout>86400</timeout>
</active-response>
```

Wazuh names the command with its timeout: `firewall-drop86400` (listed in
`/var/ossec/etc/shared/ar.conf`). That timeout is the block's duration; the hours chosen at approval
only apply to the Wolf Agent's block. A script (`!firewall-drop`) is refused: Wazuh never removes it.

### Create a Wazuh API user

A user allowed to read agents and run active response commands (`agent:read`,
`active-response:command`).

### Fill Wolf Settings → Blocking

<table>
<thead>
  <tr>
    <th>
      Field
    </th>
    
    <th>
      Value
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        Block With
      </strong>
    </td>
    
    <td>
      <code>
        wazuh
      </code>
      
       or <code>
        both
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Wazuh Active Response Command
      </strong>
    </td>
    
    <td>
      <code>
        firewall-drop86400
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Wazuh API URL
      </strong>
    </td>
    
    <td>
      <code>
        https://wazuh-manager:55000
      </code>
      
      . <code>
        http://
      </code>
      
       only to the same machine (<code>
        127.0.0.1
      </code>
      
      , <code>
        localhost
      </code>
      
      ): the password goes with every login. Changing the URL asks for the password again.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Wazuh API User
      </strong>
      
      , <strong>
        Wazuh API Password
      </strong>
    </td>
    
    <td>
      the user above
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Verify Wazuh TLS Certificate
      </strong>
    </td>
    
    <td>
      on, unless the manager has a self-signed certificate on a trusted network
    </td>
  </tr>
</tbody>
</table>
</steps>

- Wolf finds the Wazuh agent by the host's names (its Wolf hostname, its
[aliases](/security/wazuh-suricata#aliases)), then by an address only one Wazuh agent has: hosts
behind one NAT share theirs. The manager (`000`) never runs a block. When no agent matches, the action is *Failed* with the reason; add a Wolf Entity
Alias and approve again.
- The action is *Applied* or *Failed* at once, with Wazuh's answer, and journaled like any other.
It is recorded before Wolf calls Wazuh, so a block Wazuh applied always has its row.
- With `both`, each executor has its own duration (the hours asked for the Wolf Agent, the
command's timeout for Wazuh) and its own row. When Wazuh's half fails, it alone is proposed
again while the Wolf Agent's half waits for its agent.
- Tried against a Wazuh 4.9.2 manager and agent: the address was dropped with iptables on the
agent, and Wazuh removed the rule when the timeout ran out.

## CrowdSec

With a CrowdSec Local API (LAPI), approved blocks reach every bouncer of that LAPI (firewall, nginx,
Cloudflare), and Wolf and CrowdSec share detections. Off by default; runs every minute on the
central site only.

<steps level="3">

### Create the credentials

```bash [CrowdSec host]
cscli bouncers add dodock-wolf   # prints the bouncer key: decisions in
cscli machines add dodock-wolf --password '<long random password>'  # detections and blocks out
```

### Fill Wolf Settings → CrowdSec

<table>
<thead>
  <tr>
    <th>
      Setting
    </th>
    
    <th>
      Default
    </th>
    
    <th>
      Effect
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        Use CrowdSec
      </strong>
    </td>
    
    <td>
      off
    </td>
    
    <td>
      turns the integration on
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Local API URL
      </strong>
      
      , <strong>
        Bouncer API key
      </strong>
      
      , <strong>
        Machine ID
      </strong>
      
      , <strong>
        Machine password
      </strong>
    </td>
    
    <td>
      
    </td>
    
    <td>
      the LAPI and the credentials above
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Send detections
      </strong>
    </td>
    
    <td>
      on
    </td>
    
    <td>
      security events with an IP, at or above <strong>
        Minimum severity sent
      </strong>
      
       (<code>
        warning
      </code>
      
      ), become LAPI alerts with the scenario <code>
        dodock-wolf/<category>
      </code>
      
      . Past events are not replayed.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Let CrowdSec decide on detections
      </strong>
    </td>
    
    <td>
      off
    </td>
    
    <td>
      off: alerts carry <code>
        remediation: false
      </code>
      
      , CrowdSec records them (<code>
        cscli alerts list
      </code>
      
      ) and decides nothing. On: CrowdSec's profiles decide; the default profile bans the IP for 4 h, with no human approval.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Apply approved blocks
      </strong>
    </td>
    
    <td>
      on
    </td>
    
    <td>
      an approved <strong>
        Block IP
      </strong>
      
       goes to the LAPI as a <code>
        ban
      </code>
      
       decision for the approved duration (origin <code>
        dodock-wolf
      </code>
      
      ).
    </td>
  </tr>
</tbody>
</table>
</steps>

**Decisions in**: Wolf reads the LAPI's decisions (the whole list on the first run and every hour,
the changes in between), including CrowdSec's own detections, `cscli` bans and the community
blocklist when the LAPI is enrolled. A security event whose IP is under a decision gets
`payload.crowdsec` (type, origin, scenario, until) and one severity step more. Wolf's own blocks are
tagged but not raised.

The agent still applies its own block when its responder is on, and the incident comment says what
was sent where. Tested against CrowdSec 1.6.4.
