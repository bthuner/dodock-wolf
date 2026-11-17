<script setup lang="ts">
const { locale, locales } = useI18n()
const switchLocalePath = useSwitchLocalePath()

const items = computed(() => locales.value.map(l => ({
  label: l.name,
  to: switchLocalePath(l.code),
  active: l.code === locale.value
})))
</script>

<template>
  <UDropdownMenu :items="items">
    <UButton
      color="neutral"
      variant="ghost"
      icon="i-lucide-languages"
      :label="locale.toUpperCase()"
      aria-label="Language"
    />
  </UDropdownMenu>
</template>
