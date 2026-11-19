// The pictures of docs/screenshots, with no bench: the production build served by
// e2e/server.mjs, the Wolf API mocked in the page (e2e/api.js) with the demo scenario's story
// (dev/demo/scenario.py): one deployment, 60 s of 502, a scheduled job failing at night.
// The numbers are written here, not measured: the pictures show the views, not a site.
//
//   yarn build && node e2e/server.mjs &
//   node scripts/screenshots.mjs [view]
//
// Chromium at 1440 × 900, light and dark. WOLF_CHROMIUM points at a preinstalled Chromium.
import { chromium } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { BOOT, INCIDENT, fixtures, mockApi } from '../e2e/api.js'

const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/screenshots')
const origin = `http://127.0.0.1:${process.env.WOLF_E2E_PORT || 4183}`
const only = process.argv[2]

const NOW = Date.now()
const at = (m) => new Date(NOW - m * 60000).toISOString()
const SITE = 'wolf.localhost'
const SCOPE = { site: SITE, bench: 'frappe-bench', host: 'demo-host' }
const DEPLOY = 22 // minutes ago; the 502 window follows it

// one bucket per minute over the last hour: quiet traffic, then 180 responses 502 in a minute
const minutes = Array.from({ length: 58 }, (_, i) => 59 - i)
const down = (m) => m === DEPLOY - 1 || m === DEPLOY - 2
const http = (pick) => minutes.map((m) => [at(m), pick(m)])
const HTTP = {
  window: { since: at(60), until: at(0) }, bucket_seconds: 60, resolution: 'raw',
  deployments: [{ name: 'E0', at: at(DEPLOY), title: `Deployment on ${SITE}: bench update (demo)`, ...SCOPE }],
  series: {
    http_requests: http((m) => (down(m) ? 96 : 6 + ((m * 7) % 5))),
    http_5xx: http((m) => (down(m) ? 90 : 0)),
    http_502: http((m) => (down(m) ? 90 : 0)),
  },
  has_data: { http_requests: true, http_5xx: true, http_502: true },
}  // prettier-ignore

const incident = (name, title, severity, started, more = {}) => ({
  name, title, status: 'Open', severity, ...SCOPE, started_at: at(started), resolved_at: null, merged_into: null, assigned_name: null, ...more,
})
const INCIDENTS = [
  incident('WINC-00001', `502 spike after deployment: ${SITE}`, 'critical', DEPLOY - 2),
  incident('WINC-00002', `5xx spike: ${SITE}`, 'critical', DEPLOY - 2),
  incident('WINC-00003', `Nightly cron failure (01:00-04:00): ${SITE}`, 'critical', 12, { status: 'Resolved', resolved_at: at(3), assigned_name: 'Ops' }),
  incident('WINC-00004', `Security score low: ${SITE}`, 'warning', 40, { bench: null }),
]

const OPEN = {
  ...INCIDENT, name: 'WINC-00001', title: INCIDENTS[0].title, scope: SCOPE, started_at: at(DEPLOY - 2), last_event_at: at(DEPLOY - 3),
  deployment: { at: at(DEPLOY), event: 'E0', available: true }, notified_at: at(DEPLOY - 3), event_occurrences: 180,
}
const OPEN_ROWS = [
  { id: 'event:E0', kind: 'deployment', family: 'context', relation: 'preceding_change', at: at(DEPLOY), summary: `Deployment on ${SITE}: bench update (demo)`,
    scope: SCOPE, count: 1, details: { task: 'update' } },
  { id: 'event:E1', kind: 'event', family: 'evidence', relation: 'linked', at: at(DEPLOY - 1), severity: 'critical',
    summary: '502 on GET /api/method/ping', scope: { site: SITE }, count: 180, last_seen: at(DEPLOY - 2), details: { status: 502, route: '/api/method/ping' } },
  { id: 'delivery:D1', kind: 'delivery', family: 'activity', at: at(DEPLOY - 3), summary: 'Webhook to http://catcher:9999/', channel: 'webhook',
    action: 'notify', target: 'http://catcher:9999/', result: 'accepted', http_status: 200 },
  { id: 'event:E2', kind: 'event', family: 'context', relation: 'context', at: at(DEPLOY - 4), severity: 'info',
    summary: `bench migrate on ${SITE}`, scope: SCOPE, count: 1, details: { task: 'migrate' } },
]  // prettier-ignore

