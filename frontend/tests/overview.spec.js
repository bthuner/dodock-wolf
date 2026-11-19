import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import SecurityOverviewPage from '@/pages/SecurityOverviewPage.vue'
import { makeRouter } from '@/router'

const MANAGER = {
  time_zone: 'UTC', desk: { home: '/app', fallbacks: {} }, capabilities: { incidents: { available: true } },
  can: { configure: false }, satellite: false,
}  // prettier-ignore
const ago = (minutes) => new Date(Date.now() - minutes * 60000).toISOString()

const OVERVIEW = {
  restricted: false,
  scores: {
    late_hours: 3, lookback_days: 7,
    sites: [
      { site: 'b.example.com', score: 41, at: ago(20), late: false, change: -6 },
      { site: 'a.example.com', score: 82, at: ago(300), late: true, change: 0 },
      { site: 'c.example.com', score: 90, at: ago(20), late: false, change: null },
      { site: 'new.example.com', score: null, at: null, late: false, change: null },
    ],
  },
  incidents: {
    by_severity: { critical: 6, warning: 1, info: 0, total: 7 }, by_status: { Open: 5, Acknowledged: 2 },
    newest: [{ name: 'WINC-00042', title: 'Brute force on SSH: bench-01', status: 'Acknowledged', severity: 'critical',
      site: null, bench: null, host: 'bench-01', started_at: ago(30) }],
  },
  responses: {
    waiting: 1, failed: 2, failed_days: 7,
    newest: [{ name: 'WRA-1', label: 'Block 45.33.32.156 for 24 h on bench-01', status: 'Failed', incident: 'WINC-00042',
      host: 'bench-01', site: null, result: 'nft: permission denied', at: ago(5) }],
  },
  journal: { last_seq: 812, last_at: ago(1), pending: 3, oldest_pending_at: ago(9), behind: true, key: true, late_minutes: 5 },
  agents: {
    agents: { fresh: 2, stale: 1, never_seen: 0, disabled: 0, total: 3 }, satellites: { fresh: 0, stale: 0, never_seen: 0, disabled: 0, total: 0 },
    setup_reported: 2, to_fix: [{ hostname: 'bench-02', failed: 1, warnings: 0 }], silence_minutes: 5,
  },
  time_zone: 'UTC',
}  // prettier-ignore

function server(answer) {
  const fetchFn = vi.fn(async () => {
    const result = await answer()
    if (result?.status) return new Response(JSON.stringify(result.body), { status: result.status })
    return new Response(JSON.stringify({ message: result }))
  })
  vi.stubGlobal('fetch', fetchFn)
  return fetchFn
}

async function open(boot = MANAGER) {
  const router = makeRouter(createMemoryHistory('/wolf'), boot)
  await router.push('/')
  await router.isReady()
  const page = mount(SecurityOverviewPage, { global: { plugins: [router], provide: { boot } } })
  await flushPromises()
  return page
}

const section = (page, name) => page.find(`section[aria-label="${name}"]`)

afterEach(() => vi.unstubAllGlobals())

