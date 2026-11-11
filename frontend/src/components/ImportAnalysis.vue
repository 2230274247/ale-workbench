<script setup lang="ts">
import {ref,watch} from 'vue'
import {api,errorText} from '../api'
import ScientificPlot from './ScientificPlot.vue'
const props=defineProps<{item:any;jobVersion:number}>()
const result=ref<any>(null),error=ref(''),loading=ref(false)
let generation=0
async function load(){const run=++generation;result.value=null;error.value='';if(props.item.parse_result?.status!=='parsed')return;loading.value=true;try{const r=await api<any>('/analysis/calculate',{method:'POST',body:{sources:props.item.parse_result.blocks.map((_:any,index:number)=>({kind:'import_item',id:props.item.item_id,block_index:index,expected_row_version:props.jobVersion}))}});if(run===generation)result.value=r.data}catch(e){if(run===generation)error.value=errorText(e)}finally{if(run===generation)loading.value=false}}
watch(()=>[props.item.item_id,props.jobVersion],load,{immediate:true})
</script>
<template><div class="import-analysis" data-testid="import-analysis"><p v-if="loading" role="status">正在根据可信测点生成预览图表…</p><p v-if="item.parse_result?.status!=='parsed'" class="field-hint">原件已暂存；该格式或测点尚未经可信验证，不能生成科学图表。RGA / XPS 待验证文件仅作原件归档。</p><p v-if="error" role="alert" class="danger-text">{{ error }} <el-button @click="load">重试图表</el-button></p><template v-if="result"><p class="field-hint">上传后即时预览：尚未提交正式测量。默认保留全部异常点参与统计；样品、阶段和模型待人工确认。</p><ScientificPlot :analysis="result"/><details><summary>服务器统计与来源</summary><div v-for="s in result.series" :key="s.source.block_index"><p>{{ s.source.label }} · {{ s.raw_count }} 点 · 厚度均值 {{ s.statistics.thickness_nm?.mean??'无有效值' }} nm</p><p class="field-hint">SHA256 {{ s.source.sha256 }}</p></div></details></template></div></template>
