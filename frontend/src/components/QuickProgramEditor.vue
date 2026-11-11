<script setup lang="ts">
import {computed,nextTick,ref,watch} from 'vue'
import {ElMessageBox} from 'element-plus'
import QuickNumber from './QuickNumber.vue'
import QuickSourceSelect from './QuickSourceSelect.vue'
import {group,step,uid} from '../quick/model'
const props=defineProps<{modelValue:boolean;program:any;sources:string[]}>()
const emit=defineEmits(['update:modelValue','apply'])
const draft=ref<any>({outer_cycles:null,groups:[]}),baseline=ref(''),history=ref<string[]>([]),error=ref('')
const panel=ref<HTMLElement>()
const changed=computed(()=>JSON.stringify(draft.value)!==baseline.value)
const rows=[['pulse_ms','Pulse (ms)'],['purge_s','Purge (s)'],['wait_s','Wait (s)'],['delta_p_pa','ΔP (Pa)']]
watch(()=>props.modelValue,open=>{if(open){draft.value=JSON.parse(JSON.stringify(props.program));baseline.value=JSON.stringify(draft.value);history.value=[];error.value=''}})
function checkpoint(){history.value.push(JSON.stringify(draft.value));if(history.value.length>40)history.value.shift()}
function undo(){const previous=history.value.pop();if(previous)draft.value=JSON.parse(previous)}
function hasContent(s:any){return !!s.source_label?.trim()||rows.some(([key])=>s[key!]!=null&&s[key!]!=='')}
async function focus(id:string){await nextTick();document.getElementById('edit-src-'+id)?.focus()}
async function insert(g:any,index=g.steps.length){checkpoint();const value=step();g.steps.splice(index,0,value);await focus(value.step_id)}
function duplicate(g:any,index:number){checkpoint();const value={...g.steps[index],step_id:uid()};g.steps.splice(index+1,0,value);void focus(value.step_id)}
function move(g:any,index:number,d:number){checkpoint();const [value]=g.steps.splice(index,1);g.steps.splice(index+d,0,value);void focus(value.step_id)}
async function remove(g:any,index:number){if(hasContent(g.steps[index])){try{await ElMessageBox.confirm(`将删除 ${g.code} 组第 ${index+1} 步的全部参数。可使用撤销恢复。`,'删除步骤',{confirmButtonText:'删除这一步',cancelButtonText:'取消'})}catch{return}}checkpoint();g.steps.splice(index,1);if(g.steps.length)void focus(g.steps[Math.min(index,g.steps.length-1)].step_id)}
function addGroup(){checkpoint();const codes=new Set(draft.value.groups.map((g:any)=>g.code));const code=Array.from({length:16},(_,i)=>String.fromCharCode(65+i)).find(c=>!codes.has(c))!;draft.value.groups.push(group(code))}
function moveGroup(index:number,d:number){checkpoint();const [value]=draft.value.groups.splice(index,1);draft.value.groups.splice(index+d,0,value)}
async function removeGroup(index:number){const g=draft.value.groups[index];if(g.repeat_count!=null||g.steps.some(hasContent)){try{await ElMessageBox.confirm(`将删除 ${g.code} 组与全部步骤。可撤销恢复。`,'删除工艺组',{confirmButtonText:'删除本组',cancelButtonText:'取消'})}catch{return}}checkpoint();draft.value.groups.splice(index,1)}
async function askDiscard(){if(!changed.value)return true;try{await ElMessageBox.confirm('工艺结构有尚未应用的修改。关闭后，主表仍保留打开前的参数。','放弃工艺结构修改',{confirmButtonText:'放弃并关闭',cancelButtonText:'继续编辑'});return true}catch{return false}}
async function close(done?:()=>void){if(await askDiscard()){if(done)done();emit('update:modelValue',false)}}
function apply(){const invalid=panel.value?.querySelector<HTMLElement>('[aria-invalid="true"]');if(invalid){error.value='请修正标出的参数，内容仍保留。';invalid.focus();return}const unnamed=draft.value.groups.find((g:any)=>!g.code.trim());if(unnamed){error.value='请填写组名称，内容仍保留。';document.getElementById('group-code-'+unnamed.group_id)?.focus();return}emit('apply',JSON.parse(JSON.stringify(draft.value)));emit('update:modelValue',false)}
function keydown(e:KeyboardEvent){if((e.ctrlKey||e.metaKey)&&e.key==='z'&&!(e.target instanceof HTMLInputElement)&&!(e.target instanceof HTMLTextAreaElement)){e.preventDefault();undo()}}
defineExpose({hasChanges:changed,askDiscard})
</script>
<template>
 <el-dialog :model-value="modelValue" title="编辑工艺结构" width="min(1140px, 96vw)" class="quick-structure-dialog" destroy-on-close :close-on-click-modal="false" :before-close="close" @update:model-value="emit('update:modelValue',$event)">
  <div ref="panel" class="quick-page quick-structure" @keydown="keydown">
   <p>按需调整程序结构。应用后先回到主表核对，再保存实验记录；取消不会改变主表。</p>
   <p v-if="error" role="alert" class="quick-error">{{error}}</p>
   <div class="quick-grid two"><QuickNumber v-model="draft.outer_cycles" label="外层总循环次数" :min="0" :max="1000000" integer/><div class="quick-actions"><button :disabled="!history.length" @click="undo">撤销结构操作</button><button :disabled="draft.groups.length>=16" @click="addGroup">增加工艺组</button><span v-if="draft.groups.length>=16">已达到 16 组上限</span></div></div>
   <section v-for="(g,gi) in draft.groups" :key="g.group_id" class="quick-group" :aria-label="`编辑 ${g.code} 组`">
    <div class="quick-heading"><h3>{{g.code}} 组</h3><div class="quick-actions"><button :disabled="Number(gi)===0" @click="moveGroup(Number(gi),-1)">组上移</button><button :disabled="Number(gi)===draft.groups.length-1" @click="moveGroup(Number(gi),1)">组下移</button><button @click="removeGroup(Number(gi))">删除工艺组</button></div></div>
    <div class="quick-grid two"><label>组名称<input :id="'group-code-'+g.group_id" v-model="g.code" maxlength="32" :aria-label="`编辑 ${g.code} 组名称`"></label><QuickNumber v-model="g.repeat_count" :label="`编辑 ${g.code} 组循环次数`" :min="0" :max="1000000" integer/></div>
    <div class="quick-scroll" tabindex="0" :aria-label="`编辑 ${g.code} 组参数表，可横向滚动`"><table class="quick-matrix"><caption class="sr-only">{{g.code}} 组，每列包含源与完整参数</caption><thead><tr><th scope="col">参数</th><th v-for="(s,si) in g.steps" :key="s.step_id" scope="col">#{{Number(si)+1}}</th></tr></thead><tbody>
     <tr><th scope="row">源</th><td v-for="(s,si) in g.steps" :key="s.step_id"><QuickSourceSelect :id="'edit-src-'+s.step_id" :name="`编辑 ${g.code} 组 #${Number(si)+1} 源`" :options="sources" v-model="s.source_label" @update:model-value="s.enabled=true"/></td></tr>
     <tr v-for="field in rows" :key="field[0]"><th scope="row">{{field[1]}}</th><td v-for="(s,si) in g.steps" :key="s.step_id"><QuickNumber v-model="s[field[0]!]" :label="`编辑 ${g.code} 组 #${Number(si)+1} ${field[1]}`" :min="field[0]==='delta_p_pa'?-100000000:0" :max="100000000" @update:model-value="s.enabled=true"/></td></tr>
     <tr><th scope="row">步骤操作</th><td v-for="(s,si) in g.steps" :key="s.step_id"><details><summary :aria-label="`编辑 ${g.code} 组 #${Number(si)+1} 步骤菜单`">第 {{Number(si)+1}} 步操作</summary><div class="step-menu"><button :disabled="Number(si)===0" @click="move(g,Number(si),-1)">左移</button><button :disabled="Number(si)===g.steps.length-1" @click="move(g,Number(si),1)">右移</button><button :disabled="g.steps.length>=100" @click="insert(g,Number(si))">左侧插入</button><button :disabled="g.steps.length>=100" @click="insert(g,Number(si)+1)">右侧插入</button><button :disabled="g.steps.length>=100" @click="duplicate(g,Number(si))">复制此步</button><button @click="remove(g,Number(si))">删除此步</button></div></details></td></tr>
    </tbody></table></div>
    <div class="quick-actions"><button :disabled="g.steps.length>=100" @click="insert(g)">增加步骤</button><span v-if="g.steps.length>=100">本组已达到 100 步上限</span></div>
   </section>
  </div>
  <template #footer><div class="quick-page quick-actions"><span class="grow">{{changed?'结构修改尚未应用':'当前结构未修改'}}</span><button @click="close()">取消</button><button class="primary" @click="apply">应用到主表</button></div></template>
 </el-dialog>
</template>
<style>
.quick-structure-dialog{display:flex;flex-direction:column;max-height:94dvh;margin-top:3vh!important;margin-bottom:3vh;overflow:hidden}.quick-structure-dialog>.el-dialog__header,.quick-structure-dialog>.el-dialog__footer{flex-shrink:0}.quick-structure-dialog>.el-dialog__body{min-height:0;overflow:auto;overscroll-behavior:contain}.quick-structure-dialog .quick-structure{padding-bottom:0}.quick-structure-dialog .quick-actions{margin:0}.quick-structure-dialog .quick-actions .grow{flex:1}.quick-structure-dialog .quick-group{padding-top:14px}
</style>
