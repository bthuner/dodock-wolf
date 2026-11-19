<script setup>
import { Button } from 'frappe-ui'
import { computed, reactive } from 'vue'
import { RouterLink } from 'vue-router'

import { __, locale } from '@/services/i18n'
import { timeAgo, full } from '@/services/time'

// The newest value of each signal series and its state, as the server judged it
// (wolf/catalog.py). The panel adds no threshold of its own.
const props = defineProps({
  signals: { type: Object, required: true },
  timeZone: { type: String, required: true },
})

// label: a row's state; count(n): a group's tally of rows in that state
const STATE = {
  firing: { label: () => __('Rule firing'), count: (n) => (n === 1 ? __('1 rule firing') : __('{0} rules firing', [n])), glyph: '●', color: 'var(--wolf-critical)' },
  stale: { label: () => __('No new data'), count: (n) => __('{0} no new data', [n]), glyph: '◌', color: 'var(--wolf-warning)' },
  watched: { label: () => __('Within its rules'), count: (n) => __('{0} within its rules', [n]), glyph: '✓', color: 'var(--wolf-ok)' },
  unwatched: { label: () => __('No rule watches this'), count: (n) => __('{0} no rule watches this', [n]), glyph: '–', color: 'var(--wolf-muted)' },
}
// in the order drawn
const GROUPS = {
  workers: () => __('Workers and queues'),
  processes: () => __('Bench processes'),
  redis: () => __('Redis'),
  database: () => __('Database'),
  backups: () => __('Backups'),
  tls: () => __('TLS certificates'),
  security: () => __('Security exposure'),
  host: () => __('Host setup'),
}

// Each group draws its first rows; the rest on demand. The server sorts problems first, so the
// rows drawn are a group's firing and stale ones before the others. Drawing all 300 series took
// 0.1 to 0.3 s of every overview (docs/load-test.md).
const FIRST_ROWS = 10
const missingLabels = computed(() => (props.signals.missing || []).map((m) => m.label).join(', '))
const shown = reactive({}) // groups opened in full; kept while the page refreshes the same scope

const groups = computed(() => {
  const by = {}
  for (const s of props.signals.series) (by[s.group] ||= []).push(s)
  return Object.keys(GROUPS).filter((g) => by[g]).map((g) => {
    const all = by[g]
    const open = shown[g] || all.length <= FIRST_ROWS
    const hidden = open ? [] : all.slice(FIRST_ROWS)
    return {
      key: g, label: GROUPS[g](), series: open ? all : all.slice(0, FIRST_ROWS), counts: props.signals.counts[g] || {},
      total: all.length, hidden: hidden.length, hiddenProblems: hidden.filter((s) => s.state === 'firing' || s.state === 'stale').length,
      canFold: shown[g] && all.length > FIRST_ROWS,
    }
  })
})
const where = (s) => [s.site, s.bench, s.host].filter(Boolean).join(' · ')
const label = (s) => (s.label_key ? `${s.label} (${s.label_key})` : s.label)
const value = (s) => (s.value == null ? '' : `${Number(s.value).toLocaleString(locale(), { maximumFractionDigits: 2 })} ${s.unit}`)
const rule = (r) => __('{0}: {1} {2} {3} over {4} min', [r.rule_name, r.aggregation, r.operator, r.threshold, r.window_minutes])
function moreLabel(g) {
  return g.hiddenProblems
    ? __('Show the other {0} of {1}, {2} with a problem', [g.hidden, g.total, g.hiddenProblems])
    : __('Show the other {0} of {1}', [g.hidden, g.total])
}
function emailLabel(category, e) {
  return category === 'email_queue_backlog'
    ? __('Backlog reported: {0} event records, last', [e.records])
    : __('Sending errors reported: {0} event records, last', [e.records])
}
const email = computed(() => Object.entries(props.signals.email || {}))
</script>

<template>
  <section class="wolf-card space-y-4" :aria-label="__('Signals')">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h2 class="text-base font-semibold text-ink-gray-9">{{ __('Signals') }}</h2>
      <span class="text-sm text-ink-gray-6">{{ __('newest value of each series; thresholds come from the alert rules') }}</span>
    </div>
    <p v-if="signals.truncated" class="text-sm text-ink-gray-6">
      {{ __('Showing {0} of {1} series, problems first. The counts per group are exact.', [signals.series.length, signals.total_series]) }}
    </p>

    <div v-for="g in groups" :key="g.key" class="space-y-1">
      <h3 class="text-sm font-semibold text-ink-gray-8">
        {{ g.label }}
        <span class="font-normal text-ink-gray-6">
          <template v-for="(n, st) in g.counts" :key="st"> · {{ STATE[st].count(n) }}</template>
        </span>
      </h3>
      <ul class="divide-y divide-[var(--wolf-line)]">
        <li v-for="s in g.series" :key="`${s.metric_name}|${s.host}|${s.bench}|${s.site}|${s.label_key}`" class="flex flex-wrap items-baseline gap-x-3 py-1.5 text-sm">
          <span class="inline-flex min-w-[11rem] items-center gap-1" :style="{ color: STATE[s.state].color }">
            <span aria-hidden="true">{{ STATE[s.state].glyph }}</span>{{ STATE[s.state].label() }}
          </span>
          <span class="text-ink-gray-9">{{ label(s) }}</span>
          <span v-if="s.value != null && !s.stale" class="wolf-data text-ink-gray-9">{{ value(s) }}</span>
          <span class="text-ink-gray-6">{{ where(s) }}</span>
          <span class="text-ink-gray-6">
            <template v-if="s.state === 'stale' || s.stale">
              {{ s.state === 'firing' ? __('and no new data: last sample') : __('last sample') }} <time :title="full(s.last_at, timeZone)">{{ timeAgo(s.last_at) }}</time>
            </template>
          </span>
          <span v-for="r in s.rules" :key="r.name" class="text-ink-gray-6">{{ rule(r) }}</span>
          <RouterLink v-for="i in s.incidents" :key="i" class="wolf-link" :to="{ name: 'incident', params: { incident: i } }">{{ i }}</RouterLink>
          <span v-if="signals.caveats[s.metric_name]" class="w-full text-xs text-ink-gray-6">{{ signals.caveats[s.metric_name] }}</span>
        </li>
      </ul>
      <Button
        v-if="g.hidden"
        size="sm"
        variant="ghost"
        :label="moreLabel(g)"
        @click="shown[g.key] = true"
      />
      <Button v-else-if="g.canFold" size="sm" variant="ghost" :label="__('Show the first {0} only', [FIRST_ROWS])" @click="shown[g.key] = false" />
    </div>

    <div v-if="email.length" class="space-y-1">
      <h3 class="text-sm font-semibold text-ink-gray-8">{{ __('Email queue (last 24 h)') }}</h3>
      <p v-for="[category, e] in email" :key="category" class="text-sm text-ink-gray-8">
        {{ emailLabel(category, e) }} <time :title="full(e.last_at, timeZone)">{{ timeAgo(e.last_at) }}</time>
      </p>
    </div>

    <details v-if="signals.missing.length" class="text-sm text-ink-gray-6">
      <summary>{{ __('{0} signals without data in the last {1} days', [signals.missing.length, signals.lookback_days]) }}</summary>
      <p class="mt-1">
        {{ __('Not collected for this scope, not set up on the agent, or not available here. They are not zero: {0}.', [missingLabels]) }}
      </p>
    </details>
  </section>
</template>
