<script setup>
import { Button, Dialog } from 'frappe-ui'
import { computed, ref, watch } from 'vue'

import SeverityGlyph from '@/components/SeverityGlyph.vue'
import { call } from '@/services/api'
import { __ } from '@/services/i18n'
import { full } from '@/services/time'

// Merge this incident into another one (api/incident.py merge). Before anything moves, the server
// says what would: the events and comments moved, what the destination becomes, and that this
// incident is closed as merged. Nothing is shown as done before the server says so.
const props = defineProps({
  incident: { type: String, required: true },
  timeZone: { type: String, required: true },
})
const open = defineModel('open', { type: Boolean, default: false })
const emit = defineEmits(['merged'])

const data = ref(null)
const target = ref('')
const loading = ref(false)
const merging = ref(false)
const error = ref(null)
let request = 0

// the destinations once per opening, then only the preview for each choice
async function load({ withCandidates = false } = {}) {
  const mine = ++request
  loading.value = true
  error.value = null
  try {
    const answer = await call('dodock_wolf.api.incident_view.merge_preview', {
      source: props.incident,
      target: target.value || null,
      with_candidates: withCandidates ? 1 : 0,
    })
    if (mine === request) data.value = withCandidates ? answer : { ...data.value, preview: answer.preview }
  } catch (e) {
    if (mine === request) {
      error.value = e.message
      if (data.value) data.value = { ...data.value, preview: null } // no preview for a choice it is not about
    }
  } finally {
    if (mine === request) loading.value = false
  }
}

watch(open, (value) => {
  if (!value) return
  target.value = ''
  data.value = null
  load({ withCandidates: true })
})
watch(target, (value) => {
  if (!open.value) return
  if (value) load()
  else if (data.value) data.value = { ...data.value, preview: null }
})

const preview = computed(() => (target.value && data.value?.preview?.target?.name === target.value ? data.value.preview : null))
const events = (n) => (n === 1 ? __('1 event') : __('{0} events', [n]))
const comments = (n) => (n === 1 ? __('1 comment') : __('{0} comments', [n]))

async function merge() {
  merging.value = true
  error.value = null
  try {
    const res = await call('dodock_wolf.api.incident.merge', { source: props.incident, target: target.value }, { post: true })
    open.value = false
    emit('merged', res.target)
  } catch (e) {
    error.value = e.message // the server's reason; the choice stays
  } finally {
    merging.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open" :title="__('Merge {0} into another incident', [incident])" size="xl">
    <div class="space-y-3 text-base text-ink-gray-8">
      <p class="text-sm text-ink-gray-7">
        {{
          __(
            'Its events and comments move to the incident you pick, which then covers both. {0} is closed as merged, and new matches of its rule go to the destination.',
            [incident],
          )
        }}
      </p>
      <label class="block space-y-1">
        <span class="text-sm text-ink-gray-7">{{ __('Destination') }}</span>
        <select
          v-model="target"
          class="w-full rounded border border-outline-gray-2 bg-surface-white px-2 py-1.5 text-sm text-ink-gray-9"
          :disabled="!data"
          data-testid="merge-target"
        >
          <option value="">{{ data?.candidates.length ? __('Pick an unresolved incident') : data ? __('No unresolved incident to merge into') : __('Loading…') }}</option>
          <option v-for="c in data?.candidates || []" :key="c.name" :value="c.name">
            {{ c.name }} · {{ c.severity }} · {{ c.title }}{{ c.scope.site ? ` (${c.scope.site})` : '' }}
          </option>
        </select>
        <span v-if="data?.more_candidates" class="text-sm text-ink-gray-6">{{ __('The newest {0} unresolved incidents are listed.', [data.candidates.length]) }}</span>
      </label>

      <div v-if="preview" class="wolf-card space-y-2" aria-live="polite" data-testid="merge-preview">
        <p v-if="preview.error" role="alert" class="wolf-alert">{{ preview.error }}</p>
        <template v-else>
          <p>
            <b>{{ __('Moves') }}</b>
            {{ __('{0} and {1} from {2} to {3}.', [events(preview.events), comments(preview.comments), incident, preview.target.name]) }}
          </p>
          <p class="flex flex-wrap items-baseline gap-x-2">
            <b>{{ preview.target.name }}</b> {{ __('stays {0},', [__(preview.target_after.status, null, 'Wolf Incident')]) }}
            <SeverityGlyph :severity="preview.target_after.severity" />
            <span>{{ __('since') }} <time :datetime="preview.target_after.started_at">{{ full(preview.target_after.started_at, timeZone) }}</time></span>
          </p>
          <p><b>{{ incident }}</b> {{ __('becomes Resolved, merged into {0}.', [preview.target.name]) }}</p>
        </template>
      </div>
      <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>
    </div>
    <template #actions>
      <div class="flex justify-end gap-2">
        <Button :label="__('Cancel')" @click="open = false" />
        <Button
          variant="solid"
          theme="red"
          :label="target ? __('Merge into {0}', [target]) : __('Merge')"
          :disabled="!preview || !!preview.error || loading"
          :loading="merging"
          @click="merge"
        />
      </div>
    </template>
  </Dialog>
</template>
