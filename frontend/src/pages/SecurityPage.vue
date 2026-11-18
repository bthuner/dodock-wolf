<script setup>
import { Button, PageHeader, Select } from 'frappe-ui'
import { computed, inject, ref, watch } from 'vue'

import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import { useQueryParam } from '@/composables/useQueryParam'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'

// Security posture of one site (dodock_wolf/api/security.py): every check with what Wolf read
// and the fix. A check Wolf cannot read is "Unknown" and does not count as passed.
// labels and notes are functions: translated when drawn, not when the module loads
const STATUS = {
  fail: { label: () => __('Failed'), glyph: '✕', note: () => __('What to fix first: the heaviest on top.') },
  unknown: { label: () => __('Unknown'), glyph: '?', note: () => __('Wolf could not read these. They count as not passed.') },
  pass: { label: () => __('Passed'), glyph: '✓', note: () => '' },
}
const ORDER = Object.keys(STATUS)

const site = useQueryParam('site')
const sites = ref([])
const posture = ref(null)
const error = ref(null)
const sitesError = ref(null)
const loading = ref(false)
let ticket = 0

const checks = computed(() =>
  [...(posture.value?.checks || [])].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || b.weight - a.weight),
)
const siteOptions = computed(() => sites.value.map((s) => ({ label: s, value: s })))

// The score is weight passed over all weight (wolf/posture.py). The bar draws exactly that: one
// segment per check, as wide as its weight. Nothing here grades the score: Wolf has a rule for
// that ("Security score low"), and the page adds no threshold of its own.
const weight = computed(() => {
  const by = { fail: 0, unknown: 0, pass: 0, total: 0 }
  for (const c of checks.value) {
    by[c.status] += c.weight
    by.total += c.weight
  }
  return by
})
// what the score gains if this check alone passes: the server's own rounding, replayed
const gain = (c) => {
  const { pass, total } = weight.value
  if (c.status === 'pass' || !total) return 0
  return Math.round((100 * (pass + c.weight)) / total) - Math.round((100 * pass) / total)
}
const groups = computed(() =>
  ORDER.map((status) => ({
    status,
    glyph: STATUS[status].glyph,
    label: STATUS[status].label(),
    note: STATUS[status].note(),
    checks: checks.value.filter((c) => c.status === status),
  })).filter((g) => g.checks.length),
)
// `backticks` in a fix are commands or config: drawn as code, never as HTML
const parts = (text) => text.split('`').map((t, i) => ({ t, code: i % 2 === 1 })).filter((p) => p.t)

