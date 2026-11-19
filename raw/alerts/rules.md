# Alert rules

> Write a rule that reads like the brief - when X > Y for Z minutes, send alert.

A **Wolf Alert Rule** reads a window of metrics or events every minute. When its condition holds, it
opens one incident per group and notifies its channels.

The top of the form reads the rule back in plain words, and redraws it as you change a field or
a channel, before you save:

> Opens a **critical** incident when the lowest **disk_used_percent** over the last **5 min** is
> **above** **90**, **per host and series (a disk, a queue...)**. It needs at least **3** samples in
> the window. It resolves by itself once the condition no longer holds; if it matches again within
> **1 h** of being resolved, the same incident reopens. It notifies **ntfy** and **Email**, and
> again when it resolves.

If the sentence is not what you meant, the rule is not either.

## Fields

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
      <strong>
        Signal Type
      </strong>
    </td>
    
    <td>
      <code>
        metric
      </code>
      
      : aggregate metric samples (or their rollups for windows over 3 h, see <a href="/reference/metric-storage">
        Metric storage
      </a>
      
      ). <code>
        event
      </code>
      
      : count Wolf Events. <code>
        sequence
      </code>
      
      : an event followed by another on the same IP, user or host, see <a href="#sequence-rules">
        Sequence rules
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Metric Name
      </strong>
      
       / <strong>
        Event Type
      </strong>
      
      , <strong>
        Event Category
      </strong>
      
      , <strong>
        Min Severity
      </strong>
    </td>
    
    <td>
      What to read. For example <code>
        http_502
      </code>
      
      , or <code>
        security
      </code>
      
       / <code>
        web_attack_probe
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Aggregation
      </strong>
    </td>
    
    <td>
      <code>
        avg
      </code>
      
      , <code>
        min
      </code>
      
      , <code>
        max
      </code>
      
      , <code>
        sum
      </code>
      
      , <code>
        count
      </code>
      
      , <code>
        last
      </code>
      
      . Use <code>
        min
      </code>
      
       for "stayed above for Z minutes" and <code>
        sum
      </code>
      
       for counters such as <code>
        http_5xx
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Operator
      </strong>
      
      , <strong>
        Threshold
      </strong>
    </td>
    
    <td>
      <code>
        >
      </code>
      
      , <code>
        >=
      </code>
      
      , <code>
        <
      </code>
      
      , <code>
        <=
      </code>
      
      , <code>
        ==
      </code>
      
      , <code>
        !=
      </code>
      
       against a number.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Window Minutes
      </strong>
    </td>
    
    <td>
      The look-back. Default 5.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Min Samples
      </strong>
    </td>
    
    <td>
      Fewer samples in the window than this, and the rule does not breach.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Group By
      </strong>
    </td>
    
    <td>
      <code>
        host
      </code>
      
      , <code>
        bench
      </code>
      
      , <code>
        site
      </code>
      
      , <code>
        host_label
      </code>
      
       (for example per disk mount) or <code>
        none
      </code>
      
      . One incident per group.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Filter Host / Bench / Site
      </strong>
    </td>
    
    <td>
      Limit the rule to one scope.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Active From / To
      </strong>
    </td>
    
    <td>
      Only evaluate in this window. It may wrap midnight (<code>
        04:00 → 01:00
      </code>
      
      ).
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Require Recent Deployment
      </strong>
    </td>
    
    <td>
      Only fire if a deployment hit the same bench, site or host in the last <strong>
        Deployment Window Minutes
      </strong>
      
       (30).
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Fire / Resolve After Evaluations
      </strong>
    </td>
    
    <td>
      Consecutive breached (or clear) evaluations, one per scheduler tick, before an incident opens (or auto-resolves). Default 1.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Separate Resolve Threshold
      </strong>
    </td>
    
    <td>
      Hysteresis: fire above 90, resolve only once at or below 80.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Cooldown Minutes
      </strong>
    </td>
    
    <td>
      Re-fire into the just-resolved incident instead of opening a new one. An event rule reopens it only for an event newer than the resolution; a metric rule, while its window still breaches. Default 30.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Auto Resolve
      </strong>
    </td>
    
    <td>
      Resolve the incident when the condition clears. Default on.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Channels
      </strong>
    </td>
    
    <td>
      Where alerts go. See <a href="/alerts/channels">
        Channels
      </a>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Notify On Resolve
      </strong>
    </td>
    
    <td>
      Also tell the channels when the incident resolves, automatically or by hand. Default on. PagerDuty always hears it.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Escalate After Minutes
      </strong>
      
      , <strong>
        Escalation Channels
      </strong>
    </td>
    
    <td>
      If still <code>
        Open
      </code>
      
       (not acknowledged) this long after the first alert, notify the escalation channels once.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Severity
      </strong>
    </td>
    
    <td>
      Of the incident: <code>
        info
      </code>
      
      , <code>
        warning
      </code>
      
      , <code>
        critical
      </code>
      
      .
    </td>
  </tr>
