<script setup>
import { Button, PageHeader, TabButtons } from 'frappe-ui'
import { computed, inject, ref, watch } from 'vue'

import LiveStatus from '@/components/LiveStatus.vue'
import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import { useLive } from '@/composables/useLive'
import { useQueryParam } from '@/composables/useQueryParam'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'
import { duration, full } from '@/services/time'

const boot = inject('boot')
const tz = boot.time_zone

const STATUSES = ['unresolved', 'resolved', 'all']
const status = useQueryParam('status', 'unresolved', STATUSES)
const statusTabs = computed(() => [
  { value: 'unresolved', label: __('Unresolved') },
  { value: 'resolved', label: __('Resolved') },
  { value: 'all', label: __('All') },
])
const emptyText = computed(() => {
  if (status.value === 'unresolved') return __('No unresolved incidents you can see.')
  if (status.value === 'resolved') return __('No resolved incidents you can see.')
  return __('No incidents you can see.')
})

const incidents = ref([])
const paged = ref(false) // "Load more" was used: a refresh would drop those rows
const cursor = ref(null)
const hasMore = ref(false)
const loading = ref(false)
const error = ref(null)
let ticket = 0

async function load(append = false) {
  const mine = ++ticket
  loading.value = true
  error.value = null
  try {
    const page = await call('dodock_wolf.api.incident_view.list_incidents', {
      status: status.value,
      cursor: append ? cursor.value : null,
    })
    if (mine !== ticket) return // an older filter answered late
    const seen = new Set(append ? incidents.value.map((i) => i.name) : [])
    incidents.value = [...(append ? incidents.value : []), ...page.incidents.filter((i) => !seen.has(i.name))]
    paged.value = append
    cursor.value = page.paging.next_cursor
    hasMore.value = page.paging.has_more
  } catch (e) {
    if (mine === ticket) error.value = failure(e, __('these incidents'))
  } finally {
    if (mine === ticket) loading.value = false
  }
}

function scope(i) {
  return [i.site, i.bench, i.host].filter(Boolean).join(' · ')
}

watch(status, () => load(), { immediate: true })

const hub = inject('live', null)
const live = useLive(hub, {
  room: () => ({ doctype: 'Wolf Incident' }),
  matches: (m) => m.kind === 'incidents',
  refresh: async (reason) => {
    if (paged.value && reason !== 'manual') return false
    await load()
    return true
  },
})
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Incidents')" />
    <div class="flex items-center gap-2">
      <LiveStatus :live="live" :poll-seconds="hub?.pollSeconds" :pending-label="__('Incidents changed')" />
      <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="loading" @click="live.apply()" />
    </div>
  </PageHeader>
  <div class="wolf-page space-y-3">
    <TabButtons v-model="status" :options="statusTabs" />
    <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>
    <LoadingNote v-if="loading && !incidents.length && !error" :text="__('Loading incidents…')" />
    <ul v-if="incidents.length" class="wolf-card wolf-list">
      <li v-for="i in incidents" :key="i.name" :data-severity="i.resolved_at ? null : i.severity">
        <RouterLink :to="{ name: 'incident', params: { incident: i.name } }" class="wolf-list-row wolf-list-incident">
          <SeverityGlyph :severity="i.severity" />
          <div class="min-w-0">
            <div class="wolf-list-title">{{ i.title }}</div>
            <div class="wolf-list-sub">
              <span>{{ scope(i) }}</span>
              <span class="wolf-data">{{ i.name }}</span>
            </div>
          </div>
          <div class="wolf-list-end">
            <span class="wolf-badge">{{ __(i.status, null, 'Wolf Incident') }}</span>
            <div class="wolf-list-sub">
              <time class="wolf-data" :datetime="i.started_at">{{ full(i.started_at, tz) }}</time>
              <span v-if="i.resolved_at">, {{ __('lasted {0}', [duration(i.started_at, i.resolved_at)]) }}</span>
              <span v-if="i.assigned_name"> · {{ i.assigned_name }}</span>
              <span v-if="i.merged_into"> · {{ __('merged into {0}', [i.merged_into]) }}</span>
            </div>
          </div>
        </RouterLink>
      </li>
    </ul>
    <p v-if="!loading && !error && !incidents.length" class="text-sm text-ink-gray-6">
      {{ emptyText }}
    </p>
    <Button v-if="hasMore" :label="__('Load more')" :loading="loading" @click="load(true)" />
  </div>
</template>
