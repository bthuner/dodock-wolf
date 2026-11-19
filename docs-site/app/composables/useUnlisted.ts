// The unlisted section (content/<lang>/7.internals/): pages that have a URL but are kept out of
// the sidebar and the previous/next links of the listed pages, out of the search, and out of
// search engines. llms.txt lists its sections by name (nuxt.config.ts), so it leaves them out
// too. Unlisted is not private: the site is public and so is its repository. Nothing secret goes
// there.
export const UNLISTED_SECTION = '/internals'

// The route without its locale prefix: /fr/internals/apps → /internals/apps.
export function isUnlisted(path: string): boolean {
  const bare = path.replace(/^\/[a-z]{2}(?=\/|$)/, '')
  return bare === UNLISTED_SECTION || bare.startsWith(`${UNLISTED_SECTION}/`)
}
