<!-- Nuxt UI's code block, plus ```mermaid blocks drawn as diagrams (in the browser). -->
<script setup lang="ts">
import UProsePre from '@nuxt/ui/runtime/components/prose/Pre.vue'

defineOptions({ inheritAttrs: false })

// Everything else (filename, highlights, meta, icon, copy...) goes through $attrs untouched.
const props = defineProps<{
  code?: string
  language?: string
}>()

const isMermaid = computed(() => props.language === 'mermaid')
const svg = ref('')
const colorMode = useColorMode()

async function render() {
  if (!isMermaid.value || !props.code) return
  const { default: mermaid } = await import('mermaid')
  const dark = colorMode.value === 'dark'
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: 'base',
    fontFamily: 'Inter Tight, ui-sans-serif, sans-serif',
    themeVariables: dark
      ? { primaryColor: '#131A2A', primaryBorderColor: '#7FA8FF', primaryTextColor: '#ECEEF3', lineColor: '#A2AABA', background: '#0A0F1C' }
      : { primaryColor: '#FFFFFF', primaryBorderColor: '#035AEC', primaryTextColor: '#121725', lineColor: '#565D6B', background: '#F4F2EC' }
  })
  const id = `mermaid-${Math.random().toString(36).slice(2)}`
  svg.value = (await mermaid.render(id, props.code)).svg
}

onMounted(render)
watch(() => colorMode.value, render)
</script>

<template>
  <figure
    v-if="isMermaid"
    class="my-5 overflow-x-auto rounded-md border border-default bg-elevated p-4"
  >
    <!-- The SVG comes from our own Markdown, rendered by mermaid with securityLevel 'strict'. -->
    <!-- eslint-disable vue/no-v-html -->
    <div
      v-if="svg"
      class="mermaid-diagram w-full min-w-[36rem]"
      v-html="svg"
    />
    <!-- eslint-enable vue/no-v-html -->
    <pre
      v-else
      class="text-sm text-muted"
    >{{ code }}</pre>
  </figure>
  <UProsePre
    v-else
    v-bind="$attrs"
    :code="code"
    :language="language"
  >
    <slot />
  </UProsePre>
</template>
