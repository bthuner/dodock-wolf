# Security overview

> What Dodock Wolf detects, where each security signal comes from, and how every event is tagged with MITRE ATT&CK.

Dodock Wolf detects attacks on a Frappe site, its bench and its hosts. It correlates them with
health signals (5xx, failed crons, deployments) in the same incidents. Every security finding is
a **Wolf Event** of type `security` with a `category`, such as `ssh_login_after_failures` or
`permission_change`.

Wolf alone is the baseline. No security feature needs Wazuh or Suricata. When they run on your
hosts, the Wolf Agent reads their alerts too.

## Where each signal comes from

<table>
<thead>
  <tr>
    <th>
      Source
    </th>
    
    <th>
      Needs
    </th>
    
    <th>
      What it sees
    </th>
    
    <th>
      Page
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Wolf site
    </td>
    
    <td>
      the Wolf App installed on the site
    </td>
    
    <td>
      failed and privileged logins, role grants, Server and Client Scripts, System Console runs, permission changes, weakened System Settings, API keys, Webhooks, data exports, honeytokens
    </td>
    
    <td>
      <a href="/security/site-signals">
        Site signals
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      Wolf Agent: nginx
    </td>
    
    <td>
      nginx access logs tailed by the agent
    </td>
    
    <td>
      probes for secrets, CMS panels, path traversal, injections, scanners; secret files served
    </td>
    
    <td>
      <a href="/security/detection">
        Detection
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      Wolf Agent: auth log
    </td>
    
    <td>
      <code>
        /var/log/auth.log
      </code>
      
      , <code>
        /var/log/secure
      </code>
      
       or the journal
    </td>
    
    <td>
      SSH brute force then login, root logins, sudo failures, new accounts, admin group changes
    </td>
    
    <td>
      <a href="/security/detection#host-intrusion-signals">
        Detection
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      Wolf Agent: exposure
    </td>
    
    <td>
      <code>
        /proc/net/tcp{,6}
      </code>
      
       and <code>
        site_config.json
      </code>
    </td>
    
    <td>
      bench services listening beyond loopback, development settings in production
    </td>
    
    <td>
      <a href="/security/detection#exposure-and-site-config-risks">
        Detection
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      Suricata (optional)
    </td>
    
    <td>
      Suricata writing an EVE log on the host
    </td>
    
    <td>
      network IDS alerts (<code>
        network_ids_alert
      </code>
      
      )
    </td>
    
    <td>
      <a href="/security/wazuh-suricata">
        Wazuh and Suricata
      </a>
    </td>
  </tr>
  
  <tr>
    <td>
      Wazuh (optional)
    </td>
    
    <td>
      a Wazuh manager
    </td>
    
    <td>
      host IDS alerts (<code>
        hids_alert
      </code>
      
      )
    </td>
    
    <td>
      <a href="/security/wazuh-suricata">
        Wazuh and Suricata
      </a>
    </td>
  </tr>
</tbody>
</table>

Signals that only exist inside a site (logins, scripts, permissions) are captured by the Wolf
App on that site. To see them for every site of a bench, install the app on each one and set
them to satellite mode: see [Every site on a bench](/install/every-site).

## MITRE ATT&CK tags

At ingest, every `security` event gets a `mitre_attack` list in its payload: one
`{id, name, tactic}` per technique. Wolf merges the technique mapped to the event's category
with the technique IDs the agent sent. Suricata and Wazuh alerts carry the techniques of the rule
that fired. Events forwarded by satellites keep theirs.

The tags travel with the event to the [SIEM export](/security/siem-export): OCSF puts them in
`finding_info.attacks`, CEF in `cs4`.

