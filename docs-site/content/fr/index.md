---
title: Frappe Wolf
description: Observabilité et sécurité auto-hébergées pour les benches Frappe, les sites ERPNext et Dokos, et leurs hôtes Linux.
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
L'équipe se réveille avec une [chronologie d'incident]{.text-primary}, pas avec l'e-mail d'un client.

#description
Frappe Wolf repère les fenêtres de 502, les crons nocturnes en échec, les plantages de workers et les connexions suspectes sur les benches Frappe, ERPNext et Dokos. Toutes les données restent sur votre propre site Frappe.

#links
  :::u-button
  ---
  to: /fr/getting-started
  size: xl
  trailing-icon: i-lucide-arrow-right
  ---
  Bien démarrer
  :::

  :::u-button
  ---
  to: /fr/getting-started/quickstart
  size: xl
  color: neutral
  variant: outline
  icon: i-lucide-timer
  ---
  Installer en un après-midi
  :::

#default
  :::prose-pre
  ---
  code: |
    # On the bench: the Wolf App
    bench get-app https://github.com/bthuner/dodock-wolf
    bench --site wolf.example.com install-app frappe_wolf

    # On each host: the Wolf Agent
    curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh \
      | sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<token> bash
  filename: Terminal
  ---

  ```bash [Terminal]
  # On the bench: the Wolf App
  bench get-app https://github.com/bthuner/dodock-wolf
  bench --site wolf.example.com install-app frappe_wolf

  # On each host: the Wolf Agent
  curl -fsSL https://raw.githubusercontent.com/bthuner/dodock-wolf/main/agent/install.sh \
    | sudo WOLF_URL=https://wolf.example.com WOLF_TOKEN=<token> bash
  ```
  :::
::

::u-page-section
#title
Deux moitiés d'un même animal

#features
  :::u-page-feature
  ---
  icon: i-lucide-app-window
  to: /fr/install/wolf-app
  ---
  #title
  Wolf App

  #description
  Une application Frappe. Elle stocke les événements, les métriques, les règles et les incidents sous forme de DocTypes, évalue les règles d'alerte chaque minute et affiche la chronologie sur `/wolf`.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-server
  to: /fr/install/wolf-agent
  ---
  #title
  Wolf Agent

  #description
  Un démon Python sans aucune dépendance, sur chaque hôte. Il suit les logs nginx, bench et d'authentification, lit `/proc`, Redis et MariaDB, et envoie des lots en HTTPS.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-boxes
  to: /fr/install/pilot
  ---
  #title
  Des benches trouvés, pas configurés

  #description
  Découvre les benches à partir de `bench.toml` ou de `sites/`. Lit les arborescences Press et Pilot, et transforme leurs tâches de déploiement et de migration en marqueurs de déploiement.
  :::
::

::u-page-section
#title
Ce qu'il repère

#features
  :::u-page-feature
  ---
  icon: i-lucide-server-crash
  to: /fr/alerts/presets
  ---
  #title
  Fenêtres de 5xx et de 502

  #description
  Par site et par route, à partir du log d'accès nginx. Rattachées au déploiement qui les a précédées.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-alarm-clock-off
  to: /fr/alerts/presets
  ---
  #title
  Crons en échec à 2 h du matin

  #description
  Tâches planifiées en échec, planificateur bloqué, sauvegardes en échec et files d'attente RQ engorgées, avant l'équipe du matin.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-cpu
  to: /fr/agent/collected
  ---
  #title
  Workers et hôtes

  #description
  Plantages de workers, processus tués par l'OOM killer, processus arrêtés, CPU, mémoire, disque, charge, expiration TLS et réplication de la base de données.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-shield-alert
  to: /fr/security
  ---
  #title
  Accès suspects

  #description
  Force brute SSH, connexions admin depuis une nouvelle IP ou un nouveau pays, scans d'attaque web, attributions de rôles privilégiés et Server Scripts à risque.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-git-merge
  to: /fr/alerts/incidents
  ---
  #title
  Un incident, pas cinquante e-mails

  #description
  Les événements sont regroupés par site, bench ou hôte. Les canaux sont prévenus à l'ouverture, à la réouverture et à la résolution.
  :::

  :::u-page-feature
  ---
  icon: i-lucide-bell-ring
  to: /fr/alerts/channels
  ---
  #title
  Dix canaux

  #description
  E-mail, webhook, Raven, Slack, Mattermost, Matrix, ntfy, Gotify, SMS et PagerDuty, avec des liens signés Acknowledge / Resolve.
  :::
::

::u-page-section
  :::u-page-c-t-a
  ---
  links:
    - label: Lire le démarrage rapide
      to: '/fr/getting-started/quickstart'
      trailingIcon: i-lucide-arrow-right
    - label: Voir sur GitHub
      to: 'https://github.com/bthuner/dodock-wolf'
      target: _blank
      variant: subtle
      icon: i-simple-icons-github
  title: Formats ouverts, stockage auto-hébergé, aucune tarification à l'usage.
  description: Frappe Wolf est sous licence MIT et tourne sur le site Frappe que vous exploitez déjà.
  ---
  :::
::