const RESOLVED = {
  ...INCIDENT, name: 'WINC-00003', title: INCIDENTS[2].title, status: 'Resolved', scope: SCOPE, summary: 'Nightly ledger sync failed',
  started_at: at(12), last_event_at: at(8), deployment: null, alert_rule: { name: 'Nightly cron failure (01:00-04:00)', readable: true },
  acknowledged: { at: at(9), by: 'ops@example.com', by_name: 'Ops' }, resolved: { at: at(3), by: 'ops@example.com', by_name: 'Ops' },
  assigned_to: { user: 'ops@example.com', name: 'Ops' }, notified_at: at(11), event_records: 1, event_occurrences: 5,
  can: { comment: true, acknowledge: false, resolve: false, assign_to_me: false, workflow: true, postmortem: true },
}
const RESOLVED_ROWS = [
  { id: 'event:E5', kind: 'event', family: 'evidence', relation: 'linked', at: at(12), severity: 'critical', summary: 'Scheduled job failed: Nightly ledger sync',
    scope: { site: SITE }, count: 5, last_seen: at(8), details: { job: 'Nightly ledger sync', error: "NameError: name 'ledger' is not defined" } },
  { id: 'delivery:D2', kind: 'delivery', family: 'activity', at: at(11), summary: 'Webhook to http://catcher:9999/', channel: 'webhook',
    action: 'notify', target: 'http://catcher:9999/', result: 'accepted', http_status: 200 },
  { id: 'activity:a1', kind: 'activity', family: 'activity', activity: 'assignment', at: at(10), summary: 'Ops took the incident', user_name: 'Ops' },
  { id: 'activity:a2', kind: 'activity', family: 'activity', activity: 'status', at: at(9), summary: 'Ops acknowledged', user_name: 'Ops' },
  { id: 'activity:c1', kind: 'activity', family: 'activity', activity: 'comment', at: at(5), summary: 'Ops commented', user_name: 'Ops',
    text: 'The Server Script named a variable that does not exist. Disabled it; the next run is clean.' },
  { id: 'activity:a3', kind: 'activity', family: 'activity', activity: 'status', at: at(3), summary: 'Ops resolved', user_name: 'Ops' },
]  // prettier-ignore

const signal = (group, metric_name, label, value, unit, state, more = {}) => ({
  metric_name, group, label, unit, host: 'demo-host', bench: 'frappe-bench', site: null, label_key: null, value, last_at: at(1), state, stale: false,
  rules: [], incidents: [], ...more,
})
const SIGNALS = {
  series: [
    signal('security', 'security_score', 'Security score', 30, '', 'firing', { site: SITE, bench: null, incidents: ['WINC-00004'],
      rules: [{ name: 'R1', rule_name: 'Security score low', aggregation: 'last', operator: '<', threshold: 60, window_minutes: 180 }] }),
    signal('workers', 'queue_length', 'Queue length', 0, 'jobs', 'watched', { label_key: 'queue=default',
      rules: [{ name: 'R2', rule_name: 'Worker queue backlog', aggregation: 'max', operator: '>', threshold: 100, window_minutes: 10 }] }),
    signal('host', 'disk_used_percent', 'Disk used', 61, '%', 'watched', { bench: null, label_key: 'mount=/',
      rules: [{ name: 'R3', rule_name: 'Disk almost full', aggregation: 'max', operator: '>', threshold: 90, window_minutes: 5 }] }),
    signal('host', 'load_1m', 'Load (1 min)', 0.42, '', 'unwatched', { bench: null }),
  ],
  counts: { security: { firing: 1 }, workers: { watched: 1 }, host: { watched: 1, unwatched: 1 } },
  missing: [], caveats: {}, email: {}, lookback_days: 7, truncated: false, total_series: 4,
}  // prettier-ignore

const MONITORING = {
  health: { rules: { last_evaluated: at(0.5) }, problems: [], scheduler: { enabled: true, tick_seconds: 60 }, queues: { ingest_backlog_seconds: null, workers: 2 } },
  rollups: { '1m': at(2) }, silence_minutes: 5, mode: { mode: 'central' },
  agents: [{ name: 'A1', hostname: 'demo-host', kind: 'agent', state: 'fresh', last_seen: at(0.3), clock_skew_seconds: 0, agent_version: '0.1.0' }],
  note: 'An agent that reports says nothing about the rules running: each line is checked on its own.',
}

