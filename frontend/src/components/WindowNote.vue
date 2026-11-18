<script setup>
import { Button } from 'frappe-ui'
import { computed } from 'vue'

import { __ } from '@/services/i18n'
import { full } from '@/services/time'

// Says that the page reads an explicit window (a range selected on a chart), and gives the
// way back. Times come from the URL: one that is not a date is shown as written.
const props = defineProps({
  since: { type: String, required: true },
  until: { type: String, default: '' },
  timeZone: { type: String, required: true },
})
defineEmits(['reset'])

function said(iso, zone) {
  try {
    return full(iso, props.timeZone, { zone })
  } catch {
    return iso
  }
}
const text = computed(() =>
  props.until
    ? __('{0} to {1}', [said(props.since, false), said(props.until, true)])
    : __('{0} to now ({1})', [said(props.since, false), props.timeZone]),
)
</script>

<template>
  <p class="wolf-note wolf-window" data-tone="brand" role="status">
    <span>{{ __('Selected range:') }} <span class="wolf-data">{{ text }}</span></span>
    <Button size="sm" :label="__('Back to a relative window')" @click="$emit('reset')" />
  </p>
</template>
