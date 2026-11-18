<script setup>
import { Button, PageHeader, TabButtons } from 'frappe-ui'
import { computed, inject, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import LiveStatus from '@/components/LiveStatus.vue'
import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import { useLive } from '@/composables/useLive'
import { useWindow } from '@/composables/useWindow'
import CountTiles from '@/components/dash/CountTiles.vue'
import HttpChart from '@/components/dash/HttpChart.vue'
import InventoryPanel from '@/components/dash/InventoryPanel.vue'
import MonitoringPanel from '@/components/dash/MonitoringPanel.vue'
import SignalsPanel from '@/components/dash/SignalsPanel.vue'
import WindowTiles from '@/components/dash/WindowTiles.vue'
import WindowNote from '@/components/WindowNote.vue'
import { call, failure } from '@/services/api'
import { clock, full } from '@/services/time'

// The overview (no scope) and the site, host and bench dashboards (scope from the route).
const route = useRoute()
const boot = inject('boot')
const tz = boot.time_zone

const RANGES = ['1h', '6h', '24h', '7d'].map((r) => ({ value: r, label: r }))
// relative (the tabs) or explicit (a range selected on the HTTP chart): counts and HTTP read it
const win = useWindow(RANGES.map((r) => r.value))
const scope = computed(() => {
  const { site, host, bench } = route.params
  return Object.fromEntries(Object.entries({ site, host, bench }).filter(([, v]) => v))
})
const title = computed(() => {
  const s = scope.value
  if (s.bench) return `Bench ${s.bench} on ${s.host}`
  if (s.host) return `Host ${s.host}`
  if (s.site) return `Site ${s.site}`
  return 'Overview'
})
const isOverview = computed(() => !Object.keys(scope.value).length)
// a satellite keeps no incidents: saying "none open" would suggest all is well
const hasIncidents = computed(() => boot.capabilities?.incidents?.available)

const data = ref({})
const errors = ref({})
const loading = ref(false)
let ticket = 0

const PANELS = { counts: 'these counts', http: 'HTTP activity', signals: 'these signals', incidents: 'these incidents', inventory: 'the inventory', monitoring: "Wolf's own monitoring" }

async function load() {
  const mine = ++ticket
  loading.value = true
  const args = { ...scope.value, ...win.args.value }
  const jobs = {
    counts: call('dodock_wolf.api.scope.get_counts', args),
    http: call('dodock_wolf.api.dashboard.get_http', args),
    signals: call('dodock_wolf.api.dashboard.get_signals', scope.value),
  }
  if (hasIncidents.value) {
    jobs.incidents = call('dodock_wolf.api.incident_view.list_incidents', { ...scope.value, status: 'unresolved', limit: 10 })
  }
  if (isOverview.value || scope.value.host) jobs.inventory = call('dodock_wolf.api.scope.get_inventory', {})
  if (isOverview.value) jobs.monitoring = call('dodock_wolf.api.dashboard.get_monitoring', {})
  const settled = await Promise.allSettled(Object.values(jobs))
  if (mine !== ticket) return // a newer range or scope is loading
  const next = {}
  const failed = {}
  Object.keys(jobs).forEach((k, i) => {
    if (settled[i].status === 'fulfilled') next[k] = settled[i].value
    else failed[k] = failure(settled[i].reason, PANELS[k]) // each panel says it failed; the others still show
  })
  data.value = next
  errors.value = failed
  loading.value = false
}

// the inventory part for this page: every host on the overview, this host's benches on a host page
const hosts = computed(() => {
  const all = data.value.inventory?.hosts || []
  return scope.value.host ? all.filter((h) => h.host === scope.value.host) : all
})
// another scope: drop the previous one's panels at once, so its numbers never sit under the
// new title while the new ones load
watch(scope, () => {
  data.value = {}
  errors.value = {}
})
watch([scope, win.args], load, { immediate: true })

// incidents and events are announced; metrics are not (they arrive every 30 s), so the
// dashboard also refreshes on the polling timer while live. Its windows are relative: they move.
const hub = inject('live', null)
const live = useLive(hub, {
  room: () => [{ doctype: 'Wolf Incident' }, { doctype: 'Wolf Event' }],
  matches: (m) => m.kind === 'incidents' || m.kind === 'events',
  refresh: async () => {
    await load()
    return true
  },
  pollAlways: true,
  // messages carry no scope: an unrelated host's events would reload every panel; at most one
  // reload per 10 s per tab
  debounceMs: 10000,
})
</script>

<template>
  <PageHeader>
    <PageTitle :title="title" />
    <div class="flex items-center gap-2">
      <TabButtons :model-value="win.explicit.value ? null : win.range.value" :options="RANGES" @update:model-value="win.choose" />
      <LiveStatus :live="live" :poll-seconds="hub?.pollSeconds" />
      <Button label="Refresh" icon-left="lucide-refresh-cw" :loading="loading" @click="live.apply()" />
    </div>
  </PageHeader>

  <div class="wolf-page space-y-5">
    <p v-if="data.counts?.restricted" class="text-sm text-ink-gray-6">You see the sites, benches and hosts you were granted.</p>

    <WindowNote v-if="win.explicit.value" v-bind="win.explicit.value" :time-zone="tz" @reset="win.reset" />

    <LoadingNote v-if="loading && !data.counts && !errors.counts" what="the counts" />
    <CountTiles v-if="data.counts" :counts="data.counts" />
    <p v-else-if="errors.counts" role="alert" class="wolf-alert">Counts: {{ errors.counts }}</p>

    <section v-if="hasIncidents" class="wolf-card space-y-2" aria-label="Unresolved incidents">
      <div class="flex items-baseline justify-between">
        <h2 class="text-base font-semibold text-ink-gray-9">Unresolved incidents</h2>
        <RouterLink class="wolf-link text-sm" :to="{ name: 'incidents' }">All incidents</RouterLink>
      </div>
      <p v-if="errors.incidents" role="alert" class="wolf-alert">{{ errors.incidents }}</p>
      <ul v-else-if="data.incidents?.incidents.length" class="wolf-incidents">
        <li v-for="i in data.incidents.incidents" :key="i.name">
          <SeverityGlyph :severity="i.severity" />
          <RouterLink class="font-medium text-ink-gray-9 hover:underline" :to="{ name: 'incident', params: { incident: i.name } }">{{ i.title }}</RouterLink>
          <div class="wolf-incidents-meta">
            <span>{{ [i.site, i.bench, i.host].filter(Boolean).join(' · ') }}</span>
            <span class="wolf-data" :title="full(i.started_at, tz)">since {{ clock(i.started_at, tz) }}</span>
            <span>{{ i.status }}</span>
          </div>
        </li>
      </ul>
      <p v-else-if="data.incidents" class="text-sm text-ink-gray-6">None open that you can see.</p>
      <p v-if="data.incidents?.paging.has_more && data.counts" class="text-sm text-ink-gray-6">
        The 10 newest of {{ data.counts.incidents.unresolved }}.
      </p>
    </section>

    <WindowTiles v-if="data.counts?.events" :counts="data.counts" :window-query="win.query.value" :scope="scope" :incidents="hasIncidents" :time-zone="tz" />

    <HttpChart v-if="data.http" :http="data.http" :time-zone="tz" @select="win.select" />
    <p v-else-if="errors.http" role="alert" class="wolf-alert">HTTP: {{ errors.http }}</p>
    <LoadingNote v-else-if="loading" what="HTTP activity" />

    <section v-if="data.http?.deployments.length" class="wolf-card space-y-1" aria-label="Recent changes">
      <h2 class="text-base font-semibold text-ink-gray-9">Deployments in this window</h2>
      <ul class="text-sm">
        <li v-for="d in data.http.deployments" :key="d.name" class="flex flex-wrap gap-x-3 py-0.5">
          <time class="wolf-data text-ink-gray-6" :title="full(d.at, tz)">{{ clock(d.at, tz) }}</time>
          <span class="text-ink-gray-9">{{ d.title }}</span>
          <span class="text-ink-gray-6">{{ [d.site, d.bench, d.host].filter(Boolean).join(' · ') }}</span>
        </li>
      </ul>
    </section>

    <SignalsPanel v-if="data.signals" :signals="data.signals" :time-zone="tz" />
    <p v-else-if="errors.signals" role="alert" class="wolf-alert">Signals: {{ errors.signals }}</p>
    <LoadingNote v-else-if="loading" what="the signals" />
    <p v-if="errors.inventory" role="alert" class="wolf-alert">Inventory: {{ errors.inventory }}</p>

    <InventoryPanel v-if="hosts.length" :inventory="data.inventory" :host="scope.host || ''" :time-zone="tz" />

    <MonitoringPanel v-if="data.monitoring" :monitoring="data.monitoring" :time-zone="tz" compact />
    <p v-else-if="errors.monitoring" role="alert" class="wolf-alert">Monitoring: {{ errors.monitoring }}</p>
  </div>
</template>
