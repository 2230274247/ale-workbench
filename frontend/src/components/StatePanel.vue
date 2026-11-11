<script setup lang="ts">
import { FolderSearch, CircleAlert } from 'lucide-vue-next'
withDefaults(defineProps<{ title: string; description?: string; tone?: 'empty' | 'error' }>(), { tone: 'empty' })
</script>
<template>
  <div class="state-panel" :class="`state-panel--${tone}`" :role="tone === 'error' ? 'alert' : 'status'">
    <component :is="tone === 'error' ? CircleAlert : FolderSearch" :size="28" :stroke-width="1.5" aria-hidden="true" />
    <h3>{{ title }}</h3><p v-if="description">{{ description }}</p>
    <div v-if="$slots.default" class="state-panel-actions"><slot /></div>
  </div>
</template>
