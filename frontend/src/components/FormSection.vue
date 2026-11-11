<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>
<template>
  <section class="form-section-block">
    <header class="form-section-heading"><h3>{{ title }}</h3><p v-if="description">{{ description }}</p></header>
    <slot />
  </section>
</template>