describe('SecurityOverviewPage', () => {
  it('lists the scores worst first, links each site to its checks, and never shows an unscored site as 0', async () => {
    server(() => OVERVIEW)
    const page = await open()
    const scores = section(page, 'Security score by site')
    const rows = scores.findAll('li')
    expect(rows.map((r) => r.find('a').text())).toEqual(['b.example.com', 'a.example.com', 'c.example.com', 'new.example.com'])
    expect(rows[0].find('a').attributes('href')).toBe('/wolf/security?site=b.example.com')
    expect(rows[0].text()).toContain('41 / 100')
    expect(rows[0].text()).toContain('−6 in 24 h')
    expect(rows[0].text()).toContain('scored 20 min ago')
    expect(rows[1].text()).toContain('unchanged in 24 h')
    expect(rows[1].text()).toContain('no new score for over 3 h')
    expect(rows[2].text()).not.toContain('in 24 h') // nothing to compare with: no change claimed
    expect(rows[3].text()).toContain('not scored yet')
    expect(rows[3].text()).not.toMatch(/\b0 \/ 100/)
  })

  it('counts security incidents exactly by severity and links the newest', async () => {
    server(() => OVERVIEW)
    const page = await open()
    const panel = section(page, 'Open security incidents')
    expect(panel.find('.wolf-home-counts').text()).toBe('●Critical6◐Warning1○Info0')
    const link = panel.find('a[href="/wolf/incidents/WINC-00042"]')
    expect(link.text()).toBe('Brute force on SSH: bench-01')
    expect(panel.text()).toContain('Acknowledged')
    expect(panel.text()).toContain('opened 30 min ago')
    expect(panel.text()).toContain('The newest of 7.')
  })

  it('shows response actions and the journal to managers, with signing behind said so', async () => {
    server(() => OVERVIEW)
    const page = await open()
    const responses = section(page, 'Response actions')
    expect(responses.text()).toContain('Approved, waiting for their agent or satellite1')
    expect(responses.text()).toContain('Failed in the last 7 days2')
    expect(responses.text()).toContain('nft: permission denied')
    expect(responses.find('a').attributes('href')).toBe('/wolf/incidents/WINC-00042')
    const journal = section(page, 'Journal')
    expect(journal.text()).toContain('entry 812')
    expect(journal.text()).toContain('Signing is behind: the oldest unsigned entry was written 9 min ago.')
    expect(journal.find('a').attributes('href')).toBe('/wolf/security')
    const agents = section(page, 'Agents')
    expect(agents.text()).toContain('2 of 3 reporting (silent after 5 min)')
    expect(agents.text()).toContain('1 host to fix: bench-02')
    expect(agents.find('a').attributes('href')).toBe('/wolf/monitoring')
  })

  it('draws no manager panel the server did not send', async () => {
    server(() => ({ ...OVERVIEW, responses: null, journal: null, restricted: true }))
    const page = await open()
    expect(section(page, 'Response actions').exists()).toBe(false)
    expect(section(page, 'Journal').exists()).toBe(false)
    expect(page.text()).toContain('You see the sites, benches and hosts you were granted.')
  })

  it('says when a panel failed or may not be seen, and keeps the others', async () => {
    server(() => ({ ...OVERVIEW, scores: { error: 'Wolf could not read this panel: the reason is in the Error Log.' }, agents: { forbidden: true } }))
    const page = await open()
    expect(section(page, 'Security score by site').find('[role="alert"]').text()).toContain('Wolf could not read this panel')
    expect(section(page, 'Agents').text()).toContain('You may not see these agents.')
    expect(section(page, 'Open security incidents').text()).toContain('Brute force on SSH')
  })

  it('says what is empty, and only once it has read', async () => {
    server(() => ({
      ...OVERVIEW,
      scores: { sites: [], late_hours: 3 },
      incidents: { by_severity: { critical: 0, warning: 0, info: 0, total: 0 }, newest: [] },
      responses: { waiting: 0, failed: 0, failed_days: 7, newest: [] },
      journal: { last_seq: null, last_at: null, pending: 0, behind: false, key: false },
      agents: { agents: { total: 0 }, satellites: { total: 0 }, to_fix: [], setup_reported: 0, silence_minutes: 5 },
    }))
    const page = await open()
    expect(page.text()).toContain('No site known yet')
    expect(page.text()).toContain('No security incident open that you can see.')
    expect(page.text()).toContain('No action waiting, and none failed in the last 7 days.')
    expect(page.text()).toContain('none yet')
    expect(page.text()).toContain('No key yet')
    expect(page.text()).toContain('No agent registered that you can see.')
  })

  it('hides incidents on a satellite, which keeps none', async () => {
    server(() => ({ ...OVERVIEW, incidents: null, responses: null }))
    const page = await open({ ...MANAGER, capabilities: { incidents: { available: false } } })
    expect(section(page, 'Open security incidents').exists()).toBe(false)
  })

  it('says a refusal in words, and claims nothing', async () => {
    server(() => ({ status: 403, body: { exception: 'frappe.exceptions.PermissionError: Not permitted' } }))
    const page = await open()
    expect(page.find('[role="alert"]').text()).toBe('You may not see this overview.')
    expect(page.find('.wolf-home').exists()).toBe(false)
  })
})
