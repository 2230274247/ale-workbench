<script setup lang="ts">
import { computed, ref } from 'vue'
import { type GridDraft, compactRows, compactColumns, compactIssue, setCompactCell } from '../experiments/processGrid'
import ProcessGridGroup from './ProcessGridGroup.vue'
const props=defineProps<{modelValue:GridDraft;disabled?:boolean;readonly?:boolean;planned?:boolean;extraSources?:string[];planOptions?:{id:number;label:string}[]}>()
const emit=defineEmits<{'update:modelValue':[GridDraft]}>()
const advanced=ref(false)
const issue=computed(()=>compactIssue(props.modelValue))
const fullView=computed(()=>advanced.value||!!issue.value)
const columns=computed(()=>compactColumns(props.modelValue))
const commonGroup=computed(()=>{const nodes=props.modelValue.process_flow.children;return nodes.length===1&&nodes[0]!.kind==='group'?nodes[0]:undefined})
function change(){emit('update:modelValue',props.modelValue)}
function cycles(e:Event){const v=(e.target as HTMLInputElement).value;props.modelValue.process_flow.total_cycles=v===''?null:Number(v);change()}
function groupValue(key:'name'|'repeat',e:Event){const group=commonGroup.value;if(!group)return;const value=(e.target as HTMLInputElement).value;if(key==='name')group.name=value||null;else group.repeat=value===''?null:Number(value);change()}
function valueAt(column:number,row:number){const r=compactRows[row]!;return columns.value[column]?.parameter_snapshot.groups.find(g=>g.name===r.group)?.fields.find(f=>f.name===r.name)?.value??''}
function edit(column:number,row:number,e:Event){setCompactCell(props.modelValue,column,row,(e.target as HTMLInputElement).value);change()}
const sourceSuggestions=computed<string[]>(()=>{
  const names=new Set<string>()
  for(const step of props.modelValue.steps)for(const group of step.parameter_snapshot?.groups??[]){
    if(group.name!=='源')continue
    for(const field of group.fields){if(field.name!=='名称')continue;const value=String(field.value??'').trim();if(value)names.add(value)}
  }
  for(const value of props.extraSources??[]){const name=String(value??'').trim();if(name)names.add(name)}
  return [...names].sort((a,b)=>a.localeCompare(b,'zh-CN'))
})
const sourceListId=`process-grid-sources-${Math.random().toString(36).slice(2)}`
</script>
<template>
<section class="process-grid" data-testid="process-grid">
  <header>
    <strong>{{planned?'计划流程':'实际流程'}}</strong>
    <label v-if="!readonly">总循环数 <input aria-label="总循环数" type="number" min="0" max="1000000" step="1" placeholder="未知" :value="modelValue.process_flow.total_cycles??''" :disabled="disabled" @input="cycles"/></label>
    <span v-else>总循环数：{{modelValue.process_flow.total_cycles??'未知'}}</span>
    <template v-if="commonGroup&&!fullView">
      <template v-if="!readonly">
        <label>组名称 <input aria-label="流程组名称" maxlength="128" :value="commonGroup.name??''" :disabled="disabled" @input="groupValue('name',$event)"/></label>
        <label>组重复次数 <input aria-label="组重复次数" type="number" min="0" max="1000000" :value="commonGroup.repeat??''" placeholder="未知" :disabled="disabled" @input="groupValue('repeat',$event)"/></label>
      </template>
      <span v-else>{{commonGroup.name||'未命名组'}} · 重复 {{commonGroup.repeat??'未知'}} 次</span>
    </template>
    <button class="editor-toggle" type="button" :aria-expanded="fullView" :disabled="!!issue" @click="advanced=!advanced">{{fullView?'收起高级编辑':'高级编辑'}}</button>
  </header>
  <p class="field-hint">{{planned?'以下为计划条件。':'实际值独立填写。'}} 留空为未知。</p>
  <p v-if="issue" class="field-hint" role="status">{{issue}}，已展开完整视图。</p>
  <template v-if="!fullView">
    <datalist :id="sourceListId"><option v-for="name in sourceSuggestions" :key="name" :value="name"/></datalist>
    <div class="compact-scroll" tabindex="0" aria-label="五参数五步骤矩阵" data-testid="compact-grid-scroll">
      <table class="compact-matrix" data-testid="compact-process-matrix">
        <thead><tr><th scope="col">参数</th><th v-for="column in 5" :key="column" scope="col">#{{column}}</th></tr></thead>
        <tbody><tr v-for="(row,r) in compactRows" :key="row.group">
          <th scope="row">{{row.label}}</th>
          <td v-for="column in 5" :key="column">
            <span v-if="readonly">{{valueAt(column-1,r)}}</span>
            <input v-else type="text" :aria-label="`#${column} ${row.label}`" :value="valueAt(column-1,r)" :list="r===0?sourceListId:undefined" :disabled="disabled" maxlength="2000" @input="edit(column-1,r,$event)"/>
          </td>
        </tr></tbody>
      </table>
    </div>
  </template>
  <template v-else>
    <p class="field-hint">每格分别记录值与单位，改单位不会换算数值。温度、参数模板和流程顺序在此编辑。</p>
    <ProcessGridGroup :nodes="modelValue.process_flow.children" :steps="modelValue.steps" :depth="0" :disabled="disabled" :readonly="readonly" :source-suggestions="sourceSuggestions" :source-list-id="sourceListId" :plan-options="planOptions" :allow-plan-mapping="!planned" @change="change"/>
  </template>
</section>
</template>
<style scoped>
.process-grid{display:grid;gap:12px;min-width:0;max-width:100%}.process-grid>header{display:flex;align-items:center;gap:12px 20px;flex-wrap:wrap}.process-grid label{display:flex;align-items:center;gap:8px;font-size:13px}.process-grid header input{width:110px;padding:7px 8px;border:1px solid var(--line);border-radius:4px;color:var(--ink);background:#fff}.process-grid>p{margin:0}.editor-toggle{margin-left:auto;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--teal);padding:7px 10px;font:inherit;font-size:13px;cursor:pointer}.editor-toggle:disabled{color:var(--muted);cursor:default}.compact-scroll{min-width:0;max-width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:6px}.compact-matrix{width:100%;min-width:580px;border-collapse:separate;border-spacing:0;table-layout:fixed;font-size:13px;color:var(--ink)}.compact-matrix th,.compact-matrix td{height:42px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);padding:0;background:#fff;text-align:center}.compact-matrix th{font-weight:600;background:var(--soft)}.compact-matrix tr>:first-child{width:110px;position:sticky;left:0;z-index:1;text-align:left;padding:0 12px;background:#f7fafc}.compact-matrix tr>:last-child{border-right:0}.compact-matrix tbody tr:last-child>*{border-bottom:0}.compact-matrix td input{box-sizing:border-box;width:100%;min-width:0;height:41px;border:0;padding:8px 10px;border-radius:0;background:transparent;color:var(--ink);font:inherit;text-align:center}.compact-matrix td span{display:block;min-height:18px;padding:8px 10px;overflow-wrap:anywhere}.compact-matrix td input:focus,.editor-toggle:focus-visible{outline:2px solid var(--teal);outline-offset:-2px}.compact-matrix td input:disabled{background:var(--soft)}
</style>
