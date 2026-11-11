<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorText } from '../api'
import { type FlowNode, type GridStep, newGridStep, stepNode, uid } from '../experiments/processGrid'
import { type ParameterField, type ParameterSnapshot, type Row, copySnapshot, display, parameterFields, snapshotPayload } from '../experiments/model'
const props=defineProps<{nodes:FlowNode[];steps:GridStep[];depth:number;disabled?:boolean;readonly?:boolean;sourceSuggestions?:string[];sourceListId?:string;planOptions?:{id:number;label:string}[];allowPlanMapping?:boolean;parentNodes?:FlowNode[]}>()
const emit=defineEmits<{change:[]}>()
const rowName=ref('')
const columns=computed(()=>props.nodes.filter(n=>n.kind==='step').map(n=>({node:n,step:props.steps.find(s=>s.key===n.step_id)!})).filter(c=>c.step))
type GridRow={key:string;group:string;name:string;temperature?:boolean}
const gridRows=computed<GridRow[]>(()=>{const rows:GridRow[]=[{key:'temperature',group:'温度',name:'温度',temperature:true}],seen=new Set<string>();for(const {step} of columns.value)for(const g of step.parameter_snapshot.groups)for(const f of g.fields){const key=JSON.stringify([g.name,f.name]);if(!seen.has(key)){seen.add(key);rows.push({key,group:g.name,name:f.name})}}return rows})
function cell(s:GridStep,r:GridRow):ParameterField|ParameterSnapshot['temperature']|undefined {if(r.temperature)return s.parameter_snapshot.temperature;return s.parameter_snapshot.groups.find(g=>g.name===r.group)?.fields.find(f=>f.name===r.name)}
function setCell(s:GridStep,r:GridRow,key:'value'|'unit',value:string){let c=cell(s,r);if(!c&&!r.temperature){let g=s.parameter_snapshot.groups.find(g=>g.name===r.group);if(!g){g={name:r.group,fields:[]};s.parameter_snapshot.groups.push(g)}c={name:r.name,value:null,unit:null};g.fields.push(c)}if(c){c[key]=key==='unit'&&r.temperature?(value||'°C'):value||null as any;emit('change')}}
function addStep(){const s=newGridStep();props.steps.push(s);props.nodes.push(stepNode(s.key));emit('change')}
function copyStep(s:GridStep,n:FlowNode){const c=JSON.parse(JSON.stringify(s)) as GridStep;c.key=uid();c.step_id=null;c.legacy_parameters={};c.parameter_source="parameter_snapshot";c.parameter_conflict=false;c.step_name=`${s.step_name||s.step_kind} 副本`.slice(0,128);props.steps.push(c);props.nodes.splice(props.nodes.indexOf(n)+1,0,stepNode(c.key));emit('change')}
function move(n:FlowNode,d:number){const i=props.nodes.indexOf(n),j=i+d;if(j>=0&&j<props.nodes.length){props.nodes.splice(i,1);props.nodes.splice(j,0,n);emit('change')}}
function remove(n:FlowNode){const keys=new Set<string>();const visit=(node:FlowNode)=>{if(node.kind==='step')keys.add(String(node.step_id));else node.children.forEach(visit)};visit(n);for(let i=props.steps.length-1;i>=0;i--)if(keys.has(props.steps[i]!.key))props.steps.splice(i,1);props.nodes.splice(props.nodes.indexOf(n),1);emit('change')}
function addGroup(){props.nodes.push({kind:'group',id:uid(),name:'新参数组',repeat:null,children:[]});emit('change')}
function addRow(){const name=rowName.value.trim();if(!name||name.length>128)return;for(const {step} of columns.value){let g=step.parameter_snapshot.groups.find(g=>g.name==='自定义');if(!g){g={name:'自定义',fields:[]};step.parameter_snapshot.groups.push(g)}if(!g.fields.some(f=>f.name===name))g.fields.push({name,value:null,unit:null})}rowName.value='';emit('change')}
function removeRow(r:GridRow){for(const {step} of columns.value){const g=step.parameter_snapshot.groups.find(g=>g.name===r.group);if(g)g.fields=g.fields.filter(f=>f.name!==r.name)}emit('change')}
function repeatValue(e:Event,node:FlowNode){const v=(e.target as HTMLInputElement).value;node.repeat=v===''?null:Number(v);emit('change')}
function moveInto(n:FlowNode,target:string){const group=props.nodes.find(g=>g.id===target&&g.kind==='group');const height=(node:FlowNode):number=>node.kind==='step'?0:1+Math.max(0,...node.children.filter(c=>c.kind==='group').map(height));if(n.kind==='group'&&props.depth+1+height(n)>4){rowError.value='嵌套组最多 4 层，请先移出内层组';return}if(group&&group!==n){props.nodes.splice(props.nodes.indexOf(n),1);group.children.push(n);emit('change')}}
const rowError=ref('')
function renameRow(r:GridRow,event:Event){
  const input=event.target as HTMLInputElement,name=input.value.trim()
  if(!name||name.length>128||gridRows.value.some(other=>other.key!==r.key&&other.group===r.group&&other.name===name)){
    rowError.value='参数行名称需要 1–128 个字符，且同组不能重名';input.value=r.name;return
  }
  for(const {step} of columns.value){const field=cell(step,r);if(field&&'name' in field)field.name=name}
  rowError.value='';emit('change')
}
function moveOut(node:FlowNode){if(!props.parentNodes)return;props.nodes.splice(props.nodes.indexOf(node),1);props.parentNodes.push(node);emit('change')}
function copyGroup(group:FlowNode){
  const copy=JSON.parse(JSON.stringify(group)) as FlowNode
  const count=(nodes:FlowNode[]):number=>nodes.reduce((n,node)=>n+(node.kind==='step'?1:count(node.children)),0)
  if(props.steps.length+count(copy.children)>450)return
  const visit=(node:FlowNode)=>{node.id=uid();if(node.kind==='step'){
    const original=props.steps.find(s=>s.key===node.step_id)
    if(original){const step=JSON.parse(JSON.stringify(original)) as GridStep;step.key=uid();step.step_id=null;step.legacy_parameters={};step.parameter_source='parameter_snapshot';step.parameter_conflict=false;props.steps.push(step);node.step_id=step.key}
  }else node.children.forEach(visit)}
  visit(copy);copy.name=`${group.name||'流程组'} 副本`.slice(0,128);props.nodes.splice(props.nodes.indexOf(group)+1,0,copy);emit('change')
}
function tabCell(event:KeyboardEvent){
  if(event.key!=='Tab'||!(event.target instanceof HTMLInputElement)||!event.target.classList.contains('cell-input'))return
  const table=event.currentTarget as HTMLTableElement,inputs=Array.from(table.querySelectorAll<HTMLInputElement>('.cell-input:not(:disabled)'))
  const target=inputs[inputs.indexOf(event.target)+(event.shiftKey?-1:1)]
  if(target){event.preventDefault();target.focus();target.scrollIntoView({block:'nearest',inline:'nearest'})}
}
function isSourceRow(r:GridRow){return r.group==='源'&&r.name==='名称'}
function columnLabel(c:{node:FlowNode;step:GridStep},index:number){return `${index+1}. ${c.step.step_name||c.step.step_kind||'未命名步骤'}`}

