<script setup>
import { PageHeader } from 'frappe-ui'
import { computed, inject } from 'vue'
import { useRoute } from 'vue-router'

import PageTitle from '@/components/PageTitle.vue'
import { routeText } from '@/router'
import { deskFallback } from '@/services/boot'
import { __ } from '@/services/i18n'

// A view of #19 that is not built yet. It says so and hands over to the Desk page that does
// the job today; it never shows made-up numbers.
const route = useRoute()
const boot = inject('boot')
const desk = computed(() => deskFallback(boot, route))
// a satellite keeps no incidents: its central site opens them
const unavailable = computed(() => route.meta.capability && !boot.capabilities?.[route.meta.capability]?.available)
const title = computed(() => routeText(route.meta.title))
const subject = computed(() =>
  route.meta.noSubject ? '' : Object.values(route.params).flat().filter(Boolean).join(' / '),
)
</script>

<template>
  <PageHeader>
    <PageTitle :title="subject ? `${title}: ${subject}` : title" />
  </PageHeader>
  <section v-if="unavailable" class="max-w-2xl space-y-3 p-5 text-base text-ink-gray-8">
    <p>
      {{ __('This site is a satellite: it forwards its telemetry to a central Wolf site, which opens and keeps the incidents. Look for {0} there.', [title.toLowerCase()]) }}
    </p>
  </section>
  <section v-else class="max-w-2xl space-y-3 p-5 text-base text-ink-gray-8">
    <p>
      {{ __('This view is not built yet. When it is, it will show:') }}
      <span class="text-ink-gray-9">{{ routeText(route.meta.planned) }}</span>
    </p>
    <p v-if="desk">
      {{ __('Desk has it today:') }}
      <a class="wolf-link" :href="desk">{{ __('open {0} in Desk', [title.toLowerCase()]) }}</a>.
    </p>
  </section>
</template>
