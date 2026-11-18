<script setup>
import { Button, PageHeader, TabButtons, Textarea, TextInput } from 'frappe-ui'
import { computed, inject, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import LiveStatus from '@/components/LiveStatus.vue'
import LoadingNote from '@/components/LoadingNote.vue'
import MergeDialog from '@/components/MergeDialog.vue'
import PageTitle from '@/components/PageTitle.vue'
import ResponsePanel from '@/components/ResponsePanel.vue'
import SeverityGlyph from '@/components/SeverityGlyph.vue'
import SplitDialog from '@/components/SplitDialog.vue'
import TimelineRow from '@/components/TimelineRow.vue'
import { useLive } from '@/composables/useLive'
import { useQueryParam } from '@/composables/useQueryParam'
import { useTimeline } from '@/composables/useTimeline'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'
import { clock, day, duration, full } from '@/services/time'

const route = useRoute()
const router = useRouter()
const boot = inject('boot')
const tz = boot.time_zone

// labels translated when shown: the module loads before the translations
const SHOW = [
  { value: 'all', label: () => __('All'), families: ['evidence', 'context', 'activity', 'delivery'] },
  { value: 'evidence', label: () => __('Evidence'), families: ['evidence'] },
  { value: 'context', label: () => __('Context'), families: ['context'] },
  { value: 'activity', label: () => __('Activity'), families: ['activity'] },
  { value: 'delivery', label: () => __('Notifications'), families: ['delivery'] },
]
const GAP_MINUTES = 60

const name = computed(() => route.params.incident)
const show = useQueryParam('show', 'all', SHOW.map((s) => s.value))
const query = useQueryParam('q')
const families = computed(() => SHOW.find((s) => s.value === show.value).families)

const incident = ref(null)
const loadError = ref(null)
const actionError = ref(null)
const acting = ref(null)
const comment = ref('')
const posting = ref(false)
const expanded = ref(new Set())
const timeline = useTimeline(() => name.value)
const commentBox = ref(null)

// "1 record", "2 records": one sentence per form, Frappe has no plurals
function linkedEvents(records, occurrences) {
  const r = records === 1 ? __('1 record') : __('{0} records', [records])
  const o = occurrences === 1 ? __('1 reported occurrence') : __('{0} reported occurrences', [occurrences])
  return __('{0}, {1}', [r, o])
}

function anchor(row) {
  return `row-${row.id.replace(/[^A-Za-z0-9_-]/g, '-')}`
}

// a search filters the rows already loaded, and says so
const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return timeline.rows.value
  return timeline.rows.value.filter((r) =>
    [r.summary, r.text, r.category, r.source, r.channel, r.target, r.user_name].some((v) => v && String(v).toLowerCase().includes(q)),
  )
})

// date separators and long silences between rows, never a "healthy" claim
const items = computed(() => {
  const out = []
  let lastDay = null
  let lastAt = null
  for (const row of visible.value) {
    const rowDay = day(row.at, tz)
    if (rowDay !== lastDay) out.push({ type: 'day', key: `day-${rowDay}`, label: rowDay })
    else if (lastAt && (new Date(row.at) - new Date(lastAt)) / 60000 >= GAP_MINUTES) {
      out.push({ type: 'gap', key: `gap-${row.id}`, label: duration(lastAt, row.at) })
    }
    out.push({ type: 'row', key: row.id, row })
    lastDay = rowDay
    lastAt = row.at
  }
  return out
})
const filtered = computed(() => show.value !== 'all' || query.value.trim() !== '')
// rows a "same finding as" can point at: the ones on the page
const shownIds = computed(() => new Set(visible.value.map((r) => r.id)))

const scope = computed(() => {
  const s = incident.value?.scope || {}
  return [s.site, s.bench, s.host].filter(Boolean).join(' · ') // site, then bench, then host
})
const openFor = computed(() => {
  const i = incident.value
  if (!i) return ''
  return i.resolved.at
    ? __('lasted {0}', [duration(i.started_at, i.resolved.at)])
    : __('open for {0}', [duration(i.started_at, new Date().toISOString())])
})

