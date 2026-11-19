<script setup>
import { Button, PageHeader } from 'frappe-ui'
import { computed, inject, ref } from 'vue'

import LiveStatus from '@/components/LiveStatus.vue'
import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import OnboardingPanel from '@/components/dash/OnboardingPanel.vue'
import { useLive } from '@/composables/useLive'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'
import { full, timeAgo } from '@/services/time'

// The home page (dodock_wolf/api/security_overview.py): the security of the bench at a glance,
// each panel within the reader's access. One read; each panel says on its own when it could not
// be read or may not be seen, and the others still show. The general overview is Operations.
const boot = inject('boot')
const tz = boot.time_zone

const data = ref(null)
const error = ref(null)
const loading = ref(false)
let ticket = 0

async function load() {
  const mine = ++ticket
  loading.value = true
  try {
    const result = await call('dodock_wolf.api.security_overview.get_overview')
    if (mine !== ticket) return
    data.value = result
    error.value = null
  } catch (e) {
    if (mine !== ticket) return
    data.value = null // never a previous read under an error
    error.value = failure(e, __('this overview'))
  } finally {
    if (mine === ticket) loading.value = false
  }
}
load()

// each panel's own state: its data, or why it is not shown (forbidden or failed)
function panel(key, what) {
  const p = data.value?.[key]
  if (!p) return { hidden: true }
  if (p.forbidden) return { problem: __('You may not see {0}.', [what()]) }
  if (p.error) return { problem: p.error }
  return { data: p }
}
const scores = computed(() => panel('scores', () => __('these scores')))
const incidents = computed(() => panel('incidents', () => __('these incidents')))
const responses = computed(() => panel('responses', () => __('these response actions')))
const journal = computed(() => panel('journal', () => __('the journal')))
const agents = computed(() => panel('agents', () => __('these agents')))
// a satellite keeps no incidents: the server sends none, and the panel is not drawn
const hasIncidents = computed(() => boot.capabilities?.incidents?.available)

const scope = (r) => [r.site, r.bench, r.host].filter(Boolean).join(' · ')
const signed = (n) => (n > 0 ? `+${n}` : String(n).replace('-', '−'))
const shownMore = (shown, total) => total > shown

