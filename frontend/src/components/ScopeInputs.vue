<script setup>
import { TextInput } from 'frappe-ui'

import { useQueryParam } from '@/composables/useQueryParam'
import { __ } from '@/services/i18n'

// Site, host and bench in the URL. A bench is named on its host: its field appears once a host is set.
const site = useQueryParam('site')
const host = useQueryParam('host')
const bench = useQueryParam('bench')
</script>

<template>
  <TextInput :model-value="site" :placeholder="__('Site')" class="w-40" :aria-label="__('Site')" @change="site = $event.target.value.trim()" />
  <TextInput :model-value="host" :placeholder="__('Host')" class="w-36" :aria-label="__('Host')" @change="host = $event.target.value.trim()" />
  <TextInput v-if="host" :model-value="bench" :placeholder="__('Bench')" class="w-36" :aria-label="__('Bench')" @change="bench = $event.target.value.trim()" />
</template>
