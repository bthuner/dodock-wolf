const repo = 'https://github.com/bthuner/dodock-wolf'

export default defineAppConfig({
  ui: {
    colors: {
      primary: 'wolf',
      neutral: 'slate'
    },
    footer: {
      slots: {
        root: 'border-t border-default',
        left: 'text-sm text-muted'
      }
    }
  },
  seo: {
    siteName: 'Frappe Wolf'
  },
  repo,
  header: {
    search: true,
    colorMode: true,
    links: [{
      'icon': 'i-simple-icons-github',
      'to': repo,
      'target': '_blank',
      'aria-label': 'GitHub'
    }]
  },
  footer: {
    links: [{
      'icon': 'i-simple-icons-github',
      'to': repo,
      'target': '_blank',
      'aria-label': 'GitHub'
    }]
  },
  toc: {
    edit: `${repo}/edit/main/docs-site/content`,
    links: [{
      icon: 'i-lucide-star',
      label: 'GitHub',
      to: repo,
      target: '_blank'
    }, {
      icon: 'i-lucide-book-open',
      label: 'doc.dokos.io',
      to: 'https://doc.dokos.io',
      target: '_blank'
    }]
  }
})
