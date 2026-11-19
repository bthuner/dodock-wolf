<script setup>
// The setup checklist (dodock_wolf/api/onboarding.py): from a fresh install to a first test
// alert, each step read from what Wolf knows. On the overview (`compact`) it shows only while
// something is left, then gets out of the way; the Monitoring page always lists every step.
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'

const props = defineProps({ compact: { type: Boolean, default: false } })

const data = ref(null)
const error = ref(null)
const expired = ref(false)

async function load() {
  error.value = null
  try {
    data.value = await call('dodock_wolf.api.onboarding.get_onboarding')
  } catch (e) {
    expired.value = !!e?.expired
    error.value = failure(e, __('the setup checklist'))
  }
}
onMounted(load)
defineExpose({ load })

const left = computed(() => (data.value ? data.value.steps.filter((s) => !s.done) : []))
const complete = computed(() => data.value && !left.value.length)
const shown = computed(() => (props.compact ? left.value : data.value?.steps || []))
const external = (href) => /^https?:/.test(href)
// a Wolf UI page goes through the router (its base is /wolf); Desk and the docs are links
const inApp = (href) => href === '/wolf' || href.startsWith('/wolf/')
</script>

<template>
  <section v-if="data && !(compact && complete)" class="wolf-card space-y-3" :aria-label="__('Set up Wolf')">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h2 class="wolf-h2">{{ __('Set up Wolf') }}</h2>
      <span class="text-sm text-ink-gray-6">{{ __('{0} of {1} done', [data.done, data.total]) }}</span>
    </div>
    <p v-if="complete" class="text-sm text-ink-gray-7">{{ __('Wolf has what it needs to wake someone up.') }}</p>
    <ol class="space-y-2">
      <li v-for="s in shown" :key="s.id" class="flex gap-3 text-sm">
        <span aria-hidden="true" class="mt-0.5 w-4 shrink-0 text-center" :style="s.done ? 'color: var(--wolf-ok)' : 'color: var(--wolf-muted)'">{{ s.done ? '✓' : '○' }}</span>
        <div class="min-w-0">
          <div class="font-medium text-ink-gray-9">
            {{ s.title }}<span class="sr-only">{{ s.done ? ' ' + __('(done)') : ' ' + __('(to do)') }}</span>
          </div>
          <div class="text-ink-gray-7">
            {{ s.detail }}
            <template v-if="s.action && !s.done">
              ·
              <a v-if="external(s.action.href)" :href="s.action.href" target="_blank" rel="noopener" class="underline">{{ s.action.label }}</a>
              <RouterLink v-else-if="inApp(s.action.href)" :to="s.action.href.slice(5) || '/'" class="underline">{{ s.action.label }}</RouterLink>
              <a v-else :href="s.action.href" class="underline">{{ s.action.label }}</a>
            </template>
          </div>
        </div>
      </li>
    </ol>
    <p v-if="compact && !complete" class="text-sm text-ink-gray-6">
      {{ __('This list goes away once every step is done; Monitoring keeps it.') }}
    </p>
  </section>
  <!-- the page says itself when the session ended: no second alert for the same thing -->
  <p v-else-if="error && !compact && !expired" role="alert" class="wolf-alert">{{ error }}</p>
</template>
