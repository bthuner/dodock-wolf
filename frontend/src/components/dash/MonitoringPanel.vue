<script setup>
import { computed } from 'vue'

import { ago, full } from '@/services/time'

// Is Wolf itself working. Each part is shown on its own: an online agent says nothing about
// the rules running, and neither proves the agent's watchdog can alert.
const props = defineProps({
  monitoring: { type: Object, required: true },
  timeZone: { type: String, required: true },
  compact: { type: Boolean, default: false },
})

const health = computed(() => props.monitoring.health)
const agents = computed(() => props.monitoring.agents.filter((a) => a.kind === 'agent'))
const satellites = computed(() => props.monitoring.agents.filter((a) => a.kind === 'satellite'))
const STATE = { fresh: 'reporting', stale: 'silent', never_seen: 'never reported', disabled: 'disabled' }
// Frappe's scheduler tick: every job, Wolf's rule evaluation included, runs at most this often
const tickSeconds = computed(() => health.value?.scheduler?.tick_seconds || null)
const tick = computed(() => {
  const s = tickSeconds.value
  if (!s) return null
  return s % 60 === 0 ? `${s / 60} min` : `${s} s`
})
const slowTick = computed(() => tickSeconds.value > 60)
// each agent's own `wolf-agent doctor` run, every hour: what its host gives it and what to fix
const setupProblems = computed(() => agents.value.filter((a) => a.setup && (a.setup.failed || a.setup.warnings)))
function setupLabel(s) {
  if (!s) return 'not reported'
  const parts = []
  if (s.failed) parts.push(`${s.failed} failed`)
  if (s.warnings) parts.push(`${s.warnings} warning${s.warnings > 1 ? 's' : ''}`)
  return parts.length ? parts.join(', ') : 'ok'
}
</script>

<template>
  <section class="wolf-card space-y-3" aria-label="Monitoring">
    <h2 class="wolf-h2">Is Wolf working</h2>
    <dl class="wolf-facts text-sm">
      <dt>Alert rules</dt>
      <dd v-if="!health">Unknown: the site could not compute its health.</dd>
      <dd v-else-if="health.rules.last_evaluated">
        evaluated <time :title="full(health.rules.last_evaluated, timeZone)">{{ ago(health.rules.last_evaluated) }} ago</time>
        <span v-if="health.problems.length" style="color: var(--wolf-critical)"> · {{ health.problems.join('; ') }}</span>
      </dd>
      <dd v-else>no rule has run yet</dd>
      <template v-if="health">
        <dt>Scheduler</dt>
        <dd>
          {{ health.scheduler.enabled ? 'enabled' : `disabled (${health.scheduler.reason})` }}<template v-if="tick">, jobs every {{ tick }}</template>
          <p v-if="slowTick" class="text-ink-gray-7">
            Alert rules are evaluated at that pace, not every minute. Set <code>scheduler_tick_interval</code> to 60 in
            <code>common_site_config.json</code> for one-minute evaluations.
          </p>
        </dd>
        <dt>Ingest queue</dt>
        <dd>
          <template v-if="health.queues.error">unreachable: {{ health.queues.error }}</template>
          <template v-else-if="health.queues.ingest_backlog_seconds != null">oldest push waiting {{ Math.round(health.queues.ingest_backlog_seconds / 60) }} min</template>
          <template v-else>empty</template>
          <template v-if="health.queues.workers != null"> · {{ health.queues.workers }} workers</template>
        </dd>
      </template>
      <dt>Rollups done until</dt>
      <dd class="wolf-data">1m {{ monitoring.rollups['1m'] ? full(monitoring.rollups['1m'], timeZone) : 'not yet' }}</dd>
      <dt>Agents</dt>
      <dd>
        {{ agents.filter((a) => a.state === 'fresh').length }} of {{ agents.length }} reporting
        (silent after {{ monitoring.silence_minutes }} min)
      </dd>
      <dt>Host setup</dt>
      <dd>
        <template v-if="setupProblems.length">
          <span style="color: var(--wolf-warning)">{{ setupProblems.length }} host{{ setupProblems.length > 1 ? 's' : '' }} to fix</span>:
          {{ setupProblems.map((a) => a.hostname).join(', ') }}
        </template>
        <template v-else>every reporting agent has what it needs</template>
      </dd>
      <template v-if="satellites.length">
        <dt>Satellites</dt>
        <dd>{{ satellites.filter((a) => a.state === 'fresh').length }} of {{ satellites.length }} forwarding</dd>
      </template>
      <template v-if="monitoring.mode.mode === 'satellite'">
        <dt>This site</dt>
        <dd>satellite of {{ monitoring.mode.central_url }}; {{ monitoring.mode.pending }} items waiting to forward</dd>
      </template>
    </dl>
    <div v-if="!compact && monitoring.agents.length" class="wolf-tablewell">
    <table class="wolf-table">
      <thead>
        <tr><th>Host or site</th><th>Kind</th><th>State</th><th>Last seen</th><th>Clock skew</th><th>Version</th><th>Setup</th></tr>
      </thead>
      <tbody>
        <template v-for="a in monitoring.agents" :key="a.name">
          <tr>
            <td class="font-medium">{{ a.hostname }}</td>
            <td>{{ a.kind }}</td>
            <td>{{ STATE[a.state] }}</td>
            <td class="wolf-data">{{ a.last_seen ? `${ago(a.last_seen)} ago` : '' }}</td>
            <td class="wolf-data">{{ a.clock_skew_seconds != null ? `${a.clock_skew_seconds} s` : 'unknown' }}</td>
            <td class="wolf-data">{{ a.agent_version || '' }}</td>
            <td>
              <span v-if="a.kind !== 'agent'"></span>
              <span v-else :title="a.setup ? `checked ${full(a.setup.checked_at, timeZone)}` : 'older agents do not report it'"
                :style="a.setup && a.setup.failed ? 'color: var(--wolf-critical)' : a.setup && a.setup.warnings ? 'color: var(--wolf-warning)' : ''"
              >{{ setupLabel(a.setup) }}</span>
            </td>
          </tr>
          <tr v-if="a.setup && a.setup.problems.length">
            <td colspan="7">
              <details>
                <summary class="text-sm">What {{ a.hostname }} needs (<code>wolf-agent doctor</code> on the host shows the same)</summary>
                <ul class="mt-1 space-y-1 text-sm">
                  <li v-for="(p, i) in a.setup.problems" :key="i">
                    <strong>{{ p.status === 'fail' ? 'Fail' : 'Warning' }}</strong> ({{ p.area }}): {{ p.title }}
                    <div v-if="p.fix" class="text-ink-gray-7">Fix: <code>{{ p.fix }}</code></div>
                  </li>
                </ul>
              </details>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    </div>
    <p class="text-sm text-ink-gray-6">{{ monitoring.note }}</p>
  </section>
</template>