</tbody>
</table>

The rule form shows **Last Evaluated**, **Last Fired** and **Last Error**.

## Examples

<tabs>
<tabs-item label="502 spike">
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
      Signal Type
    </td>
    
    <td>
      <code>
        metric
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Metric Name
    </td>
    
    <td>
      <code>
        http_502
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Aggregation
    </td>
    
    <td>
      <code>
        sum
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Operator, Threshold
    </td>
    
    <td>
      <code>
        >=
      </code>
      
      , <code>
        10
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Window Minutes
    </td>
    
    <td>
      <code>
        5
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Group By
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
  </tr>
</tbody>
</table>

*10 or more 502 responses on a site within 5 minutes.*

</tabs-item>

<tabs-item label="Disk stayed full">
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
      Signal Type
    </td>
    
    <td>
      <code>
        metric
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Metric Name
    </td>
    
    <td>
      <code>
        disk_used_percent
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Aggregation
    </td>
    
    <td>
      <code>
        min
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Operator, Threshold
    </td>
    
    <td>
      <code>
        >
      </code>
      
      , <code>
        90
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Window Minutes
    </td>
    
    <td>
      <code>
        15
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Group By
    </td>
    
    <td>
      <code>
        host_label
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Separate Resolve Threshold
    </td>
    
    <td>
      <code>
        80
      </code>
    </td>
  </tr>
</tbody>
</table>

*Every sample of a mount above 90 % for 15 minutes. Resolves at or below 80 %.*

</tabs-item>

<tabs-item label="Night cron">
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
      Signal Type
    </td>
    
    <td>
      <code>
        event
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Event Type
    </td>
    
    <td>
      <code>
        cron_failure
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Aggregation
    </td>
    
    <td>
      <code>
        count
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Operator, Threshold
    </td>
    
    <td>
      <code>
        >=
      </code>
      
      , <code>
        1
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Window Minutes
    </td>
    
    <td>
      <code>
        10
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Group By
    </td>
    
    <td>
      <code>
        site
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Active From / To
    </td>
    
    <td>
      <code>
        01:00
      </code>
      
       → <code>
        04:00
      </code>
    </td>
  </tr>
</tbody>
</table>

*Any failed scheduled job between 01:00 and 04:00.*

</tabs-item>
</tabs>

## Sequence rules