// Grid-level template controls live on the root group only; columns inside nested
// groups are offered too, because props.steps already holds the whole record.
const allColumns=computed(()=>{const out:{node:FlowNode;step:GridStep}[]=[];const visit=(nodes:FlowNode[])=>{for(const n of nodes){if(n.kind==='step'){const s=props.steps.find(x=>x.key===n.step_id);if(s)out.push({node:n,step:s})}else visit(n.children)}};visit(props.nodes);return out})
const templates=ref<Row[]>([]),templateId=ref<number|null>(null),targetKey=ref<string|null>(null),templateName=ref('')
const templateBusy=ref(false),templateError=ref(''),templateNotice=ref('')
const speciesNames=ref<string[]>([])
async function loadTemplates(){
  if(props.readonly||props.depth!==0)return
  templateBusy.value=true;templateError.value=''
  try{
    const all:Row[]=[];let page=1
    while(true){
      const r=await api<Row[]>('/step-parameter-templates',{query:{page,size:200}})
      all.push(...r.data)
      if(!r.meta?.has_next)break
      page++
    }
    templates.value=all
  }catch(e){templateError.value=`模板列表加载失败：${errorText(e)}`}
  finally{templateBusy.value=false}
}
function targetColumn(){return allColumns.value.find(c=>c.step.key===targetKey.value)}
function applyTemplate(){
  const t=templates.value.find(x=>x.template_id===templateId.value),target=targetColumn()
  if(!t||!target){templateError.value='请选择参数模板和要应用到的步骤列';return}
  target.step.parameter_snapshot=copySnapshot(t.definition as ParameterSnapshot)
  target.step.step_kind=target.step.parameter_snapshot.step_type
  templateError.value='';templateNotice.value=`已把模板「${t.template_name}」复制到「${target.step.step_name||target.step.step_kind}」；保存流程后写入记录，历史值不会被改写。`
  emit('change')
}
async function saveAsTemplate(){
  const target=targetColumn()
  if(!target)return
  const name=templateName.value.trim()
  if(!name||name.length>128){templateError.value='请填写模板名称（1–128 个字符）';return}
  templateError.value='';templateNotice.value='';templateBusy.value=true
  try{
    const definition=snapshotPayload(target.step.parameter_snapshot)
    const r=await api<Row>('/step-parameter-templates',{method:'POST',body:{template_name:name,definition}})
    await loadTemplates()
    templateId.value=r.data.template_id
    templateNotice.value=`已把「${target.step.step_name||target.step.step_kind}」的参数结构另存为模板「${name}」；模板保存在数据库，已有步骤快照不受影响。`
  }catch(e){templateError.value=`模板保存失败：${errorText(e)}`}
  finally{templateBusy.value=false}
}
async function loadSpeciesSuggestions(){
  if(props.readonly||props.depth!==0)return
  try{
    const systems:Row[]=[];let page=1
    while(true){
      const r=await api<Row[]>('/chemistry-systems',{query:{page,size:200,status:'active'}})
      systems.push(...r.data)
      if(!r.meta?.has_next||page>=5)break
      page++
    }
    const names=new Set<string>()
    await Promise.allSettled(systems.slice(0,20).map(async s=>{
      const d=await api<Row>(`/chemistry-systems/${s.system_id}`)
      for(const sp of (d.data.species??[])){
        if(!['precursor','reactant'].includes(String(sp.role)))continue
        if(sp.species_name)names.add(String(sp.species_name))
        if(sp.species_code)names.add(String(sp.species_code))
      }
    }))
    speciesNames.value=[...names]
  }catch{
    // Chemistry suggestions are optional and must never block the grid.
  }
}
onMounted(()=>{if(!props.readonly&&props.depth===0){void loadTemplates();void loadSpeciesSuggestions()}})
</script>
<template><section class="process-grid-group" :data-depth="depth">
<datalist v-if="!readonly&&depth===0&&sourceListId" :id="sourceListId"><option v-for="name in [...new Set([...(sourceSuggestions??[]),...speciesNames])]" :key="name" :value="name"/></datalist>
<div v-if="!readonly&&depth===0" class="grid-template-bar" data-testid="grid-template-bar">
  <label>当前列 <select v-model="targetKey" aria-label="模板目标列" :disabled="disabled||templateBusy||!allColumns.length"><option :value="null">选择步骤列…</option><option v-for="(c,i) in allColumns" :key="c.step.key" :value="c.step.key">{{columnLabel(c,i)}}</option></select></label>
  <label>参数模板 <select v-model.number="templateId" aria-label="参数模板" :disabled="disabled||templateBusy"><option :value="null">选择模板…</option><option v-for="t in templates" :key="t.template_id" :value="t.template_id">{{t.template_name}}</option></select></label>
  <el-button :disabled="disabled||templateBusy||!templateId||!targetKey" @click="applyTemplate">应用到当前列</el-button>
  <el-input v-model="templateName" aria-label="模板名称" placeholder="模板名称" maxlength="128" :disabled="disabled||templateBusy"/>
  <el-button :disabled="disabled||templateBusy||!targetKey||!templateName.trim()" @click="saveAsTemplate">另存为当前列为模板</el-button>
  <el-button :disabled="templateBusy" @click="loadTemplates">刷新模板</el-button>
  <p class="field-hint template-hint">模板只是参数结构的一份副本：应用到当前列不会改写历史，保存流程后才写入记录。</p>
  <p v-if="templateError" class="field-hint danger-text" role="alert">{{templateError}}</p>
  <p v-if="templateNotice" class="field-hint" role="status">{{templateNotice}}</p>
