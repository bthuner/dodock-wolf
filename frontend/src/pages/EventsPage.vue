<script setup>
import { Button, PageHeader } from 'frappe-ui'
import { inject, ref } from 'vue'

import ExploreFilters from '@/components/ExploreFilters.vue'
import LiveStatus from '@/components/LiveStatus.vue'
import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import { useExplore } from '@/composables/useExplore'
import { useLive } from '@/composables/useLive'
import { __ } from '@/services/i18n'
import { call } from '@/services/api'
import { EVENT_TYPES, SEVERITIES, pick } from '@/services/filters'
import { clock, day, full } from '@/services/time'

const boot = inject('boot')
const tz = boot.time_zone
const list = useExplore('dodock_wolf.api.explore.list_events', 'events', {
  itemKey: (e) => e.name,
  extraArgs: (q) => ({ event_type: pick(q.type, EVENT_TYPES), severity: pick(q.severity, SEVERITIES) }),
})

// payloads load when a row opens, and show as text
const open = ref({})
async function toggle(name) {
  if (open.value[name]) {
    const { [name]: _, ...rest } = open.value
    open.value = rest
    return
  }
  open.value = { ...open.value, [name]: { loading: true } }
  try {
    const event = await call('dodock_wolf.api.explore.get_event', { name })
    open.value = { ...open.value, [name]: { text: JSON.stringify(event.payload, null, 2) } }
  } catch (e) {
    open.value = { ...open.value, [name]: { error: e.message } }
  }
}
const where = (e) => [e.site, e.bench, e.host].filter(Boolean).join(' · ')

// new events never reshuffle the list under the reader: a button offers them
const hub = inject('live', null)
const live = useLive(hub, {
  room: () => ({ doctype: 'Wolf Event' }),
  matches: (m) => m.kind === 'events',
  refresh: async (reason) => {
    if (reason !== 'manual') return false
    await list.load()
    return true
  },
  polls: false, // a poll would only reshuffle the list: the reader refreshes
})
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Events')" />
    <div class="flex items-center gap-2">
      <LiveStatus :live="live" :poll-seconds="hub?.pollSeconds" :pending-label="__('New events recorded')" />
      <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="list.loading.value" @click="live.apply()" />
    </div>
  </PageHeader>
  <div class="wolf-page space-y-3">
    <ExploreFilters types />
    <p v-if="list.meta.value" class="text-sm text-ink-gray-6">
      {{ __("Event records active in the window, newest first; times in {0}. A record's count is every repeat it absorbed, inside the window or not.", [tz]) }}
    </p>
    <p v-if="list.error.value" role="alert" class="wolf-alert">{{ list.error.value }}</p>
    <ul v-if="list.items.value.length" class="wolf-card wolf-list">
      <li v-for="e in list.items.value" :key="e.name" :data-severity="e.severity" :data-open="open[e.name] ? '' : null">
        <div class="wolf-list-row wolf-list-event">
          <time class="wolf-data wolf-list-time" :datetime="e.first_seen" :title="full(e.first_seen, tz)">{{ day(e.first_seen, tz) }} {{ clock(e.first_seen, tz) }}</time>
          <SeverityGlyph :severity="e.severity" />
          <div class="min-w-0">
            <div class="flex flex-wrap items-baseline gap-x-2">
              <span class="wolf-list-title">{{ e.title }}</span>
              <span class="wolf-badge">{{ e.event_type.replace(/_/g, ' ') }}</span>
            </div>
            <div class="wolf-list-sub">
              <span>{{ where(e) }}</span>
              <span v-if="e.count > 1" class="wolf-data">{{ __('{0} reported, last {1}', [e.count, clock(e.last_seen, tz)]) }}</span>
              <span v-if="e.category">{{ e.category }}</span>
              <RouterLink v-if="e.incident" class="wolf-link" :to="{ name: 'incident', params: { incident: e.incident } }">{{ e.incident }}</RouterLink>
              <RouterLink v-if="e.event_type === 'error' && e.fingerprint" class="wolf-link" :to="{ name: 'error-group', params: { fingerprint: e.fingerprint } }">{{ __('error group') }}</RouterLink>
              <button type="button" class="wolf-link" :aria-expanded="!!open[e.name]" @click="toggle(e.name)">{{ open[e.name] ? __('Hide details') : __('Details') }}</button>
            </div>
            <template v-if="open[e.name]">
              <p v-if="open[e.name].error" role="alert" class="wolf-alert mt-2">{{ open[e.name].error }}</p>
              <pre v-else-if="open[e.name].text" class="wolf-data wolf-details">{{ open[e.name].text }}</pre>
            </template>
          </div>
        </div>
      </li>
    </ul>
    <LoadingNote v-if="list.loading.value && !list.items.value.length && !list.error.value" :text="__('Loading events…')" />
    <p v-if="!list.loading.value && !list.error.value && !list.items.value.length" class="text-sm text-ink-gray-6">{{ __('No event records match.') }}</p>
    <Button v-if="list.hasMore.value" :label="__('Load more')" :loading="list.loading.value" @click="list.load(true)" />
  </div>
</template>
