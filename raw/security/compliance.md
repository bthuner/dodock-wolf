# Compliance and posture

> Track NIS2, DORA and GDPR reporting deadlines on incidents, draft the regulatory report, and read each site's security score.

## Regulatory reporting

A **Wolf Incident** has a section *Regulatory reporting (NIS2 / DORA / GDPR)* with three flags.
Each flag starts its own deadlines. The deadlines are shown on the incident, in Desk and in the
Wolf UI. For the rest of the incident workflow, see [Incidents](/alerts/incidents).

<caution>

Wolf tracks dates only. It does not decide whether an incident is significant, major or a
breach, and it sends nothing to an authority.

</caution>

### NIS2 Article 23

Tick **Significant incident (NIS2 Art. 23)**. **Aware since (NIS2)** is set to now; correct it if
you learnt of the incident earlier.

<table>
<thead>
  <tr>
    <th>
      Obligation
    </th>
    
    <th>
      Due
    </th>
    
    <th>
      Record when sent
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Early warning to the CSIRT or authority
    </td>
    
    <td>
      24 h after <em>
        Aware since
      </em>
    </td>
    
    <td>
      <strong>
        Early warning sent at
      </strong>
    </td>
  </tr>
  
  <tr>
    <td>
      Incident notification
    </td>
    
    <td>
      72 h after <em>
        Aware since
      </em>
    </td>
    
    <td>
      <strong>
        Incident notification sent at
      </strong>
    </td>
  </tr>
  
  <tr>
    <td>
      Final report
    </td>
    
    <td>
      one month after the notification
    </td>
    
    <td>
      <strong>
        Final report sent at
      </strong>
    </td>
  </tr>
  
  <tr>
    <td>
      Intermediate report (Art. 23(4)(c))
    </td>
    
    <td>
      the deadline the CSIRT or authority gave
    </td>
    
    <td>
      <strong>
        Intermediate report sent at
      </strong>
    </td>
  </tr>
</tbody>
</table>

- Until the notification is sent, the final report counts from the notification's deadline and
is marked *estimated*.
- An intermediate report is only due when the CSIRT or the authority asks for one. Record
**Intermediate report requested at** and, if they gave one, **Intermediate report due by**.
Without a deadline it is listed "as asked" and never reminded.
- Art. 23(4)(e): while the incident is still open, the report draft reminds you that an ongoing
incident gets a progress report at the final report's date, and the final report one month
after it is handled.

### DORA Article 19

For financial entities. Tick **Major ICT-related incident (DORA Art. 19)**. **Aware since (DORA)**
and **Classified as major at** are both set to now; correct them if needed.

The time limits follow Delegated Regulation (EU) 2025/301, Art. 5:

<table>
<thead>
  <tr>
    <th>
      Obligation
    </th>
    
    <th>
      Due
    </th>
    
    <th>
      Record when sent
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Initial notification
    </td>
    
    <td>
      4 h after <em>
        Classified as major
      </em>
      
      , and no later than 24 h after <em>
        Aware since
      </em>
      
      . A classification made later than those 24 h gives 4 h from the classification
    </td>
    
    <td>
      <strong>
        Initial notification sent at
      </strong>
    </td>
  </tr>
  
  <tr>
    <td>
      Intermediate report
    </td>
    
    <td>
      72 h after the initial notification
    </td>
    
    <td>
      <strong>
        Intermediate report sent at
      </strong>
    </td>
  </tr>
  
  <tr>
    <td>
      Final report
    </td>
    
    <td>
      one month after the latest intermediate report
    </td>
    
    <td>
      <strong>
        Final report sent at
      </strong>
    </td>
  </tr>
</tbody>
</table>

- Until a report is sent, the next one counts from its deadline and is marked *estimated*.
- Record the latest intermediate report: an updated one moves the final report's deadline.
- The weekend and bank holiday extension of Art. 5(4) is not applied. It depends on the entity
and its Member State, and an earlier deadline is always met.
- DORA reports go through the authority's own templates. The report draft is a starting point.

### GDPR Article 33

Tick **Personal data breach (GDPR Art. 33)**. **Aware since (GDPR)** is set to now. The
notification to the supervisory authority (CNIL in France) is due 72 h after it. Record it in
**Authority notified at**.

### Shared fields

**Authority reference** records the reference the authority gave. It appears in the report draft.

### Deadline alerts

Every 5 minutes, the `check_deadlines` job records one `regulatory_deadline` event per obligation:

- when it is due within 6 h;
- again when it is overdue.

Each event is linked to the incident, so it is on its timeline, with a comment. The
**Regulatory deadline** preset alerts on them (critical).

<warning>

Like every preset, *Regulatory deadline* has no channels. Add the channels of whoever reports to
the CSIRT or the CNIL, or the reminders reach nobody. See [Presets](/alerts/presets).

</warning>

### Report draft

**Regulatory report** (Desk → **Actions**) or **Report draft** (Wolf UI) builds a Markdown draft:

- the facts: incident, scope, severity, status, start and resolution times, authority reference,
the flags and their dates;
- the deadlines, with what was sent and when;
- the incident summary;
- the postmortem's impact, root cause, lessons and measures, when there is one;
- the timeline: events and comments.

It is a starting point for the authority's form. Check every fact before sending it.

## Security score

