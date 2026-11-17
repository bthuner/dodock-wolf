<!-- A Wolf UI screenshot in the reader's colour mode: public/img/<name>-{light,dark}.jpg,
     taken on the demo bench (docs/screenshots). -->
<script setup lang="ts">
const publicPath = usePublicPath()

defineProps<{
  name: string
  alt: string
  caption?: string
}>()
</script>

<template>
  <figure class="my-6">
    <UColorModeImage
      :light="publicPath(`/img/${name}-light.jpg`)"
      :dark="publicPath(`/img/${name}-dark.jpg`)"
      :alt="alt"
      class="w-full rounded-lg border border-default shadow-sm"
      loading="lazy"
    />
    <figcaption
      v-if="caption"
      class="mt-2 text-sm text-muted text-center"
    >
      {{ caption }}
    </figcaption>
  </figure>
</template>
