<script setup>
import { Button, PageHeader, Select, TabButtons } from 'frappe-ui'
import { LineChart } from 'frappe-ui/charts'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import ScopeInputs from '@/components/ScopeInputs.vue'
import { useChartRange } from '@/composables/useChartRange'
import { useQueryParam } from '@/composables/useQueryParam'
import { useWindow } from '@/composables/useWindow'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'
import { RANGES } from '@/services/filters'
import { timeAgo, axisLabel, full } from '@/services/time'

// One metric over a window, as the server's catalog allows it to be read. Every choice is in
// the URL; a selected range of points becomes an explicit since/until.
const route = useRoute()
const router = useRouter()
const boot = inject('boot')
const tz = boot.time_zone

const catalog = ref([])
const labels = ref([])
const result = ref(null)
const error = ref(null)
const catalogError = ref(null)
const catalogLoaded = ref(false)
const loading = ref(false)
const showTable = ref(false)
let ticket = 0
let labelTicket = 0

const metric = useQueryParam('metric', 'cpu_usage')
const win = useWindow(RANGES)
const { range, explicit } = win
const site = useQueryParam('site')
const host = useQueryParam('host')
const bench = useQueryParam('bench')
const label = useQueryParam('label')
// a metric the catalog does not list (not seen lately): read as a custom level, and said so,
// rather than leaving an empty page
const listed = computed(() => catalog.value.find((m) => m.metric === metric.value))
const spec = computed(() =>
  listed.value || (metric.value && catalog.value.length
    ? { metric: metric.value, label: metric.value, unit: '', kind: 'unknown', seen: false, label_key: 'label', unlisted: true,
        aggregations: ['avg', 'min', 'max', 'last'], default_aggregation: 'avg', group_bys: ['none', 'host', 'bench', 'site', 'host_label'] }
    : null),
)
const aggregation = useQueryParam('agg', '')
const groupBy = useQueryParam('group', '')

// functions: translated when drawn, not when the module loads
const GROUP_LABELS = {
  none: () => __('All together'),
  host: () => __('Per host'),
  bench: () => __('Per bench'),
  site: () => __('Per site'),
  host_label: () => __('Per host and label'),
}
const KINDS = {
  interval_count: () => __('counted per push interval, summed per bucket for a total'),
  gauge: () => __('a level at each sample'),
}
const kindText = (kind) => (KINDS[kind] || (() => __('a custom metric, read as a level')))()
const metricOptions = computed(() =>
  catalog.value.map((m) => {
    const name = `${m.label}${m.unit ? ` (${m.unit})` : ''}`
    return { value: m.metric, label: m.seen ? name : __('{0} · no data', [name]) }
  }),
)
const aggOptions = computed(() => (spec.value?.aggregations || []).map((a) => ({ value: a, label: a })))
const groupOptions = computed(() => (spec.value?.group_bys || []).map((g) => ({ value: g, label: GROUP_LABELS[g]?.() ?? g })))
const labelOptions = computed(() => [{ value: '', label: __('Any {0}', [spec.value?.label_key || 'label']) }, ...labels.value.map((l) => ({ value: l, label: l }))])

async function loadCatalog() {
  try {
    catalog.value = (await call('dodock_wolf.api.metrics.get_metric_catalog')).metrics
  } catch (e) {
    catalogError.value = failure(e, __('the metric catalog'))
  } finally {
    catalogLoaded.value = true
  }
}

async function loadLabels() {
  const mine = ++labelTicket // a slower answer for the previous metric must not land here
  labels.value = []
  if (!spec.value?.label_key) return
  try {
    const answer = await call('dodock_wolf.api.metrics.get_labels', { metric: metric.value, site: site.value, host: host.value, bench: host.value ? bench.value : undefined })
    if (mine === labelTicket) labels.value = answer.labels
  } catch {
    // the filter stays usable with "any"
  }
}

async function query() {
  if (!spec.value) return
  const mine = ++ticket
  loading.value = true
  error.value = null
  const args = {
    metric: metric.value,
    // only what the catalog allows for this metric; otherwise its default
    aggregation: spec.value.aggregations.includes(aggregation.value) ? aggregation.value : spec.value.default_aggregation,
    group_by: spec.value.group_bys.includes(groupBy.value) ? groupBy.value : 'none',
    label: label.value || undefined,
    site: site.value || undefined,
    host: host.value || undefined,
    bench: host.value ? bench.value || undefined : undefined,
    ...(explicit.value || { range: range.value }),
  }
  try {
    const answer = await call('dodock_wolf.api.metrics.query_metric', args)
    if (mine === ticket) result.value = answer
  } catch (e) {
    if (mine === ticket) error.value = failure(e, __('this metric'))
  } finally {
    if (mine === ticket) loading.value = false
  }
}

