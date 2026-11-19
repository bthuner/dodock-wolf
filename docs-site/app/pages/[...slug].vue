<script setup lang="ts">
import type { ContentNavigationItem } from '@nuxt/content'
import { findPageHeadline } from '@nuxt/content/utils'
import { withoutTrailingSlash } from 'ufo'

definePageMeta({
  layout: 'docs'
})

const route = useRoute()
const { toc } = useAppConfig()
const { docs, t } = useDocsLocale()
const navigation = inject<Ref<ContentNavigationItem[]>>('navigation')
const routePath = computed(() => withoutTrailingSlash(route.path))

const { data: page } = await useAsyncData(routePath.value, () => queryCollection(docs.value).path(routePath.value).first())
if (!page.value) {
  throw createError({ statusCode: 404, statusMessage: 'Page not found', fatal: true })
}

// An unlisted page (useUnlisted.ts) is not indexed. Its previous/next links stay inside the
// section, and no listed page points into it.
const unlisted = isUnlisted(routePath.value)

const { data: surround } = await useAsyncData(`${routePath.value}-surround`, () => {
  return queryCollectionItemSurroundings(docs.value, routePath.value, {
    fields: ['description']
  }).where('path', unlisted ? 'LIKE' : 'NOT LIKE', `%${UNLISTED_SECTION}%`)
})

const title = page.value.seo?.title || page.value.title
const description = page.value.seo?.description || page.value.description

useSeoMeta({
  title,
  ogTitle: title,
  description,
  ogDescription: description,
  robots: unlisted ? 'noindex, nofollow' : undefined
})

const headline = computed(() => findPageHeadline(navigation?.value, page.value?.path))

const links = computed(() => [
  ...(toc?.edit
    ? [{
        icon: 'i-lucide-pencil',
        label: t.value.edit,
        to: `${toc.edit}/${page.value?.stem}.${page.value?.extension}`,
        target: '_blank'
      }]
    : []),
  ...(toc?.links || [])
])
</script>

<template>
  <UPage v-if="page">
    <UPageHeader
      :title="page.title"
      :description="page.description"
      :headline="headline"
    >
      <template #links>
        <UButton
          v-for="(link, index) in page.links"
          :key="index"
          v-bind="link"
        />

        <PageHeaderLinks />
      </template>
    </UPageHeader>

    <UPageBody>
      <ContentRenderer
        v-if="page"
        :value="page"
      />

      <USeparator v-if="surround?.length" />

      <UContentSurround :surround="surround" />
    </UPageBody>

    <template
      v-if="page?.body?.toc?.links?.length"
      #right
    >
      <UContentToc
        :title="t.toc"
        :links="page.body?.toc?.links"
      >
        <template #bottom>
          <div
            class="hidden lg:block space-y-6"
            :class="{ 'mt-6!': page.body?.toc?.links?.length }"
          >
            <USeparator
              v-if="page.body?.toc?.links?.length"
              type="dashed"
            />

            <UPageLinks
              :title="t.community"
              :links="links"
            />
          </div>
        </template>
      </UContentToc>
    </template>
  </UPage>
</template>
