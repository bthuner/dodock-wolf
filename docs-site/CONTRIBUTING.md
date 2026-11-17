# Writing the Dodock Wolf docs

The site is Nuxt 4 + Nuxt UI 4 + Nuxt Content 3, the same stack as doc.dokos.io.

```bash
nvm use            # Node 24 (.nvmrc)
yarn install
yarn dev           # http://localhost:3000, French at /fr
yarn generate      # static site in .output/public
yarn check:links   # every internal link and #anchor of that build
```

## Publishing

`.github/workflows/pages.yml` publishes the site to GitHub Pages on every push to `main` that
touches `docs-site/`: <https://bthuner.github.io/dodock-wolf/>, with the making-of page at
`/making-of/`. It builds with `NUXT_APP_BASE_URL=/dodock-wolf/`, so files of `public/` referenced
from code go through `usePublicPath()` (router links get the base by themselves). To preview that
build locally:

```bash
NUXT_APP_BASE_URL=/dodock-wolf/ yarn generate
NUXT_APP_BASE_URL=/dodock-wolf/ yarn check:links
```

## Layout

```
content/
  en/                       English, served at /
    index.md                landing page
    1.getting-started/
      .navigation.yml       section title and icon
      1.index.md            → /getting-started
      2.quickstart.md       → /getting-started/quickstart
  fr/                       French, served at /fr, same file names
```

The number prefix orders pages and is dropped from the URL. Every English page has a French
twin at the same path, so the language switch lands on the same page.

## Map

| Section | Pages |
|---|---|
| `1.getting-started` | `1.index` (introduction), `2.quickstart`, `3.concepts` |
| `2.install` | `1.wolf-app`, `2.wolf-agent`, `3.every-site` (satellites), `4.press`, `5.pilot` |
| `3.agent` | `1.collected` (what is collected), `2.configuration`, `3.commands`, `4.scrubbing`, `5.watchdog`, `6.response-actions` |
| `4.alerts` | `1.rules`, `2.presets`, `3.channels`, `4.incidents`, `5.status-pages` |
| `5.security` | `1.index` (overview), `2.site-signals`, `3.detection` (web and host), `4.access` (roles, scopes, secrets), `5.journal` (tamper-evident journal, deception, IP reputation), `6.compliance` (NIS2/GDPR), `7.siem-export`, `8.wazuh-suricata` |
| `6.reference` | `1.protocol`, `2.ui-api`, `3.metric-storage`, `4.performance` (load test), `5.development` |

Link between pages with absolute paths without the number prefix and without the locale:
`/agent/configuration#tls`. In French pages, prefix with `/fr`: `/fr/agent/configuration`.
Link to repository files with `https://github.com/bthuner/dodock-wolf/blob/main/<path>`.

## Front matter

```yaml
---
title: Alert rules             # sidebar label and H1, short
description: One sentence that says what the page lets the reader do.
navigation:
  icon: i-lucide-bell          # optional, Lucide icons only
---
```

Do not repeat the title as a `#` heading: the page header renders it. Start sections at `##`.

## Components

Nuxt UI prose components, written in MDC:

````md
::note
Neutral context.
::

::tip
A shortcut or a good default.
::

::warning
Something that loses data, delays alerts, or surprises.
::

::caution
Security impact.
::

::steps{level="3"}
### Install the app
...
### Register the host
...
::

::tabs
  :::tabs-item{label="nftables"}
  ...
  :::
  :::tabs-item{label="fail2ban"}
  ...
  :::
::

::code-group
```bash [MariaDB]
...
```
```bash [Postgres]
...
```
::

::card-group
  :::card{title="Wolf Agent" icon="i-lucide-server" to="/install/wolf-agent"}
  One line.
  :::
::

::field-group
  :::field{name="push_interval" type="number"}
  Seconds between pushes. Default `30`.
  :::
::

::collapsible
Long detail the reader rarely needs.
::
````

Wolf UI screenshots (light and dark, from `docs/screenshots`) follow the reader's colour mode:
`:screenshot{name="overview" alt="The Wolf UI overview"}`. Names: `overview`, `incident`,
`incident-resolved`, `metrics`, `monitoring`, `security`.

Code blocks take a file name: ` ```json [config.json] `.

## Voice

From `docs/making-of/brand.md`:

1. State, don't dramatise. Numbers over adjectives: "count ≥ 10 in 5 min", not "many errors".
2. Lead with scope: site, then bench, then host.
3. One wolf metaphor per page at most. The product is a tool.
4. Names: *Dodock Wolf* (the product), *Wolf Agent* (the host daemon), *Wolf App* (the Frappe
   app). DocTypes keep their technical names (**Wolf Alert Rule**).
5. Short sentences. Tables for settings and fields. Settings paths in bold:
   **Wolf Settings → Retention**.
6. Only what the code and the repository docs say. Anything planned is marked as planned.

French pages use "vous", French typography (espace insécable avant `: ; ? !`, guillemets
« »), and keep code, setting keys, DocType names, event types and CLI output in English.
