import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import SecurityPage from '@/pages/SecurityPage.vue'
import { makeRouter } from '@/router'

const BOOT = { time_zone: 'Europe/Paris', desk: { home: '/app', fallbacks: {} }, capabilities: {} }

const POSTURE = {
  site: 'a.example.com', local: false, hosts: ['bench-01'], recent_hours: 3,
  score: 41, coverage: 59, passed: 2, failed: 2, unknown: 4,
  checks: [
    { id: 'tls', label: 'TLS certificates valid for 14 days or more', weight: 2, status: 'pass', evidence: '60 days left', fix: null },
    { id: 'two_factor', label: 'Two-factor authentication for System Managers', weight: 3, status: 'unknown',
      evidence: 'no recent site_setting sample: the agent reads them from the site\'s database', fix: null },
    { id: 'exposure', label: 'Bench services not listening beyond loopback', weight: 3, status: 'fail',
      evidence: 'bench-01: 1 service(s)', fix: 'Bind MariaDB, Redis, socket.io and gunicorn to 127.0.0.1' },
  ],
}  // prettier-ignore

function server(handlers) {
  const fetchFn = vi.fn(async (url) => {
    const method = url.split('/api/method/')[1].split('?')[0]
    return new Response(JSON.stringify({ message: await handlers[method](url) }), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchFn)
  return fetchFn
}

async function open(path = '/security') {
  const router = makeRouter(createMemoryHistory('/wolf'), BOOT)
  await router.push(path)
  await router.isReady()
  const page = mount(SecurityPage, { global: { plugins: [router], provide: { boot: BOOT } } })
  await flushPromises()
  return page
}

afterEach(() => vi.unstubAllGlobals())

describe('SecurityPage', () => {
  it('shows the score, failures first, evidence in words and the fix', async () => {
    const fetchFn = server({
      'dodock_wolf.api.security.list_sites': () => ['a.example.com'],
      'dodock_wolf.api.security.get_posture': () => POSTURE,
    })
    const page = await open('/security?site=a.example.com')
    expect(fetchFn.mock.calls.some(([u]) => u.includes('get_posture?site=a.example.com'))).toBe(true)
    const text = page.text()
    expect(text).toContain('41 / 100')
    expect(text).toContain('2 passed, 2 failed, 4 unknown')
    expect(text).toContain('Wolf could read 59% of the weight')
    expect(text).toContain('System Settings of this site are read by the agent from its database')
    const rows = page.findAll('[data-check]')
    expect(rows.map((r) => r.attributes('data-check'))).toEqual(['exposure', 'two_factor', 'tls']) // failures first
    expect(rows[0].text()).toContain('(Failed)')
    expect(rows[0].get('.wolf-fix').text()).toContain('Bind MariaDB')
    expect(rows[1].text()).toContain('(Unknown)') // never shown as passed
    expect(rows[2].text()).toContain('(Passed)')
    // each state has its own group, with the word in its title
    expect(page.findAll('.wolf-checks-head h2').map((h) => h.text().replace(/\s+/g, ' '))).toEqual(['✕ Failed 1', '? Unknown 1', '✓ Passed 1'])
  })

  it('draws the weight of every check, and what passing one would add', async () => {
    server({
      'dodock_wolf.api.security.list_sites': () => ['a.example.com'],
      'dodock_wolf.api.security.get_posture': () => POSTURE,
    })
    const page = await open('/security?site=a.example.com')
    const bar = page.get('.wolf-weightbar')
    expect(bar.attributes('aria-label')).toBe('Weight of the checks: 3 failed, 3 unknown, 2 passed, of 8')
    const segments = bar.findAll('.wolf-weightbar-seg')
    expect(segments.map((s) => [s.attributes('data-status'), s.element.style.flexGrow])).toEqual([['fail', '3'], ['unknown', '3'], ['pass', '2']])
    // 2 of 8 passed is 25; with the failed check (weight 3) it is 5 of 8, 63: +38. Nothing for a passed one.
    const rows = page.findAll('[data-check]')
    expect(rows[0].get('.wolf-check-gain').text()).toBe('+38')
    expect(rows[2].find('.wolf-check-gain').exists()).toBe(false)
  })

  it('draws the commands of a fix as code, never as HTML', async () => {
    const check = { id: 'hsts', label: 'HSTS', weight: 1, status: 'fail', evidence: 'no header', fix: 'Add `add_header <b>x</b>;` to nginx.' }
    server({
      'dodock_wolf.api.security.list_sites': () => [],
      'dodock_wolf.api.security.get_posture': () => ({ ...POSTURE, checks: [check] }),
    })
    const page = await open()
    const fix = page.get('.wolf-fix')
    expect(fix.get('code').text()).toBe('add_header <b>x</b>;')
    expect(fix.find('b').exists()).toBe(false)
    expect(fix.get('p').text()).toBe('Add add_header <b>x</b>; to nginx.')
  })

  it('says why a site is refused', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (url.includes('list_sites')) return new Response(JSON.stringify({ message: [] }))
      return new Response(JSON.stringify({}), { status: 403 })
    }))  // prettier-ignore
    const page = await open('/security?site=other.example.com')
    expect(page.get('[role=alert]').text()).toBe('You may not see this site.')
  })

  it('shows the journal to managers and its verification', async () => {
    server({
      'dodock_wolf.api.security.list_sites': () => [],
      'dodock_wolf.api.security.get_posture': () => POSTURE,
      'dodock_wolf.api.journal.get_status': () => ({ entries: 42, pending: 3, anchor: `42:${'a'.repeat(64)}`, key: true }),
      'dodock_wolf.api.journal.verify': () => ({ ok: false, checked: 9, problem: { seq: 10, why: 'content does not match its digest' } }),
    })
    const router = makeRouter(createMemoryHistory('/wolf'), BOOT)
    await router.push('/security')
    await router.isReady()
    const boot = { ...BOOT, can: { configure: true } }
    const page = mount(SecurityPage, { global: { plugins: [router], provide: { boot } } })
    await flushPromises()
    expect(page.text()).toContain('42 signed entries, 3 waiting to be signed')
    expect(page.text()).toContain(`42:${'a'.repeat(64)}`)
    await page.findAll('button').find((b) => b.text() === 'Verify').trigger('click')
    await flushPromises()
    expect(page.get('[role=status]').text()).toBe('Broken at entry 10: content does not match its digest')
    expect(page.text()).toContain('Kept forever')
  })

  it('says what the retention purged, and that verification checks it', async () => {
    server({
      'dodock_wolf.api.security.list_sites': () => [],
      'dodock_wolf.api.security.get_posture': () => POSTURE,
      'dodock_wolf.api.journal.get_status': () => ({ entries: 30, last_seq: 42, pending: 0, anchor: `42:${'a'.repeat(64)}`, key: true,
        retention_days: 365, purged_through: 12, purged_at: '2026-11-02 03:17:00' }),
      'dodock_wolf.api.journal.verify': () => ({ ok: true, checked: 30, first_seq: 13, purged_through: 12, problem: null }),
    })
    const router = makeRouter(createMemoryHistory('/wolf'), BOOT)
    await router.push('/security')
    await router.isReady()
    const page = mount(SecurityPage, { global: { plugins: [router], provide: { boot: { ...BOOT, can: { configure: true } } } } })
    await flushPromises()
    expect(page.text()).toContain('Entries older than 365 days are purged every night.')
    expect(page.text()).toContain('Entries 1 to 12 were purged')
    await page.findAll('button').find((b) => b.text() === 'Verify').trigger('click')
    await flushPromises()
    expect(page.get('[role=status]').text().replace(/\s+/g, ' ')).toBe(
      'Verified: 30 entries, every digest and MAC matches, no gap, and the journal starts where the last purge stopped (entry 13).')
  })
})
