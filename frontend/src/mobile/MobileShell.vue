<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ClipboardList, History, ChartNoAxesCombined, UserRound, FlaskConical } from 'lucide-vue-next'
import { useAuth } from '../auth'
import './mobile.css'
const route = useRoute(), auth = useAuth()
const title = computed(() => String(route.meta.title || 'ALE 移动版'))
const tabs = [
  { path: '/m/quick', label: '快录', icon: ClipboardList },
  { path: '/m/history', label: '历史', icon: History },
  { path: '/m/dataset', label: '数据集', icon: ChartNoAxesCombined },
  { path: '/m/me', label: '我的', icon: UserRound },
]
const active = (path: string) => route.path === path || route.path.startsWith(`${path}/`)
const initial = computed(() => (auth.user?.display_name || auth.user?.username || 'U').slice(0, 1))
</script>

<template>
  <div class="m-app">
    <header class="m-topbar">
      <span class="m-mark" aria-hidden="true"><FlaskConical :size="17" /></span>
      <h1>{{ title }}</h1>
      <router-link to="/m/me" class="m-user" :aria-label="`账户：${auth.user?.display_name || auth.user?.username || '当前账户'}`">{{ initial }}</router-link>
    </header>
    <main class="m-main"><router-view :key="route.path" /></main>
    <nav class="m-bottom" aria-label="移动端主导航">
      <router-link v-for="tab in tabs" :key="tab.path" :to="tab.path" :aria-current="active(tab.path) ? 'page' : undefined">
        <component :is="tab.icon" aria-hidden="true" /><span>{{ tab.label }}</span>
      </router-link>
    </nav>
  </div>
</template>
