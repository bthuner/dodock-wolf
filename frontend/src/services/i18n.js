// Translations for the Wolf UI, as Desk's __() does them: boot.messages (dodock_wolf/api/spa.py)
// holds the user's language for the app's own strings (dodock_wolf/locale), keyed `text` or
// `text:context`. A string without a translation shows as it is, in English.
//
//   __('Incidents')
//   __('{0} of {1} reporting', [fresh, total])
//   __('Open', null, 'Wolf Incident')   // a status: its DocType's own entry first
//
// Write whole sentences with placeholders, never pieces glued together: word order changes from
// one language to another. Frappe's extractor reads the first argument, so it must be a literal.

let messages = {}
let lang = 'en'

export function setMessages(boot) {
  messages = (boot && boot.messages) || {}
  lang = (boot && boot.lang) || 'en'
  if (typeof document !== 'undefined') document.documentElement.lang = lang
}

export function currentLang() {
  return lang
}

export function __(text, replace, context) {
  if (typeof text !== 'string' || !text) return text
  let out = (context && messages[`${text}:${context}`]) || messages[text] || text
  if (replace && typeof replace === 'object') {
    out = out.replace(/\{(\d+)\}/g, (match, i) => (replace[i] === undefined ? match : String(replace[i])))
  }
  return out
}

// `app.use(i18n)`: __ in every template.
export default {
  install(app) {
    app.config.globalProperties.__ = __
  },
}
