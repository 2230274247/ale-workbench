<script setup lang="ts">
import {computed,ref} from 'vue'
const props=defineProps<{modelValue:any;label:string;name?:string;min?:number;max?:number;integer?:boolean;decimals?:number}>()
const emit=defineEmits(['update:modelValue'])
const key='qn-'+Math.random().toString(36).slice(2)
const touched=ref(false)
const invalid=computed(()=>{const v=props.modelValue;if(v===null||v==='')return false;return !Number.isFinite(Number(v))||!/^[-+]?(?:\d+\.?\d*|\.\d+)$/.test(String(v))||(props.min!==undefined&&Number(v)<props.min)||(props.max!==undefined&&Number(v)>props.max)||(props.integer&&!Number.isInteger(Number(v)))||(props.decimals!==undefined&&(String(v).split('.')[1]?.length??0)>props.decimals)})
function input(event:Event){touched.value=true;emit('update:modelValue',(event.target as HTMLInputElement).value)}
</script>
<template><div class="qn"><label :for="key">{{label}}</label><input :id="key" :aria-label="name||label" :value="modelValue??''" inputmode="decimal" :aria-invalid="invalid" :aria-describedby="invalid?key+'-error':undefined" @input="input"><span v-if="invalid" :id="key+'-error'" class="field-error">{{label}}：请输入{{integer?'整数':'有效数字'}}{{min!==undefined?`（≥ ${min}）`:''}}{{max!==undefined?`（≤ ${max}）`:''}}{{decimals!==undefined?`，最多 ${decimals} 位小数`:''}}</span></div></template>
