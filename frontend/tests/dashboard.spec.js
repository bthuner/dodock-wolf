import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import DashboardPage from '@/pages/DashboardPage.vue'
import { makeRouter } from '@/router'

const BOOT = { time_zone: 'UTC', desk: { home: '/app', fallbacks: {} }, capabilities: { incidents: { available: true } } }
const NOW = new Date().toISOString()
const OLD = new Date(Date.now() - 40 * 60000).toISOString()

const COUNTS = {
  restricted: false,
  window: { since: OLD, until: NOW, relative: '24h' },
  events: { records: 12, occurrences: 40, by_type: { error: { records: 5, occurrences: 30 }, cron_failure: { records: 2, occurrences: 2 } } },
  incidents: { unresolved: 60, critical_unresolved: 7, unacknowledged: 40, sites_with_unresolved: 3, unresolved_without_site: 5,
    opened_in_window: 4, resolved_in_window: 1 },
  agents: { agent: { fresh: 3, stale: 1, never_seen: 0, disabled: 0 }, satellite: { fresh: 0, stale: 0, never_seen: 0, disabled: 0 } },
}
const HTTP = {
  window: { since: OLD, until: NOW }, bucket_seconds: 720, resolution: '1m', deployments: [],
  series: { http_requests: [[OLD, 10], [NOW, null]], http_5xx: [[OLD, 2], [NOW, null]], http_502: [[OLD, 1], [NOW, null]] },
  has_data: { http_requests: true, http_5xx: true, http_502: true },
}
const SIGNALS = {
  series: [
    { metric_name: 'queue_length', group: 'workers', label: 'Queue length', unit: 'jobs', host: 'h1', bench: 'b1', label_key: 'queue=default', value: 930, last_at: NOW, state: 'firing',
      rules: [{ name: 'R1', rule_name: 'Worker queue backlog', aggregation: 'min', operator: '>', threshold: 500, window_minutes: 10 }], incidents: ['WINC-00009'] },
    { metric_name: 'redis_used_memory_percent', group: 'redis', label: 'Redis memory used', unit: '%', host: 'h1', bench: 'b1', value: 12, last_at: OLD, state: 'stale', rules: [], incidents: [] },
  ],
  counts: { workers: { firing: 1 }, redis: { stale: 1 } },
  missing: [{ metric: 'backup_age_hours', label: 'Newest backup age' }],
  caveats: {}, email: {}, lookback_days: 7, truncated: false, total_series: 2,
}

function server(overrides = {}) {
  const handlers = {
    'dodock_wolf.api.scope.get_counts': () => COUNTS,
    'dodock_wolf.api.dashboard.get_http': () => HTTP,
    'dodock_wolf.api.dashboard.get_signals': () => SIGNALS,
    'dodock_wolf.api.incident_view.list_incidents': () => ({ incidents: [], paging: { has_more: false } }),
    'dodock_wolf.api.scope.get_inventory': () => ({ hosts: [], note: '' }),
    'dodock_wolf.api.dashboard.get_monitoring': () => ({ health: null, rollups: {}, agents: [], silence_minutes: 5, mode: { mode: 'central' }, note: '' }),
    ...overrides,
  }
  const fetchFn = vi.fn(async (url) => {
    const method = url.split('/api/method/')[1].split('?')[0]
    try {
      return new Response(JSON.stringify({ message: await handlers[method](url) }))
    } catch (e) {
      return new Response(JSON.stringify({ exception: `frappe.Error: ${e.message}` }), { status: 500 })
    }
  })
  vi.stubGlobal('fetch', fetchFn)
  return fetchFn
}

async function open(path = '/operations') {
  const router = makeRouter(createMemoryHistory('/wolf'), BOOT)
  await router.push(path)
  await router.isReady()
  const page = mount(DashboardPage, {
    global: { plugins: [router], provide: { boot: BOOT }, stubs: { LineChart: { template: '<div class="chart-stub" />' } } },
  })
  await flushPromises()
  return { page, router }
}

