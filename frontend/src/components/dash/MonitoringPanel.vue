<script setup>
import { computed } from 'vue'

import { __ } from '@/services/i18n'
import { timeAgo, full } from '@/services/time'

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
function stateLabel(state) {
  switch (state) {
    case 'fresh': return __('reporting')
    case 'stale': return __('silent')
    case 'never_seen': return __('never reported')
    case 'disabled': return __('disabled')
    default: return state
  }
}
function kindLabel(kind) {
  if (kind === 'agent') return __('agent')
  if (kind === 'satellite') return __('satellite')
  return kind
}
// Frappe's scheduler tick: every job, Wolf's rule evaluation included, runs at most this often
const tickSeconds = computed(() => health.value?.scheduler?.tick_seconds || null)
const tick = computed(() => {
  const s = tickSeconds.value
  if (!s) return null
  return s % 60 === 0 ? __('{0} min', [s / 60]) : __('{0} s', [s])
})
const slowTick = computed(() => tickSeconds.value > 60)
const schedulerText = computed(() => {
  const sch = health.value.scheduler
  if (sch.enabled) return tick.value ? __('enabled, jobs every {0}', [tick.value]) : __('enabled')
  return tick.value ? __('disabled ({0}), jobs every {1}', [sch.reason, tick.value]) : __('disabled ({0})', [sch.reason])
})
// a translated sentence cut around its placeholders, to put an element (a <code>) in their place
const pieces = (text) => text.split(/(\{\d+\})/).filter(Boolean)
// each agent's own `wolf-agent doctor` run, every hour: what its host gives it and what to fix
// only agents that report: an older agent, or one within its first hour, has no setup yet
const setupReported = computed(() => agents.value.filter((a) => a.setup && a.state === 'fresh'))
const setupProblems = computed(() => setupReported.value.filter((a) => a.setup.failed || a.setup.warnings))
function setupLabel(s) {
  if (!s) return __('not reported')
  const warnings = s.warnings > 1 ? __('{0} warnings', [s.warnings]) : __('{0} warning', [s.warnings])
  if (s.failed && s.warnings) return __('{0} failed, {1}', [s.failed, warnings])
  if (s.failed) return __('{0} failed', [s.failed])
  if (s.warnings) return warnings
  return __('ok')
}
</script>

