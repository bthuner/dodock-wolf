Dodock Wolf Observability — MVP
One-line summary

First-class observability for Frappe benches, ERPNext sites, Linux hosts, and internal services — owned by Dokos, not Datadog.
Vision

Give Dokos and self-hosted Frappe operators a unified, privacy-first observability plane that:

    Treats Frappe, ERPNext, Pilot benches, Linux, and internal services as first-class citizens.

    Surfaces 5xx/502 windows, cron/scheduler failures, and security anomalies before customers notice.

    Stays vendor-free by using open standards (OpenTelemetry, syslog, JSON logs) and self-hosted storage.

    Is simple enough to adopt in one afternoon on a new Dokos stack.

MVP goals

    Detect and alert on:

        HTTP 5xx/502 spikes per site and per bench.

        Failed scheduler/cron jobs (including overnight jobs like 2AM tasks).

        Worker crashes and queue backlogs.

        Suspicious access patterns (multiple failed logins, admin login from unusual IP, unexpected new users with high roles).

    Provide a single UI inside Frappe ("Dodock Wolf") that shows:

        Timeline of incidents for a given site/bench.

        Error snapshots with context (route, user, traceback, deployment window).

        Host metrics for core resources (CPU, RAM, disk, load) with simple thresholds.

    Keep configuration dead-simple:

        YAML or DocType-driven alert rules ("when X > Y for Z minutes, send alert").

        Sensible presets for Dokos (e.g., 502 spike after deployment; cron failures between 1–4AM).

        One command to install the agent on a host and register it with a Wolf site.

Non-goals (MVP)

    Full Datadog replacement across all products.

    LLM observability, data observability, or complex SLO dashboards.

    Deep UX analytics or RUM.

The MVP focuses on:

    Operational safety for Dokos/Frappe: errors, cron, workers, hosts.

    Basic security signals.

Architecture sketch
Components

    Dodock Wolf App (server-side):

        Frappe app installed on Dokos/Frappe sites.

        Stores events, metrics, alerts, configurations in DocTypes.

        Exposes APIs for agents to send telemetry.

        Provides UI for timelines, dashboards, and alert configuration.

    Wolf Agent (host-side):

        Lightweight daemon (Rust or Python) running on Linux hosts.

        Collects:

            System metrics (CPU, RAM, disk, load).

            Logs from:

                Frappe bench logs (bench.log, worker.log, scheduler.log, frappe.web.log).

                Nginx/access logs for 5xx/502.

                System logs (journalctl, /var/log/auth.log) for security signals.

            Optional OpenTelemetry traces from Frappe apps.

        Ships normalized events/metrics to the Wolf App over HTTPS.

    Pilot integration:

        Use bench.toml and Pilot Admin API to auto-discover benches, sites, processes, and log paths.

        Attach Wolf configuration to benches in Pilot ("enable Wolf for this bench" toggle).

Data model (DocTypes)

    Wolf Event:

        type: error, cron_failure, worker_failure, security, host_metric_alert.

        site, bench, host.

        timestamp.

        severity: info, warning, critical.

        payload (JSON with details).

    Wolf Metric Sample:

        host, site, bench.

        metric_name (e.g., cpu_usage, load_1m, disk_used_percent).

        value.

        timestamp.

    Wolf Alert Rule:

        name, enabled.

        signal_type: metric, event.

        query / filter DSL (site, bench, host, type).

        condition (e.g., value > 0 for 5 minutes, count >= 5 in 10 minutes).

        channels: email, webhook, Raven channel, etc.

    Wolf Incident:

        Aggregation of events that share a root cause.

        status: open, acknowledged, resolved.

        Links to deployments (manual or Pilot events).

Key flows
1. Deployment → 502 → cron failure at 2AM

    Admin runs deployment on a Dokos/Pilot bench.

    Pilot exposes task logs and status.

    Nginx starts returning 502 for some routes; nginx/access.log and frappe.web.log capture 502s.

    Nightly cron at 2AM fails due to migration issue; scheduler.log and Frappe Error Log show the stack trace.

    Wolf Agent:

        Tails nginx and Frappe logs, counts 502 and 5xx responses per site/route.

        Parses scheduler logs for failed jobs.

        Sends events to Wolf App.

    Wolf App:

        Groups events into an Incident.

        Fires alerts via email/Raven if 502s exceed threshold or cron failures occur.