// the chart: one row per bucket, one column per group; null stays a gap
const long = computed(() => {
  const pts = result.value?.series[0]?.points || []
  return new Set(pts.map(([at]) => axisLabel(at, tz, false))).size < pts.length
})
const rows = computed(() => {
  const series = result.value?.series || []
  if (!series.length) return []
  return series[0].points.map(([at], i) => ({
    at: axisLabel(at, tz, long.value),
    iso: at,
    ...Object.fromEntries(series.map((s) => [s.name, s.points[i][1]])),
  }))
})
const unit = computed(() => result.value?.metric.unit || '')

// a range of the chart becomes an explicit window: by dragging, or point by point
const chart = ref(null)
const selection = useChartRange({
  chart,
  buckets: () => rows.value.map((r) => r.iso),
  bucketSeconds: () => result.value.bucket_seconds,
  onSelect: win.select,
})
const { pending, band } = selection
function resetRange() {
  selection.cancel()
  win.reset()
}
function chooseRange(value) {
  selection.cancel()
  win.choose(value)
}
const bucket = (seconds) => (seconds >= 3600 ? __('{0} h', [seconds / 3600]) : __('{0} min', [seconds / 60]))
const value = (v) => (v == null ? '' : `${Number(v).toLocaleString('en', { maximumFractionDigits: 2 })} ${unit.value}`)

