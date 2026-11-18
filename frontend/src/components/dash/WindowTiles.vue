<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { __ } from '@/services/i18n'
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
  return w.relative
    ? __('last {0}', [w.relative])
    : __('{0} to {1}', [full(w.since, props.timeZone, { zone: false }), full(w.until, props.timeZone, { zone: false })])
})
</script>

<template>
  <section :aria-label="__('In this window')" class="space-y-2">
    <h2 class="wolf-label">{{ __('In this window') }}<template v-if="label"> · <span class="wolf-data wolf-label-data">{{ label }}</span></template></h2>
    <dl class="wolf-tiles">
      <div class="wolf-tile">
        <dt>{{ __('Event records') }}</dt>
        <dd class="wolf-data wolf-tile-figure">{{ counts.events.records }}</dd>
        <dd class="wolf-tile-note">
          {{ __('{0} occurrences', [counts.events.occurrences]) }} · <RouterLink class="wolf-link" :to="to('events')">{{ __('Events') }}</RouterLink>
        </dd>
      </div>
      <div class="wolf-tile">
        <dt>{{ __('Errors') }}</dt>
        <dd class="wolf-data wolf-tile-figure">{{ records('error') }}</dd>
        <dd class="wolf-tile-note">
          {{ __('records') }} · <RouterLink class="wolf-link" :to="to('errors')">{{ __('Error groups') }}</RouterLink>
        </dd>
      </div>
      <div class="wolf-tile">
        <dt>{{ __('Cron and worker failures') }}</dt>
        <dd class="wolf-data wolf-tile-figure">{{ records('cron_failure') + records('worker_failure') }}</dd>
        <dd class="wolf-tile-note">
          <RouterLink class="wolf-link" :to="to('events', { type: 'cron_failure' })">{{ __('{0} cron', [records('cron_failure')]) }}</RouterLink> ·
          <RouterLink class="wolf-link" :to="to('events', { type: 'worker_failure' })">{{ __('{0} worker', [records('worker_failure')]) }}</RouterLink>
        </dd>
      </div>
      <div v-if="incidents" class="wolf-tile">
        <dt>{{ __('Incidents opened') }}</dt>
        <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.opened_in_window }}</dd>
        <dd class="wolf-tile-note">{{ __('{0} resolved', [counts.incidents.resolved_in_window]) }}</dd>
      </div>
      <div v-else class="wolf-tile">
        <dt>{{ __('Security events') }}</dt>
        <dd class="wolf-data wolf-tile-figure">{{ records('security') }}</dd>
        <dd class="wolf-tile-note"><RouterLink class="wolf-link" :to="to('events', { type: 'security' })">{{ __('Events') }}</RouterLink></dd>
      </div>
    </dl>
  </section>
</template>
