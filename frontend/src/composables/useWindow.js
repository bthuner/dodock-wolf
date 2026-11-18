import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { pick } from '@/services/filters'

// The time window of a page, kept in the URL: relative (`?range=7d`) or explicit
// (`?since=&until=`, what a range selected on a chart becomes). Explicit wins, as on the server
// (wolf/window.py). The pages that share it read the same window from the same link.
export function useWindow(ranges, fallback = '24h') {
  const route = useRoute()
  const router = useRouter()

  const range = computed(() => pick(route.query.range, ranges, fallback))
  const explicit = computed(() => {
    const { since, until } = route.query
    return since ? { since: String(since), ...(until ? { until: String(until) } : {}) } : null
  })
  // what the API calls take
  const args = computed(() => explicit.value || { range: range.value })
  // the same window for a link to another page (the default range is not written)
  const query = computed(() => explicit.value || (range.value === fallback ? {} : { range: range.value }))

  function replace(patch) {
    const next = { ...route.query, ...patch }
    delete next.cursor
    router.replace({ query: next, hash: route.hash })
  }
  const select = (since, until) => replace({ since, until, range: undefined })
  const reset = () => replace({ since: undefined, until: undefined })
  const choose = (value) => replace({ range: value === fallback ? undefined : value, since: undefined, until: undefined })

  return { range, explicit, args, query, select, reset, choose }
}
