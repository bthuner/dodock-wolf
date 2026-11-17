<script setup lang="ts">
import { useClipboard } from '@vueuse/core'
import { withoutTrailingSlash } from 'ufo'

const route = useRoute()
const toast = useToast()
const { copy, copied } = useClipboard()
const { siteUrl } = useRuntimeConfig().public
const { t } = useDocsLocale()
const publicPath = usePublicPath()

const routePath = computed(() => withoutTrailingSlash(route.path))
const mdPath = computed(() => `${siteUrl}/raw${routePath.value}.md`)

const items = computed(() => [
  {
    label: t.value.copyLink,
    icon: 'i-lucide-link',
    onSelect() {
      copy(mdPath.value)
      toast.add({ title: t.value.copied, icon: 'i-lucide-check-circle' })
    }
  },
  {
    label: t.value.viewMarkdown,
    icon: 'i-simple-icons-markdown',
    target: '_blank',
    to: `/raw${routePath.value}.md`
  }
])

async function copyPage() {
  copy(await $fetch<string>(publicPath(`/raw${routePath.value}.md`)))
}
</script>

<template>
  <UFieldGroup>
    <UButton
      :label="t.copyPage"
      :icon="copied ? 'i-lucide-copy-check' : 'i-lucide-copy'"
      color="neutral"
      variant="outline"
      :ui="{ leadingIcon: [copied && 'text-primary', 'size-3.5'] }"
      @click="copyPage"
    />
    <UDropdownMenu
      :items="items"
      :content="{ align: 'end', side: 'bottom', sideOffset: 8 }"
      :ui="{ content: 'w-48' }"
    >
      <UButton
        icon="i-lucide-chevron-down"
        size="sm"
        color="neutral"
        variant="outline"
        aria-label="More"
      />
    </UDropdownMenu>
  </UFieldGroup>
</template>
