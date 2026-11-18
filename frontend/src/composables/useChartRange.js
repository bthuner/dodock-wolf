import { onBeforeUnmount, ref } from 'vue'

// A range selected on a frappe-ui axis chart, three ways to the same result:
//   - drag across the plot (a tinted band follows the pointer);
//   - click or tap two buckets;
//   - walk the chart with the arrow keys and press Enter twice (the chart's `select` event).
// `chart` is the template ref of the chart component (it exposes its ECharts instance),
// `buckets()` the ISO start of every bucket drawn, in order. `onSelect(since, until)` gets the
// first bucket's start and the last bucket's end.
export function useChartRange({ chart, buckets, bucketSeconds, onSelect }) {
  const pending = ref(null) // first bucket of a range chosen point by point
  const band = ref(null) // { left, width, top, height } in px inside the wrapper, while dragging
  let drag = null
  let last = { iso: null, at: 0 }

  const instance = () => chart.value?.chart || null
  const xOf = (inst, event) => event.clientX - inst.getDom().getBoundingClientRect().left
  function indexAt(inst, x) {
    const i = Math.round(Number(inst.convertFromPixel({ xAxisIndex: 0 }, x)))
    return Number.isFinite(i) ? Math.min(Math.max(i, 0), buckets().length - 1) : null
  }

  // the plot area inside the chart (without the axes), for the band's height; the whole chart
  // if ECharts does not say
  function plotRect(inst, dom) {
    try {
      const rect = inst.getModel().getComponent('grid').coordinateSystem.getRect()
      if (rect?.height > 0) return rect
    } catch {
      // an ECharts without this model: the band covers the chart's height
    }
    return { y: 0, height: dom.height }
  }

  function commit(a, b) {
    const [since, lastStart] = [a, b].sort()
    pending.value = null
    onSelect(since, new Date(new Date(lastStart).getTime() + bucketSeconds() * 1000).toISOString())
  }
  // one bucket chosen: the start of a range, or its end
  function point(iso) {
    if (!iso) return
    // a click on a drawn point reaches here twice, from the plot and from the chart's own event
    const now = Date.now()
    if (iso === last.iso && now - last.at < 250) return
    last = { iso, at: now }
    if (!pending.value) pending.value = iso
    else commit(pending.value, iso)
  }

  function down(event) {
    if (event.button) return
    const inst = instance()
    if (!inst || !buckets().length) return
    const dom = inst.getDom().getBoundingClientRect()
    const x = event.clientX - dom.left
    if (!inst.containPixel({ gridIndex: 0 }, [x, event.clientY - dom.top])) return // the legend, the axes
    drag = { x, moved: false, wrap: event.currentTarget, touch: event.pointerType === 'touch' }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancelDrag)
  }
  function move(event) {
    const inst = instance()
    if (!drag || !inst || drag.touch) return // a finger scrolls the page; two taps select
    const dom = inst.getDom().getBoundingClientRect()
    const x = Math.min(Math.max(event.clientX - dom.left, 0), dom.width)
    if (Math.abs(x - drag.x) > 4) drag.moved = true
    if (!drag.moved) return
    const wrap = drag.wrap.getBoundingClientRect()
    const plot = plotRect(inst, dom)
    band.value = { left: dom.left - wrap.left + Math.min(x, drag.x), width: Math.abs(x - drag.x), top: dom.top - wrap.top + plot.y, height: plot.height }
  }
  function release() {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', cancelDrag)
    drag = null
    band.value = null
  }
  function cancelDrag() {
    release()
  }
  function up(event) {
    const inst = instance()
    const from = drag
    release()
    if (!from || !inst) return
    const all = buckets()
    const a = indexAt(inst, from.x)
    const b = indexAt(inst, xOf(inst, event))
    if (a == null || b == null) return
    if (!from.moved) point(all[b])
    else if (a !== b) {
      last = { iso: all[b], at: Date.now() } // the click that ends the drag is not a new start
      commit(all[a], all[b])
    }
  }
  function cancel() {
    pending.value = null
  }
  onBeforeUnmount(release)

  return { pending, band, down, cancel, onPoint: (event) => point(event?.row?.iso) }
}
