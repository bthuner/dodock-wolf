# Wolf UI screenshots

Taken on 2026-11-17 (Overview and Operations on 2026-11-19) from the production build of the
Wolf UI, with no bench behind it: `frontend/scripts/screenshots.mjs` serves the build as the browser tests do and answers the
Wolf API in the page. The data follows the demo scenario
([`dev/demo`](../../dev/demo/README.md)): one deployment, 60 s of backend downtime (180
responses 502), and a scheduled job failing at night. The numbers are written in the script,
not measured on a site: the pictures show the views, not a bench. Chromium at 1440 × 900,
light and dark themes as the system asks.

```bash
cd frontend
yarn build && node e2e/server.mjs &
node scripts/screenshots.mjs          # or one view: node scripts/screenshots.mjs security
```

| View | Light | Dark |
|---|---|---|
| Overview, the home page: the site's security score, no security incident, the journal signing, the agent | [light](overview-light.jpg) | [dark](overview-dark.jpg) |
| Operations, last hour: exact counts, the 502 window after the deployment | [light](operations-light.jpg) | [dark](operations-dark.jpg) |
| Incident "502 spike after deployment", open: the preceding change, evidence and context apart | [light](incident-light.jpg) | [dark](incident-dark.jpg) |
| Incident "Nightly cron failure", owner set, acknowledged, commented and resolved | [light](incident-resolved-light.jpg) | [dark](incident-resolved-dark.jpg) |
| Monitoring: rules, scheduler pace, queue, rollups, agent | [light](monitoring-light.jpg) | [dark](monitoring-dark.jpg) |
| Security: the score and the weight of every check, unknown checks shown as unknown, the journal verified | [light](security-light.jpg) | [dark](security-dark.jpg) |

With no socket.io server behind the build, the views that update live say **Checks every
60 s**. On a bench whose socket.io server accepts them, they say **Live**.
