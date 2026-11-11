<script setup lang="ts">
import {ref,watch} from 'vue'
import {ElMessageBox} from 'element-plus'
import {api,errorText} from '../api'
import {useAuth} from '../auth'
import LifecycleDialog from './LifecycleDialog.vue'
const props=defineProps<{code:string}>()
const auth=useAuth(),status=ref<Record<string,any>|null>(null),error=ref(''),busy=ref(false),lifecycle=ref(false)
let sequence=0
watch(()=>props.code,()=>{sequence++;status.value=null;error.value='';busy.value=false})
async function check(){const current=++sequence;busy.value=true;error.value='';try{const r=await api<Record<string,any>>('/batches/code-status',{query:{code:props.code.trim()}});if(current===sequence)status.value=r.data}catch(e){if(current===sequence)error.value=errorText(e)}finally{if(current===sequence)busy.value=false}}
async function rename(){try{const b=status.value!.existing;const code=await ElMessageBox.prompt('仅允许完全没有样品、实验及其他关联的误建记录。历史身份与归档状态保留。','更正未使用批次编号',{inputValue:b.batch_code+'-OLD',inputValidator:v=>!!v?.trim()&&v.trim().length<=64||'请输入 1–64 字符'});const reason=await ElMessageBox.prompt('填写此次更正原因，将写入审计。','更正原因',{inputValidator:v=>!!v?.trim()||'请填写原因'});busy.value=true;await api(`/batches/${b.batch_id}/code`,{method:'PATCH',body:{batch_code:code.value,reason:reason.value,expected_row_version:b.row_version}});await check()}catch(e){if(e!=='cancel'&&e!=='close')error.value=errorText(e)}finally{busy.value=false}}
</script>
<template><div class="field-hint"><el-button link type="primary" :disabled="!code.trim()" :loading="busy" @click="check">检查编号 / 查找已有批次</el-button><p v-if="error" role="alert">{{error}}</p><template v-if="status"><p role="status">{{status.message}}</p><template v-if="status.existing"><router-link :to="{path:'/batches',query:{batch_id:status.existing.batch_id}}">打开已有批次 {{status.existing.batch_code}}</router-link><el-button v-if="auth.canWrite" link @click="lifecycle=true">恢复 / 安全清理影响预览</el-button><el-button v-if="status.can_rename&&auth.canWrite" link :disabled="busy" @click="rename">更正未使用批次编号</el-button><p v-else>此批次已有样品或科研关联，保留原编号。请使用已有批次，或为新批次换一个编号。</p><LifecycleDialog v-model="lifecycle" kind="batches" :id="status.existing.batch_id" :row-version="status.existing.row_version" :code="status.existing.batch_code" @applied="check"/></template></template></div></template>
