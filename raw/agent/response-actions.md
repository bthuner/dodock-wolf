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
      the public addresses of the incident's security events, for the agent that saw each one
    </td>
    
    <td>
      the agent, with its next push, when allowed on that host (below); and <a href="#crowdsec">
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
other action, target or agent.
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