**Wolf → Security** (`/wolf/security`) shows a score out of 100 per site, with every check, what
Wolf read and the fix.

<table>
<thead>
  <tr>
    <th>
      Check
    </th>
    
    <th>
      Weight
    </th>
    
    <th>
      Read from
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Two-factor authentication for System Managers (global switch and the role)
    </td>
    
    <td>
      3
    </td>
    
    <td>
      System Settings and Role: on the Wolf site itself, else the agent's <code>
        site_setting
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Password policy, minimum score 3
    </td>
    
    <td>
      2
    </td>
    
    <td>
      System Settings (as above)
    </td>
  </tr>
  
  <tr>
    <td>
      Lockout after 1–10 failed logins
    </td>
    
    <td>
      1
    </td>
    
    <td>
      System Settings (as above)
    </td>
  </tr>
  
  <tr>
    <td>
      Guests cannot upload files
    </td>
    
    <td>
      1
    </td>
    
    <td>
      System Settings (as above)
    </td>
  </tr>
  
  <tr>
    <td>
      No development settings in <code>
        site_config.json
      </code>
    </td>
    
    <td>
      3
    </td>
    
    <td>
      the site config on the Wolf site, else the agent's <code>
        site_config_risks
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Bench services not listening beyond loopback
    </td>
    
    <td>
      3
    </td>
    
    <td>
      the agent's <code>
        exposed_services
      </code>
      
       on the site's hosts
    </td>
  </tr>
  
  <tr>
    <td>
      A backup newer than 26 h
    </td>
    
    <td>
      2
    </td>
    
    <td>
      <code>
        backup_age_hours
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      TLS certificates valid for 14 days or more
    </td>
    
    <td>
      2
    </td>
    
    <td>
      <code>
        tls_days_left
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      HSTS for 180 days or more, on every domain
    </td>
    
    <td>
      1
    </td>
    
    <td>
      the agent's <code>
        hsts_max_age_days
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      SPF for the mail domain, ending in <code>
        -all
      </code>
      
       or <code>
        ~all
      </code>
    </td>
    
    <td>
      1
    </td>
    
    <td>
      DNS, for the domains of the outgoing Email Accounts (Wolf site only)
    </td>
  </tr>
  
  <tr>
    <td>
      DMARC policy <code>
        quarantine
      </code>
      
       or <code>
        reject
      </code>
    </td>
    
    <td>
      1
    </td>
    
    <td>
      DNS, <code>
        _dmarc.<domain>
      </code>
      
      , then its parents' <code>
        sp=
      </code>
      
       / <code>
        p=
      </code>
      
       (Wolf site only)
    </td>
  </tr>
  
  <tr>
    <td>
      No published security advisory applies to Frappe or ERPNext
    </td>
    
    <td>
      3
    </td>
    
    <td>
      the agent's <code>
        app_version
      </code>
      
       for the site's benches, and the Wolf site's own packages, against GitHub Security Advisories
    </td>
  </tr>
</tbody>
</table>

- A check Wolf cannot read is **unknown** and counts as not passed. `coverage` says how much of
the weight Wolf could read.
- Agent samples older than 3 h are not used.
- The score is stored hourly as the `security_score` metric. The **Security score low** preset
fires when a site's score is below 60.

### Where the inputs come from

- **System Settings of other sites**: the agent reads them hourly from each site's database, with
the site's own credentials: five System Settings rows and the System Manager role's two-factor
flag, nothing else. It uses the `mariadb` / `mysql` client or `psql`. Without a client on the
host, those checks stay unknown. The Wolf site always reads its own settings.
- **Exposure and site config**: see [Exposure and site-config risks](/security/detection#exposure-and-site-config-risks).
- **HSTS**: with the hourly TLS check, the agent sends `HEAD /` and reads
`Strict-Transport-Security` from the first response. Redirects are not followed. A missing
header counts as 0 days. No HTTP answer sends no sample, so the check stays unknown.
- **SPF and DMARC**: the Wolf site reads DNS through the resolvers of `/etc/resolv.conf`, for the
domains of its enabled outgoing Email Accounts, cached 1 h (10 min after a DNS failure, which
makes the check unknown). SPF needs one `v=spf1` record ending in `-all` or `~all`;
`redirect=` passes without being followed, `include:` is not followed. DMARC needs
`p=quarantine` or `p=reject`; `p=none` fails. A subdomain without a record follows its parent's
`sp=` (else `p=`).
- **Security advisories**: once a day, the Wolf site reads the published advisories of
`frappe/frappe` and `frappe/erpnext` from the GitHub API, unauthenticated: nothing about the
installation is sent. A copy older than 7 days is not used. The agent sends `app_version` per
bench and app hourly; development versions are not sent. Any advisory that applies fails the
check; the evidence counts them by severity and names the version that fixes them all on that
line. A major line no advisory of the last year names (Dodock, or a line out of support such as
13.x) is unknown, never safe. Turn the check off with **Wolf Settings → Check versions against
GitHub Security Advisories**; it is then unknown.

### Related presets

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
        Security score low
      </em>
    </td>
    
    <td>
      <code>
        security_score
      </code>
      
       below 60, per site (warning)
    </td>
  </tr>
  
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
      
       above 0, per host (critical)
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

### Not covered yet

- Advisories of other apps (HRMS, Dokos' own).
- SPF and DMARC of the mail domains of sites other than the Wolf site.
