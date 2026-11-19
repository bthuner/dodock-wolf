<script setup lang="ts">
const { seo } = useAppConfig()
const { code, docs } = useDocsLocale()
const head = useLocaleHead()
const publicPath = usePublicPath()
const { siteUrl } = useRuntimeConfig().public

const route = useRoute()
const { data: fullNavigation } = await useAsyncData(() => `navigation-${code.value}`, () => queryCollectionNavigation(docs.value).then(unwrapLocaleRoot), { watch: [code] })
// The unlisted section (useUnlisted.ts) shows in the sidebar only to a reader who is already in it.
const navigation = computed(() => (fullNavigation.value || []).filter(item => isUnlisted(route.path) || !isUnlisted(item.path)))
const { data: files } = useLazyAsyncData(() => `search-${code.value}`, () => queryCollectionSearchSections(docs.value)
  // the unlisted section is not searchable (useUnlisted.ts)
  .where('path', 'NOT LIKE', `%${UNLISTED_SECTION}%`), {
  server: false,
  watch: [code]
})

useHead({
  meta: [
    { name: 'viewport', content: 'width=device-width, initial-scale=1' }
  ],
  link: [
    { rel: 'icon', type: 'image/png', href: publicPath('/favicon-32.png') },
    { rel: 'apple-touch-icon', href: publicPath('/logo-192.png') },
    ...(head.value.link || [])
  ],
  htmlAttrs: {
    lang: () => head.value.htmlAttrs?.lang
  }
})

useSeoMeta({
  titleTemplate: `%s - ${seo?.siteName}`,
  ogSiteName: seo?.siteName,
  ogImage: `${siteUrl}/og-1200x630.png`,
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