<template>
  <section class="wolf-card space-y-3" :aria-label="__('Monitoring')">
    <h2 class="wolf-h2">{{ __('Is Wolf working') }}</h2>
    <dl class="wolf-facts text-sm">
      <dt>{{ __('Alert rules') }}</dt>
      <dd v-if="!health">{{ __('Unknown: the site could not compute its health.') }}</dd>
      <dd v-else-if="health.rules.last_evaluated">
        {{ __('evaluated') }} <time :title="full(health.rules.last_evaluated, timeZone)">{{ timeAgo(health.rules.last_evaluated) }}</time>
        <span v-if="health.problems.length" style="color: var(--wolf-critical)"> · {{ health.problems.join('; ') }}</span>
      </dd>
      <dd v-else>{{ __('no rule has run yet') }}</dd>
      <template v-if="health">
        <dt>{{ __('Scheduler') }}</dt>
        <dd>
          {{ schedulerText }}
          <p v-if="slowTick" class="text-ink-gray-7">
            {{ __('Alert rules are evaluated at that pace, not every minute.') }}
            <template v-for="(p, i) in pieces(__('Set {0} to 60 in {1} for one-minute evaluations.'))" :key="i"
              ><code v-if="p === '{0}'">scheduler_tick_interval</code><code v-else-if="p === '{1}'">common_site_config.json</code
              ><template v-else>{{ p }}</template></template
            >
          </p>
        </dd>
        <dt>{{ __('Ingest queue') }}</dt>
        <dd>
          <template v-if="health.queues.error">{{ __('unreachable: {0}', [health.queues.error]) }}</template>
          <template v-else-if="health.queues.ingest_backlog_seconds != null">{{ __('oldest push waiting {0} min', [Math.round(health.queues.ingest_backlog_seconds / 60)]) }}</template>
          <template v-else>{{ __('empty') }}</template>
          <template v-if="health.queues.workers != null"> · {{ health.queues.workers === 1 ? __('{0} worker', [1]) : __('{0} workers', [health.queues.workers]) }}</template>
        </dd>
      </template>
      <dt>{{ __('Rollups done until') }}</dt>
      <dd class="wolf-data">1m {{ monitoring.rollups['1m'] ? full(monitoring.rollups['1m'], timeZone) : __('not yet') }}</dd>
      <dt>{{ __('Agents') }}</dt>
      <dd>
        {{ __('{0} of {1} reporting (silent after {2} min)', [agents.filter((a) => a.state === 'fresh').length, agents.length, monitoring.silence_minutes]) }}
      </dd>
      <dt>{{ __('Host setup') }}</dt>
      <dd>
        <template v-if="setupProblems.length">
          <span style="color: var(--wolf-warning)">{{ setupProblems.length > 1 ? __('{0} hosts to fix', [setupProblems.length]) : __('1 host to fix') }}</span>:
          {{ setupProblems.map((a) => a.hostname).join(', ') }}
        </template>
        <template v-else-if="setupReported.length">{{ __('every reporting agent has what it needs') }}</template>
        <template v-else>{{ __('not reported yet (agents check their host every hour)') }}</template>
      </dd>
      <template v-if="satellites.length">
        <dt>{{ __('Satellites') }}</dt>
        <dd>{{ __('{0} of {1} forwarding', [satellites.filter((a) => a.state === 'fresh').length, satellites.length]) }}</dd>
      </template>
      <template v-if="monitoring.mode.mode === 'satellite'">
        <dt>{{ __('This site') }}</dt>
        <dd>{{ __('satellite of {0}; {1} items waiting to forward', [monitoring.mode.central_url, monitoring.mode.pending]) }}</dd>
      </template>
    </dl>
    <div v-if="!compact && monitoring.agents.length" class="wolf-tablewell">
    <table class="wolf-table">
      <thead>
        <tr>
          <th>{{ __('Host or site') }}</th>
          <th>{{ __('Kind') }}</th>
          <th>{{ __('State') }}</th>
          <th>{{ __('Last seen') }}</th>
          <th>{{ __('Clock skew') }}</th>
          <th>{{ __('Version') }}</th>
          <th>{{ __('Setup') }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="a in monitoring.agents" :key="a.name">
          <tr>
            <td class="font-medium">{{ a.hostname }}</td>
            <td>{{ kindLabel(a.kind) }}</td>
            <td>{{ stateLabel(a.state) }}</td>
            <td class="wolf-data">{{ a.last_seen ? timeAgo(a.last_seen) : '' }}</td>
            <td class="wolf-data">{{ a.clock_skew_seconds != null ? __('{0} s', [a.clock_skew_seconds]) : __('unknown') }}</td>
            <td class="wolf-data">{{ a.agent_version || '' }}</td>
            <td>
              <span v-if="a.kind !== 'agent'"></span>
              <span v-else
                :style="a.setup && a.setup.failed ? 'color: var(--wolf-critical)' : a.setup && a.setup.warnings ? 'color: var(--wolf-warning)' : ''"
              >{{ setupLabel(a.setup) }}</span>
              <span v-if="a.setup" class="block text-xs text-ink-gray-6">{{ __('checked') }} <time :datetime="a.setup.checked_at">{{ timeAgo(a.setup.checked_at) }}</time></span>
            </td>
          </tr>
          <tr v-if="a.setup && a.setup.problems.length">
            <td colspan="7">
              <details>
                <summary class="text-sm">
                  <template v-for="(p, i) in pieces(__('What {0} needs ({1} on the host shows the same)', [a.hostname]))" :key="i"
                    ><code v-if="p === '{1}'">wolf-agent doctor</code><template v-else>{{ p }}</template></template
                  >
                </summary>
                <ul class="mt-1 space-y-1 text-sm">
                  <li v-for="(p, i) in a.setup.problems" :key="i">
                    <strong>{{ p.status === 'fail' ? __('Fail') : __('Warning') }}</strong> ({{ p.area }}): {{ p.title }}
                    <div v-if="p.fix" class="text-ink-gray-7">{{ __('Fix: {0}', [p.fix]) }}</div>
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
