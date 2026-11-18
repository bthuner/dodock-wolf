<script setup>
import { computed } from 'vue'

import { __ } from '@/services/i18n'

// Exact counts from get_counts: never computed from a list on screen.
const props = defineProps({ counts: { type: Object, required: true } })

const agentsNote = computed(() => {
  const { agent, satellite } = props.counts.agents
  return satellite.fresh + satellite.stale
    ? __('{0} silent, satellites {1} reporting / {2} silent', [agent.stale, satellite.fresh, satellite.stale])
    : __('{0} silent', [agent.stale])
})
</script>

<template>
  <section :aria-label="__('Now')" class="space-y-2">
  <h2 class="wolf-label">{{ __('Now') }}</h2>
  <dl class="wolf-tiles">
    <div class="wolf-tile">
      <dt>{{ __('Unresolved incidents') }}</dt>
      <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.unresolved }}</dd>
      <dd class="wolf-tile-note">
        <span v-if="counts.incidents.critical_unresolved" aria-hidden="true" style="color: var(--wolf-critical)">● </span>{{ counts.incidents.critical_unresolved === 1 ? __('1 critical') : __('{0} critical', [counts.incidents.critical_unresolved]) }}
      </dd>
    </div>
    <div class="wolf-tile">
      <dt>{{ __('Not acknowledged') }}</dt>
      <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.unacknowledged }}</dd>
      <dd class="wolf-tile-note">{{ __('open, nobody on it yet') }}</dd>
    </div>
    <div class="wolf-tile">
      <dt>{{ __('Sites with unresolved incidents') }}</dt>
      <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.sites_with_unresolved }}</dd>
      <dd class="wolf-tile-note">{{ __('+ {0} host or bench-wide', [counts.incidents.unresolved_without_site]) }}</dd>
    </div>
    <div class="wolf-tile">
      <dt>{{ __('Agents reporting') }}</dt>
      <dd class="wolf-data wolf-tile-figure">
        {{ counts.agents.agent.fresh }}<small> / {{ counts.agents.agent.fresh + counts.agents.agent.stale + counts.agents.agent.never_seen }}</small>
      </dd>
      <dd class="wolf-tile-note">{{ agentsNote }}</dd>
    </div>
  </dl>
  </section>
</template>