The team wakes up with a clear incident timeline, not a surprise email from the customer at 9AM.
2. Security: suspicious access

    Linux host logs multiple failed SSH logins, or auth.log shows brute-force attempts.

    Frappe site logs repeated failed logins or an admin login from a new country/IP.

    Wolf Agent ships security events to Wolf App.

    Wolf App raises a security alert and shows correlation with infrastructure metrics.

Technical feasibility notes
Frappe side

    Frappe already has:

        Error Snapshots for 500+ responses.

        Desk logs (Error Log, Activity Log).

        Bench/server logs (bench.log, scheduler.log, worker.log, frappe.web.log).

        Configurable logging via enable_frappe_logger and site-level logs.

    Wolf App can:

        Reuse frappe.log_error() to create structured events when app code detects anomalies.

        Add server scripts or hooks to emit events on key operations (deployments, migrations, scheduler failures).

        Define DocTypes for Wolf Event, Metric Sample, Alert Rule, Incident.

[Logging docs reference: Frappe logging separates Desk logs (Error Log, etc.) from server logs at bench/site level, including bench.log, scheduler.log, and worker.log.]
Pilot integration

    Pilot already exposes:

        Admin UI and Admin API for benches, sites, processes, logs, tasks, database tools, updates, and settings.

        bench.toml as the source of truth for apps, database, Redis, workers, nginx, S3, and monitoring settings.

    Wolf can:

        Read bench.toml to discover log paths and process definitions.

        Use Pilot’s Admin API for status (e.g., deployment tasks) and annotate incidents.

Press / Frappe Cloud alignment

    Press implements full-service cloud hosting for the Frappe stack, with dashboards for apps, servers, sites, billing, backups, and updates.

    Long term, Wolf should be compatible with Press deployments, but the MVP can start with Dokos-managed benches and vanilla Pilot setups.

Agent feasibility (Rust vs Python)

    Rust:

        Pros: low overhead, safe concurrency, good for long-running daemon, native system metrics.

        Cons: slower iteration for Frappe devs, fewer contributors comfortable with Rust.

    Python:

        Pros: matches Frappe ecosystem, easier contribution and packaging, reuses existing libraries.

        Cons: slightly higher resource cost; needs care for async IO when tailing logs.

MVP recommendation: start with Python agent (fastest path for Dokos and Frappe contributors), keep protocol and packaging generic enough to allow a Rust agent later.
Inspiration from SigNoz & Datadog

    SigNoz:

        Unified observability with logs, metrics, traces, and exceptions in one platform.

        OpenTelemetry-native instrumentation; ClickHouse-backed storage for fast queries and cost-effective retention.

        Alerting on any telemetry signal with anomaly detection and Apdex-based detection.

    Datadog:

        Deep correlations between metrics, logs, traces, security events, and jobs, with ML-powered anomaly detection.

        Observability Pipelines for in-flight filtering, sampling, and routing of logs, metrics, traces.

        Rich alerting and incident views for job failures, long-running tasks, and data observability.

Wolf MVP will not copy all features but will:

    Correlate Frappe app logs, bench/server logs, and host metrics in one Frappe-native UI.

    Provide simple alerting rules inspired by SigNoz/Datadog, but tailored to Frappe and Dokos.

    Keep data in Dokos-controlled storage and avoid opaque usage-based pricing.

MVP backlog (high-level)

    Dodock Wolf App

        Define DocTypes: Wolf Event, Wolf Metric Sample, Wolf Alert Rule, Wolf Incident.

        Build basic UI: list views, incident timeline, per-site/bench overview.

        Implement alert delivery: email + Raven channel webhook.

    Wolf Agent (Python)

        CLI to register agent with Wolf site (API key/secret).

        Collect host metrics (CPU, RAM, disk, load) using standard libraries.

        Tail key logs and parse events:

            nginx/access logs for 5xx/502.

            frappe.web.log.

            scheduler.log, worker.log, bench.log.

            /var/log/auth.log and/or journalctl for security.

        Send batched telemetry to Wolf App periodically.

    Pilot integration

        Read bench.toml to auto-configure log paths.

        Optional: small Pilot plugin or config section to enable Wolf.

    Preset alert rules for Dokos

        502 spike after deployment window.

        Cron/scheduler failure between 01:00–04:00.

        Worker queue length above threshold.

        Multiple failed logins or admin login from new IP.

