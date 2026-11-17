# Scrubbing

> How the agent removes personal data and secrets from events before they leave the host.

Before an event is spooled or sent, the agent scrubs its title and every string in its payload:
sample lines, tracebacks, messages, routes. It is on by default.

<table>
<thead>
  <tr>
    <th>
      What
    </th>
    
    <th>
      Becomes
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      e-mail addresses, also URL-encoded (<code>
        jane%40example.com
      </code>
      
      )
    </td>
    
    <td>
      <code>
        [EMAIL]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        Authorization:
      </code>
      
       / <code>
        Proxy-Authorization:
      </code>
      
       header values, <code>
        Cookie:
      </code>
      
       / <code>
        Set-Cookie:
      </code>
      
       values
    </td>
    
    <td>
      <code>
        [REDACTED]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        Bearer …
      </code>
      
      , <code>
        token <key>:<secret>
      </code>
      
      , <code>
        Basic …
      </code>
      
       credentials
    </td>
    
    <td>
      <code>
        [REDACTED]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      JWTs (<code>
        eyJ….….…
      </code>
      
      )
    </td>
    
    <td>
      <code>
        [JWT]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      values of <code>
        password
      </code>
      
      , <code>
        pwd
      </code>
      
      , <code>
        new_password
      </code>
      
      , <code>
        *_secret
      </code>
      
      , <code>
        *_token
      </code>
      
      , <code>
        api_key
      </code>
      
      , <code>
        sid
      </code>
      
      , <code>
        session_id
      </code>
      
      , <code>
        otp
      </code>
      
      , <code>
        signature
      </code>
      
      , in query strings, forms, JSON or Python dict reprs
    </td>
    
    <td>
      <code>
        [REDACTED]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      card-like numbers (13–19 digits, Luhn-valid, issuer digit 2–6)
    </td>
    
    <td>
      <code>
        [CARD]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      IBAN-like strings (mod-97 checked)
    </td>
    
    <td>
      <code>
        [IBAN]
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      IP addresses, only with <code>
        "ips": true
      </code>
    </td>
    
    <td>
      <code>
        [IP:<8 hex>]
      </code>
      
      , a keyed hash, stable per agent
    </td>
  </tr>
</tbody>
</table>

## IP addresses

IPs are kept by default, because the SSH brute-force and "admin login from a new IP" rules are built
on them. Turn `ips` on if addresses count as personal data for you and you can live without per-IP
grouping in titles.

## What never changes

Type, host, bench, site, timestamp and fingerprint. Fingerprints are computed from the raw lines
before scrubbing, so grouping and deduplication on the Wolf site work the same either way.

Metrics carry no free text and are not scrubbed. Text you type yourself
(`mark-deployment --note`) is sent as is.

## Settings

```json [/etc/wolf-agent/config.json]
"scrub": {
  "enabled": true,
  "ips": false,
  "extra_patterns": [
    "internal-\\d{4}",
    {"pattern": "CUST-\\d{6}", "replacement": "[CUSTOMER]"}
  ],
  "keep": ["@dokos.io", "noreply@example.com"]
}
```

<field-group>
<field name="extra_patterns" type="array">

More regexes: a string (replaced by `[REDACTED]`) or `{"pattern", "replacement"}`. Invalid ones
are logged and skipped.

</field>

<field name="keep" type="array">

Values never replaced: exact strings (case-insensitive), or `@domain` to keep every address at that
domain, such as your own system mails.

</field>

<field name="enabled" type="boolean">

`"scrub": false` or `"enabled": false` ships the lines as they are.

</field>
</field-group>

Run `wolf-agent check` to see exactly what would be sent.
