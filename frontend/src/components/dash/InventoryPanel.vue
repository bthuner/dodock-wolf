<script setup>
import { Button, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { ago, full } from '@/services/time'

// Hosts > benches > sites as get_inventory answers them, drawn as a schematic: a host, the
// rail to its benches, each bench's sites. Nothing is judged here: the panel says where each
// host is known from and when it was last seen, as the server says it.
const props = defineProps({
  inventory: { type: Object, required: true },
  host: { type: String, default: '' }, // a host page draws this host only
  timeZone: { type: String, required: true },
})

// the first hosts are drawn, the rest on demand (drawing 101 hosts was part of the page's time)
const FIRST_HOSTS = 20
const allHosts = ref(false)
const query = ref('')
watch(() => props.host, () => {
  allHosts.value = false
  query.value = ''
})

const REGISTERED = { agent: 'Agent registered', satellite: 'Known through a satellite' }
const TELEMETRY = ['events', 'metrics', 'incidents']

// a host's rows: its benches, then the sites seen on it with no bench named
function rowsOf(h) {
  const rows = (h.benches || []).map((b) => ({ key: `b:${b.bench}`, bench: b.bench, sites: b.sites || [] }))
  if (h.sites?.length) rows.push({ key: 'no-bench', bench: null, sites: h.sites })
  return rows
}

const hosts = computed(() => {
  const all = props.inventory.hosts || []
  return (props.host ? all.filter((h) => h.host === props.host) : all).map((h) => {
    const sources = h.sources || []
    const registered = ['agent', 'satellite'].find((s) => sources.includes(s))
    return { ...h, registered, telemetry: TELEMETRY.filter((s) => sources.includes(s)), rows: rowsOf(h) }
  })
})
// sites seen with no host at all: listed apart, never attached to a guessed host
const unplaced = computed(() => (props.host ? [] : props.inventory.unplaced_sites || []))

const totals = computed(() => {
  const sites = new Set(unplaced.value.map((s) => s.site))
  let benches = 0
  for (const h of hosts.value) {
    for (const r of h.rows) {
      if (r.bench) benches++
      for (const s of r.sites) sites.add(s.site)
    }
  }
  return { hosts: hosts.value.length, benches, sites: sites.size }
})
const plural = (n, word) => (n === 1 ? word : `${word === 'bench' ? 'benche' : word}s`)
const figures = computed(() => {
  const t = totals.value
  const all = [{ n: t.hosts, label: plural(t.hosts, 'host') }, { n: t.benches, label: plural(t.benches, 'bench') }, { n: t.sites, label: plural(t.sites, 'site') }]
  return props.host ? all.slice(1) : all
})
const canFilter = computed(() => totals.value.hosts >= 4 || totals.value.sites >= 10)

// the filter keeps a host that matches whole, else its benches and sites that match
const needle = computed(() => query.value.trim().toLowerCase())
const hit = (text) => (text || '').toLowerCase().includes(needle.value)
const matched = computed(() => {
  if (!needle.value) return hosts.value
  return hosts.value
    .map((h) => {
      if (hit(h.host)) return h
      const rows = h.rows
        .map((r) => (r.bench && hit(r.bench) ? r : { ...r, sites: r.sites.filter((s) => hit(s.site)) }))
        .filter((r) => (r.bench && hit(r.bench)) || r.sites.length)
      return rows.length ? { ...h, rows } : null
    })
    .filter(Boolean)
})
const matchedUnplaced = computed(() => (needle.value ? unplaced.value.filter((s) => hit(s.site)) : unplaced.value))
const shown = computed(() => (allHosts.value ? matched.value : matched.value.slice(0, FIRST_HOSTS)))

// a site name reads by its first label; the rest of the domain repeats across the list
function parts(site) {
  const dot = (site || '').indexOf('.')
  return dot > 0 ? [site.slice(0, dot), site.slice(dot)] : [site, '']
}
</script>

<template>
  <section class="wolf-card wolf-estate" aria-label="Hosts, benches and sites">
    <div class="wolf-estate-head">
      <div>
        <h2 class="wolf-h2">{{ host ? 'Benches and sites on this host' : 'Hosts, benches and sites' }}</h2>
        <dl class="wolf-estate-totals">
          <div v-for="f in figures" :key="f.label">
            <dt>{{ f.label }}</dt>
            <dd class="wolf-data">{{ f.n }}</dd>
          </div>
        </dl>
      </div>
      <TextInput
        v-if="canFilter"
        v-model="query"
        type="search"
        class="w-64 max-w-full"
        placeholder="Find a host, bench or site"
        aria-label="Find a host, bench or site"
      />
    </div>

    <div class="wolf-estate-cols" aria-hidden="true">
      <span>Host</span>
      <span>Bench</span>
      <span>Sites</span>
    </div>

    <ul class="wolf-estate-list">
      <li v-for="h in shown" :key="h.host" class="wolf-estate-host" :data-registered="h.registered ? 'yes' : 'no'">
        <div class="wolf-estate-id">
          <div class="wolf-estate-name">
            <span class="wolf-estate-dot" aria-hidden="true" />
            <RouterLink class="wolf-data" :to="{ name: 'host', params: { host: h.host } }">{{ h.host }}</RouterLink>
            <span v-if="h.rows.length" class="wolf-estate-lead" aria-hidden="true" />
          </div>
          <p class="wolf-estate-meta">
            {{ REGISTERED[h.registered] || 'No agent registered' }}<template v-if="h.last_seen">
              · <span :title="full(h.last_seen, timeZone)">seen {{ ago(h.last_seen) }} ago</span></template>
          </p>
          <ul v-if="h.telemetry.length" class="wolf-estate-srcs" aria-label="Telemetry received">
            <li v-for="s in h.telemetry" :key="s">{{ s }}</li>
          </ul>
        </div>

        <ul v-if="h.rows.length" class="wolf-estate-benches">
          <li v-for="r in h.rows" :key="r.key" class="wolf-estate-bench" :data-unknown="r.bench ? null : ''">
            <div class="wolf-estate-benchname">
              <RouterLink v-if="r.bench" class="wolf-data" :to="{ name: 'bench', params: { host: h.host, bench: r.bench } }">{{ r.bench }}</RouterLink>
              <span v-else class="wolf-estate-nobench">bench not known</span>
              <span v-if="r.sites.length > 1" class="wolf-data wolf-estate-count" :aria-label="`${r.sites.length} sites`">{{ r.sites.length }}</span>
            </div>
            <ul v-if="r.sites.length" class="wolf-estate-sites">
              <li v-for="s in r.sites" :key="s.site">
                <RouterLink class="wolf-data wolf-estate-site" :to="{ name: 'site', params: { site: s.site } }">{{ parts(s.site)[0] }}<span>{{ parts(s.site)[1] }}</span></RouterLink>
              </li>
            </ul>
            <p v-else class="wolf-estate-none">no site seen</p>
          </li>
        </ul>
        <p v-else class="wolf-estate-none wolf-estate-bare">no bench seen</p>
      </li>
    </ul>

    <div v-if="matchedUnplaced.length" class="wolf-estate-unplaced">
      <h3 class="wolf-label">Sites with no known host</h3>
      <ul class="wolf-estate-sites">
        <li v-for="s in matchedUnplaced" :key="s.site">
          <RouterLink class="wolf-data wolf-estate-site" :to="{ name: 'site', params: { site: s.site } }">{{ parts(s.site)[0] }}<span>{{ parts(s.site)[1] }}</span></RouterLink>
        </li>
      </ul>
    </div>

    <p v-if="needle && !matched.length && !matchedUnplaced.length" class="wolf-estate-empty" role="status">
      No host, bench or site contains “{{ query.trim() }}”.
      <button type="button" class="wolf-link" @click="query = ''">Clear the filter</button>
    </p>

    <div class="wolf-estate-foot">
      <p v-if="needle && matched.length" role="status">{{ matched.length }} of {{ hosts.length }} {{ plural(hosts.length, 'host') }} match.</p>
      <Button
        v-if="matched.length > FIRST_HOSTS"
        size="sm"
        variant="ghost"
        :label="allHosts ? `Show the first ${FIRST_HOSTS} hosts only` : `Show the other ${matched.length - FIRST_HOSTS} of ${matched.length} hosts`"
        @click="allHosts = !allHosts"
      />
      <p v-if="inventory.note">{{ inventory.note }}</p>
    </div>
  </section>
</template>
