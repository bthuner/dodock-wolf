# Site signals

> Turn on the security signals the Wolf site captures by itself, with no agent, and set up the GeoIP database for new-country logins.

The site running Dodock Wolf records its own signals from Frappe's documents and requests. No
agent is needed. Each signal has a switch in **Wolf Settings**, and all are on by default.

These signals are only seen from inside a site. To get them for the other sites of a bench,
install the Wolf App on each one in satellite mode: it captures the same signals, with the same
switches, and forwards them to the central site. See [Every site on a bench](/install/every-site).

## Logins and roles

**Wolf Settings → Local signals (this site)**:

<table>
<thead>
  <tr>
    <th>
      Setting
    </th>
    
    <th>
      Category
    </th>
    
    <th>
      What it records
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
      <strong>
        Capture failed logins
      </strong>
    </td>
    
    <td>
      <code>
        frappe_failed_login
      </code>
    </td>
    
    <td>
      a failed desk login (Activity Log), with the user and IP
    </td>
    
    <td>
      warning
    </td>
    
    <td>
      <em>
        Repeated failed Frappe logins
      </em>
      
      : 5+ in 10 min, per site
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Flag privileged logins from new IPs
      </strong>
    </td>
    
    <td>
      <code>
        new_admin_ip
      </code>
    </td>
    
    <td>
      a privileged user logs in from an IP none of their earlier logins came from
    </td>
    
    <td>
      warning
    </td>
    
    <td>
      <em>
        Admin login from new IP
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Flag privileged logins from new countries
      </strong>
    </td>
    
    <td>
      <code>
        admin_login_new_country
      </code>
    </td>
    
    <td>
      a privileged login from a country none of the user's earlier logins came from. Needs a <a href="#geoip-database">
        GeoIP database
      </a>
    </td>
    
    <td>
      critical
    </td>
    
    <td>
      <em>
        Admin login from new country
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Flag users granted privileged roles
      </strong>
    </td>
    
    <td>
      <code>
        privileged_user
      </code>
    </td>
    
    <td>
      an enabled user receives a privileged role
    </td>
    
    <td>
      critical for System Manager or Administrator, else warning
    </td>
    
    <td>
      <em>
        Privileged role granted
      </em>
    </td>
  </tr>
</tbody>
</table>

**Privileged Roles** lists the roles that count as privileged, one per line. Default:
`System Manager`, `Administrator`, `Wolf Manager`.

The same section holds the non-security local signals: **Capture failed Scheduled Job Logs**
(`cron_failure`) and **Capture Error Logs** (failed backups as `backup_failed`). **Watch the Email
Queue** records Email Queue backlogs and sending errors.

## Risky application changes

**Wolf Settings → Flag risky application changes** (on by default) covers:

<table>
<thead>
  <tr>
    <th>
      Category
    </th>
    
    <th>
      What raises it
    </th>
    
    <th>
      ATT&CK
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
        server_script_change
      </code>
    </td>
    
    <td>
      a Server Script created, enabled, or with its code, type or trigger changed
    </td>
    
    <td>
      T1059.006
    </td>
    
    <td>
      <em>
        Server Script can run new code
      </em>
      
       (the event is critical for API and scheduled scripts or guest access)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        client_script_change
      </code>
    </td>
    
    <td>
      the same for a Client Script
    </td>
    
    <td>
      T1059.007
    </td>
    
    <td>
      <em>
        Client Script can run new code
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        console_execution
      </code>
    </td>
    
    <td>
      each System Console run (Python or SQL)
    </td>
    
    <td>
      T1059.006
    </td>
    
    <td>
      <em>
        System Console used
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        permission_change
      </code>
    </td>
    
    <td>
      see <a href="#permission-drift">
        Permission drift
      </a>
    </td>
    
    <td>
      T1098
    </td>
    
    <td>
      <em>
        Permission rules changed
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        security_settings_weakened
      </code>
    </td>
    
    <td>
      see <a href="#weakened-settings">
        Weakened settings
      </a>
    </td>
    
    <td>
      T1562.001
    </td>
    
    <td>
      <em>
        Security settings weakened
      </em>
      
       (critical)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        api_key_generated
      </code>
    </td>
    
    <td>
      a new API secret written for a user
    </td>
    
    <td>
      T1098.001
    </td>
    
    <td>
      <em>
        API key generated
      </em>
      
       (the event is critical for privileged users)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        api_key_new_ip
      </code>
    </td>
    
    <td>
      see <a href="#api-key-used-from-a-new-ip">
        API key used from a new IP
      </a>
    </td>
    
    <td>
      T1078, T1552
    </td>
    
    <td>
      <em>
        API key used from a new IP
      </em>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        webhook_external
      </code>
    </td>
    
    <td>
      a Webhook created, enabled or pointed at another host
    </td>
    
    <td>
      T1567
    </td>
    
    <td>
      <em>
        Webhook to a new host
      </em>
    </td>
  </tr>
