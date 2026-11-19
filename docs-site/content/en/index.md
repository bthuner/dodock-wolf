---
title: Dodock Wolf
description: Self-hosted observability and security for Frappe benches, ERPNext and Dokos sites, and their Linux hosts.
---

::u-page-hero
---
orientation: horizontal
ui:
  title: wolf-hero-title text-5xl sm:text-6xl lg:text-7xl
---
#top
:hero-background

#title
The team wakes up to an [incident timeline]{.text-primary}, not a customer email.

#description
Dodock Wolf catches 502 windows, failed nightly crons, worker crashes and suspicious logins on Frappe, ERPNext and Dokos benches. All data stays on your own Frappe site.

#links
  :::u-button
  ---
  to: /getting-started
  size: xl
  trailing-icon: i-lucide-arrow-right
  ---
  Get started
  :::

  :::u-button
  ---
  to: /getting-started/quickstart
  size: xl
  color: neutral
  variant: outline
  icon: i-lucide-timer
  ---
  Install in an afternoon
  :::

#default
  :::prose-pre
  ---
  code: |
    # On the bench: the Wolf App
    bench get-app https://github.com/bthuner/dodock-wolf
    bench --site wolf.example.com install-app dodock_wolf

    # On each host: the Wolf Agent
    curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh \
      | sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<token> bash
  filename: Terminal
  ---

  ```bash [Terminal]
  # On the bench: the Wolf App
  bench get-app https://github.com/bthuner/dodock-wolf
  bench --site wolf.example.com install-app dodock_wolf

  # On each host: the Wolf Agent
  curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh \
    | sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<token> bash
  ```
  :::
::

::u-page-section
#title
Two halves of one animal

#features
  :::u-page-feature
  ---
  icon: i-lucide-app-window
  to: /install/wolf-app
  ---
  #title
  Wolf App

  #description
  A Frappe app. It stores events, metrics, rules and incidents as DocTypes, evaluates alert rules every minute and shows the timeline at `/wolf`.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-server
  to: /install/wolf-agent
  ---
  #title
  Wolf Agent

  #description
  A Python daemon with no dependencies on each host. It tails nginx, bench and auth logs, reads `/proc`, Redis and MariaDB, and pushes batches over HTTPS.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-boxes
  to: /install/pilot
  ---
  #title
  Benches found, not configured

  #description
  Discovers benches from `bench.toml` or `sites/`. Reads Pilot benches, and turns their deploy and migrate tasks into deployment markers.
  :::
::

::u-page-section
#title
What it catches

#features
  :::u-page-feature
  ---
  icon: i-lucide-server-crash
  to: /alerts/presets
  ---
  #title
  5xx and 502 windows

  #description
  Per site and per route, from the nginx access log. Tied to the deployment that preceded them.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-alarm-clock-off
  to: /alerts/presets
  ---
  #title
  Failed crons at 2AM

  #description
  Failed scheduled jobs, a stalled scheduler, failed backups and RQ backlogs, before the morning shift.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-cpu
  to: /agent/collected
  ---
  #title
  Workers and hosts

  #description
  Worker crashes, OOM kills, processes down, CPU, memory, disk, load, TLS expiry and database replication.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-shield-alert
  to: /security
  ---
  #title
  Suspicious access

  #description
  SSH brute force, admin logins from a new IP or country, web attack scans, privileged role grants and risky Server Scripts.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-git-merge
  to: /alerts/incidents
  ---
  #title
  One incident, not fifty emails

  #description
  Events are grouped per site, bench or host. Channels hear about it when it opens, reopens and resolves.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-bell-ring
  to: /alerts/channels
  ---
  #title
  Ten channels

  #description
  Email, webhook, Raven, Slack, Mattermost, Matrix, ntfy, Gotify, SMS and PagerDuty, with signed Acknowledge / Resolve links.
  :::
::

::u-page-section
  :::u-page-c-t-a
  ---
  links:
    - label: Read the quickstart
      to: '/getting-started/quickstart'
      trailingIcon: i-lucide-arrow-right
    - label: View on GitHub
      to: 'https://github.com/bthuner/dodock-wolf'
      target: _blank
      variant: subtle
      icon: i-simple-icons-github
  title: Open formats, self-hosted storage, no usage-based pricing.
  description: Dodock Wolf is MIT-licensed and runs on the Frappe site you already operate.
  ---
  :::
::
