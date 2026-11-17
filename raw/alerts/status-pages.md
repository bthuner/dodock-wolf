# Status pages

> Publish a public status page for a site, with no internal detail.

A **Wolf Status Page** shows a site's health to guests at `/wolf-status/<slug>`. It is opt-in.

## Create one

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
        Title
      </strong>
    </td>
    
    <td>
      Shown at the top of the page.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Slug
      </strong>
    </td>
    
    <td>
      The address: <code>
        https://wolf.example.com/wolf-status/<slug>
      </code>
      
      .
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Site
      </strong>
    </td>
    
    <td>
      The site whose incidents are shown.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Bench
      </strong>
    </td>
    
    <td>
      Optional: also show the bench's incidents.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Description
      </strong>
    </td>
    
    <td>
      Optional text under the title.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Show History Days
      </strong>
    </td>
    
    <td>
      How far back resolved incidents are listed.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Minimum Severity
      </strong>
    </td>
    
    <td>
      Incidents below it are not shown.
    </td>
  </tr>
  
  <tr>
    <td>
      <strong>
        Enabled
      </strong>
    </td>
    
    <td>
      Until it is ticked, the address answers 404.
    </td>
  </tr>
</tbody>
</table>

## What guests see

- An overall banner.
- Open incidents, and those resolved in the last *Show History Days*.
- For each: a title, the severity, a public status (*Investigating*, *Identified*, *Resolved*) and
the times.

Hosts, rules, summaries and payloads never leave the server.

<caution>

Internal titles often name hosts. An incident is shown as "Degraded performance" or "Service
disruption" unless you fill its **Public Title**.

</caution>