afterEach(() => vi.unstubAllGlobals())

describe('HttpChart labels', () => {
  it('stay unique over a whole day, so a deployment lands in its own bucket', async () => {
    const { default: HttpChart } = await import('@/components/dash/HttpChart.vue')
    const start = Date.parse('2026-10-29T10:36:00Z')
    const points = Array.from({ length: 121 }, (_, i) => [new Date(start + i * 720000).toISOString(), i])
    const http = { ...HTTP, bucket_seconds: 720, series: { http_requests: points, http_5xx: points, http_502: points },
      window: { since: points[0][0], until: points[120][0] },
      deployments: [{ name: 'D1', at: new Date(start + 120 * 720000 + 60000).toISOString() }] }
    let captured
    const page = mount(HttpChart, {
      props: { http, timeZone: 'UTC' },
      global: { stubs: { LineChart: { props: ['data', 'referenceLines'], setup(p) { captured = p; return () => null } } } },
    })
    await flushPromises()
    const labels = captured.data.map((r) => r.at)
    expect(new Set(labels).size).toBe(labels.length)
    expect(captured.referenceLines.map((l) => l.value)).toEqual([labels[120]])
    page.unmount()
  })
})

describe('DashboardPage', () => {
  it('shows exact counts, not the length of a list', async () => {
    server()
    const { page } = await open()
    expect(page.text()).toContain('60')
    expect(page.text()).toContain('7 critical')
    expect(page.text()).toContain('+ 5 host or bench-wide')
  })

  it('keeps signal states apart and never shows missing signals as zero', async () => {
    server()
    const { page } = await open()
    const text = page.text()
    expect(text).toContain('Rule firing')
    expect(text).toContain('Worker queue backlog: min > 500 over 10 min') // the rule's threshold, not the UI's
    expect(text).toContain('No new data')
    expect(text).toContain('last sample 40 min ago')
    expect(text).not.toMatch(/Redis memory used\s+12 %/) // a stale value is not shown as current
    expect(text).toContain('1 signals without data in the last 7 days')
    expect(text).toContain('They are not zero')
  })

  it('says 502 is part of 5xx, and that no HTTP data is not no traffic', async () => {
    server({ 'dodock_wolf.api.dashboard.get_http': () => ({ ...HTTP, has_data: { http_requests: false, http_5xx: false, http_502: false } }) })
    const { page } = await open()
    expect(page.text()).toContain('502 responses are part of the 5xx count')
    expect(page.text()).toContain('which is not the same as no traffic')
    expect(page.find('.chart-stub').exists()).toBe(false)
  })

  it('shows the other panels when one fails', async () => {
    server({ 'dodock_wolf.api.dashboard.get_signals': () => { throw new Error('boom') } })
    const { page } = await open()
    expect(page.text()).toContain('Signals: boom')
    expect(page.text()).toContain('7 critical')
  })

  it('draws the first 10 rows of a group and the rest on demand, problems first', async () => {
    const row = (i, state) => ({ metric_name: 'queue_length', group: 'workers', label: 'Queue length', unit: 'jobs', host: `h${String(i).padStart(2, '0')}`,
      value: i, last_at: state === 'stale' ? OLD : NOW, state, rules: [], incidents: [] })
    // the server's order: firing, then stale, then the others
    const series = [...Array.from({ length: 9 }, (_, i) => row(i, 'firing')), ...Array.from({ length: 3 }, (_, i) => row(9 + i, 'stale')),
      ...Array.from({ length: 13 }, (_, i) => row(12 + i, 'unwatched'))]
    server({ 'dodock_wolf.api.dashboard.get_signals': () => ({ ...SIGNALS, series, counts: { workers: { firing: 9, stale: 3, unwatched: 13 } }, total_series: 25 }) })
    const { page } = await open()
    const rows = () => page.findAll('[aria-label="Signals"] li')
    expect(rows()).toHaveLength(10)
    expect(page.text()).toContain('· 9 rules firing · 3 no new data') // the group's counts stay exact
    const more = page.findAll('button').find((b) => b.text().startsWith('Show the other'))
    expect(more.text()).toBe('Show the other 15 of 25, 2 with a problem')
    await more.trigger('click')
    expect(rows()).toHaveLength(25)
    const fold = page.findAll('button').find((b) => b.text() === 'Show the first 10 only')
    await fold.trigger('click')
    expect(rows()).toHaveLength(10)
  })

  it('draws the first 20 hosts and the rest on demand', async () => {
    const hosts = Array.from({ length: 23 }, (_, i) => ({ host: `host-${i}`, sources: ['agent'], benches: [] }))
    server({ 'dodock_wolf.api.scope.get_inventory': () => ({ hosts, note: '' }) })
    const { page } = await open()
    const drawn = () => page.findAll('[aria-label="Hosts, benches and sites"] > ul > li')
    expect(drawn()).toHaveLength(20)
    const more = page.findAll('button').find((b) => b.text() === 'Show the other 3 of 23 hosts')
    await more.trigger('click')
    expect(drawn()).toHaveLength(23)
  })

  it('draws a host with its benches and sites, says where it is known from, and filters', async () => {
    const site = (s) => ({ site: s, sources: ['agent'] })
    const hosts = [
      { host: 'h1', sources: ['agent', 'events', 'metrics'], last_seen: OLD, benches: [{ bench: 'erp-bench', sites: [site('a.example.com'), site('b.example.com')] }] },
      { host: 'h2', sources: ['metrics'], benches: [{ bench: 'frappe-bench', sites: [] }], sites: [site('lost.example.com')] },
      { host: 'h3', sources: ['agent'], benches: [] },
      { host: 'h4', sources: ['satellite'], benches: [{ bench: 'frappe-bench', sites: [site('c.example.com')] }] },
    ]
    server({ 'dodock_wolf.api.scope.get_inventory': () => ({ hosts, unplaced_sites: [site('nohost.example.com')], note: 'Note.' }) })
    const { page } = await open()
    const panel = page.find('[aria-label="Hosts, benches and sites"]')
    const drawn = () => panel.findAll('.wolf-estate-host')
    expect(panel.find('.wolf-estate-totals').text()).toBe('hosts4benches3sites5')
    expect(drawn()[0].text()).toContain('Agent registered · seen 40 min ago')
    expect(drawn()[0].find('[aria-label="Telemetry received"]').text()).toBe('eventsmetrics')
    // a host known from telemetry alone says so; its site with no bench is not given one
    expect(drawn()[1].attributes('data-registered')).toBe('no')
    expect(drawn()[1].text()).toContain('No agent registered')
    expect(drawn()[1].text()).toContain('no site seen')
    expect(drawn()[1].text()).toContain('bench not known')
    expect(drawn()[2].text()).toContain('no bench seen')
    expect(drawn()[3].text()).toContain('Known through a satellite')
    expect(panel.text()).toContain('Sites with no known host')
    expect(panel.find('a[href="/wolf/sites/nohost.example.com"]').exists()).toBe(true)
    expect(panel.find('a[href="/wolf/hosts/h1/benches/erp-bench"]').exists()).toBe(true)

    const input = panel.find('input[aria-label="Find a host, bench or site"]')
    await input.setValue('B.exam')
    expect(drawn()).toHaveLength(1)
    expect(drawn()[0].findAll('.wolf-estate-site').map((a) => a.text())).toEqual(['b.example.com'])
    expect(panel.text()).toContain('1 of 4 hosts match.')
    expect(panel.text()).not.toContain('Sites with no known host')
    await input.setValue('frappe-bench') // a bench that matches keeps all its sites
    expect(drawn().map((h) => h.find('a').text())).toEqual(['h2', 'h4'])
    expect(drawn()[1].text()).toContain('c.example.com')
    await input.setValue('zzz')
    expect(panel.text()).toContain('No host, bench or site contains “zzz”.')
    await panel.findAll('button').find((b) => b.text() === 'Clear the filter').trigger('click')
    expect(drawn()).toHaveLength(4)
  })

  it('draws one host on its page, without the sites that have no host', async () => {
    const hosts = [{ host: 'h1', sources: ['agent'], benches: [{ bench: 'b1', sites: [{ site: 'a.example.com' }] }] }, { host: 'h2', sources: ['agent'], benches: [] }]
    server({ 'dodock_wolf.api.scope.get_inventory': () => ({ hosts, unplaced_sites: [{ site: 'nohost.example.com' }], note: '' }) })
    const { page } = await open('/hosts/h1')
    const panel = page.find('[aria-label="Hosts, benches and sites"]')
    expect(panel.find('h2').text()).toBe('Benches and sites on this host')
    expect(panel.findAll('.wolf-estate-host')).toHaveLength(1)
    expect(panel.find('.wolf-estate-totals').text()).toBe('bench1site1')
    expect(panel.text()).not.toContain('nohost.example.com')
  })

  it('reads the counts and the chart for a range selected on the chart, and goes back', async () => {
    const fetchFn = server()
    const { page, router } = await open('/sites/a.example.com?range=7d')
    const asked = (method) => fetchFn.mock.calls.map(([url]) => String(url)).filter((u) => u.includes(method)).at(-1)
    expect(asked('get_http')).toContain('range=7d')
    // the window's figures, each linked to its explorer with the same window and scope
    const tiles = page.find('[aria-label="In this window"]')
    expect(tiles.text()).toContain('In this window · last 24h')
    expect(tiles.text()).toContain('40 occurrences')
    expect(tiles.text()).toContain('1 resolved')
    expect(tiles.findAll('a').map((a) => [a.text(), a.attributes('href')])).toEqual([
      ['Events', '/wolf/events?range=7d&site=a.example.com'],
      ['Error groups', '/wolf/errors?range=7d&site=a.example.com'],
      ['2 cron', '/wolf/events?range=7d&site=a.example.com&type=cron_failure'],
      ['0 worker', '/wolf/events?range=7d&site=a.example.com&type=worker_failure'],
    ])

    page.findComponent({ name: 'HttpChart' }).vm.$emit('select', '2026-11-18T10:00:00Z', '2026-11-18T10:24:00.000Z')
    await flushPromises()
    const q = router.currentRoute.value.query
    expect([q.since, q.until, q.range]).toEqual(['2026-11-18T10:00:00Z', '2026-11-18T10:24:00.000Z', undefined])
    for (const method of ['get_counts', 'get_http']) {
      expect(asked(method)).toContain('since=2026-11-18T10%3A00%3A00Z')
      expect(asked(method)).toContain('until=2026-11-18T10%3A24%3A00.000Z')
      expect(asked(method)).not.toContain('range=')
    }
    expect(asked('get_signals')).not.toContain('since=') // signals are their newest values, whatever the window
    expect(page.text()).toContain('Selected range: 18/11/2026, 10:00:00 to 18/11/2026, 10:24:00 (UTC)')
    expect(page.find('[aria-label="In this window"] a').attributes('href')).toBe('/wolf/events?since=2026-11-18T10:00:00Z&until=2026-11-18T10:24:00.000Z&site=a.example.com')

    await page.findAll('button').find((b) => b.text() === 'Back to a relative window').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.since).toBeUndefined()
    expect(asked('get_http')).toContain('range=24h')
    expect(page.text()).not.toContain('Selected range')
  })

  it('scopes a bench by its host and keeps the range in the URL', async () => {
    const fetchFn = server()
    const { router } = await open('/hosts/h2/benches/frappe-bench?range=7d')
    const counts = fetchFn.mock.calls.map(([url]) => url).find((u) => u.includes('get_counts'))
    expect(counts).toContain('host=h2')
    expect(counts).toContain('bench=frappe-bench')
    expect(counts).toContain('range=7d')
    expect(router.currentRoute.value.query.range).toBe('7d')
  })
})

