# Access and secrets

> Give people the right Wolf role, limit a Wolf User to some sites, benches or hosts, and manage agent secrets and the push rate limit.

## Roles

Installing the Wolf App creates two roles.

<table>
<thead>
  <tr>
    <th>
      Role
    </th>
    
    <th>
      Can
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <strong>
        Wolf Manager
      </strong>
    </td>
    
    <td>
      see and configure everything, approve response actions, edit Wolf User Scope rows
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Wolf User
      </strong>
    </td>
    
    <td>
      read only. Can comment on incidents. Can be limited with Wolf User Scope
    </td>
  </tr>
</tbody>
</table>

System Manager has the same rights as Wolf Manager. The Wolf UI at `/wolf` answers 403 to users
without the Wolf User or Wolf Manager role.

## Wolf User Scope

By default a Wolf User sees every site, bench and host. To limit one, add **Wolf User Scope**
rows at `/app/wolf-user-scope` (Wolf Managers only). One row per grant:

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
      User
    </td>
    
    <td>
      the Wolf User
    </td>
  </tr>
  
  <tr>
    <td>
      Scope
    </td>
    
    <td>
      <code>
        site
      </code>
      
      , <code>
        bench
      </code>
      
       or <code>
        host
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Value
    </td>
    
    <td>
      the name as it appears on Wolf events
    </td>
  </tr>
</tbody>
</table>

For example:

<table>
<thead>
  <tr>
    <th>
      User
    </th>
    
    <th>
      Scope
    </th>
    
    <th>
      Value
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <a href="mailto:jane@client.com">
        jane@client.com
      </a>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      erp.client.com
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="mailto:jane@client.com">
        jane@client.com
      </a>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      shop.client.com
    </td>
  </tr>
  
  <tr>
    <td>
      <a href="mailto:ops-team@dokos.io">
        ops-team@dokos.io
      </a>
    </td>
    
    <td>
      host
    </td>
    
    <td>
      bench-02
    </td>
  </tr>
</tbody>
</table>

A restricted user then sees only the Wolf Events, Metric Samples and Rollups, Incidents, Silences
and Agents whose site, bench or host matches one of their rows. This applies in list views,
reports, forms, link searches, the Wolf Overview page, charts and incident timelines.

- Rows are OR-ed.
- Host-wide records (CPU, disk, SSH logins: no site) need a `host` row.
- A Wolf User without any row is not restricted.
- Alert rule definitions stay readable by every Wolf User.

<note>

Frappe's own User Permissions cannot do this, because site, bench and host are plain Data fields.
Wolf uses `permission_query_conditions` and `has_permission` hooks instead.

</note>

## Agent secrets

Each Wolf Agent authenticates with an agent ID and a secret.

- Wolf stores only a salted HMAC-SHA256 hash of the secret.
- The secret is shown once: at registration, or when you click **Rotate secret** on the Wolf
Agent form.
- Nobody can read it back from the site. To move an agent or recover a lost config, rotate the
secret or register the host again.

Agents registered before hashing existed keep working: `bench migrate` hashes their stored secret
and deletes the encrypted copy.

A satellite site keeps its own secret encrypted in its Wolf Settings, since it has to send it.
The central site stores only the hash.

**Wolf Settings → Registration Token** is the shared secret that `wolf-agent register --token`
must present. Leave it empty to refuse new registrations. To stop accepting one agent's events,
disable its **Wolf Agent**.

## Push rate limit

Each agent, satellite included, may push at most **Wolf Settings → Max Pushes Per Minute** times
(default `120`, `0` turns the limit off). Excess pushes get HTTP 429. The agent keeps them in its
spool and retries with backoff.

The Wazuh integration endpoint has its own limit of 600 calls per minute, since Wazuh sends one
call per alert. See [Wazuh and Suricata](/security/wazuh-suricata#wazuh-integration-route).

Wire details: [Protocol](/reference/protocol).

## Scrubbing

The agent strips e-mail addresses, credentials, card numbers and IBANs from events before they
leave the host. IP addresses are kept by default, because the security rules group by them. See
[Scrubbing](/agent/scrubbing).
