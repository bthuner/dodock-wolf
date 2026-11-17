<script setup>
import { Button, PageHeader, Select } from 'frappe-ui'
import { computed, inject, ref, watch } from 'vue'

import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import { useQueryParam } from '@/composables/useQueryParam'
import { call, failure } from '@/services/api'

// Security posture of one site (dodock_wolf/api/security.py): every check with what Wolf read
// and the fix. A check Wolf cannot read is "Unknown" and does not count as passed.
const STATUS = {
  fail: { label: 'Failed', glyph: '✕', note: 'What to fix first: the heaviest on top.' },
  unknown: { label: 'Unknown', glyph: '?', note: 'Wolf could not read these. They count as not passed.' },
  pass: { label: 'Passed', glyph: '✓', note: '' },
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
  ORDER.map((status) => ({ status, ...STATUS[status], checks: checks.value.filter((c) => c.status === status) })).filter((g) => g.checks.length),
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
    sitesError.value = failure(e, 'the sites')
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
      error.value = failure(e, 'this site')
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
    <PageTitle title="Security" />
    <div class="flex items-center gap-2">
      <Select
        v-if="siteOptions.length > 1"
        :model-value="posture?.site || site"
        :options="siteOptions"
        aria-label="Site"
        class="w-64"
        @update:model-value="(v) => (site = v)"
      />
      <Button label="Refresh" icon-left="lucide-refresh-cw" :loading="loading" @click="load" />
    </div>
  </PageHeader>

  <div class="wolf-page wolf-security" :class="{ 'wolf-security-rail': journal }">
    <div class="wolf-security-top space-y-3">
      <p v-if="sitesError" role="alert" class="wolf-alert">Sites: {{ sitesError }}</p>
      <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>
      <LoadingNote v-if="loading && !posture && !error" what="the security score" />

      <section v-if="posture" class="wolf-card wolf-score" aria-label="Score">
        <div class="wolf-score-figure">
          <div class="wolf-label">Security score</div>
          <div class="wolf-data wolf-score-number">{{ posture.score }}<span class="wolf-score-of"> / 100</span></div>
          <div class="wolf-score-site">{{ posture.site }}</div>
        </div>

        <div class="wolf-score-weights">
          <div class="wolf-label">Weight of the {{ checks.length }} checks</div>
          <div
            class="wolf-weightbar"
            role="img"
            :aria-label="`Weight of the checks: ${weight.fail} failed, ${weight.unknown} unknown, ${weight.pass} passed, of ${weight.total}`"
            :data-hot="hot ? '' : null"
          >
            <span
              v-for="c in checks"
              :key="c.id"
              class="wolf-weightbar-seg"
              :data-status="c.status"
              :data-on="hot === c.id ? '' : null"
              :style="{ flexGrow: c.weight }"
              :title="`${c.label}: ${STATUS[c.status].label.toLowerCase()}, weight ${c.weight}`"
              @mouseenter="hot = c.id"
              @mouseleave="hot = null"
              @click="reveal(c.id)"
            />
          </div>
          <ul class="wolf-legend">
            <li v-for="s in ORDER" :key="s" :data-status="s">
              <span class="wolf-legend-key" :data-status="s" aria-hidden="true" />
              <span class="wolf-legend-word">{{ STATUS[s].label }}</span>
              <span class="wolf-data wolf-legend-n">{{ weight[s] }}<span class="wolf-legend-of"> of {{ weight.total }}</span></span>
            </li>
          </ul>
        </div>

        <dl class="wolf-score-facts">
          <div>
            <dt>Checks</dt>
            <dd>{{ posture.passed }} passed, {{ posture.failed }} failed, {{ posture.unknown }} unknown</dd>
          </div>
          <div>
            <dt>Coverage</dt>
            <dd>Wolf could read {{ posture.coverage }}% of the weight</dd>
          </div>
          <div v-if="posture.hosts.length">
            <dt>Hosts</dt>
            <dd class="wolf-data">{{ posture.hosts.join(', ') }}</dd>
          </div>
        </dl>

        <p class="wolf-score-note">
          The score is the weight of the checks that passed out of all of them: a check Wolf cannot read counts as not
          passed. Agent samples older than {{ posture.recent_hours }} h are not used.
          <template v-if="!posture.local">
            System Settings of this site are read by the agent from its database, hourly.
          </template>
        </p>
      </section>
    </div>

    <section v-if="posture" class="wolf-security-main space-y-5" aria-label="Checks">
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
                <span class="wolf-label">Fix</span>
                <p>
                  <template v-for="(p, i) in parts(c.fix)" :key="i"><code v-if="p.code" class="wolf-data">{{ p.t }}</code><template v-else>{{ p.t }}</template></template>
                </p>
              </div>
            </div>
            <div class="wolf-check-weight">
              <span v-if="gain(c)" class="wolf-data wolf-check-gain" :title="`The score gains ${gain(c)} if this check passes`">+{{ gain(c) }}</span>
              <span class="wolf-check-w">weight <span class="wolf-data">{{ c.weight }}</span></span>
            </div>
          </li>
        </ul>
      </div>
      <p v-if="weight.fail + weight.unknown" class="text-sm" style="color: var(--wolf-muted)">
        +N is what the score gains if that check alone passes.
      </p>
    </section>

    <aside v-if="journal" class="wolf-security-side">
      <section class="wolf-card wolf-journal" aria-label="Journal">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="wolf-h2">Tamper-evident journal</h2>
          <Button size="sm" label="Verify" icon-left="lucide-shield-check" :loading="verifying" @click="verifyJournal" />
        </div>

        <div v-if="verdict" class="wolf-verdict" :data-ok="verdict.ok ? 'yes' : 'no'">
          <span aria-hidden="true">{{ verdict.ok ? '✓' : '✕' }}</span>
          <p role="status">
            <template v-if="verdict.ok">
              Verified: {{ verdict.checked }} entries, every digest and MAC matches, no gap<template v-if="verdict.purged_through">,
              and the journal starts where the last purge stopped (entry {{ verdict.purged_through + 1 }})</template>.
            </template>
            <template v-else>Broken<template v-if="verdict.problem?.seq"> at entry {{ verdict.problem.seq }}</template>: {{ verdict.problem?.why }}</template>
          </p>
        </div>

        <p>
          {{ journal.entries }} signed entries, {{ journal.pending }} waiting to be signed (within a minute).
          <template v-if="!journal.key">No key yet: it is created with the first signature.</template>
        </p>
        <p>
          <template v-if="journal.retention_days">Entries older than {{ journal.retention_days }} days are purged every night.</template>
          <template v-else>Kept forever (Wolf Settings → Journal Retention Days).</template>
          <template v-if="journal.purged_through">
            Entries 1 to {{ journal.purged_through }} were purged; a signed purge record says where, and verification checks it.
          </template>
        </p>

        <div v-if="journal.anchor" class="wolf-anchor">
          <div class="flex items-center justify-between gap-2">
            <span class="wolf-label">Anchor</span>
            <Button
              v-if="canCopy"
              size="sm"
              variant="ghost"
              :label="copied ? 'Copied' : 'Copy'"
              :icon-left="copied ? 'lucide-check' : 'lucide-copy'"
              @click="copyAnchor"
            />
          </div>
          <code class="wolf-data">{{ journal.anchor }}</code>
          <p>To copy somewhere Wolf cannot write (a ticket, a password manager).</p>
        </div>
      </section>
    </aside>
  </div>
</template>
