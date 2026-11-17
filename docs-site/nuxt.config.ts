import { readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

// Every page of content/{en,fr}, as a route. The sidebar (UContentNavigation) unmounts collapsed
// branches, so link crawling alone misses pages; doc.dokos.io seeds its routes the same way.
const CONTENT_DIR = fileURLToPath(new URL('./content', import.meta.url))
function contentRoutes(): string[] {
  const walk = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap(e =>
    e.isDirectory() ? walk(join(dir, e.name)) : e.name.endsWith('.md') ? [join(dir, e.name)] : [])
  return walk(CONTENT_DIR).map((file) => {
    const [locale, ...parts] = relative(CONTENT_DIR, file).replace(/\.md$/, '').split('/')
    const segments = parts.map(s => s.replace(/^\d+\./, '')).filter(s => s !== 'index')
    return `${locale === 'en' ? '' : `/${locale}`}/${segments.join('/')}`.replace(/\/$/, '') || '/'
  })
}

// Same stack as doc.dokos.io (gitlab.com/dokos/documentation): Nuxt + Nuxt UI + Nuxt Content.
// English lives at /, French at /fr. Each language is its own content tree (content/en,
// content/fr) and its own pair of collections (content.config.ts).
export default defineNuxtConfig({
  modules: [
    '@nuxt/eslint',
    '@nuxt/image',
    '@nuxt/ui',
    '@nuxt/content',
    '@nuxtjs/i18n',
    'nuxt-llms'
  ],

  devtools: {
    enabled: true
  },

  css: ['~/assets/css/main.css'],

  content: {
    build: {
      markdown: {
        toc: {
          searchDepth: 1
        },
        highlight: {
          langs: ['bash', 'shell', 'json', 'yaml', 'toml', 'python', 'ini', 'xml', 'nginx', 'js', 'ts', 'sql', 'diff']
        }
      }
    },
    // Node's built-in sqlite: no native module to build.
    experimental: {
      sqliteConnector: 'native'
    }
  },

  runtimeConfig: {
    public: {
      // Placeholder until the site has a host: set NUXT_PUBLIC_SITE_URL at build time.
      siteUrl: process.env.NUXT_PUBLIC_SITE_URL || 'https://wolf.dokos.io'
    }
  },

  compatibilityDate: '2026-06-30',

  nitro: {
    prerender: {
      routes: ['/', '/fr', ...contentRoutes()],
      crawlLinks: true,
      // A broken link fails the build. DOCS_ALLOW_BROKEN=1 previews a half-written tree.
      failOnError: process.env.DOCS_ALLOW_BROKEN !== '1'
    }
  },

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  },

  i18n: {
    defaultLocale: 'en',
    strategy: 'prefix_except_default',
    locales: [
      { code: 'en', language: 'en-GB', name: 'English' },
      { code: 'fr', language: 'fr-FR', name: 'Français' }
    ],
    detectBrowserLanguage: false
  },

  icon: {
    provider: 'server',
    serverBundle: 'local',
    fallbackToApi: false,
    // Server-rendered icon CSS is deduplicated across prerendered pages, so an icon first drawn
    // on one page loses its style on the next. Bundle every icon the app and content use.
    clientBundle: {
      scan: { globInclude: ['app/**/*.vue', 'app/**/*.ts', 'content/**/*.md', 'content/**/*.yml'] },
      icons: ['simple-icons:github', 'simple-icons:markdown']
    }
  },

  llms: {
    domain: 'https://wolf.dokos.io',
    title: 'Frappe Wolf',
    description: 'Self-hosted observability and security for Frappe benches, ERPNext and Dokos sites, and their Linux hosts.',
    full: {
      title: 'Frappe Wolf: full documentation',
      description: 'Every page of the Frappe Wolf documentation, in English.'
    },
    sections: [
      { title: 'Getting started', contentCollection: 'docs_en', contentFilters: [{ field: 'path', operator: 'LIKE', value: '/getting-started%' }] },
      { title: 'Install', contentCollection: 'docs_en', contentFilters: [{ field: 'path', operator: 'LIKE', value: '/install%' }] },
      { title: 'Wolf Agent', contentCollection: 'docs_en', contentFilters: [{ field: 'path', operator: 'LIKE', value: '/agent%' }] },
      { title: 'Alerts and incidents', contentCollection: 'docs_en', contentFilters: [{ field: 'path', operator: 'LIKE', value: '/alerts%' }] },
      { title: 'Security', contentCollection: 'docs_en', contentFilters: [{ field: 'path', operator: 'LIKE', value: '/security%' }] },
      { title: 'Reference', contentCollection: 'docs_en', contentFilters: [{ field: 'path', operator: 'LIKE', value: '/reference%' }] }
    ]
  }
})
