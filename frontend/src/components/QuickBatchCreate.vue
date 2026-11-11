<script setup lang="ts">
import BatchCodeStatus from './BatchCodeStatus.vue'
import {ref} from 'vue'
import {api,errorText} from '../api'
const emit=defineEmits<{created:[Record<string,any>]}>()
const open=ref(false),busy=ref(false),error=ref(''),code=ref(''),name=ref(''),material=ref('')
async function save(){
 if(busy.value)return
 if(!code.value.trim()||!name.value.trim()){error.value='请填写批次编号与名称';return}
 busy.value=true;error.value=''
 try{const r=await api<Record<string,any>>('/batches',{method:'POST',body:{batch_code:code.value.trim(),batch_name:name.value.trim(),material:material.value.trim()||'未记录'}});emit('created',r.data);open.value=false}
 catch(e){error.value=errorText(e)}finally{busy.value=false}
}
</script>
<template><el-button @click="open=true">新建批次</el-button>
<el-dialog v-model="open" title="新建样品所属批次" width="min(480px,94vw)" append-to-body :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
<p class="field-hint">批次是沉积记录；母片与切割小样分别建档，不由批次名称推断。</p>
<el-alert v-if="error" :title="error" type="error" :closable="false"/>
<el-form label-position="top" :disabled="busy"><el-form-item label="批次编号" required><el-input v-model="code" aria-label="快速批次编号" maxlength="64" placeholder="例如 S01"/><BatchCodeStatus :code="code"/></el-form-item><el-form-item label="批次名称" required><el-input v-model="name" aria-label="快速批次名称" maxlength="255"/></el-form-item><el-form-item label="材料（未知可留空，保存为未记录）"><el-input v-model="material" aria-label="快速批次材料" maxlength="128"/></el-form-item></el-form>
<template #footer><el-button :disabled="busy" @click="open=false">取消</el-button><el-button type="primary" :loading="busy" @click="save">创建并选中批次</el-button></template>
</el-dialog></template>
