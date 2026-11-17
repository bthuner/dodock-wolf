// Checks every internal link and #anchor of the generated site (.output/public), in both
// languages. Run after `yarn generate`: `node scripts/check-links.mjs`. Exits 1 on a broken link.
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('../.output/public', import.meta.url).pathname
const pages = new Map() // route -> { ids, links }

const walk = dir => readdirSync(dir, { withFileTypes: true }).flatMap(e =>
  e.isDirectory() ? walk(join(dir, e.name)) : e.name === 'index.html' ? [join(dir, e.name)] : [])

for (const file of walk(root)) {
  const html = readFileSync(file, 'utf8')
  const route = '/' + relative(root, file).replace(/index\.html$/, '').replace(/\/$/, '')
  const main = html // header, sidebar and footer included: they link too
  const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]))
  const links = [...main.matchAll(/\shref="(\/[^"]*)"/g)].map(m => m[1].replace(/&amp;/g, '&'))
  pages.set(route === '/' ? '/' : route, { ids, links })
}

const broken = []
for (const [route, { links }] of pages) {
  for (const href of links) {
    if (/^\/(_nuxt|raw|img|_fonts|__nuxt_content|llms|favicon|logo|og-)/.test(href)) continue
    const [withQuery, hash] = href.split('#')
    const path = withQuery.split('?')[0]
    const target = path.replace(/\/$/, '') || '/'
    const page = pages.get(target)
    if (!page) {
      if (!existsSync(join(root, target))) broken.push(`${route} → ${href} (no page)`)
      continue
    }
    if (hash && !page.ids.has(decodeURIComponent(hash))) broken.push(`${route} → ${href} (no anchor)`)
  }
}

const unique = [...new Set(broken)].sort()
console.log(`${pages.size} pages checked, ${unique.length} broken link(s)`)
for (const b of unique) console.log('  ' + b)
process.exit(unique.length ? 1 : 0)
