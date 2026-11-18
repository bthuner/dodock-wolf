<script setup>
import { PageHeader } from 'frappe-ui'
import { computed, inject, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'
import { clock, day, full } from '@/services/time'

const route = useRoute()
const boot = inject('boot')
const tz = boot.time_zone
const group = ref(null)
const error = ref(null)

async function load() {
  error.value = null
  group.value = null // another fingerprint: never show the previous group under it
  try {
    group.value = await call('dodock_wolf.api.explore.get_error_group', { fingerprint: route.params.fingerprint })
  } catch (e) {
    group.value = null
    error.value = e.status === 404 ? __('No error group with this fingerprint that you can see.') : failure(e, __('this error group'))
  }
}
watch(() => route.params.fingerprint, load, { immediate: true })

const payload = computed(() => group.value?.representative.payload || {})
const traceback = computed(() => payload.value.traceback || payload.value.exception || null)
const rest = computed(() => {
  const { traceback: _t, exception: _e, ...others } = payload.value
  return Object.keys(others).length ? JSON.stringify(others, null, 2) : ''
})
const where = (s) => [s.site, s.bench, s.host].filter(Boolean).join(' · ')
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Error group')" />
  </PageHeader>
  <section v-if="error" class="max-w-2xl space-y-3 p-5 text-base text-ink-gray-8">
    <p role="alert" class="wolf-alert">{{ error }}</p>
    <RouterLink class="wolf-link" :to="{ name: 'errors' }">{{ __('Back to errors') }}</RouterLink>
  </section>
  <div v-else-if="!group" class="p-5"><LoadingNote :text="__('Loading the error group…')" /></div>
  <div v-else class="wolf-page space-y-5">
    <header class="wolf-card wolf-incident-head" :data-severity="group.severity">
      <SeverityGlyph :severity="group.severity" />
      <h1 class="wolf-incident-title">{{ group.title }}</h1>
      <dl class="wolf-factgrid">
        <div><dt>{{ __('Records') }}</dt><dd class="wolf-data">{{ group.records }}</dd></div>
        <div><dt>{{ __('Reported occurrences') }}</dt><dd class="wolf-data">{{ group.occurrences }}</dd></div>
        <div><dt>{{ __('First seen') }}</dt><dd class="wolf-data">{{ full(group.first_seen, tz) }}</dd></div>
        <div><dt>{{ __('Last seen') }}</dt><dd class="wolf-data">{{ full(group.last_seen, tz) }}</dd></div>
        <div class="wolf-factgrid-wide"><dt>{{ __('Fingerprint') }}</dt><dd class="wolf-data break-all">{{ group.fingerprint }}</dd></div>
      </dl>
      <p class="text-sm text-ink-gray-6">{{ __('Every record of this group you may see, whatever its age.') }}</p>
    </header>

    <section class="wolf-card wolf-tablecard" :aria-label="__('Where')">
      <h2 class="wolf-h2">{{ __('Where it happened') }}</h2>
      <table class="wolf-table">
        <thead>
          <tr>
            <th>{{ __('Site · bench · host') }}</th>
            <th class="wolf-num">{{ __('Records') }}</th>
            <th class="wolf-num">{{ __('Reported') }}</th>
            <th>{{ __('First seen') }}</th>
            <th>{{ __('Last seen') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in group.scopes" :key="where(s)">
            <td>
              <RouterLink v-if="s.site" class="wolf-link" :to="{ name: 'site', params: { site: s.site } }">{{ s.site }}</RouterLink>
              <span class="text-ink-gray-6">{{ s.site ? ' · ' : '' }}{{ [s.bench, s.host].filter(Boolean).join(' · ') }}</span>
            </td>
            <td class="wolf-data wolf-num">{{ s.records }}</td>
            <td class="wolf-data wolf-num">{{ s.occurrences }}</td>
            <td class="wolf-data">{{ day(s.first_seen, tz) }} {{ clock(s.first_seen, tz) }}</td>
            <td class="wolf-data">{{ day(s.last_seen, tz) }} {{ clock(s.last_seen, tz) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="group.incidents.length || group.incidents_not_visible" class="wolf-card space-y-2" :aria-label="__('Incidents')">
      <h2 class="wolf-h2">{{ __('Incidents with these errors') }}</h2>
      <p v-for="i in group.incidents" :key="i.name" class="flex flex-wrap items-baseline gap-x-2 text-sm">
        <SeverityGlyph :severity="i.severity" :show-label="false" />
        <RouterLink class="wolf-link wolf-data" :to="{ name: 'incident', params: { incident: i.name } }">{{ i.name }}</RouterLink>
        <span class="font-medium text-ink-gray-9">{{ i.title }}</span> <span class="text-ink-gray-6">({{ __(i.status, null, 'Wolf Incident') }})</span>
      </p>
      <p v-if="group.incidents_not_visible" class="text-sm text-ink-gray-6">{{ __('and {0} you may not see', [group.incidents_not_visible]) }}</p>
    </section>

    <section class="wolf-card space-y-2" :aria-label="__('Newest record')">
      <h2 class="wolf-h2">{{ __('Newest record') }}</h2>
      <p class="text-sm text-ink-gray-6">
        {{ __('{0} · last seen {1}', [where(group.representative), full(group.representative.last_seen, tz)]) }}
      </p>
      <pre v-if="traceback" class="wolf-data wolf-details">{{ traceback }}</pre>
      <pre v-if="rest" class="wolf-data wolf-details">{{ rest }}</pre>
      <p v-if="!traceback && !rest" class="text-sm text-ink-gray-6">{{ __('This record carries no details.') }}</p>
    </section>

    <section class="wolf-card space-y-2" :aria-label="__('Records')">
      <h2 class="wolf-h2">{{ __('Records, most recently seen first') }}</h2>
      <ul class="wolf-rows">
        <li v-for="r in group.recent_records" :key="r.name">
          <time class="wolf-data text-ink-gray-6" :title="__('last seen {0}', [full(r.last_seen, tz)])">{{ day(r.last_seen, tz) }} {{ clock(r.last_seen, tz) }}</time>
          <span>{{ where(r) }}</span>
          <span v-if="r.count > 1" class="wolf-data text-ink-gray-6">{{ __('{0} reported', [r.count]) }}</span>
          <RouterLink v-if="r.incident" class="wolf-link" :to="{ name: 'incident', params: { incident: r.incident } }">{{ r.incident }}</RouterLink>
        </li>
      </ul>
      <p v-if="group.more_records" class="text-sm text-ink-gray-6">{{ __('Older records are not listed; the counts above include them.') }}</p>
    </section>
  </div>
</template>