const check = (id, label, weight, status, evidence, fix = null) => ({ id, label, weight, status, evidence, fix })
const POSTURE = {
  site: SITE, local: true, hosts: ['demo-host'], recent_hours: 3, score: 30, coverage: 57, passed: 4, failed: 3, unknown: 5,
  checks: [
    check('two_factor', 'Two-factor authentication for System Managers', 3, 'fail', 'disabled in System Settings',
      'System Settings → Enable Two Factor Auth, and tick Two Factor Authentication on the System Manager role.'),
    check('password_policy', 'Password policy', 2, 'fail', 'minimum score 2', 'System Settings → Enable Password Policy, minimum score 3 or more.'),
    check('hsts', 'HSTS for 180 days or more', 1, 'fail', `${SITE}: no Strict-Transport-Security header`,
      'Add `add_header Strict-Transport-Security "max-age=31536000" always;` to the site\'s HTTPS server block in nginx.'),
    check('exposure', 'Bench services not listening beyond loopback', 3, 'unknown', "no recent exposed_services sample from the agent on this site's hosts"),
    check('advisories', 'No published security advisory applies to Frappe or ERPNext', 3, 'unknown',
      "frappe 5.18.15: the last year's advisories name 14.x, 15.x, 16.x, not 5.x (a fork such as Dodock, numbered differently, or a line out of support)"),
    check('backup', 'A backup newer than 26 h', 2, 'unknown', 'no recent backup_age_hours sample'),
    check('spf', 'SPF for the mail domain, ending in -all or ~all', 1, 'unknown', "no outgoing Email Account on this site, or another site's mail domain"),
    check('dmarc', 'DMARC policy quarantine or reject', 1, 'unknown', "no outgoing Email Account on this site, or another site's mail domain"),
    check('site_config', 'No development settings in site_config.json', 3, 'pass', 'none of developer_mode, allow_tests, plain-HTTP host_name, allow_cors *'),
    check('tls', 'TLS certificates valid for 14 days or more', 2, 'pass', '61 days left'),
    check('login_lockout', 'Lockout after failed logins', 1, 'pass', 'locked after 10 failed logins'),
    check('guest_uploads', 'Guests cannot upload files', 1, 'pass', 'guests may not upload'),
  ],
}  // prettier-ignore

const base = fixtures()
const overrides = (view) => ({
  'dodock_wolf.api.spa.get_boot': () => ({ ...BOOT, user: { name: 'ops@example.com', full_name: 'Ops' } }),
  'dodock_wolf.api.scope.get_counts': () => ({
    restricted: false,
    incidents: { unresolved: 3, critical_unresolved: 2, unacknowledged: 3, sites_with_unresolved: 1, unresolved_without_site: 0 },
    agents: { agent: { fresh: 1, stale: 0, never_seen: 0, disabled: 0 }, satellite: { fresh: 0, stale: 0, never_seen: 0, disabled: 0 } },
  }),
  'dodock_wolf.api.dashboard.get_http': () => HTTP,
  'dodock_wolf.api.dashboard.get_signals': () => SIGNALS,
  'dodock_wolf.api.dashboard.get_monitoring': () => MONITORING,
  'dodock_wolf.api.incident_view.list_incidents': () => ({ incidents: INCIDENTS.filter((i) => !i.resolved_at), paging: { has_more: false, next_cursor: null } }),
  'dodock_wolf.api.incident_view.get_incident': () => (view === 'incident-resolved' ? RESOLVED : OPEN),
  'dodock_wolf.api.incident_view.get_timeline': () => ({
    ...base['dodock_wolf.api.incident_view.get_timeline'](), rows: view === 'incident-resolved' ? RESOLVED_ROWS : OPEN_ROWS,
  }),
  'dodock_wolf.api.scope.get_inventory': () => ({
    hosts: [{ host: 'demo-host', sources: ['agent', 'events', 'metrics'], benches: [{ bench: 'frappe-bench', sites: [{ site: SITE }] }] }],
    note: 'Known from agents, events and metrics of the last 7 days.',
  }),
  'dodock_wolf.api.security.list_sites': () => [SITE],
  'dodock_wolf.api.security.get_posture': () => POSTURE,
  'dodock_wolf.api.journal.get_status': () => ({ entries: 7, pending: 0, key: true, anchor: `7:${'3fa94c0be17d58a2'.repeat(4)}` }),
  'dodock_wolf.api.journal.verify': () => ({ ok: true, checked: 7, problem: null }),
})

const VIEWS = [
  ['overview', '/wolf/?range=1h'],
  ['incident', '/wolf/incidents/WINC-00001'],
  ['incident-resolved', '/wolf/incidents/WINC-00003'],
  ['monitoring', '/wolf/monitoring'],
  ['security', '/wolf/security'],
]

const browser = await chromium.launch(process.env.WOLF_CHROMIUM ? { executablePath: process.env.WOLF_CHROMIUM } : {})
for (const scheme of ['light', 'dark']) {
  for (const [view, url] of VIEWS) {
    if (only && view !== only) continue
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: scheme })
    const calls = await mockApi(page, overrides(view))
    await page.goto(origin + url)
    await page.waitForLoadState('networkidle')
    if (view === 'security') await page.getByRole('button', { name: 'Verify' }).click()
    await page.waitForTimeout(400) // the chart's first drawing
    const missing = calls.filter((c) => !c.mocked).map((c) => c.method)
    if (missing.length) throw new Error(`${view}: not mocked: ${missing.join(', ')}`)
    await page.screenshot({ path: path.join(out, `${view}-${scheme}.jpg`), type: 'jpeg', quality: 88 })
    await page.close()
    console.log(`${view}-${scheme}.jpg`)
  }
}
await browser.close()
