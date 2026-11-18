<script setup>
import { Button, PageHeader } from 'frappe-ui'
import { inject } from 'vue'

import ExploreFilters from '@/components/ExploreFilters.vue'
import LiveStatus from '@/components/LiveStatus.vue'
import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import { useExplore } from '@/composables/useExplore'
import { useLive } from '@/composables/useLive'
import { __ } from '@/services/i18n'
import { full } from '@/services/time'

const boot = inject('boot')
const tz = boot.time_zone
const list = useExplore('dodock_wolf.api.explore.list_error_groups', 'groups', { itemKey: (g) => g.fingerprint })

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
    <PageTitle :title="__('Errors')" />
    <div class="flex items-center gap-2">
      <LiveStatus :live="live" :poll-seconds="hub?.pollSeconds" :pending-label="__('New events recorded')" />
      <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="list.loading.value" @click="live.apply()" />
    </div>
  </PageHeader>
  <div class="wolf-page space-y-3">
    <ExploreFilters />
    <p class="text-sm text-ink-gray-6">
      {{
        __(
          "Groups with error records active in the window. Their figures cover all their records you may see, whatever their age; occurrences add up each record's reported count, so they are not a count for the window.",
        )
      }}
    </p>
    <p v-if="list.error.value" role="alert" class="wolf-alert">{{ list.error.value }}</p>
    <div v-if="list.items.value.length" class="wolf-card wolf-tablecard">
      <table class="wolf-table">
        <thead>
          <tr>
            <th class="wolf-th-main">{{ __('Error') }}</th>
            <th class="wolf-num">{{ __('Records') }}</th>
            <th class="wolf-num wolf-th-wrap">{{ __('Reported occurrences') }}</th>
            <th class="wolf-num">{{ __('Sites') }}</th>
            <th>{{ __('First seen') }}</th>
            <th>{{ __('Last seen') }}</th>
            <th class="wolf-num">{{ __('Incidents') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="g in list.items.value" :key="g.fingerprint" :data-severity="g.severity">
            <td>
              <div class="flex items-baseline gap-2">
                <SeverityGlyph :severity="g.severity" :show-label="false" />
                <RouterLink class="wolf-table-title hover:underline" :to="{ name: 'error-group', params: { fingerprint: g.fingerprint } }">{{ g.title }}</RouterLink>
              </div>
              <div class="wolf-table-sub">{{ [g.latest.site, g.latest.bench, g.latest.host].filter(Boolean).join(' · ') }}</div>
            </td>
            <td class="wolf-data wolf-num">{{ g.records }}<span v-if="g.records_in_window !== g.records" class="wolf-table-sub wolf-table-under">{{ ' ' + __('({0} in window)', [g.records_in_window]) }}</span></td>
            <td class="wolf-data wolf-num">{{ g.occurrences }}</td>
            <td class="wolf-data wolf-num">{{ g.sites }}<span v-if="g.host_wide" class="wolf-table-sub wolf-table-under">{{ ' ' + __('+ host-wide') }}</span></td>
            <td class="wolf-data"><time :datetime="g.first_seen">{{ full(g.first_seen, tz, { zone: false }) }}</time></td>
            <td class="wolf-data"><time :datetime="g.last_seen">{{ full(g.last_seen, tz, { zone: false }) }}</time></td>
            <td class="wolf-data wolf-num">{{ g.incidents || '' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <LoadingNote v-if="list.loading.value && !list.items.value.length && !list.error.value" :text="__('Loading error groups…')" />
    <p v-if="!list.loading.value && !list.error.value && !list.items.value.length" class="text-sm text-ink-gray-6">{{ __('No error groups match.') }}</p>
    <p v-if="list.items.value.length" class="text-sm text-ink-gray-6">{{ __('Times in {0}.', [tz]) }}</p>
    <Button v-if="list.hasMore.value" :label="__('Load more')" :loading="list.loading.value" @click="list.load(true)" />
  </div>
</template>
