<script setup>
import { Button } from 'frappe-ui'
import { onMounted, ref, watch } from 'vue'

import { call } from '@/services/api'
import { full } from '@/services/time'

// Response actions (dodock_wolf/api/response.py): Wolf proposes, a Wolf Manager confirms each
// one with a second click, and the result is recorded. Nothing runs on its own.
const props = defineProps({
  incident: { type: String, required: true },
  timeZone: { type: String, required: true },
})
const emit = defineEmits(['changed'])

const data = ref(null)
const error = ref(null)
const confirming = ref(null) // key of the proposal waiting for its confirmation
const hours = ref(24)
const busy = ref(false)

const key = (p) => `${p.action}|${p.target}|${p.host || p.agent || ''}` // a block is one address on one host
const STATUS = { Approved: 'Approved, waiting for the agent', Applied: 'Applied', Failed: 'Failed', Expired: 'Expired' }

async function load() {
  error.value = null
  try {
    const answer = await call('dodock_wolf.api.response.get_response', { incident: props.incident })
    // an answer without the expected lists shows nothing rather than breaking the incident page
    data.value = { ...answer, proposals: answer?.proposals || [], actions: answer?.actions || [], held: answer?.held || [] }
    hours.value = answer?.default_hours || 24
  } catch (e) {
    error.value = e.message
  }
}

async function confirm(p) {
  busy.value = true
  error.value = null
  try {
    await call(
      'dodock_wolf.api.response.approve',
      { incident: props.incident, action: p.action, target: p.target, agent: p.agent, host: p.host, duration_hours: hours.value, reason: p.reason },
      { post: true },
    )
    confirming.value = null
    await load()
    emit('changed')
  } catch (e) {
    error.value = e.message // the server's reason; nothing was applied
  } finally {
    busy.value = false
  }
}

onMounted(load)
watch(() => props.incident, load)
defineExpose({ load })
</script>

<template>
  <section v-if="data && (data.proposals.length || data.actions.length || data.held.length)" class="wolf-card space-y-3" aria-label="Response">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h2 class="wolf-h2">Response</h2>
      <span class="text-sm text-ink-gray-6">proposed from the incident's security events; each one needs your confirmation</span>
    </div>
    <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>

    <ul v-if="data.proposals.length" class="space-y-2">
      <li v-for="p in data.proposals" :key="key(p)" class="flex flex-wrap items-center gap-2 text-sm">
        <span class="text-ink-gray-9">{{ p.label }}</span>
        <span class="text-ink-gray-6">({{ p.reason }})</span>
        <template v-if="data.can_approve">
          <Button v-if="confirming !== key(p)" size="sm" label="Approve…" @click="confirming = key(p)" />
          <template v-else>
            <label v-if="p.action === 'block_ip' && (p.executors || ['wolf_agent']).includes('wolf_agent')" class="flex items-center gap-1 text-ink-gray-7">
              for
              <input v-model.number="hours" type="number" min="1" :max="data.max_hours" class="w-16 rounded border px-1" aria-label="Hours" />
              h
            </label>
            <Button size="sm" variant="solid" theme="red" :loading="busy" label="Confirm" @click="confirm(p)" />
            <Button size="sm" variant="ghost" label="Cancel" @click="confirming = null" />
          </template>
        </template>
      </li>
    </ul>
    <p v-if="data.proposals.length && !data.can_approve" class="text-sm text-ink-gray-6">Only a Wolf Manager can approve these.</p>

    <!-- a block on a host the address reached through a proxy would stop nothing there -->
    <ul v-if="data.held.length" class="space-y-1 text-sm text-ink-gray-7">
      <li v-for="h in data.held" :key="`${h.target}|${h.host}`">
        Not proposed: block {{ h.target }}<span v-if="h.host"> on {{ h.host }}</span>. It reached that host through the
        proxy {{ h.via_proxy }}, so its packets come from the proxy there: block it on the proxy, where a Wolf Agent
        reading the proxy's access log proposes it.
      </li>
    </ul>

    <table v-if="data.actions.length" class="w-full text-left text-sm">
      <thead class="text-ink-gray-6">
        <tr>
          <th class="py-1 font-normal">Action</th>
          <th class="py-1 font-normal">Status</th>
          <th class="py-1 font-normal">Approved</th>
          <th class="py-1 font-normal">Result</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in data.actions" :key="a.name" class="border-t border-outline-gray-1 align-top">
          <td class="py-1 pr-3">
            {{ a.action }} {{ a.target }}<span v-if="a.host" class="text-ink-gray-6"> on {{ a.host }}</span>
            <span v-if="a.executor === 'wazuh'" class="text-ink-gray-6"> with Wazuh</span>
          </td>
          <td class="py-1 pr-3" :style="a.status === 'Failed' ? { color: 'var(--wolf-critical)' } : null">{{ STATUS[a.status] || a.status }}</td>
          <td class="wolf-data py-1 pr-3">{{ a.approved_by }}, {{ full(a.approved_at, timeZone) }}</td>
          <td class="py-1 text-ink-gray-7">
            {{ a.result || '—' }}<span v-if="a.expires_at"> · until {{ full(a.expires_at, timeZone) }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
