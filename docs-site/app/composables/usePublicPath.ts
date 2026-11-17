import { joinURL } from 'ufo'

// A file of public/ under the app's base URL: /logo-192.png locally, /dodock-wolf/logo-192.png on
// GitHub Pages (NUXT_APP_BASE_URL). Router links get the base by themselves; plain src, href and
// $fetch do not.
export function usePublicPath() {
  const base = useRuntimeConfig().app.baseURL
  return (path: string) => joinURL(base, path)
}
