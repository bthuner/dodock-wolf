import { createRouter, createWebHistory } from 'vue-router'

import { __ } from '@/services/i18n'

const Pending = () => import('@/pages/PendingPage.vue')

// Every view of #19. `fallback` names the Desk page (boot.desk.fallbacks) that covers a view
// until it is built here; `planned` tells the reader what the view will show. `title` (and
// `planned`) is a function, so it is translated when shown, not when this module loads.
export const routes = [
  { path: '/', name: 'overview', component: () => import('@/pages/DashboardPage.vue'), meta: { title: () => __('Overview') } },
  { path: '/incidents', name: 'incidents', component: () => import('@/pages/IncidentsPage.vue'),
    meta: { title: () => __('Incidents'), capability: 'incidents' } },
  { path: '/incidents/:incident', name: 'incident', component: () => import('@/pages/IncidentPage.vue'),
    meta: { title: () => __('Incident'), capability: 'incidents' } },
  { path: '/events', name: 'events', component: () => import('@/pages/EventsPage.vue'), meta: { title: () => __('Events') } },
  { path: '/errors', name: 'errors', component: () => import('@/pages/ErrorsPage.vue'), meta: { title: () => __('Errors') } },
  { path: '/errors/:fingerprint', name: 'error-group', component: () => import('@/pages/ErrorGroupPage.vue'), meta: { title: () => __('Error group') } },
  { path: '/logs', name: 'logs', component: () => import('@/pages/LogsPage.vue'), meta: { title: () => __('Logs') } },
  { path: '/sites/:site', name: 'site', component: () => import('@/pages/DashboardPage.vue'), meta: { title: () => __('Site') } },
  { path: '/hosts/:host', name: 'host', component: () => import('@/pages/DashboardPage.vue'), meta: { title: () => __('Host') } },
  // bench names repeat across hosts, so a bench is always addressed through its host
  { path: '/hosts/:host/benches/:bench', name: 'bench', component: () => import('@/pages/DashboardPage.vue'), meta: { title: () => __('Bench') } },
  { path: '/security', name: 'security', component: () => import('@/pages/SecurityPage.vue'), meta: { title: () => __('Security') } },
  { path: '/monitoring', name: 'monitoring', component: () => import('@/pages/MonitoringPage.vue'), meta: { title: () => __('Monitoring') } },
  // where a view this site cannot have leads (incidents on a satellite); ?from= keeps the link
  { path: '/unavailable/:path(.*)*', name: 'unavailable', component: Pending,
    meta: { title: () => __('Incidents'), capability: 'incidents', noSubject: true } },
  { path: '/:path(.*)*', name: 'not-found', component: () => import('@/pages/NotFoundPage.vue'), meta: { title: () => __('Not found') } },
]

// a route's title or planned text in the reader's language; a plain string is shown as it is
export function routeText(value) {
  return typeof value === 'function' ? value() : value || ''
}

export function makeRouter(history = createWebHistory('/wolf'), boot = null) {
  const router = createRouter({ history, routes })
  // a view that needs a backend this site lacks (incidents on a satellite) explains instead
  router.beforeEach((to) => {
    const cap = to.meta.capability
    if (cap && boot && to.name !== 'unavailable' && !boot.capabilities?.[cap]?.available) {
      return { name: 'unavailable', params: { path: to.path.split('/').filter(Boolean) }, query: { from: to.fullPath } }
    }
  })
  router.afterEach((to) => {
    const title = routeText(to.meta.title)
    document.title = title ? __('{0} · Dodock Wolf', [title]) : 'Dodock Wolf'
  })
  return router
}
