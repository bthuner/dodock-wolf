<script setup>
import { Sidebar, SidebarHeader, SidebarItem, SidebarLabel, useColorScheme } from 'frappe-ui'

import { computed, inject } from 'vue'

import { logout } from '@/services/boot'
import { __ } from '@/services/i18n'

const boot = inject('boot')
const { colorScheme, setColorScheme } = useColorScheme()

const SCHEMES = [
  { value: 'light', label: () => __('Light theme') },
  { value: 'dark', label: () => __('Dark theme') },
  { value: 'system', label: () => __('System theme') },
]

const menu = computed(() => [
  ...SCHEMES.map((s) => ({
    label: s.label(),
    selected: colorScheme.value === s.value,
    onClick: () => setColorScheme(s.value),
  })),
  { label: __('Open Desk'), icon: 'lucide-external-link', onClick: () => window.location.assign(boot.desk.home) },
  { label: __('Log out'), icon: 'lucide-log-out', onClick: () => logout() },
])
</script>

<template>
  <Sidebar aria-label="Wolf">
    <SidebarHeader
      title="Dodock Wolf"
      :subtitle="boot.user.full_name"
      logo="/assets/dodock_wolf/images/wolf.png"
      :menu-items="menu"
    />
    <div class="flex-1 overflow-y-auto px-2 pb-2">
      <SidebarItem :label="__('Overview')" icon="lucide-layout-dashboard" :route="{ name: 'overview' }" />
      <SidebarItem
        v-if="boot.capabilities.incidents.available"
        :label="__('Incidents')"
        icon="lucide-siren"
        :route="{ name: 'incidents' }"
      />
      <SidebarItem :label="__('Events')" icon="lucide-list" :route="{ name: 'events' }" />
      <SidebarItem :label="__('Errors')" icon="lucide-bug" :route="{ name: 'errors' }" />
      <SidebarItem :label="__('Security')" icon="lucide-shield" :route="{ name: 'security' }" />
      <SidebarLabel>{{ __('Explore') }}</SidebarLabel>
      <SidebarItem :label="__('Logs')" icon="lucide-scroll-text" :route="{ name: 'logs' }" />
      <SidebarLabel>Wolf</SidebarLabel>
      <SidebarItem :label="__('Operations')" icon="lucide-gauge" :route="{ name: 'operations' }" />
      <SidebarItem :label="__('Monitoring')" icon="lucide-activity" :route="{ name: 'monitoring' }" />
      <SidebarItem
        v-if="boot.can.configure"
        :label="__('Alert rules (Desk)')"
        icon="lucide-bell"
        :href="boot.desk.fallbacks.alert_rules"
      />
    </div>
  </Sidebar>
</template>