</div>
<p v-if="rowError" class="danger-text" role="alert">{{rowError}}</p><ol class="flow-order" aria-label="明确流程顺序"><li v-for="(node,index) in nodes" :key="node.id"><span>{{index+1}}. {{node.kind==='group'?node.name:steps.find(s=>s.key===node.step_id)?.step_name||steps.find(s=>s.key===node.step_id)?.step_kind}}<template v-if="node.kind==='group'">（组重复 {{node.repeat??'未知'}} 次）</template></span></li></ol>
<div v-if="!readonly" class="grid-tools"><el-button :disabled="disabled||steps.length>=450" @click="addStep">添加步骤列</el-button><el-button :disabled="disabled||depth>=4" @click="addGroup">添加嵌套组</el-button><template v-if="columns.length"><el-input v-model="rowName" aria-label="自定义参数行名称" placeholder="自定义参数行名称" maxlength="128" :disabled="disabled" @keyup.enter="addRow"/><el-button :disabled="disabled||!rowName.trim()" @click="addRow">添加参数行</el-button></template></div>
<div v-if="columns.length" class="process-grid-scroll" tabindex="0" aria-label="步骤列与参数行网格"><table class="process-matrix" @keydown="tabCell"><thead><tr><th scope="col" class="row-label">参数 / 单位</th><th v-for="{step,node} in columns" :key="step.key" scope="col"><template v-if="readonly"><strong>{{step.step_name||step.step_kind}}</strong><small>分类：{{step.step_kind}}</small></template><template v-else><el-input v-model="step.step_name" aria-label="步骤列名称" maxlength="128" :disabled="disabled" @input="emit('change')"/><el-input v-model="step.step_kind" aria-label="步骤列分类" maxlength="128" placeholder="自由分类" :disabled="disabled" @input="step.parameter_snapshot.step_type=step.step_kind;emit('change')"/><div class="column-tools"><el-button link :disabled="disabled" aria-label="左移步骤列" @click="move(node,-1)">左移</el-button><el-button link :disabled="disabled" aria-label="右移步骤列" @click="move(node,1)">右移</el-button><el-button link :disabled="disabled" @click="copyStep(step,node)">复制列</el-button><el-button link type="danger" :disabled="disabled" @click="remove(node)">移除列</el-button></div><el-button v-if="parentNodes" link :disabled="disabled" @click="moveOut(node)">移出到上级</el-button><label v-if="allowPlanMapping" class="plan-map">映射计划步骤 <select :value="step.plan_step_id??''" aria-label="映射计划步骤" :disabled="disabled" @change="step.plan_step_id=($event.target as HTMLSelectElement).value?Number(($event.target as HTMLSelectElement).value):null;emit('change')"><option value="">不映射</option><option v-if="step.plan_step_id&&!(planOptions??[]).some(o=>o.id===step.plan_step_id)" :value="step.plan_step_id">计划步骤 #{{step.plan_step_id}}</option><option v-for="o in planOptions??[]" :key="o.id" :value="o.id">{{o.label}}</option></select></label><select v-if="nodes.some(n=>n.kind==='group')" aria-label="移动步骤到组" :disabled="disabled" @change="moveInto(node,($event.target as HTMLSelectElement).value)"><option value="">移入分组…</option><option v-for="g in nodes.filter(n=>n.kind==='group')" :value="g.id" :key="g.id">{{g.name}}</option></select></template><small>参数：{{step.parameter_source==='legacy_fields'?'旧记录（保存后按网格记录）':'网格记录'}}</small><small v-if="step.step_id">步骤 #{{step.step_id}}<span v-if="step.plan_step_id"> · 计划 #{{step.plan_step_id}}</span></small></th></tr></thead><tbody><tr v-for="r in gridRows" :key="r.key"><th scope="row" class="row-label"><strong>{{r.group}}</strong><input v-if="!readonly&&r.group==='自定义'" class="row-name" aria-label="重命名自定义参数行" :value="r.name" maxlength="128" :disabled="disabled" @change="renameRow(r,$event)"/><span v-else-if="r.name!==r.group">{{r.name}}</span><el-button v-if="!readonly&&!r.temperature" link type="danger" :disabled="disabled" @click="removeRow(r)">移除此行</el-button></th><td v-for="{step} in columns" :key="step.key"><template v-if="readonly"><span>{{display(cell(step,r)?.value)}}</span><small>{{cell(step,r)?.unit||'无单位'}}</small></template><div v-else class="matrix-cell"><input class="cell-input" type="text" :value="cell(step,r)?.value??''" :aria-label="`${step.step_name||step.step_kind} ${r.group} ${r.name} 值`" placeholder="未记录" maxlength="2000" :disabled="disabled" :list="isSourceRow(r)?sourceListId:undefined" @input="setCell(step,r,'value',($event.target as HTMLInputElement).value)"/><input class="cell-input unit-input" type="text" :value="cell(step,r)?.unit??''" :aria-label="`${step.step_name||step.step_kind} ${r.group} ${r.name} 单位`" placeholder="无单位" maxlength="32" :disabled="disabled" @input="setCell(step,r,'unit',($event.target as HTMLInputElement).value)"/></div></td></tr></tbody></table></div>
<details v-for="{step} in columns.filter(c=>Object.keys(c.step.legacy_parameters??{}).length)" :key="`legacy-${step.key}`" class="legacy-parameters"><summary>{{step.step_name||step.step_kind}} · 原始旧参数（只读）<strong v-if="step.parameter_conflict"> · 可能冲突</strong></summary><p>{{step.parameter_source==='parameter_snapshot'?'当前参数以网格记录为准。旧字段仅供历史核对；共存值可能不同，不自动换算或覆盖。':'原始参数尚无网格记录；网格显示原值与原单位。保存后以网格记录为准，原始字段继续保留。'}}</p><dl><template v-for="(value,key) in step.legacy_parameters" :key="key"><dt>{{parameterFields.find(f=>f.key===String(key))?.label??key}}</dt><dd v-if="String(key)==='custom_parameters'&&value&&typeof value==='object'"><div v-for="(entry,name) in value" :key="name">{{name}}：{{display(entry.value)}} {{entry.unit||'无单位'}}<span v-if="entry.note"> · {{entry.note}}</span></div></dd><dd v-else>{{display(value)}}</dd></template></dl></details>
<article v-for="group in nodes.filter(n=>n.kind==='group')" :key="group.id" class="nested-process-group"><header><template v-if="readonly"><strong>{{group.name}}</strong><span>重复 {{group.repeat??'未知'}} 次</span></template><template v-else><el-input v-model="group.name" aria-label="流程组名称" maxlength="128" :disabled="disabled" @input="emit('change')"/><label>组重复次数 <input type="number" min="0" max="1000000" step="1" :value="group.repeat??''" placeholder="未知" :disabled="disabled" aria-label="组重复次数" @input="repeatValue($event,group)"/></label><el-button link :disabled="disabled" @click="move(group,-1)">组上移</el-button><el-button link :disabled="disabled" @click="move(group,1)">组下移</el-button><el-button link :disabled="disabled||steps.length>=450" @click="copyGroup(group)">复制组</el-button><el-button v-if="parentNodes" link :disabled="disabled" @click="moveOut(group)">移出到上级</el-button><select v-if="nodes.some(n=>n.kind==='group'&&n.id!==group.id)" aria-label="移动组到组" :disabled="disabled||depth>=3" @change="moveInto(group,($event.target as HTMLSelectElement).value)"><option value="">移入分组…</option><option v-for="g in nodes.filter(n=>n.kind==='group'&&n.id!==group.id)" :key="g.id" :value="g.id">{{g.name}}</option></select><el-button link type="danger" :disabled="disabled" @click="remove(group)">移除组</el-button></template></header><ProcessGridGroup :nodes="group.children" :parent-nodes="nodes" :steps="steps" :depth="depth+1" :readonly="readonly" :disabled="disabled" :source-suggestions="sourceSuggestions" :source-list-id="sourceListId" :plan-options="planOptions" :allow-plan-mapping="allowPlanMapping" @change="emit('change')"/></article>
<p v-if="!nodes.length" class="field-hint">此组尚无步骤。添加步骤列或嵌套组。</p>
</section></template>
<style scoped>
.row-name{width:130px;max-width:100%;padding:7px;border:1px solid var(--line);border-radius:4px;color:var(--ink)}.flow-order{margin:0;padding:8px 12px;display:flex;flex-wrap:wrap;gap:10px 24px;list-style:none;background:var(--soft);font-size:12px}.process-grid-group{min-width:0;display:grid;gap:16px}.grid-tools{display:flex;flex-wrap:wrap;gap:8px}.grid-tools>.el-input{width:200px}.grid-template-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--line);border-radius:6px;background:#fff}.grid-template-bar label{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}.grid-template-bar select{max-width:220px;padding:7px;border:1px solid var(--line);background:white;color:var(--ink);border-radius:4px}.grid-template-bar>.el-input{width:190px}.template-hint{flex-basis:100%;margin:0}.process-grid-scroll{overflow:auto;max-height:650px;border:1px solid var(--line);border-radius:6px}.process-matrix{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}.process-matrix th,.process-matrix td{min-width:230px;padding:10px 12px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);text-align:left;vertical-align:top;background:#fff}.process-matrix thead th{background:var(--soft);position:sticky;top:0;z-index:2}.process-matrix .row-label{min-width:145px;width:145px;position:sticky;left:0;z-index:1;background:#f7fafc}.process-matrix thead .row-label{z-index:3}.row-label strong,.row-label span,small{display:block}small{font-weight:400;color:var(--muted);margin:5px 0;overflow-wrap:anywhere}.matrix-cell{display:grid;grid-template-columns:minmax(100px,1fr) 88px;gap:6px}.cell-input{width:100%;min-width:0;padding:7px 9px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit}.cell-input:focus{outline:2px solid var(--teal);outline-offset:-1px}.unit-input{padding:7px 6px}.column-tools{display:flex;flex-wrap:wrap;gap:5px}.plan-map{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);margin-top:6px}.plan-map select{max-width:190px;padding:5px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink)}.process-matrix th>.el-input+ .el-input{margin-top:7px}.nested-process-group{border-left:3px solid var(--teal);padding:12px;background:#f6fafb;min-width:0}.nested-process-group>header{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px}.nested-process-group>header>.el-input{width:210px}.nested-process-group label{font-size:12px;display:flex;align-items:center;gap:8px}input[type=number]{width:105px;background:white;border:1px solid var(--line);border-radius:4px;padding:8px;color:var(--ink)}select{max-width:200px;padding:7px;border:1px solid var(--line);background:white;color:var(--ink)}@media(max-width:620px){.nested-process-group{padding:8px}.matrix-cell{grid-template-columns:115px 80px}.grid-template-bar select{max-width:150px}.grid-template-bar>.el-input{width:150px}}
</style>