async function loadIncident() {
  loadError.value = null
  try {
    incident.value = await call('dodock_wolf.api.incident_view.get_incident', { incident: name.value })
  } catch (e) {
    incident.value = null
    loadError.value = failure(e, __('this incident'))
  }
}

async function refresh() {
  await loadIncident()
  if (incident.value) await timeline.load(families.value, timeline.rows.value.length)
}

const TIMELINE_RELOAD_LIMIT = 500 // useTimeline reloads at most this many rows in one call
// Live: the header follows at once; new timeline rows are added below without scrolling, and
// a button says how many arrived and takes the reader to the first one.
const fresh = ref([])
const hub = inject('live', null)
const live = useLive(hub, {
  room: () => ({ doc: ['Wolf Incident', name.value] }),
  matches: (m) => m.kind === 'incident' && m.incident === name.value,
  refresh: async (reason) => {
    if (reason !== 'manual' && timeline.rows.value.length > TIMELINE_RELOAD_LIMIT) {
      // a reload would cut the rows paged in past the limit: the header follows, rows wait
      await loadIncident()
      return false
    }
    const before = new Set(timeline.rows.value.map((r) => r.id))
    await refresh()
    if (reason === 'manual' || !before.size) return true
    const added = timeline.rows.value.filter((r) => !before.has(r.id)).map((r) => r.id)
    if (added.length) fresh.value = [...new Set([...fresh.value, ...added])]
    return true
  },
})
const freshVisible = computed(() => fresh.value.filter((id) => timeline.rows.value.some((r) => r.id === id)))

async function showFresh() {
  const row = timeline.rows.value.find((r) => r.id === freshVisible.value[0])
  fresh.value = []
  if (!row) return
  await nextTick()
  const el = document.getElementById(anchor(row))
  el?.scrollIntoView({ block: 'center' })
  el?.focus?.()
}

// NIS2 / GDPR deadlines (api/compliance.py): tracked here, set in Desk, nothing sent anywhere
function regStatus(status) {
  switch (status) {
    case 'open':
      return __('Open')
    case 'due_soon':
      return __('Due within 6 h')
    case 'overdue':
      return __('Overdue')
    case 'done':
      return __('Sent on time')
    case 'done_late':
      return __('Sent late')
    default:
      return undefined
  }
}
const report = ref(null)
const reportError = ref(null)
async function loadReport() {
  reportError.value = null
  try {
    report.value = (await call('dodock_wolf.api.compliance.get_report', { incident: name.value })).markdown
  } catch (e) {
    reportError.value = e.message
  }
}

async function act(action) {
  acting.value = action
  actionError.value = null
  try {
    incident.value = await call('dodock_wolf.api.incident_view.act', { incident: name.value, action }, { post: true })
    await timeline.load(families.value, timeline.rows.value.length)
  } catch (e) {
    actionError.value = e.message // the server's reason; nothing changed on screen
  } finally {
    acting.value = null
  }
}

// merge, split and postmortem: the workflow's own methods, behind dialogs that say what moves
const merging = ref(false)
const splitting = ref(false)
const workflowNote = ref(null) // what the last workflow action did, with a link
function onMerged(target) {
  // the destination is where the incident goes on: open it (this one is now closed as merged)
  router.push({ name: 'incident', params: { incident: target } })
}
async function onSplit(name) {
  workflowNote.value = { link: name } // "Events moved to <name>."
  await refresh()
}
const postmortemBusy = ref(false)
async function writePostmortem() {
  postmortemBusy.value = true
  actionError.value = null
  try {
    const name = await call('dodock_wolf.api.incident.create_postmortem', { incident: incident.value.name }, { post: true })
    incident.value = { ...incident.value, postmortem: name }
    window.location.assign(`/app/wolf-postmortem/${encodeURIComponent(name)}`)
  } catch (e) {
    actionError.value = e.message
  } finally {
    postmortemBusy.value = false
  }
}

