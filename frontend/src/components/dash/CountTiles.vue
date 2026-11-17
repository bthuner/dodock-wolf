<script setup>
// Exact counts from get_counts: never computed from a list on screen.
defineProps({ counts: { type: Object, required: true } })
</script>

<template>
  <dl class="wolf-tiles">
    <div class="wolf-tile">
      <dt>Unresolved incidents</dt>
      <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.unresolved }}</dd>
      <dd class="wolf-tile-note">
        <span v-if="counts.incidents.critical_unresolved" aria-hidden="true" style="color: var(--wolf-critical)">● </span>{{ counts.incidents.critical_unresolved }} critical
      </dd>
    </div>
    <div class="wolf-tile">
      <dt>Not acknowledged</dt>
      <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.unacknowledged }}</dd>
      <dd class="wolf-tile-note">open, nobody on it yet</dd>
    </div>
    <div class="wolf-tile">
      <dt>Sites with unresolved incidents</dt>
      <dd class="wolf-data wolf-tile-figure">{{ counts.incidents.sites_with_unresolved }}</dd>
      <dd class="wolf-tile-note">+ {{ counts.incidents.unresolved_without_site }} host or bench-wide</dd>
    </div>
    <div class="wolf-tile">
      <dt>Agents reporting</dt>
      <dd class="wolf-data wolf-tile-figure">
        {{ counts.agents.agent.fresh }}<small> / {{ counts.agents.agent.fresh + counts.agents.agent.stale + counts.agents.agent.never_seen }}</small>
      </dd>
      <dd class="wolf-tile-note">
        {{ counts.agents.agent.stale }} silent<span v-if="counts.agents.satellite.fresh + counts.agents.satellite.stale">,
        satellites {{ counts.agents.satellite.fresh }} reporting / {{ counts.agents.satellite.stale }} silent</span>
      </dd>
    </div>
  </dl>
</template>