First demo scenario

    Single Dokos bench with ERPNext and a few sites.

    Install Wolf App on one site.

    Deploy Python agent on the host.

    Trigger:

        Simulated deployment + nginx reload causing a short 502 window.

        A failing cron job at 2AM.

    Show:

        Incident timeline in Wolf.

        Alerts emitted to email/Raven.

Product direction (since 19 November 2026, issue #136)

    The MVP brief above predates Frappe Cloud v2, which has its own telemetry (frappe/datum), control plane (frappe/central), and incidents, SLOs, paging and status page (frappe/beacon). Dokos does not pursue features that overlap Frappe's. So:

    - New work goes to the security and compliance of the bench:
      - Frappe-level signals: permissions, Server Scripts, settings, exports, API keys, logins, honeytokens, the security score;
      - host and web security: SSH/auth, nginx attacks, file integrity, outbound connections;
      - response actions;
      - evidence: the journal, NIS2/DORA/GDPR, SIEM export;
      - the agent that collects them.

      The rule and incident engine and the channels are extended only where security needs it.
    - Release v0.1.0 (a GitHub tag, GitHub only) keeps the whole tool as it was for legacy Press customers and self-hosted operators; it gets security fixes only. Dokos moves its hosted customers to its own Frappe Cloud v2 tenant (dokopilot guests, which keep Pilot's layout: Wolf's Pilot support stays).
    - Removed from main in 0.2 (kept in v0.1.0): the Press v1 integration, the observability demos, public status pages, the metrics explorer, digests, host resource metrics (CPU, memory, swap, disk, load).
    - Frozen, kept as it is until a later step recentres it on what security reads (`catalog.SECURITY_METRICS` names those metrics; the others are operations metrics): dashboards, service metric collectors and their presets, escalation. Fix bugs and security issues, keep the translations and Frappe/Dokos compatibility, but add no features.
    - Not pursued (overlaps Frappe): SLOs and error budgets, status-page uptime bars, subscriptions, unlisted incidents and maintenance announcements, on-call rotations and phone paging, traces, log search.
    - Interoperability over rebuilding: connect to Wazuh, Suricata, CrowdSec, SIEMs, PagerDuty, and Frappe's tools as they open up (a Beacon channel, a Datum sink, Frappe Cloud v2 hosts as Pilot hosts: #133, #134, #135).

    When a request falls in the frozen or not-pursued lists, say so and point to #136 before building it.

Documentation site

    The user documentation lives in docs-site/ (Nuxt UI + Nuxt Content, the same stack as doc.dokos.io), in two languages: content/en/ and content/fr/, with the same file at the same path in both. docs-site/CONTRIBUTING.md has the page map and conventions, docs-site/scripts/TRANSLATING.md the French glossary and typography.

    When a change affects what users see or do, update the docs in the same pull request, in English and in French. This covers a setting, field, command, config key, event type, metric, preset, API, channel, default value, behaviour or install step that is added, renamed, changed or removed. Purely internal changes (refactors, tests, CI) need no docs.

    - Edit the English page, then mirror the change in its French twin. Never leave one language behind.
    - A new page gets a twin with the same file name in the other language.
    - When presets change in dodock_wolf/wolf/presets.py, run `yarn presets` in docs-site/ and paste the tables into both content/en/4.alerts/2.presets.md and content/fr/4.alerts/2.presets.md (translating the conditions).
    - Keep the repository docs (README.md, agent/README.md, docs/*.md) consistent with the site when they cover the same thing.
    - Check with `yarn generate && yarn check:links` in docs-site/ (Node 24, see .nvmrc). The docs CI job runs the same checks, so a broken page or link fails the PR.

App translations

    The app's own strings (Desk, the Wolf UI, the rule sentence, server messages) are translated in dodock_wolf/locale/: main.pot is the template, one <lang>.po per available language (French today). Keep every available language complete in the same pull request as the change, as for the docs. docs-site/scripts/TRANSLATING.md ("Translating the app") has the steps and the rules.

    - Write user-visible text translatable: `_("…")` in Python, `__("…")` in Desk JS and in the Wolf UI (`import { __ } from '@/services/i18n'`). The first argument is a literal, and the whole call stays on one line (Frappe's extractor reads one line; a context is the third argument, never a nested `__()`); whole sentences with `{0}` placeholders, never pieces glued together; separate singular and plural strings. In the Wolf UI never call `__()` at module load: translate at render time.
    - A status shown from a Select field is translated with its DocType as context: `__(status, null, 'Wolf Incident')`, `_(status, context="Wolf Incident")`.
    - In the pure modules (dodock_wolf/wolf/), import `_`, `fmt`, `N_` and `translate` from wolf/i18n.py. `fmt(_("{0} of {1}"), a, b)`, never `.format()` on a translation. A table built when the module loads marks its literals with `N_()` and is translated with `translate()` where it is shown; `translate(value, "Wolf Incident")` for a status in a variable. Never `_(variable)`: the extractor would put its name in the catalog.
    - Translate server text when it is shown, never in what is stored (titles, comments, journal, payloads) or in the cache every reader shares (wolf/read_cache.py). A function that serves both takes `translate=False` and stays English by default.
    - When a change adds, changes or removes strings, on a bench: `bench generate-pot-file --app dodock_wolf`, then `python3 ci/locale_contexts.py`, then `bench update-po-files --app dodock_wolf --locale <lang>` for each language. Reset the files' header (the tool writes `app_email` into it) and translate every new or changed entry with the glossary. An empty msgstr shows Frappe's own translation when it has one, not the English.
    - Never give a plain entry a translation that differs from Frappe's own for the same string: Frappe merges every app's translations, so it would replace Frappe's wording across Desk. Leave it empty, or use a context entry (`LABELS` in ci/locale_contexts.py).
    - A new Select option that is a word for people gets its translation in `TRANSLATED` (ci/locale_contexts.py); a code value stays pinned to the English.
    - Check with `python3 -m unittest tests.test_locale` (every template string present, placeholders, tags and code kept, every Select option with its own entry).
    - A new language: add `<lang>.po` (`bench create-po-file`), its `TRANSLATED` and `LABELS` entries, and its docs (docs-site/content/<lang>/).

Repositories: GitHub and GitLab

    The repository lives on GitHub (github.com/bthuner/dodock-wolf) and on GitLab (gitlab.com/dokos/dodock-wolf). For now GitHub is where pull requests are reviewed and merged; GitLab follows. Never merge on GitLab: main would diverge.

    - Push every branch to both. `origin` fetches from GitHub and pushes to both (`git remote set-url --add --push origin …` for each); a clone without that setup pushes with `git push origin <branch> && git push gitlab <branch>`.
    - After a pull request is merged on GitHub, bring GitLab's main up to it: `git fetch origin && git push gitlab origin/main:refs/heads/main`. Check that both mains name the same commit (`git ls-remote origin main; git ls-remote gitlab main`).
    - Both sides have the same CI: .github/workflows/ci.yml and .gitlab-ci.yml. A job added or changed on one side is added or changed on the other in the same pull request.
    - GitHub's CI is the one a merge waits for. GitLab's runs only when the user asks for it (`glab ci run -b <branch> -R dokos/dodock-wolf`, or "Run pipeline"): a push starts nothing there, so never wait on GitLab before merging.
    - Issues and pull requests stay on GitHub; GitLab holds the imported history.

Commit and PR attribution

    Every commit message, pull request description, issue body, and issue, pull request or review comment ends with the single line "Co-authored with AI".

    Never add "Co-Authored-By: Claude", "Claude-Session" links, "Generated with Claude Code" or "Generated by Claude Code" footers, or any other Claude/Anthropic mention, to commits, PRs, issues, comments, reviews or files in this repository. Tools may append such a footer when posting: read the post back and edit it out.

    Commits are authored and committed as Théo Hunerblaes <theohunerblaes@me.com>, never as Claude <noreply@anthropic.com>. If `git config user.email` says noreply@anthropic.com (Claude Code cloud containers set it so), run these in the repository before the first commit:

        git config user.name "Théo Hunerblaes"
        git config user.email "theohunerblaes@me.com"
        git config commit.gpgsign false

    Signing stays off there: the container's key signs as Claude, so GitHub would mark the commits "Unverified".

    A merge commit is titled "Merge pull request #N: <PR title>", so it never names a claude/… branch.