// an incident's change reloads the page; scores, journal, agents and the events (which would
// reload every panel at each one) change without a message: poll while live, as the dashboards do
const hub = inject('live', null)
const live = useLive(hub, {
  room: () => ({ doctype: 'Wolf Incident' }),
  matches: (m) => m.kind === 'incidents',
  refresh: async () => {
    await load()
    return true
  },
  pollAlways: true,
  debounceMs: 10000,
})
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Overview')" />
    <div class="flex items-center gap-2">
      <LiveStatus :live="live" :poll-seconds="hub?.pollSeconds" />
      <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="loading" @click="live.apply()" />
    </div>
  </PageHeader>

  <div class="wolf-page space-y-5">
    <OnboardingPanel v-if="boot.can?.configure && !boot.satellite" compact />
    <p v-if="data?.restricted" class="text-sm text-ink-gray-6">{{ __('You see the sites, benches and hosts you were granted.') }}</p>
    <LoadingNote v-if="loading && !data && !error" :text="__('Loading the security overview…')" />
    <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>

    <div v-if="data" class="wolf-home">
      <!-- a satellite records no score: the central site keeps them -->
      <p v-if="data.satellite" class="wolf-card wolf-home-scores text-sm text-ink-gray-6">{{ __('Security scores are kept on the central site.') }}</p>
      <section v-else class="wolf-card wolf-home-scores space-y-2" :aria-label="__('Security score by site')">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="wolf-h2">{{ __('Security score by site') }}</h2>
          <RouterLink class="wolf-link text-sm" :to="{ name: 'security' }">{{ __('Security') }}</RouterLink>
        </div>
        <p v-if="scores.problem" role="alert" class="wolf-alert">{{ scores.problem }}</p>
        <template v-else-if="scores.data">
          <ul v-if="scores.data.sites.length" class="wolf-scores">
            <li v-for="s in scores.data.sites" :key="s.site" :data-scored="s.score != null ? 'yes' : 'no'">
              <RouterLink class="wolf-scores-site font-medium text-ink-gray-9 hover:underline" :to="{ name: 'security', query: { site: s.site } }">{{ s.site }}</RouterLink>
              <template v-if="s.score != null">
                <span class="wolf-data wolf-scores-figure">{{ s.score }}<span class="wolf-scores-of"> / 100</span></span>
                <span class="wolf-scores-bar" aria-hidden="true"><span :style="{ width: `${s.score}%` }" /></span>
                <span class="wolf-scores-meta">
                  <span v-if="s.change === 0">{{ __('unchanged in 24 h') }}</span>
                  <span v-else-if="s.change != null" class="wolf-data">{{ __('{0} in 24 h', [signed(s.change)]) }}</span>
                  <time :datetime="s.at" :title="full(s.at, tz)">{{ __('scored {0}', [timeAgo(s.at)]) }}</time>
                  <span v-if="s.late" style="color: var(--wolf-warning)">{{ __('no new score for over {0} h: the hourly job may not run', [scores.data.late_hours]) }}</span>
                </span>
              </template>
              <span v-else class="wolf-scores-meta">{{ __('not scored yet') }}</span>
            </li>
          </ul>
          <p v-else class="text-sm text-ink-gray-6">{{ __('No site known yet: a site is scored once Wolf reads it, hourly.') }}</p>
          <p class="text-sm text-ink-gray-6">{{ __('Worst first. The score is recorded every hour; open a site for its checks and their fixes.') }}</p>
        </template>
      </section>

      <section v-if="hasIncidents && !incidents.hidden" class="wolf-card space-y-2" :aria-label="__('Open security incidents')">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="wolf-h2">{{ __('Open security incidents') }}</h2>
          <RouterLink class="wolf-link text-sm" :to="{ name: 'incidents' }">{{ __('All incidents') }}</RouterLink>
        </div>
        <p v-if="incidents.problem" role="alert" class="wolf-alert">{{ incidents.problem }}</p>
        <template v-else-if="incidents.data">
          <dl class="wolf-home-counts">
            <div v-for="sev in ['critical', 'warning', 'info']" :key="sev">
              <dt><SeverityGlyph :severity="sev" /></dt>
              <dd class="wolf-data">{{ incidents.data.by_severity[sev] }}</dd>
            </div>
          </dl>
          <ul v-if="incidents.data.newest.length" class="wolf-incidents">
            <li v-for="i in incidents.data.newest" :key="i.name">
              <SeverityGlyph :severity="i.severity" />
              <RouterLink class="font-medium text-ink-gray-9 hover:underline" :to="{ name: 'incident', params: { incident: i.name } }">{{ i.title }}</RouterLink>
              <div class="wolf-incidents-meta">
                <span>{{ scope(i) }}</span>
                <time class="wolf-data" :datetime="i.started_at" :title="full(i.started_at, tz)">{{ __('opened {0}', [timeAgo(i.started_at)]) }}</time>
                <span>{{ __(i.status, null, 'Wolf Incident') }}</span>
              </div>
            </li>
          </ul>
          <p v-else class="text-sm text-ink-gray-6">{{ __('No security incident open that you can see.') }}</p>
          <p v-if="shownMore(incidents.data.newest.length, incidents.data.by_severity.total)" class="text-sm text-ink-gray-6">
            {{ incidents.data.newest.length === 1 ? __('The newest of {0}.', [incidents.data.by_severity.total]) : __('The {0} newest of {1}.', [incidents.data.newest.length, incidents.data.by_severity.total]) }}
          </p>
        </template>
      </section>

      <section v-if="!responses.hidden" class="wolf-card space-y-2" :aria-label="__('Response actions')">
        <h2 class="wolf-h2">{{ __('Response actions') }}</h2>
        <p v-if="responses.problem" role="alert" class="wolf-alert">{{ responses.problem }}</p>
        <template v-else-if="responses.data">
          <dl class="wolf-facts text-sm">
            <dt>{{ __('Approved, waiting for their agent or satellite') }}</dt>
            <dd class="wolf-data">{{ responses.data.waiting }}</dd>
            <dt>{{ __('Failed in the last {0} days', [responses.data.failed_days]) }}</dt>
            <dd class="wolf-data" :style="responses.data.failed ? 'color: var(--wolf-critical)' : ''">{{ responses.data.failed }}</dd>
          </dl>
          <ul v-if="responses.data.newest.length" class="wolf-home-list text-sm">
            <li v-for="a in responses.data.newest" :key="a.name">
              <span class="text-ink-gray-9">{{ a.label }}</span>
              <span class="wolf-home-meta">
                <span>{{ __(a.status, null, 'Wolf Response Action') }}</span>
                <time :datetime="a.at" :title="full(a.at, tz)">{{ timeAgo(a.at) }}</time>
                <RouterLink v-if="a.incident" class="wolf-link" :to="{ name: 'incident', params: { incident: a.incident } }">{{ a.incident }}</RouterLink>
              </span>
              <span v-if="a.result" class="wolf-home-result">{{ a.result }}</span>
            </li>
          </ul>
          <p v-else class="text-sm text-ink-gray-6">{{ __('No action waiting, and none failed in the last {0} days.', [responses.data.failed_days]) }}</p>
        </template>
      </section>

      <section v-if="!journal.hidden" class="wolf-card space-y-2" :aria-label="__('Journal')">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="wolf-h2">{{ __('Tamper-evident journal') }}</h2>
          <RouterLink class="wolf-link text-sm" :to="{ name: 'security' }">{{ __('Verify the journal') }}</RouterLink>
        </div>
        <p v-if="journal.problem" role="alert" class="wolf-alert">{{ journal.problem }}</p>
        <template v-else-if="journal.data">
          <dl class="wolf-facts text-sm">
            <dt>{{ __('Newest signed entry') }}</dt>
            <dd v-if="journal.data.last_seq">
              <span>{{ __('entry {0}', [journal.data.last_seq]) }}</span>,
              <time :datetime="journal.data.last_at" :title="full(journal.data.last_at, tz)">{{ timeAgo(journal.data.last_at) }}</time>
            </dd>
            <dd v-else>{{ __('none yet') }}</dd>
            <dt>{{ __('Waiting to be signed') }}</dt>
            <dd class="wolf-data">{{ journal.data.pending }}</dd>
          </dl>
          <p v-if="journal.data.behind" role="status" class="text-sm" style="color: var(--wolf-warning)">
            {{ __('Signing is behind: the oldest unsigned entry was written {0}. Entries are signed every minute; check that the scheduler runs.', [timeAgo(journal.data.oldest_pending_at)]) }}
          </p>
          <p v-else class="text-sm text-ink-gray-6">{{ __('Signing runs: entries are signed within a minute.') }}</p>
          <p v-if="!journal.data.key" class="text-sm text-ink-gray-6">{{ __('No key yet: it is created with the first signature.') }}</p>
        </template>
      </section>

      <section v-if="!agents.hidden" class="wolf-card space-y-2" :aria-label="__('Agents')">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="wolf-h2">{{ __('Agents') }}</h2>
          <RouterLink class="wolf-link text-sm" :to="{ name: 'monitoring' }">{{ __('Monitoring') }}</RouterLink>
        </div>
        <p v-if="agents.problem" role="alert" class="wolf-alert">{{ agents.problem }}</p>
        <template v-else-if="agents.data">
          <dl v-if="agents.data.agents.total || agents.data.satellites.total" class="wolf-facts text-sm">
            <template v-if="agents.data.agents.total">
              <dt>{{ __('Agents') }}</dt>
              <dd>{{ __('{0} of {1} reporting (silent after {2} min)', [agents.data.agents.fresh, agents.data.agents.total, agents.data.silence_minutes]) }}</dd>
              <template v-if="agents.data.agents.stale">
                <dt>{{ __('Silent') }}</dt>
                <dd class="wolf-data" style="color: var(--wolf-warning)">{{ agents.data.agents.stale }}</dd>
              </template>
              <template v-if="agents.data.agents.never_seen">
                <dt>{{ __('Never reported') }}</dt>
                <dd class="wolf-data">{{ agents.data.agents.never_seen }}</dd>
              </template>
              <dt>{{ __('Host setup') }}</dt>
              <dd>
                <template v-if="agents.data.to_fix.length">
                  <span style="color: var(--wolf-warning)">{{ agents.data.to_fix.length > 1 ? __('{0} hosts to fix', [agents.data.to_fix.length]) : __('1 host to fix') }}</span>:
                  {{ agents.data.to_fix.map((h) => h.hostname).join(', ') }}
                </template>
                <template v-else-if="agents.data.setup_reported">{{ __('every reporting agent has what it needs') }}</template>
                <template v-else>{{ __('not reported yet (agents check their host every hour)') }}</template>
              </dd>
            </template>
            <template v-if="agents.data.satellites.total">
              <dt>{{ __('Satellites') }}</dt>
              <dd>{{ __('{0} of {1} forwarding', [agents.data.satellites.fresh, agents.data.satellites.total]) }}</dd>
            </template>
          </dl>
          <p v-else class="text-sm text-ink-gray-6">{{ __('No agent registered that you can see.') }}</p>
        </template>
      </section>
    </div>
  </div>
</template>
