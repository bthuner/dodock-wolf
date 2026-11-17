<script setup lang="ts">
import type { NuxtError } from '#app'

const props = defineProps<{
  error: NuxtError
}>()

const { code, docs, t } = useDocsLocale()

useHead({ htmlAttrs: { lang: code.value } })
useSeoMeta({ title: t.value.notFound, description: t.value.notFoundDescription })

const { data: navigation } = await useAsyncData(`navigation-${code.value}`, () => queryCollectionNavigation(docs.value).then(unwrapLocaleRoot))
const { data: files } = useLazyAsyncData(`search-${code.value}`, () => queryCollectionSearchSections(docs.value), {
  server: false
})

provide('navigation', navigation)

const shown = computed(() => props.error.statusCode === 404
  ? { ...props.error, statusMessage: t.value.notFound, message: t.value.notFoundDescription }
  : props.error)
</script>

<template>
  <UApp>
    <AppHeader />

    <UError :error="shown" />

    <AppFooter />

    <ClientOnly>
      <LazyUContentSearch
        :files="files"
        :navigation="navigation"
      />
    </ClientOnly>
  </UApp>
</template>
