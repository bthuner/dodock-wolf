# Channels

> Send alerts to email, chat, push, SMS or PagerDuty, and set up each destination.

Each row of a rule's **Channels** (or **Escalation Channels**) table is one destination. Secrets
(tokens, keys, webhook URLs) are Password fields: stored encrypted, never logged, and scrubbed from
every recorded error.

**Send test notification** on the rule form sends a TEST to every enabled row and shows what each
one answered.

## Types

<table>
<thead>
  <tr>
    <th>
      Type
    </th>
    
    <th>
      Sends
    </th>
    
    <th>
      Settings
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Email
    </td>
    
    <td>
      one email per recipient, with signed Acknowledge / Resolve links
    </td>
    
    <td>
      Recipients
    </td>
  </tr>
  
  <tr>
    <td>
      Webhook
    </td>
    
    <td>
      generic JSON <code>
        {text, incident}
      </code>
      
       (<a href="/reference/protocol">
        protocol
      </a>
      
      )
    </td>
    
    <td>
      Webhook URL
    </td>
  </tr>
  
  <tr>
    <td>
      Raven
    </td>
    
    <td>
      a message in a Raven channel
    </td>
    
    <td>
      Raven Channel
    </td>
  </tr>
  
  <tr>
    <td>
      Slack
    </td>
    
    <td>
      Block Kit message with a severity colour bar and Open / Acknowledge / Resolve buttons
    </td>
    
    <td>
      Incoming Webhook URL*
    </td>
  </tr>
  
  <tr>
    <td>
      Mattermost
    </td>
    
    <td>
      message attachment with colour, fields and Acknowledge / Resolve links
    </td>
    
    <td>
      Incoming Webhook URL*
    </td>
  </tr>
  
  <tr>
    <td>
      Matrix
    </td>
    
    <td>
      <code>
        m.room.message
      </code>
      
       with an HTML body
    </td>
    
    <td>
      Homeserver URL, Room ID, Access Token*
    </td>
  </tr>
  
  <tr>
    <td>
      ntfy
    </td>
    
    <td>
      push with title, priority, tags, click and action buttons
    </td>
    
    <td>
      Server URL (default ntfy.sh), Topic, Access Token* (optional)
    </td>
  </tr>
  
  <tr>
    <td>
      Gotify
    </td>
    
    <td>
      push with priority mapped from severity and a click URL
    </td>
    
    <td>
      Server URL, Application Token*
    </td>
  </tr>
  
  <tr>
    <td>
      SMS
    </td>
    
    <td>
      short text (one or two SMS) through any HTTP gateway
    </td>
    
    <td>
      Phone Numbers, Gateway URL template, Method, Body, Auth Header, Secret*, Max Length
    </td>
  </tr>
  
  <tr>
    <td>
      PagerDuty
    </td>
    
    <td>
      Events API v2: trigger, acknowledge, resolve; <code>
        dedup_key
      </code>
      
       = incident name
    </td>
    
    <td>
      Routing Key*, Events API URL
    </td>
  </tr>
</tbody>
</table>

* Password field: stored encrypted, shown as asterisks.

## Who hears what

- Opened and reopened incidents go to the **Channels**; escalations to the **Escalation Channels**.
- When someone acknowledges or resolves an incident (Desk or a signed link), **PagerDuty** channels
always get the matching `acknowledge` / `resolve` event, so the alert closes on call too.
- The other channels hear a resolution only when the rule has **Notify On Resolve**.
- A test from the rule form triggers then resolves on PagerDuty, so it never leaves an alert open.
- During a [maintenance window](/alerts/rules#maintenance-windows), notifications wait until it ends.

## Signed action links

Alerts for unresolved incidents carry signed **Acknowledge** / **Resolve** links, valid 24 h
(**Wolf Settings → Action Link Hours**). Opening a link shows a confirmation page; only its button
acts, so mail scanners cannot acknowledge for you. Security incidents also carry a link per
[response action](/agent/response-actions) Wolf proposes; those ask for a Wolf Manager's login.

## Delivery status

Every attempt is recorded as a **Wolf Delivery**: channel, target without secrets, kind, PagerDuty
action, ok or error, HTTP status. The incident lists them under **Deliveries**. Deliveries follow
the event retention.

## Upgrading from 0.1

Digests were removed in 0.2: every channel sends each alert at once. A channel that used hourly
digests in 0.1 now gets every alert as it happens. Digests still pending at the upgrade are
dropped, not sent: the upgrade prints how many and records the count in an **Error Log** titled
*Dodock Wolf 0.2: pending digests dropped*. Release [v0.1.0](/getting-started#staying-on-v010)
keeps digests.

## Setup per type

<collapsible name="Slack">

Create an app → **Incoming Webhooks** → **Add New Webhook to Workspace**, and paste the
`https://hooks.slack.com/services/…` URL. Buttons open the incident or the signed action page, so no
Slack interactivity endpoint is needed. Slack may show a warning icon on link buttons of apps
without one.

</collapsible>

<collapsible name="Mattermost">

**Integrations → Incoming Webhooks → Add**, and paste the `https://…/hooks/…` URL.

</collapsible>

<collapsible name="Matrix">

Create a bot account, invite it to the room and join. Get its access token (Element: **Settings →
Help & About → Access Token**, or `POST /_matrix/client/v3/login`). The Room ID is the internal
`!…:server` one (**Room settings → Advanced**), not an alias. Messages are sent with
`PUT /_matrix/client/v3/rooms/{room}/send/…`.

</collapsible>

<collapsible name="ntfy">

Any topic on ntfy.sh or your own server. On a public server, pick an unguessable topic, or protect it
and paste an access token (`tk_…`). Priority: critical 5, warning 4, info 3, resolved 2; escalations
one step higher.

</collapsible>

<collapsible name="Gotify">

**Apps → Create application**, and paste its token. Priority: critical 8, warning 5, info 3,
resolved 2; escalations two steps higher.

</collapsible>

<collapsible name="SMS">

Provider agnostic. The Gateway URL and the optional Body Template take `{to}`, `{text}` and
`{secret}` placeholders: URL-encoded in the URL and form bodies, JSON-escaped in JSON bodies. The Auth
Header is a header line such as `Authorization: Bearer {secret}`. Put API keys in **Secret**, never
in the URL. One request per phone number.

The text (kind, severity, title, scope, and the incident URL when it fits) is folded to the GSM-7
alphabet and cut on a word boundary to 160 characters (one SMS) or 306 (two). Text that needs
Unicode fits 70 / 134.

```text [A gateway that takes JSON]
Gateway URL:   https://sms.example.com/api/send
Method / Body: POST, json, {"to": "{to}", "message": "{text}"}
Auth Header:   Authorization: Bearer {secret}
```

</collapsible>

<collapsible name="PagerDuty">

Add an **Events API v2** integration to a service and paste its integration key as the Routing Key.
Change the Events API URL for the EU region (`https://events.eu.pagerduty.com/v2/enqueue`), or for an
Events-v2 compatible receiver: Grafana OnCall, Opsgenie and others accept the same body.

</collapsible>