A rule of type `sequence` fires when an event of one list of categories follows an event of another
on the same entity. For example: a web probe, then an SSH login from the same address within the hour.

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
      <strong>
        First Event Categories
      </strong>
    </td>
    
    <td>
      Categories of the first event, one per line, for example <code>
        web_attack_probe
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        First Event Min Severity
      </strong>
    </td>
    
    <td>
      Only first events at or above this severity. The scope filters apply to the second event.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Then Event Categories
      </strong>
    </td>
    
    <td>
      Categories of the event that must follow, one per line.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Same
      </strong>
    </td>
    
    <td>
      <code>
        ip
      </code>
      
      : the second event's remote address (<code>
        payload.ip
      </code>
      
      ), public only. <code>
        user
      </code>
      
      : the same user on the same site. <code>
        host
      </code>
      
      : the same host under any of its names (<strong>
        Wolf Entity Alias
      </strong>
      
      ).
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Within Minutes
      </strong>
    </td>
    
    <td>
      The longest gap between the two events. Default 60.
    </td>
  </tr>
</tbody>
</table>

- The threshold counts the second events seen in the window.
- There is one incident per entity value (`ip 203.0.113.5`), scoped like its newest second event.
- The gap runs from the first event's last occurrence to the second's latest, so repeats folded into
one record count. A brute force of thousands of first events is one candidate.
- The incident links both events. An event already in another incident stays there, and the
incident's timeline, which starts at the first event, shows it anyway.

Three [presets](/alerts/presets#sequences-across-sources) use it.

## Maintenance windows

A **Wolf Silence** (host, bench, site and/or rule, **Starts At**, **Ends At**) keeps incidents
opening, so the timeline stays complete, but holds back their notifications. Incidents still open
when the window ends are notified then.

Create one:

- in Desk (**Wolf Silence → New**);
- through the REST API: `POST /api/resource/Wolf Silence`;
- with the deployment marker: `wolf-agent mark-deployment --bench main --silence 15m`.

## Test a rule

**Send test notification** on the rule form sends a TEST to every enabled channel row and shows
what each one answered.

## Rules as YAML

Alert rules can live in a file: in git, reviewed in a pull request, copied from one Wolf site to another.

```bash
bench --site wolf.example.com wolf-rules export -o rules.yaml           # every rule; --rule NAME for some
bench --site wolf.example.com wolf-rules import rules.yaml              # what it would change
bench --site wolf.example.com wolf-rules import rules.yaml --apply      # write it
```

In Desk, the **Wolf Alert Rule** list's menu has **Export to YAML** (the selected rules, or all) and **Import from YAML**, which previews first and applies only after a second click. Both need the Wolf Manager or System Manager role.

```yaml [rules.yaml]
version: 1
rules:
- rule_name: Disk almost full
  enabled: 1
  severity: critical
  metric_name: disk_used_percent
  aggregation: min
  threshold: 90
  group_by: host_label
  channels:
  - channel_type: ntfy
    ntfy_server: https://ntfy.example.com
    ntfy_topic: ops
```

- **Field names** are the rule form's own. A rule lists only what differs from the defaults, and on import **a field the file leaves out goes back to its default**: the file says all of a rule.
- **Matched by rule_name**: a new name creates a rule, an existing one is updated. Rules not in the file are left alone.
- **Secrets are never written**: chat webhook URLs, tokens, the PagerDuty routing key, the SMS secret, every password field. A file that holds one is refused, to keep them out of git. A generic Webhook's URL and an SMS auth header template are not secret fields: they are exported.
- **Channels keep their stored secrets.** On import a channel matches the existing row of its type with the same settings (Email recipients, ntfy server and topic, Matrix room, SMS URL and numbers…). Slack, Mattermost and PagerDuty rows have nothing but their secret to tell them apart: they match by position, and only when the file keeps as many of them. A channel that matches nothing is new: when it needs a secret it comes in disabled, to set it in the form and then enable it.
- **Nothing half-applied**: an unknown field (a typo), a value the field cannot take (a Select option it does not have, a number that is not one), a rule the form would refuse or a name used twice makes the import apply nothing, and says which rule and why.
- **Quote times**: `active_from: '22:00'`. YAML reads an unquoted `22:00` as a number, and the import refuses it.
- The evaluator's own state (last evaluation, last fired, hysteresis counters) is never exported nor imported.