</tbody>
</table>

Editing a script's description or disabling a script raises nothing.

<caution>

Script events keep the first 300 characters of the code. A script that holds a secret puts part
of it in the event.

</caution>

### Permission drift

All of these are `permission_change` events:

- **Role Permission Manager**: add, update, remove and reset. Older Frappe versions write
`update`, `remove` and `reset` with raw SQL, so Wolf reads them from the request.
- **Custom DocPerm** saved or deleted anywhere else: Data Import, the REST API, code
(`payload.kind` is `custom_docperm`, `via` says how). Each event lists the rights granted and
removed. A new rule is compared with the DocType's standard rule, so the copies Frappe makes
before the first custom change grant nothing. A right given to `Guest` or `All` is critical.
- **User Permission** that lets its user see more (`user_permission`). The first User Permission
of a user for a DocType only restricts and raises nothing. A further value, an edit that allows
another value, user or DocType, or removing the last one (which lifts the restriction) raises an
event.
- **Desk access**: a Website user (customer, supplier portal) given a desk role, which makes them
a System User (`desk_access`).
- **Role Profile** created or granting more roles.

### Weakened settings

A System Settings save raises `security_settings_weakened` (critical) when it:

- turns off two-factor authentication, the password policy, one session per user, SSO-only login
or logout on password reset;
- lowers the minimum password score or the lockout duration;
- allows more failed logins, or removes the lockout;
- lengthens sessions;
- lets guests upload files.

### API key used from a new IP

Every successful request authenticated by an API key (`Authorization: token key:secret` or
`Basic`) records the key's address in **Wolf API Key IP**.

- The key's first address, and any address in its first 24 h, form its baseline.
- After that, an address outside every known /24 (IPv4) or /64 (IPv6) raises `api_key_new_ip`,
critical for privileged users. A new address inside a known network is recorded silently.
- Addresses unused for a year are forgotten. Deleting a row forgets an address.
- The proposed responses are revoking the user's API keys and blocking the address.

### Limits

- Changes made with raw SQL (a patch, `bench mariadb`) fire no document event and are not seen.
Patches and migrations are skipped on purpose.
- A User Permission restricted to one DocType (`applicable_for`) is counted with the user's
others for the same allowed DocType.

## Unusual data exports

**Wolf Settings → Flag unusual data exports** (on by default) raises `data_exfiltration`
(T1567, T1030). Preset: *Unusual data export*.

- **What counts**: report exports, Data Export, Data Import templates with records, bulk PDFs,
and every list read (`frappe.client.get_list`, the list and report views,
`/api/resource/<DocType>`), whatever the page size. A script paging through a table adds up
like one big read.
- **How**: the response size of each request counts towards the user's total for the clock
hour. Every hour, the totals become `user_export_bytes` samples, one series per user
(`labels.user`).
- **When**: past **Export Floor (MB per hour)** (default `50`), the hour is compared with the
user's largest hour over the last 14 days. Warning at **Export Factor** (default `5`) times
that hour, critical at 20 times. A user without any history is critical, except while the site
itself has less than 14 days of history: then it is a warning.
- **How often**: at most one event per user, hour and severity, so a warning can be followed by
a critical. The payload has the hour's bytes, requests and rows, the baseline, the ratio, the
last request and the IP.

<note>

The `user_export_bytes` series names users. Anyone who may read the site's metrics in Wolf sees
how much each user took out per hour.

</note>

Not counted: files sent as they are (private files, backups), printing one document, and the
file of a background list export (its request is counted). An export spread across two clock
hours is split in two. Satellites keep raw samples for 2 days, so their baseline covers 2 days,
not 14.

## GeoIP database

*Admin login from new country* needs an offline GeoIP database on the server. Wolf never calls
an online lookup service.

<steps level="3">

### Download a database

Either format works:

- a MaxMind-format `.mmdb` file: GeoLite2-Country or GeoLite2-City (free MaxMind account),
DB-IP "IP to Country Lite" (`dbip-country-lite-*.mmdb`, CC BY 4.0) or IPinfo Lite. Wolf reads
it with its own reader, so no extra Python package is needed;
- a CSV of ranges, one per line: `start_ip,end_ip,CC` (DB-IP or IPinfo "country lite" CSV),
integer `start,end,CC,...` (IP2Location LITE DB1) or `network/prefix,CC`. Header lines are
skipped.

### Set the path

Set **Wolf Settings → GeoIP Database** to the file's path. A relative path is read from the site
directory, for example `private/files/dbip-country.mmdb`.

### Keep it fresh

Refresh the file monthly. Wolf reloads it when it changes.

</steps>

Private and loopback addresses have no country. A user whose earlier logins all came from such
addresses has no baseline yet, so nothing is flagged until a first public login is known.

## Turning a signal off

Untick its switch in **Wolf Settings**. On a satellite, the same switches apply to the signals it
forwards.