describe('MonitoringPanel', () => {
  const MONITORING = (tick) => ({
    health: {
      rules: { last_evaluated: NOW, age_seconds: 30 }, problems: [],
      scheduler: { enabled: true, reason: null, last_job_run: NOW, age_seconds: 30, tick_seconds: tick },
      queues: { ingest_backlog_seconds: null, workers: 2 },
    },
    rollups: {}, agents: [], silence_minutes: 5, mode: { mode: 'central' },
  })

  it("says how often jobs run, and what Frappe's 4-minute default means for alert rules", async () => {
    const { default: MonitoringPanel } = await import('@/components/dash/MonitoringPanel.vue')
    const slow = mount(MonitoringPanel, { props: { monitoring: MONITORING(240), timeZone: 'UTC' } })
    expect(slow.text()).toContain('enabled, jobs every 4 min')
    expect(slow.text()).toContain('Alert rules are evaluated at that pace, not every minute')
    expect(slow.text()).toContain('scheduler_tick_interval')
    const fast = mount(MonitoringPanel, { props: { monitoring: MONITORING(60), timeZone: 'UTC' } })
    expect(fast.text()).toContain('enabled, jobs every 1 min')
    expect(fast.text()).not.toContain('scheduler_tick_interval')
    // an older Frappe without the setting: nothing claimed
    const unknown = mount(MonitoringPanel, { props: { monitoring: MONITORING(null), timeZone: 'UTC' } })
    expect(unknown.text()).not.toContain('jobs every')
  })

  it("shows each agent's setup checks, and the fix for each problem", async () => {
    const { default: MonitoringPanel } = await import('@/components/dash/MonitoringPanel.vue')
    const agent = (hostname, setup) => ({ name: hostname, hostname, kind: 'agent', status: 'Active', state: 'fresh', last_seen: NOW,
      clock_skew_seconds: 0, agent_version: '0.1.0', setup })  // prettier-ignore
    const monitoring = {
      ...MONITORING(60),
      agents: [
        agent('f1', { checked_at: NOW, failed: 1, warnings: 1, problems: [
          { area: 'logs', status: 'fail', title: 'cannot read /home/frappe/benches/b1/logs/web.log (permission denied)',
            fix: 'give wolf-agent access: add it to the group of the user who owns the folder (frappe...)' },
          { area: 'benches', status: 'warn', title: 'b1: queue Redis redis://127.0.0.1:11000 unreachable', fix: 'start the bench\'s queue Redis' },
        ] }),  // prettier-ignore
        agent('n1', { checked_at: NOW, failed: 0, warnings: 0, problems: [] }),
        agent('old', null),
      ],
    }
    const full = mount(MonitoringPanel, { props: { monitoring, timeZone: 'UTC' } })
    expect(full.text()).toContain('1 host to fix: f1')
    expect(full.text()).toContain('1 failed, 1 warning')
    expect(full.text()).toContain('not reported') // an agent from before the setup checks
    expect(full.text()).toContain('cannot read /home/frappe/benches/b1/logs/web.log (permission denied)')
    expect(full.text()).toContain('Fix: give wolf-agent access')
    const compact = mount(MonitoringPanel, { props: { monitoring, timeZone: 'UTC', compact: true } })
    expect(compact.text()).toContain('1 host to fix: f1')
    expect(compact.find('table').exists()).toBe(false)
    expect(full.text()).toMatch(/checked .* ago/)
    // no agent has reported yet: nothing claimed
    const none = mount(MonitoringPanel, { props: { monitoring: { ...monitoring, agents: [agent('old', null)] }, timeZone: 'UTC' } })
    expect(none.text()).toContain('not reported yet')
  })
})
