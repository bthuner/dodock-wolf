import { defineContentConfig, defineCollection, z } from '@nuxt/content'

// One landing page and one docs tree per language. Paths match the routes @nuxtjs/i18n
// builds: English without a prefix, French under /fr.
const links = z.array(z.object({
  label: z.string(),
  icon: z.string(),
  to: z.string(),
  target: z.string().optional()
})).optional()

const locales = { en: '', fr: '/fr' } as const

export default defineContentConfig({
  collections: Object.fromEntries(Object.entries(locales).flatMap(([code, prefix]) => [
    [`landing_${code}`, defineCollection({
      type: 'page',
      source: { include: `${code}/index.md`, prefix: prefix || '/' }
    })],
    [`docs_${code}`, defineCollection({
      type: 'page',
      source: { include: `${code}/**`, exclude: [`${code}/index.md`], prefix },
      schema: z.object({ links })
    })]
  ]))
})
