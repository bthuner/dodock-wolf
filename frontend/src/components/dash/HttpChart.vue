<script setup>
import { LineChart } from 'frappe-ui/charts'
import { computed, ref } from 'vue'

import { useChartRange } from '@/composables/useChartRange'
import { axisLabel, clock, full } from '@/services/time'

// Requests, 5xx and 502 per bucket (interval counts summed). 502 is part of 5xx, so the lines
// are drawn side by side, never stacked. A bucket without samples stays a gap.
const props = defineProps({
  http: { type: Object, required: true },
  timeZone: { type: String, required: true },
})
// a range selected on the chart: the page reads its windowed data for it
const emit = defineEmits(['select'])

const LABELS = { http_requests: 'Requests', http_5xx: '5xx', http_502: '502 (part of 5xx)' }
// a category axis needs one label per bucket: add the date when the clock alone repeats
// (windows of a day or more)
const long = computed(() => {
  const clocks = props.http.series.http_requests.map(([at]) => axisLabel(at, props.timeZone, false))
  return new Set(clocks).size < clocks.length
})
const label = (iso) => axisLabel(iso, props.timeZone, long.value)

const rows = computed(() =>
  props.http.series.http_requests.map(([at], i) => ({
    at: label(at),
    iso: at,
    [LABELS.http_requests]: props.http.series.http_requests[i][1],
    [LABELS.http_5xx]: props.http.series.http_5xx[i][1],
    [LABELS.http_502]: props.http.series.http_502[i][1],
  })),
)
// a deployment marks the bucket it fell in: "preceding change", not a cause. Past a few,
// labels pile up on each other: the lines stay, the list under the chart names them.
const LABELLED = 3
const markers = computed(() => {
  const starts = props.http.series.http_requests.map(([at]) => new Date(at).getTime())
  const labelled = props.http.deployments.length <= LABELLED
  const seen = new Set()
  return props.http.deployments.flatMap((d) => {
    const t = new Date(d.at).getTime()
    const i = starts.findLastIndex((s) => s <= t)
    // outside the drawn buckets (the one still filling): in the list only
    if (i < 0 || t >= starts[i] + props.http.bucket_seconds * 1000 || seen.has(i)) return []
    seen.add(i)
    return [{ axis: 'x', value: rows.value[i].at, label: labelled ? `deploy ${clock(d.at, props.timeZone)}` : undefined, dashed: true }]
  })
})
const chart = ref(null)
const selection = useChartRange({
  chart,
  buckets: () => props.http.series.http_requests.map(([at]) => at),
  bucketSeconds: () => props.http.bucket_seconds,
  onSelect: (since, until) => emit('select', since, until),
})
const { pending, band } = selection
const anyData = computed(() => Object.values(props.http.has_data).some(Boolean))
</script>

<template>
  <div class="wolf-card space-y-2">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h2 class="text-base font-semibold text-ink-gray-9">HTTP responses</h2>
      <span class="text-sm text-ink-gray-6">
        per {{ http.bucket_seconds / 60 }} min, read from {{ http.resolution }} data, times in {{ timeZone }}
      </span>
    </div>
    <p v-if="pending" class="wolf-note" data-tone="brand" role="status">
      <span>Range starts at {{ full(pending, timeZone, { zone: false }) }}: select the point where it ends.</span>
      <button type="button" class="wolf-link" @click="selection.cancel()">Cancel</button>
    </p>
    <div v-if="anyData" class="wolf-brush h-64" @pointerdown="selection.down">
      <LineChart ref="chart" :data="rows" x="at" :y="Object.values(LABELS)" :x-axis="{ type: 'category' }" :reference-lines="markers" @select="selection.onPoint" />
      <div v-if="band" class="wolf-brush-band" aria-hidden="true" :style="{ left: `${band.left}px`, width: `${band.width}px`, top: `${band.top}px`, height: `${band.height}px` }" />
    </div>
    <p v-else class="text-sm text-ink-gray-6">
      No HTTP counts in this window. The agent counts responses from nginx access logs; none arrived
      for this scope, which is not the same as no traffic.
    </p>
    <p class="text-sm text-ink-gray-6">
      <template v-if="anyData">Drag across the chart, or click two points (with the keyboard: arrow keys, then Enter twice), to read this page for the range between them. </template>
      502 responses are part of the 5xx count, not in addition to it. Breaks in a line are buckets without data.
      <template v-if="http.deployments.length"> Dashed lines are deployments<template v-if="http.deployments.length > LABELLED">, listed below</template>.</template>
    </p>
  </div>
</template>
