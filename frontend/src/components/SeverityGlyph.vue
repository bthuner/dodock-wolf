<script setup>
import { computed } from 'vue'

import { __ } from '@/services/i18n'

// brand.md: severity is a moon phase plus its word, never colour alone. The word is translated
// when shown, not when this module loads.
const PHASES = {
  info: { glyph: '○', label: () => __('Info'), color: 'var(--wolf-info)' },
  warning: { glyph: '◐', label: () => __('Warning'), color: 'var(--wolf-warning)' },
  critical: { glyph: '●', label: () => __('Critical'), color: 'var(--wolf-critical)' },
  resolved: { glyph: '✓', label: () => __('Resolved'), color: 'var(--wolf-ok)' },
}

const props = defineProps({
  severity: { type: String, default: null },
  showLabel: { type: Boolean, default: true },
})

const phase = computed(() => PHASES[props.severity] || null)
</script>

<template>
  <span v-if="phase" class="inline-flex items-center gap-1" :style="{ color: phase.color }">
    <span aria-hidden="true">{{ phase.glyph }}</span>
    <span :class="showLabel ? '' : 'sr-only'">{{ phase.label() }}</span>
  </span>
</template>
