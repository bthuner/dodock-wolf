// Times arrive in UTC and are shown in the site's time zone (boot.time_zone), never the
// browser's: an operator abroad reads the same 02:00 as the team. Day and month names follow
// the reader's language (boot.lang); English keeps the en-GB day-month order.

import { __, locale } from '@/services/i18n'

function parts(iso, timeZone, options) {
  return new Intl.DateTimeFormat(locale(), { timeZone, ...options }).format(new Date(iso))
}

export function clock(iso, timeZone) {
  return iso ? parts(iso, timeZone, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : ''
}

export function day(iso, timeZone) {
  return iso ? parts(iso, timeZone, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

export function full(iso, timeZone, { zone = true } = {}) {
  if (!iso) return ''
  const text = parts(iso, timeZone, {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  })
  return zone ? `${text} (${timeZone})` : text
}

// minutes, hours and minutes, or days and hours between two times
function span(fromIso, toIso) {
  const minutes = Math.max(0, Math.round((new Date(toIso) - new Date(fromIso)) / 60000))
  if (minutes < 60) return { minutes }
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return { hours, minutes: String(minutes % 60).padStart(2, '0') }
  return { days: Math.floor(hours / 24), hours: hours % 24 }
}

export function duration(fromIso, toIso) {
  if (!fromIso || !toIso) return ''
  const s = span(fromIso, toIso)
  if (s.days != null) return __('{0} d {1} h', [s.days, s.hours])
  if (s.hours != null) return __('{0} h {1} min', [s.hours, s.minutes])
  return __('{0} min', [s.minutes])
}

// chart axis label in the site's zone: the clock for a day or less, else the date too
export function axisLabel(iso, timeZone, withDate) {
  const options = withDate
    ? { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
    : { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
  return parts(iso, timeZone, options)
}

// The time since `iso` as a whole phrase: "3 min ago" (French "il y a 3 min").
export function timeAgo(iso, now = new Date()) {
  if (!iso) return ''
  const s = span(iso, now.toISOString())
  if (s.days != null) return __('{0} d {1} h ago', [s.days, s.hours])
  if (s.hours != null) return __('{0} h {1} min ago', [s.hours, s.minutes])
  return __('{0} min ago', [s.minutes])
}
