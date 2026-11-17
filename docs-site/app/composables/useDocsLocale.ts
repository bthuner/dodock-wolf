// The collections of the current language (content.config.ts) and the UI strings that are
// not in the Markdown.
const strings = {
  en: {
    toc: 'On this page',
    community: 'Community',
    edit: 'Edit this page',
    copyPage: 'Copy page',
    copied: 'Copied to clipboard',
    copyLink: 'Copy Markdown link',
    viewMarkdown: 'View as Markdown',
    notFound: 'Page not found',
    notFoundDescription: 'This page does not exist, or not in this language yet.',
    credits: 'Dodock Wolf · MIT · Built by Dokos'
  },
  fr: {
    toc: 'Sur cette page',
    community: 'Communauté',
    edit: 'Modifier cette page',
    copyPage: 'Copier la page',
    copied: 'Copié dans le presse-papiers',
    copyLink: 'Copier le lien Markdown',
    viewMarkdown: 'Voir en Markdown',
    notFound: 'Page introuvable',
    notFoundDescription: 'Cette page n’existe pas, ou pas encore dans cette langue.',
    credits: 'Dodock Wolf · MIT · Conçu par Dokos'
  }
} as const

export type DocsLocale = keyof typeof strings

export function useDocsLocale() {
  const { locale } = useI18n()
  const code = computed(() => (locale.value in strings ? locale.value : 'en') as DocsLocale)
  return {
    code,
    t: computed(() => strings[code.value]),
    docs: computed(() => `docs_${code.value}` as const),
    landing: computed(() => `landing_${code.value}` as const)
  }
}

// French pages live under /fr, which Nuxt Content turns into one "Fr" parent holding the whole
// tree. The sidebar wants the sections themselves.
export function unwrapLocaleRoot<T extends { path: string, children?: T[] }>(items: T[]): T[] {
  return items.length === 1 && /^\/[a-z]{2}$/.test(items[0]!.path) && items[0]!.children
    ? items[0]!.children
    : items
}
