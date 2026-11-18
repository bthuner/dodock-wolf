<script setup>
import { Button } from 'frappe-ui'
import { computed } from 'vue'

import { __ } from '@/services/i18n'

// What keeps the view current, said plainly: live, reconnecting, polling, or paused.
const props = defineProps({
  live: { type: Object, required: true },
  pollSeconds: { type: Number, default: 60 },
  // translated by the caller; empty: "Changes waiting"
  pendingLabel: { type: String, default: '' },
})

const label = computed(() => {
  const l = props.live
  if (l.paused.value) return __('Paused')
  if (l.state.value === 'live') return __('Live')
  if (l.state.value === 'connecting') return __('Connecting…')
  if (l.state.value === 'polling') return l.polls ? __('Checks every {0} s', [props.pollSeconds]) : __('Not live: refresh by hand')
  return __('Refresh by hand')
})
// a known change, or one that may have been missed while the socket was away
const pendingText = computed(() =>
  props.live.pendingReason?.value === 'reconnect'
    ? __('Reconnected, changes may have been missed')
    : props.pendingLabel || __('Changes waiting'),
)
</script>

<template>
  <div class="flex items-center gap-2 text-sm text-ink-gray-6">
    <span role="status" aria-live="polite" class="wolf-live" :data-state="live.paused.value ? 'paused' : live.state.value">{{ label }}</span>
    <Button
      v-if="live.state.value !== 'off'"
      size="sm"
      variant="ghost"
      :label="live.paused.value ? __('Resume') : __('Pause')"
      :aria-pressed="live.paused.value"
      @click="live.toggle()"
    />
    <Button v-if="live.pending.value" size="sm" variant="subtle" :label="__('{0} · Refresh', [pendingText])" @click="live.apply()" />
  </div>
</template>