onMounted(async () => {
  await loadCatalog()
  await Promise.all([loadLabels(), query()])
})
// another metric: its label, aggregation and grouping choices go in the same navigation, so
// no query runs with the previous metric's label
function chooseMetric(value) {
  if (value === metric.value) return
  router.replace({ query: { ...route.query, metric: value, label: undefined, agg: undefined, group: undefined } })
}
watch(() => route.query, query)
watch([metric, site, host, bench], loadLabels)
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Metrics')" />
    <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="loading" @click="query" />
  </PageHeader>
  <div class="wolf-page space-y-4">
    <div class="wolf-card wolf-toolbar">
    <div class="flex flex-wrap items-center gap-2">
      <Select :model-value="metric" :options="metricOptions" class="w-72" :aria-label="__('Metric')" @update:model-value="chooseMetric" />
      <Select v-if="aggOptions.length" :model-value="spec && spec.aggregations.includes(aggregation) ? aggregation : spec?.default_aggregation"
        :options="aggOptions" class="w-28" :aria-label="__('Aggregation')" @update:model-value="aggregation = $event" />
      <Select v-if="groupOptions.length" :model-value="spec && spec.group_bys.includes(groupBy) ? groupBy : 'none'"
        :options="groupOptions" class="w-48" :aria-label="__('Group by')" @update:model-value="groupBy = $event === 'none' ? '' : $event" />
      <Select v-if="spec?.label_key" :model-value="label" :options="labelOptions" class="w-48" :aria-label="__('Filter by {0}', [spec.label_key])"
        @update:model-value="label = $event" />
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <TabButtons :model-value="explicit ? null : range" :options="RANGES.map((r) => ({ value: r, label: r }))" @update:model-value="chooseRange" />
      <ScopeInputs />
      <Button v-if="explicit" :label="__('Back to a relative window')" @click="resetRange" />
    </div>
    </div>

    <p v-if="spec?.unlisted" class="wolf-note" data-tone="warning">
      {{ __('{0} is not in the catalog and had no data you can see in the last 7 days. It is read as a custom metric.', [metric]) }}
    </p>
    <p v-if="spec" class="text-sm text-ink-gray-6">
      {{ spec.unit ? __('{0}: {1}, in {2}.', [spec.label, kindText(spec.kind), spec.unit]) : __('{0}: {1}.', [spec.label, kindText(spec.kind)]) }}
      <template v-if="spec.caveat"> {{ spec.caveat }}</template>
    </p>
    <p v-if="catalogError" role="alert" class="wolf-alert">{{ __('Catalog: {0}', [catalogError]) }}</p>
    <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>

    <LoadingNote v-if="!catalogLoaded" :text="__('Loading the metric catalog…')" />
    <LoadingNote v-else-if="loading && !result && !error" :text="__('Loading the samples…')" />
    <section v-if="result" class="wolf-card space-y-3" :aria-label="__('Chart')">
      <h2 class="wolf-h2">{{ spec?.label || metric }}</h2>
      <p class="text-sm text-ink-gray-6">
        {{
          __('{0} per {1}, read from {2} data, {3} to {4}.', [
            result.aggregation,
            bucket(result.bucket_seconds),
            result.resolution,
            full(result.window.since, tz),
            full(result.window.until, tz, { zone: false }),
          ])
        }}
        {{ __('Whole buckets only: the one still filling shows when it closes.') }}
        <template v-if="result.retention.clipped">
          {{
            ' ' +
            __('Data before {0} is no longer kept at this resolution: those buckets are empty, not zero.', [
              full(result.retention.kept_from, tz, { zone: false }),
            ])
          }}
        </template>
        <template v-if="result.groups.total > result.groups.shown">
          {{ ' ' + __('Showing {0} of {1} groups, {2}.', [result.groups.shown, result.groups.total, result.groups.ranked_by]) }}
        </template>
      </p>
      <p v-if="pending" class="wolf-note" data-tone="brand">
        {{ __('Range starts at {0}: select the point where it ends.', [full(pending, tz, { zone: false })]) }}
      </p>
      <div v-if="rows.length" class="wolf-brush h-72" @pointerdown="selection.down">
        <!-- a click in the plot selects its bucket, as Enter does on the keyboard cursor -->
        <LineChart ref="chart" :data="rows" x="at" :y="result.series.map((s) => s.name)" :x-axis="{ type: 'category' }" show-data-points @select="selection.onPoint" />
        <div v-if="band" class="wolf-brush-band" aria-hidden="true" :style="{ left: `${band.left}px`, width: `${band.width}px`, top: `${band.top}px`, height: `${band.height}px` }" />
      </div>
      <p v-else class="text-sm text-ink-gray-6">{{ __('No samples of this metric for this scope and window. That is no data, not zero.') }}</p>
      <p v-if="rows.length" class="text-sm text-ink-gray-6">
        {{ __('Drag across the chart, or click two points (or move along the chart with the arrow keys and press Enter twice), to look at the range between them.') }}
        {{ __('Breaks in a line are buckets without samples.') }}
      </p>

      <ul v-if="result.series.length" class="wolf-rows">
        <li v-for="s in result.series" :key="s.name">
          <span class="wolf-rows-main">{{ s.name }}</span>
          <span class="wolf-data wolf-rows-figure">{{ result.aggregation }} {{ value(s.value) }}</span>
          <span class="text-ink-gray-6">{{ __('{0} samples', [s.samples]) }}</span>
          <span v-if="result.live" :style="s.stale ? { color: 'var(--wolf-warning)' } : {}" class="text-ink-gray-6">
            {{ s.stale ? __('no new data, last sample') : __('last sample') }} <time :title="full(s.last_sample, tz)">{{ timeAgo(s.last_sample) }}</time>
          </span>
          <span v-else class="text-ink-gray-6">{{ __('last sample in this window at') }} <time>{{ full(s.last_sample, tz, { zone: false }) }}</time></span>
        </li>
      </ul>

      <Button v-if="rows.length" size="sm" :icon-left="showTable ? 'lucide-chevron-up' : 'lucide-table'" :label="showTable ? __('Hide the data table') : __('Show the data as a table')" @click="showTable = !showTable" />
      <div v-if="showTable" class="wolf-tablewell">
        <table class="wolf-table">
          <caption class="sr-only">{{ __('{0}, {1} per bucket', [spec?.label, result.aggregation]) }}</caption>
          <thead>
            <tr><th scope="col">{{ __('Bucket start ({0})', [tz]) }}</th><th v-for="s in result.series" :key="s.name" scope="col" class="wolf-num wolf-th-data">{{ s.name }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.iso">
              <th scope="row" class="wolf-data">{{ full(r.iso, tz, { zone: false }) }}</th>
              <td v-for="s in result.series" :key="s.name" class="wolf-data wolf-num">{{ r[s.name] == null ? __('no data') : value(r[s.name]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