// the bar and the list point at each other
const hot = ref(null)
function reveal(id) {
  document.getElementById(`check-${id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

async function loadSites() {
  try {
    sites.value = await call('dodock_wolf.api.security.list_sites')
  } catch (e) {
    sitesError.value = failure(e, __('the sites'))
  }
}

async function load() {
  const mine = ++ticket
  loading.value = true
  error.value = null
  try {
    const result = await call('dodock_wolf.api.security.get_posture', { site: site.value || undefined })
    if (mine === ticket) posture.value = result
  } catch (e) {
    if (mine === ticket) {
      posture.value = null
      error.value = failure(e, __('this site'))
    }
  } finally {
    if (mine === ticket) loading.value = false
  }
}

// tamper-evident journal (dodock_wolf/api/journal.py), managers only
const boot = inject('boot', {})
const journal = ref(null)
const verdict = ref(null)
const verifying = ref(false)
const copied = ref(false)
async function loadJournal() {
  if (!boot?.can?.configure) return
  try {
    journal.value = await call('dodock_wolf.api.journal.get_status')
  } catch {
    journal.value = null
  }
}
async function verifyJournal() {
  verifying.value = true
  try {
    verdict.value = await call('dodock_wolf.api.journal.verify', {}, { post: true })
  } catch (e) {
    verdict.value = { ok: false, problem: { why: e.message } }
  } finally {
    verifying.value = false
  }
}
const canCopy = typeof navigator !== 'undefined' && !!navigator.clipboard
async function copyAnchor() {
  try {
    await navigator.clipboard.writeText(journal.value.anchor)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    copied.value = false // the anchor stays on screen, to select by hand
  }
}

loadSites()
loadJournal()
watch(site, load, { immediate: true })
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Security')" />
    <div class="flex items-center gap-2">
      <Select
        v-if="siteOptions.length > 1"
        :model-value="posture?.site || site"
        :options="siteOptions"
        :aria-label="__('Site')"
        class="w-64"
        @update:model-value="(v) => (site = v)"
      />
      <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="loading" @click="load" />
    </div>
  </PageHeader>

  <div class="wolf-page wolf-security" :class="{ 'wolf-security-rail': journal }">
    <div class="wolf-security-top space-y-3">
      <p v-if="sitesError" role="alert" class="wolf-alert">{{ __('Sites: {0}', [sitesError]) }}</p>
      <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>
      <LoadingNote v-if="loading && !posture && !error" :text="__('Loading the security score…')" />

      <section v-if="posture" class="wolf-card wolf-score" :aria-label="__('Score')">
        <div class="wolf-score-figure">
          <div class="wolf-label">{{ __('Security score') }}</div>
          <div class="wolf-data wolf-score-number">{{ posture.score }}<span class="wolf-score-of"> / 100</span></div>
          <div class="wolf-score-site">{{ posture.site }}</div>
        </div>

        <div class="wolf-score-weights">
          <div class="wolf-label">{{ __('Weight of the {0} checks', [checks.length]) }}</div>
          <div
            class="wolf-weightbar"
            role="img"
            :aria-label="__('Weight of the checks: {0} failed, {1} unknown, {2} passed, of {3}', [weight.fail, weight.unknown, weight.pass, weight.total])"
            :data-hot="hot ? '' : null"
          >
            <span
              v-for="c in checks"
              :key="c.id"
              class="wolf-weightbar-seg"
              :data-status="c.status"
              :data-on="hot === c.id ? '' : null"
              :style="{ flexGrow: c.weight }"
              :title="__('{0}: {1}, weight {2}', [c.label, STATUS[c.status].label().toLowerCase(), c.weight])"
              @mouseenter="hot = c.id"
              @mouseleave="hot = null"
              @click="reveal(c.id)"
            />
          </div>
          <ul class="wolf-legend">
            <li v-for="s in ORDER" :key="s" :data-status="s">
              <span class="wolf-legend-key" :data-status="s" aria-hidden="true" />
              <span class="wolf-legend-word">{{ STATUS[s].label() }}</span>
              <span class="wolf-data wolf-legend-n">{{ weight[s] }}<span class="wolf-legend-of">{{ ' ' + __('of {0}', [weight.total]) }}</span></span>
            </li>
          </ul>
        </div>

        <dl class="wolf-score-facts">
          <div>
            <dt>{{ __('Checks') }}</dt>
            <dd>{{ __('{0} passed, {1} failed, {2} unknown', [posture.passed, posture.failed, posture.unknown]) }}</dd>
          </div>
          <div>
            <dt>{{ __('Coverage') }}</dt>
            <dd>{{ __('Wolf could read {0}% of the weight', [posture.coverage]) }}</dd>
          </div>
          <div v-if="posture.hosts.length">
            <dt>{{ __('Hosts') }}</dt>
            <dd class="wolf-data">{{ posture.hosts.join(', ') }}</dd>
          </div>
        </dl>

        <p class="wolf-score-note">
          {{
            __(
              'The score is the weight of the checks that passed out of all of them: a check Wolf cannot read counts as not passed. Agent samples older than {0} h are not used.',
              [posture.recent_hours],
            )
          }}
          <template v-if="!posture.local">
            {{ __('System Settings of this site are read by the agent from its database, hourly.') }}
          </template>
        </p>
      </section>
    </div>

    <section v-if="posture" class="wolf-security-main space-y-5" :aria-label="__('Checks')">
      <div v-for="g in groups" :key="g.status" class="wolf-checks" :data-status="g.status">
        <header class="wolf-checks-head">
          <h2>
            <span class="wolf-mark" :data-status="g.status" aria-hidden="true">{{ g.glyph }}</span>
            {{ g.label }}
            <span class="wolf-data wolf-checks-count">{{ g.checks.length }}</span>
          </h2>
          <p v-if="g.note">{{ g.note }}</p>
        </header>
        <ul class="wolf-card wolf-checks-list">
          <li
            v-for="c in g.checks"
            :id="`check-${c.id}`"
            :key="c.id"
            class="wolf-check"
            :data-check="c.id"
            :data-status="c.status"
            :data-on="hot === c.id ? '' : null"
            @mouseenter="hot = c.id"
            @mouseleave="hot = null"
          >
            <div class="wolf-check-body">
              <h3>{{ c.label }} <span class="sr-only">({{ g.label }})</span></h3>
              <p class="wolf-check-evidence">{{ c.evidence }}</p>
              <div v-if="c.fix" class="wolf-fix">
                <span class="wolf-label">{{ __('Fix') }}</span>
                <p>
                  <template v-for="(p, i) in parts(c.fix)" :key="i"><code v-if="p.code" class="wolf-data">{{ p.t }}</code><template v-else>{{ p.t }}</template></template>
                </p>
              </div>
            </div>
            <div class="wolf-check-weight">
              <span v-if="gain(c)" class="wolf-data wolf-check-gain" :title="__('The score gains {0} if this check passes', [gain(c)])">+{{ gain(c) }}</span>
              <span class="wolf-check-w">{{ __('weight') }} <span class="wolf-data">{{ c.weight }}</span></span>
            </div>
          </li>
        </ul>
      </div>
      <p v-if="weight.fail + weight.unknown" class="text-sm" style="color: var(--wolf-muted)">
        {{ __('+N is what the score gains if that check alone passes.') }}
      </p>
    </section>

    <aside v-if="journal" class="wolf-security-side">
      <section class="wolf-card wolf-journal" :aria-label="__('Journal')">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="wolf-h2">{{ __('Tamper-evident journal') }}</h2>
          <Button size="sm" :label="__('Verify')" icon-left="lucide-shield-check" :loading="verifying" @click="verifyJournal" />
        </div>

        <div v-if="verdict" class="wolf-verdict" :data-ok="verdict.ok ? 'yes' : 'no'">
          <span aria-hidden="true">{{ verdict.ok ? '✓' : '✕' }}</span>
          <p role="status">
            <template v-if="verdict.ok && verdict.purged_through">
              {{
                __(
                  'Verified: {0} entries, every digest and MAC matches, no gap, and the journal starts where the last purge stopped (entry {1}).',
                  [verdict.checked, verdict.purged_through + 1],
                )
              }}
            </template>
            <template v-else-if="verdict.ok">{{ __('Verified: {0} entries, every digest and MAC matches, no gap.', [verdict.checked]) }}</template>
            <template v-else-if="verdict.problem?.seq">{{ __('Broken at entry {0}: {1}', [verdict.problem.seq, verdict.problem?.why]) }}</template>
            <template v-else>{{ __('Broken: {0}', [verdict.problem?.why]) }}</template>
          </p>
        </div>

        <p>
          {{ __('{0} signed entries, {1} waiting to be signed (within a minute).', [journal.entries, journal.pending]) }}
          <template v-if="!journal.key">{{ __('No key yet: it is created with the first signature.') }}</template>
        </p>
        <p>
          <template v-if="journal.retention_days">{{ __('Entries older than {0} days are purged every night.', [journal.retention_days]) }}</template>
          <template v-else>{{ __('Kept forever (Wolf Settings → Journal Retention Days).') }}</template>
          <template v-if="journal.purged_through">
            {{ ' ' + __('Entries 1 to {0} were purged; a signed purge record says where, and verification checks it.', [journal.purged_through]) }}
          </template>
        </p>

        <div v-if="journal.anchor" class="wolf-anchor">
          <div class="flex items-center justify-between gap-2">
            <span class="wolf-label">{{ __('Anchor') }}</span>
            <Button
              v-if="canCopy"
              size="sm"
              variant="ghost"
              :label="copied ? __('Copied') : __('Copy')"
              :icon-left="copied ? 'lucide-check' : 'lucide-copy'"
              @click="copyAnchor"
            />
          </div>
          <code class="wolf-data">{{ journal.anchor }}</code>
          <p>{{ __('To copy somewhere Wolf cannot write (a ticket, a password manager).') }}</p>
        </div>
      </section>
    </aside>
  </div>
</template>