async function postComment() {
  posting.value = true
  actionError.value = null
  try {
    await call('dodock_wolf.api.incident.add_comment', { incident: name.value, content: comment.value }, { post: true })
    comment.value = '' // cleared only once it is saved
    // the Comment button is disabled now that the box is empty: the box takes the focus, unless
    // the reader has moved on meanwhile
    const active = document.activeElement
    if (!active || active === document.body || commentBox.value?.contains(active)) commentBox.value?.querySelector('textarea')?.focus()
    await timeline.load(families.value, timeline.rows.value.length + 1)
  } catch (e) {
    actionError.value = e.message
  } finally {
    posting.value = false
  }
}

function toggle(id) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

async function revealHash() {
  if (!route.hash) return
  const row = timeline.rows.value.find((r) => `#${anchor(r)}` === route.hash)
  if (!row) return
  expanded.value = new Set([...expanded.value, row.id])
  await nextTick()
  document.getElementById(anchor(row))?.scrollIntoView({ block: 'center' })
}

onMounted(async () => {
  await refresh()
  await revealHash()
})
watch(families, () => timeline.load(families.value))
watch(name, () => {
  // another incident: never show the previous one under the new name while it loads
  incident.value = null
  loadError.value = null
  timeline.reset()
  fresh.value = []
  workflowNote.value = null
  // another incident: never show the previous one's report draft
  report.value = null
  reportError.value = null
  refresh()
})
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Incident {0}', [name])" />
    <div class="flex items-center gap-2">
      <LiveStatus :live="live" :poll-seconds="hub?.pollSeconds" />
      <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="timeline.loading.value" @click="live.apply()" />
    </div>
  </PageHeader>

  <section v-if="loadError" class="max-w-2xl space-y-3 p-5 text-base text-ink-gray-8">
    <p role="alert" class="wolf-alert">{{ loadError }}</p>
    <RouterLink class="wolf-link" :to="{ name: 'incidents' }">{{ __('Back to incidents') }}</RouterLink>
  </section>

  <div v-else-if="!incident" class="p-5"><LoadingNote :text="__('Loading the incident…')" /></div>
  <div v-else class="wolf-page wolf-incident space-y-5">
    <header class="wolf-card wolf-incident-head" :data-severity="incident.resolved.at ? null : incident.severity">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-gray-6">
        <SeverityGlyph :severity="incident.severity" />
        <span class="wolf-badge">{{ __(incident.status, null, 'Wolf Incident') }}</span>
        <span v-if="scope">{{ scope }}</span>
      </div>
      <h1 class="wolf-incident-title">{{ incident.title }}</h1>
      <dl class="wolf-factgrid">
        <div>
          <dt>{{ __('Started') }}</dt>
          <dd><time class="wolf-data" :datetime="incident.started_at">{{ full(incident.started_at, tz) }}</time>, {{ openFor }}</dd>
        </div>
        <div v-if="incident.acknowledged.at">
          <dt>{{ __('Acknowledged') }}</dt>
          <dd>{{ incident.acknowledged.by_name || incident.acknowledged.by }}, <time class="wolf-data">{{ clock(incident.acknowledged.at, tz) }}</time></dd>
        </div>
        <div v-if="incident.resolved.at">
          <dt>{{ __('Resolved') }}</dt>
          <dd>{{ incident.resolved.by_name || incident.resolved.by || __('automatically') }}, <time class="wolf-data">{{ clock(incident.resolved.at, tz) }}</time></dd>
        </div>
        <div>
          <dt>{{ __('Owner') }}</dt>
          <dd>{{ incident.assigned_to ? incident.assigned_to.name : __('Nobody yet') }}</dd>
        </div>
        <div v-if="incident.deployment">
          <dt>{{ __('Deployment before it') }}</dt>
          <dd>
            <time class="wolf-data">{{ full(incident.deployment.at, tz) }}</time>
            <span v-if="!incident.deployment.available">, {{ __('details deleted by retention') }}</span>
          </dd>
        </div>
        <div v-if="incident.alert_rule">
          <dt>{{ __('Rule') }}</dt>
          <dd>{{ incident.alert_rule.name }}</dd>
        </div>
        <div v-if="incident.silenced">
          <dt>{{ __('Silenced') }}</dt>
          <dd>{{ __('Yes: no notifications are sent for it') }}</dd>
        </div>
        <div>
          <dt>{{ __('Linked events') }}</dt>
          <dd>{{ linkedEvents(incident.event_records, incident.event_occurrences) }}</dd>
        </div>
      </dl>
      <section v-if="incident.regulatory" class="wolf-incident-part space-y-2" :aria-label="__('Regulatory reporting')">
        <h2 class="text-sm font-semibold text-ink-gray-9">
          {{
            __('Regulatory reporting: {0}', [
              [
                incident.regulatory.nis2 && __('NIS2 significant incident'),
                incident.regulatory.dora && __('DORA major ICT-related incident'),
                incident.regulatory.gdpr && __('GDPR personal data breach'),
              ]
                .filter(Boolean)
                .join(', '),
            ])
          }}
          <span v-if="incident.regulatory.reference" class="font-normal text-ink-gray-6">· {{ __('reference {0}', [incident.regulatory.reference]) }}</span>
        </h2>
        <table class="w-full text-left text-sm">
          <thead class="text-ink-gray-6">
            <tr>
              <th class="py-1 font-normal">{{ __('Obligation') }}</th>
              <th class="py-1 font-normal">{{ __('Due') }}</th>
              <th class="py-1 font-normal">{{ __('Sent') }}</th>
              <th class="py-1 font-normal">{{ __('Status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in incident.regulatory.deadlines" :key="d.id" class="border-t border-outline-gray-1">
              <td class="py-1 pr-3">{{ d.label }}</td>
              <td class="wolf-data py-1 pr-3">
                <template v-if="d.due_at">{{ full(d.due_at, tz) }}<span v-if="d.estimated">{{ ' ' + __('(estimated)') }}</span></template>
                <template v-else>{{ __('as asked') }}</template>
              </td>
              <td class="wolf-data py-1 pr-3">{{ d.done_at ? full(d.done_at, tz) : '—' }}</td>
              <td class="py-1" :style="d.status === 'overdue' ? { color: 'var(--wolf-critical)', fontWeight: 600 } : null">
                {{ regStatus(d.status) }}
              </td>
            </tr>
          </tbody>
        </table>
        <p class="text-sm text-ink-gray-6">
          {{ __('Wolf tracks the dates; it does not decide whether the incident is reportable and sends nothing. Record the sending times in Desk.') }}
          <Button size="sm" variant="ghost" :label="__('Report draft')" @click="loadReport" />
        </p>
        <p v-if="reportError" role="alert" class="wolf-alert">{{ reportError }}</p>
        <pre v-if="report" class="wolf-data wolf-details">{{ report }}</pre>
      </section>
      <p v-if="incident.merged_into" class="text-sm">
        {{ __('Merged into') }}
        <RouterLink class="wolf-link" :to="{ name: 'incident', params: { incident: incident.merged_into } }">{{ incident.merged_into }}</RouterLink>.
      </p>
      <div class="wolf-incident-part flex flex-wrap items-center gap-2">
        <Button v-if="incident.can.acknowledge" variant="solid" :label="__('Acknowledge')" :loading="acting === 'acknowledge'" @click="act('acknowledge')" />
        <Button v-if="incident.can.assign_to_me" :label="__('Assign to me')" :loading="acting === 'assign_to_me'" @click="act('assign_to_me')" />
        <Button v-if="incident.can.resolve" :label="__('Resolve')" :loading="acting === 'resolve'" @click="act('resolve')" />
        <Button v-if="incident.can.merge" :label="__('Merge…')" @click="merging = true" />
        <Button v-if="incident.can.split" :label="__('Split…')" @click="splitting = true" />
        <a v-if="incident.can.postmortem && incident.postmortem" class="wolf-link text-sm"
           :href="`/app/wolf-postmortem/${encodeURIComponent(incident.postmortem)}`">{{ __('Postmortem {0} (Desk)', [incident.postmortem]) }}</a>
        <Button v-else-if="incident.can.postmortem" :label="__('Write the postmortem')" :loading="postmortemBusy" @click="writePostmortem" />
        <span v-else-if="incident.can.workflow && !incident.merged_into && incident.status !== 'Resolved'" class="text-sm text-ink-gray-6">
          {{ __('The postmortem comes once it is resolved.') }}
        </span>
      </div>
      <p v-if="workflowNote" role="status" class="text-sm">
        {{ __('Events moved to') }}
        <RouterLink class="wolf-link" :to="{ name: 'incident', params: { incident: workflowNote.link } }">{{ workflowNote.link }}</RouterLink>.
      </p>
      <p v-if="actionError" role="alert" class="wolf-alert">{{ actionError }}</p>
      <MergeDialog v-if="incident.can.merge" v-model:open="merging" :incident="incident.name" :time-zone="tz" @merged="onMerged" />
      <SplitDialog v-if="incident.can.split" v-model:open="splitting" :incident="incident.name" :time-zone="tz" @split="onSplit" />
    </header>

    <ResponsePanel :incident="incident.name" :time-zone="tz" @changed="refresh" />

    <section class="wolf-card wolf-timeline space-y-3" :aria-label="__('Timeline')">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="wolf-h2 mr-auto">{{ __('Timeline') }}</h2>
        <TabButtons v-model="show" :options="SHOW.map(({ value, label }) => ({ value, label: label() }))" />
        <TextInput v-model="query" type="search" :placeholder="__('Search loaded rows')" class="w-56" :aria-label="__('Search loaded rows')" />
        <span class="text-sm text-ink-gray-6">{{ __('Times in {0}', [tz]) }}</span>
      </div>
      <p v-if="query.trim()" class="text-sm text-ink-gray-6">
        {{
          timeline.paging.value.has_more
            ? __('{0} of {1} loaded rows match; more rows are not loaded yet.', [visible.length, timeline.rows.value.length])
            : __('{0} of {1} loaded rows match.', [visible.length, timeline.rows.value.length])
        }}
      </p>
      <p v-for="(cut, key) in timeline.meta.value.truncated" :key="key" class="text-sm text-ink-gray-6">
        {{
          key === 'activity_version'
            ? __('Activity shows the newest {0} of {1} recorded changes; older ones are in Desk.', [cut.shown, cut.total])
            : __('Activity shows the newest {0} of {1} comments; older ones are in Desk.', [cut.shown, cut.total])
        }}
      </p>
      <p v-if="timeline.error.value" role="alert" class="wolf-alert">{{ timeline.error.value }}</p>

      <ol class="wolf-rail">
        <template v-for="item in items" :key="item.key">
          <li v-if="item.type === 'day'" class="wolf-day">{{ item.label }}</li>
          <li v-else-if="item.type === 'gap'" class="wolf-gap">
            {{ filtered ? __('{0} with no matching rows', [item.label]) : __('{0} with no recorded activity', [item.label]) }}
          </li>
          <TimelineRow
            v-else
            :row="item.row"
            :time-zone="tz"
            :anchor="anchor(item.row)"
            :duplicate-anchor="item.row.duplicate_of && shownIds.has(`event:${item.row.duplicate_of}`) ? anchor({ id: `event:${item.row.duplicate_of}` }) : ''"
            :targeted="route.hash === `#${anchor(item.row)}`"
            :expanded="expanded.has(item.row.id)"
            @toggle="toggle(item.row.id)"
          />
        </template>
      </ol>
      <LoadingNote v-if="!timeline.loaded.value && !timeline.error.value" :text="__('Loading the timeline…')" />
      <p v-if="timeline.loaded.value && !timeline.loading.value && !timeline.error.value && !visible.length" class="text-sm text-ink-gray-6">
        {{ filtered ? __('No rows match this filter.') : __('Nothing recorded in this window.') }}
      </p>
      <Button
        v-if="freshVisible.length"
        variant="subtle"
        :label="freshVisible.length === 1 ? __('1 new row: show') : __('{0} new rows: show', [freshVisible.length])"
        @click="showFresh"
      />
      <Button v-if="timeline.paging.value.has_more" :label="__('Load more')" :loading="timeline.loading.value" @click="timeline.more(families)" />
    </section>

    <section ref="commentBox" class="wolf-card space-y-2" :aria-label="__('Comment')">
      <Textarea v-model="comment" :rows="3" :placeholder="__('Add a comment for the team')" :aria-label="__('Comment')" />
      <Button :label="__('Comment')" :disabled="!comment.trim()" :loading="posting" @click="postComment" />
    </section>
  </div>
</template>
