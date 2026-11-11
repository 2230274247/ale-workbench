<script setup lang="ts">
import {ref,onMounted} from 'vue'
import {api,errorText} from '../api'
import '../quick/quick.css'
const items=ref<any[]>([]),error=ref('')
onMounted(async()=>{try{items.value=(await api<any[]>('/quick/templates')).data}catch(e){error.value=errorText(e)}})
</script>
<template><div class="quick-page"><header class="quick-heading"><div><p class="eyebrow">ALE WORKBENCH / RECIPES</p><h1>工艺模板</h1><p>独立参数快照 · 历史实验不随模板改变</p></div><RouterLink to="/quick">进入快录选择模板</RouterLink></header><p v-if="error" role="alert" class="quick-error">{{error}}</p><section class="quick-card"><p v-if="!items.length">暂无模板。保存实验快录后，在“更多参数与模板”输入名称并保存。</p><details v-for="t in items" :key="t.template_id"><summary>{{t.name}} · 版本 {{t.version}} · {{t.created_at}}</summary><pre tabindex="0">{{JSON.stringify(t.snapshot,null,2)}}</pre></details></section></div></template>

