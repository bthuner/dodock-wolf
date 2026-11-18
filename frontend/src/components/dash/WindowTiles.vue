<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { full } from '@/services/time'

// What happened in the window, from get_counts: exact counts, never computed from a list on
// screen. Each figure links to its explorer with the same window and scope.
const props = defineProps({
  counts: { type: Object, required: true },
  windowQuery: { type: Object, required: true }, // { range } or { since, until }, as the URL holds it
  scope: { type: Object, required: true },
  incidents: { type: Boolean, default: false },
  timeZone: { type: String, required: true },
})

const types = computed(() => props.counts.events.by_type || {})
const records = (type) => types.value[type]?.records || 0
const to = (name, extra = {}) => ({ name, query: { ...props.windowQuery, ...props.scope, ...extra } })
const label = computed(() => {
  const w = props.counts.window
  if (!w) return ''
  return w.relative ? `last ${w.relative}` : `${full(w.since, props.timeZone, { zone: false })} to ${full(w.until, props.timeZone, { zone: false })}`
})
</script>

<template>
  <section aria-label="In this window" class="space-y-2">
    <h2 class="wolf-label">In this window<template v-if="label"> · <span class="wolf-data wolf-label-data">{{ label }}</span></template></h2>
    <dl class="wolf-tiles">
      <div class="wolf-tile">
        <dt>Event records</dt>
        <dd class="wolf-data wolf-tile-figure">{{ counts.events.records }}</dd>
        <dd class="wolf-tile-note">
          {{ counts.events.occurrences }} occurrences · <RouterLink class="wolf-link" :to="to('events')">Events</RouterLink>
        </dd>
      </div>
      <div class="wolf-tile">
        <dt>Errors</dt>
        <dd class="wolf-data wolf-tile-figure">{{ records('error') }}</dd>
        <dd class="wolf-tile-note">
          records · <RouterLink class="wolf-link" :to="to('errors')">Error groups</RouterLink>
        </dd>
      </div>
      <div class="wolf-tile">
        <dt>Cron and worker failures</dt>
        <dd class="wolf-data wolf-tile-figure">{{ records('cron_failure') + records('worker_failure') }}</dd>
        <dd class="wolf-tile-note">
          <RouterLink class="wolf-link" :to="to('events', { type: 'cron_failure' })">{{ records('cron_failure') }} cron</RouterLink> ·
          <RouterLink class="wolf-link" :to="to('events', { type: 'worker_failure' })">{{ records('worker_failure') }} worker</RouterLink>
        </dd>
      </div>
      <div v-if="incidents" class="wolf-tile">
        <dt>Incidents opened</dt>
        <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.opened_in_window }}</dd>
        <dd class="wolf-tile-note">{{ counts.incidents.resolved_in_window }} resolved</dd>
      </div>
      <div v-else class="wolf-tile">
        <dt>Security events</dt>
        <dd class="wolf-data wolf-tile-figure">{{ records('security') }}</dd>
        <dd class="wolf-tile-note"><RouterLink class="wolf-link" :to="to('events', { type: 'security' })">Events</RouterLink></dd>
      </div>
    </dl>
  </section>
</template>
