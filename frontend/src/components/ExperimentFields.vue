<script setup lang="ts">
import { type Field, type Row, label } from '../experiments/model'
defineProps<{fields:Field[]; model:Row; disabled?:boolean}>()
</script>
<template><div class="form-grid"><el-form-item v-for="f in fields" :key="f.key" :label="f.label" :required="f.required" :class="{'span-2':f.type==='textarea'}">
<el-switch v-if="f.type==='bool'" v-model="model[f.key]" :disabled="disabled" />
<el-select v-else-if="f.type==='select'" v-model="model[f.key]" :clearable="!f.required" :disabled="disabled" placeholder="未知 / 未填写"><el-option v-for="o in f.options" :key="o" :value="o" :label="label(o)" /></el-select>
<el-date-picker v-else-if="f.type==='date'||f.type==='datetime'" v-model="model[f.key]" :type="f.type==='date'?'date':'datetime'" :value-format="f.type==='date'?'YYYY-MM-DD':undefined" :disabled="disabled" clearable placeholder="未记录" />
<el-input v-else v-model="model[f.key]" :type="f.type==='textarea'?'textarea':'text'" :rows="3" :maxlength="f.max??(f.type==='textarea'?20000:undefined)" :inputmode="f.type==='decimal'?'decimal':f.type==='id'||f.type==='count'?'numeric':'text'" :disabled="disabled" :placeholder="f.required?'请填写':'未填写'" />
</el-form-item></div></template>