<table>
<thead>
  <tr>
    <th>
      Category
    </th>
    
    <th>
      Raised by
    </th>
    
    <th>
      ATT&CK
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
      agent (auth)
    </td>
    
    <td>
      T1110 Brute Force
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ssh_root_login
      </code>
    </td>
    
    <td>
      agent (auth)
    </td>
    
    <td>
      T1078.003 Local Accounts
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        ssh_login_after_failures
      </code>
    </td>
    
    <td>
      agent (auth)
    </td>
    
    <td>
      T1110, T1078
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sudo_failure
      </code>
    </td>
    
    <td>
      agent (auth)
    </td>
    
    <td>
      T1548.003 Sudo and Sudo Caching
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        account_created
      </code>
    </td>
    
    <td>
      agent (auth)
    </td>
    
    <td>
      T1136.001 Create Local Account
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        service_account_created
      </code>
    </td>
    
    <td>
      agent (auth)
    </td>
    
    <td>
      T1136.001 Create Local Account
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        admin_group_change
      </code>
    </td>
    
    <td>
      agent (auth)
    </td>
    
    <td>
      T1098 Account Manipulation
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        web_attack_probe
      </code>
    </td>
    
    <td>
      agent (nginx)
    </td>
    
    <td>
      T1595.003, plus the technique of each rule hit (T1190, T1189, T1552, T1595.002…)
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        web_sensitive_file_exposed
      </code>
    </td>
    
    <td>
      agent (nginx)
    </td>
    
    <td>
      T1552.001 Credentials In Files
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        service_exposed
      </code>
      
      , <code>
        insecure_site_config
      </code>
    </td>
    
    <td>
      agent (exposure)
    </td>
    
    <td>
      T1190 Exploit Public-Facing Application
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        network_ids_alert
      </code>
    </td>
    
    <td>
      agent (Suricata)
    </td>
    
    <td>
      from the rule's <code>
        mitre_technique_id
      </code>
      
       metadata
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        hids_alert
      </code>
    </td>
    
    <td>
      agent or integration (Wazuh)
    </td>
    
    <td>
      from the rule's <code>
        rule.mitre.id
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        frappe_failed_login
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1110
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        new_admin_ip
      </code>
      
      , <code>
        admin_login_new_country
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1078 Valid Accounts
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        privileged_user
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1098
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        server_script_change
      </code>
      
      , <code>
        console_execution
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1059.006 Python
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        client_script_change
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1059.007 JavaScript
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        permission_change
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1098 Account Manipulation
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        security_settings_weakened
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1562.001 Disable or Modify Tools
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        api_key_generated
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1098.001 Additional Cloud Credentials
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        api_key_new_ip
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1078 Valid Accounts, T1552 Unsecured Credentials
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        webhook_external
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1567 Exfiltration Over Web Service
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        data_exfiltration
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      T1567, T1030 Data Transfer Size Limits
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        honeytoken_triggered
      </code>
    </td>
    
    <td>
      site
    </td>
    
    <td>
      decoy user T1078, T1110; decoy API key T1552; decoy path T1083
    </td>
  </tr>
</tbody>
</table>

## Alerting and response

Each signal has a preset alert rule. Presets are installed with no channels: they open
incidents but notify nobody until you add a channel. See [Presets](/alerts/presets).

On a security incident, a Wolf Manager can approve a response: block an IP on the host, disable
a user, log out their sessions or revoke their API keys. Nothing runs without that approval. See
[Response actions](/agent/response-actions).

## Pages in this section

<card-group>
<card icon="i-lucide-globe" title="Site signals" to="/security/site-signals">

Logins, scripts, permissions, settings, API keys and exports seen by the Wolf site, with no agent.

</card>

<card icon="i-lucide-radar" title="Web and host detection" to="/security/detection">

Web attacks from nginx, intrusion signals from the auth log, exposed services.

</card>

<card icon="i-lucide-key-round" title="Access and secrets" to="/security/access">

Wolf Manager and Wolf User, Wolf User Scope, hashed agent secrets, push rate limit.

</card>

<card icon="i-lucide-book-lock" title="Journal and deception" to="/security/journal">

Tamper-evident journal, honeytokens and IP reputation lists.

</card>

<card icon="i-lucide-scale" title="Compliance and posture" to="/security/compliance">

NIS2, DORA and GDPR deadlines on incidents, and the security score per site.

</card>

<card icon="i-lucide-send" title="SIEM export" to="/security/siem-export">

Syslog export in OCSF or CEF to rsyslog, Wazuh, Graylog or another collector.

</card>

<card icon="i-lucide-network" title="Wazuh and Suricata" to="/security/wazuh-suricata">

Optional sources, and the entities shared across every source.

</card>
</card-group>
