<script setup>
import { Button, PageHeader } from 'frappe-ui'
import { inject, onMounted, ref } from 'vue'

import LoadingNote from '@/components/LoadingNote.vue'
import PageTitle from '@/components/PageTitle.vue'
import MonitoringPanel from '@/components/dash/MonitoringPanel.vue'
import OnboardingPanel from '@/components/dash/OnboardingPanel.vue'
import { call, failure } from '@/services/api'
import { __ } from '@/services/i18n'

const boot = inject('boot')
const monitoring = ref(null)
const error = ref(null)
const loading = ref(false)
const onboarding = ref(null)

async function load() {
  loading.value = true
  error.value = null
  onboarding.value?.load()
  try {
    monitoring.value = await call('dodock_wolf.api.dashboard.get_monitoring')
  } catch (e) {
    error.value = failure(e, __("Wolf's own monitoring"))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <PageHeader>
    <PageTitle :title="__('Monitoring')" />
    <Button :label="__('Refresh')" icon-left="lucide-refresh-cw" :loading="loading" @click="load" />
  </PageHeader>
  <div class="wolf-page space-y-5">
    <p v-if="error" role="alert" class="wolf-alert">{{ error }}</p>
    <LoadingNote v-if="loading && !monitoring && !error" />
    <OnboardingPanel v-if="boot.can?.configure && !boot.satellite" ref="onboarding" />
    <MonitoringPanel v-if="monitoring" :monitoring="monitoring" :time-zone="boot.time_zone" />
  </div>
</template>
