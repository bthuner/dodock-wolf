import { afterEach, describe, expect, it } from 'vitest'

import { __, currentLang, setMessages } from '@/services/i18n'

describe('__', () => {
  afterEach(() => setMessages(null))

  it('shows the English when nothing is loaded, placeholders filled', () => {
    expect(__('Incidents')).toBe('Incidents')
    expect(__('{0} of {1} reporting', [2, 3])).toBe('2 of 3 reporting')
    expect(currentLang()).toBe('en')
  })

  it('uses the context entry first, then the plain one, as Desk does', () => {
    setMessages({
      lang: 'fr',
      messages: { Open: 'Ouvrir', 'Open:Wolf Incident': 'Ouvert', '{0} of {1} reporting': '{0} sur {1} envoient' },
    })
    expect(__('Open', null, 'Wolf Incident')).toBe('Ouvert')
    expect(__('Open')).toBe('Ouvrir')
    expect(__('Open', null, 'Wolf Postmortem Action Item')).toBe('Ouvrir')
    expect(__('{0} of {1} reporting', [2, 3])).toBe('2 sur 3 envoient')
    expect(__('Not translated')).toBe('Not translated')
    expect(currentLang()).toBe('fr')
    expect(document.documentElement.lang).toBe('fr')
  })

  it('leaves a placeholder it has no value for, and ignores what is not a string', () => {
    expect(__('{0} and {1}', ['a'])).toBe('a and {1}')
    expect(__(null)).toBe(null)
    expect(__('')).toBe('')
  })
})
