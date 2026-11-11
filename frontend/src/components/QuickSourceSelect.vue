<script setup lang="ts">
import {computed} from 'vue'
const props=defineProps<{modelValue:string|null;name:string;options:string[];id:string;disabled?:boolean}>()
const emit=defineEmits(['update:modelValue'])
const choices=computed(()=>Array.from(new Set([...props.options,props.modelValue].filter((v):v is string=>!!v))))
</script>
<template>
 <el-select class="quick-source-select" :id="id" :aria-label="name" :disabled="disabled" :model-value="modelValue||undefined" filterable clearable placeholder="选择实验源" no-data-text="请先添加实际源名称" no-match-text="未找到，请在上方添加源" popper-class="quick-source-options" @update:model-value="emit('update:modelValue',$event||'')">
  <el-option v-for="source in choices" :key="source" :label="source" :value="source"/>
 </el-select>
</template>
<style>
.quick-source-select{width:100%;min-width:116px}.quick-page .quick-source-select .el-select__wrapper{min-height:44px;border:1px solid #899eac;border-radius:9px;background:var(--lab-inset-surface,#edf3f6);box-shadow:var(--lab-inset);padding:9px 11px;color:#203a4b}.quick-page .quick-source-select .el-select__wrapper.is-focused{outline:3px solid #087f8c;outline-offset:2px}.quick-page .quick-source-select .el-select__placeholder{color:#536b7d}.quick-page .quick-source-select input{min-height:0!important;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;outline:none!important}.quick-source-options{--el-text-color-regular:#203a4b;--el-fill-color-light:#e0eeee;--el-color-primary:#08717b}.quick-source-options .el-select-dropdown__item{min-height:36px;color:#203a4b}.quick-source-options .el-select-dropdown__item.is-selected{color:#08717b;font-weight:600}
</style>
