<script setup lang="ts">
import { watch } from 'vue'
import { ElMessageBox, ElMessage, ElNotification } from 'element-plus'
import { useAuth } from './auth'
const auth=useAuth()
watch(()=>auth.sessionEpoch,()=>{ElMessageBox.close();ElMessage.closeAll();ElNotification.closeAll()},{flush:'sync'})
</script>
<template><router-view v-slot="{Component,route}"><component :is="Component" v-if="route.meta.public || auth.user" :key="`${auth.sessionEpoch}:${route.meta.public?'public':'session'}`" /></router-view></template>
