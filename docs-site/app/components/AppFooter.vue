<script setup lang="ts">
const { footer } = useAppConfig()
const { t } = useDocsLocale()
</script>

<template>
  <UFooter>
    <template #left>
      {{ t.credits }}
    </template>

    <template #right>
      <template v-if="footer?.links">
        <UButton
          v-for="(link, index) of footer?.links"
          :key="index"
          v-bind="{ color: 'neutral', variant: 'ghost', ...link }"
        />
      </template>
    </template>
  </UFooter>
</template>
