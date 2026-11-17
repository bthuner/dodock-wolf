<!-- The official mark (docs/making-of/brand.md): used as supplied, never redrawn. -->
<script setup lang="ts">
const publicPath = usePublicPath()
</script>

<template>
  <span class="inline-flex items-center gap-2">
    <img
      :src="publicPath('/logo-192.png')"
      alt=""
      width="28"
      height="28"
      class="size-7 rounded-md"
    >
    <span class="font-semibold text-highlighted tracking-tight">Dodock Wolf</span>
  </span>
</template>
