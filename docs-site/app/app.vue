<script setup lang="ts">
const { seo } = useAppConfig()
const { code, docs } = useDocsLocale()
const head = useLocaleHead()

const { data: navigation } = await useAsyncData(() => `navigation-${code.value}`, () => queryCollectionNavigation(docs.value).then(unwrapLocaleRoot), { watch: [code] })
const { data: files } = useLazyAsyncData(() => `search-${code.value}`, () => queryCollectionSearchSections(docs.value), {
  server: false,
  watch: [code]
})

useHead({
  meta: [
    { name: 'viewport', content: 'width=device-width, initial-scale=1' }
  ],
  link: [
    { rel: 'icon', type: 'image/png', href: '/favicon-32.png' },
    { rel: 'apple-touch-icon', href: '/logo-192.png' },
    ...(head.value.link || [])
  ],
  htmlAttrs: {
    lang: () => head.value.htmlAttrs?.lang
  }
})

useSeoMeta({
  titleTemplate: `%s - ${seo?.siteName}`,
  ogSiteName: seo?.siteName,
  ogImage: '/og-1200x630.png',
  twitterCard: 'summary_large_image'
})

provide('navigation', navigation)
</script>

<template>
  <UApp>
    <NuxtLoadingIndicator color="#035AEC" />

    <AppHeader />

    <UMain>
      <NuxtLayout>
        <NuxtPage />
      </NuxtLayout>
    </UMain>

    <AppFooter />

    <ClientOnly>
      <LazyUContentSearch
        :files="files"
        :navigation="navigation"
      />
    </ClientOnly>
  </UApp>
</template>
