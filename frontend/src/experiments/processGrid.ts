import { defaultSnapshot, legacySnapshot, snapshotPayload, type ParameterSnapshot, type Row } from './model'
// step_note is client-side context only: the grid never sends it, so PUT keeps the stored note.
export interface GridStep { key:string;step_id:number|null;step_kind:string;step_name:string|null;parameter_snapshot:ParameterSnapshot;plan_step_id:number|null;step_note?:string|null;legacy_parameters?:Row;parameter_source?:string;parameter_conflict?:boolean }
export interface FlowNode {kind:'group'|'step';id:string;name?:string|null;repeat?:number|null;step_id?:string|number|null;children:FlowNode[]}
export interface ProcessFlow {version:1;total_cycles:number|null;children:FlowNode[]}
export interface GridDraft {steps:GridStep[];process_flow:ProcessFlow}
export const uid=()=>`n-${crypto.randomUUID()}`
export const newGridStep=():GridStep=>({key:uid(),step_id:null,step_kind:'通用处理',step_name:'新步骤',parameter_snapshot:defaultSnapshot('通用处理'),plan_step_id:null})
export const stepNode=(key:string):FlowNode=>({kind:'step',id:uid(),step_id:key,children:[]})
export function gridDraft(record:Row,planned=false):GridDraft {
  const steps:GridStep[]=(record.steps??[]).map((s:Row)=>({key:`s-${s.step_id}`,step_id:s.step_id,step_kind:s.step_kind,step_name:s.step_name??null,step_note:s.step_note??null,parameter_snapshot:s.parameter_snapshot?JSON.parse(JSON.stringify(s.parameter_snapshot)):legacySnapshot(s,planned),plan_step_id:planned?null:s.plan_step_id??null,legacy_parameters:s.legacy_parameters??{},parameter_source:s.parameter_source??(s.parameter_snapshot?"parameter_snapshot":"legacy_fields"),parameter_conflict:s.parameter_conflict??false}))
  const flow:ProcessFlow=record.process_flow?JSON.parse(JSON.stringify(record.process_flow)):{version:1,total_cycles:null,children:steps.map(s=>stepNode(s.key))}
  function convert(nodes:FlowNode[]){for(const n of nodes){if(n.kind==='step')n.step_id=`s-${n.step_id}`;else convert(n.children)}}
  if(record.process_flow)convert(flow.children)
  return {steps,process_flow:flow}
}
export function gridPayload(draft:GridDraft){return {steps:draft.steps.map(s=>({key:s.key,step_id:s.step_id,plan_step_id:s.plan_step_id,step_name:s.step_name?.trim()||null,step_kind:s.step_kind.trim(),parameter_snapshot:snapshotPayload(s.parameter_snapshot)})),process_flow:JSON.parse(JSON.stringify(draft.process_flow))}}
export function clearFlowRepeats(flow:ProcessFlow){flow.total_cycles=null;const visit=(ns:FlowNode[])=>ns.forEach(n=>{if(n.kind==='group'){n.repeat=null;visit(n.children)}});visit(flow.children);return flow}

// Empty compact columns are a view, not persisted steps. The stable flow node ID
// remembers explicitly edited sparse slots across the existing API round trip.
export const compactRows = [
  {group:'源',name:'名称',label:'源',unit:null},
  {group:'脉冲',name:'时长',label:'脉冲 (ms)',unit:'ms'},
  {group:'吹扫',name:'时长',label:'吹扫 (s)',unit:'s'},
  {group:'等待',name:'时长',label:'等待 (s)',unit:'s'},
  {group:'压差',name:'压差',label:'压差 (Pa)',unit:'Pa'},
] as const
export function compactNodes(draft:GridDraft):FlowNode[] {
  const nodes=draft.process_flow.children
  return nodes.length===1&&nodes[0]!.kind==='group'?nodes[0]!.children:nodes
}
export function compactColumns(draft:GridDraft):(GridStep|undefined)[] {
  const slots:(GridStep|undefined)[]=Array(5).fill(undefined)
  const nodes=compactNodes(draft)
  // Reserve all stored explicit slots before placing ordinary historical nodes.
  for(const n of nodes){const match=/^compact-slot-([1-5])-/.exec(n.id);if(match)slots[Number(match[1])-1]=draft.steps.find(s=>s.key===n.step_id)}
  for(const n of nodes){if(/^compact-slot-[1-5]-/.test(n.id))continue;const i=slots.findIndex(s=>!s);if(i>=0)slots[i]=draft.steps.find(s=>s.key===n.step_id)}
  return slots
}
export function compactIssue(draft:GridDraft):string {
  const nodes=compactNodes(draft)
  if(nodes.some(n=>n.kind!=='step')||nodes.length!==draft.steps.length)return '包含复杂流程顺序或嵌套组'
  if(nodes.length>5)return '包含五列以外的步骤'
  const reserved=nodes.map(n=>/^compact-slot-([1-5])-/.exec(n.id)?.[1]).filter(Boolean)
  if(new Set(reserved).size!==reserved.length)return '步骤位置需要完整显示'
  const projected=compactColumns(draft).filter(Boolean).map(s=>s!.key)
  if(nodes.some((n,i)=>n.step_id!==projected[i]))return '步骤顺序需要完整显示'
  for(const s of draft.steps){
    if(s.parameter_source==='legacy_fields'||Object.keys(s.legacy_parameters??{}).length)return '包含旧格式参数，按原值和原单位显示'
    if(s.parameter_snapshot.temperature.value!==null&&s.parameter_snapshot.temperature.value!=='')return '包含温度或高级参数'
    for(const g of s.parameter_snapshot.groups)for(const f of g.fields){
      const row=compactRows.find(r=>r.group===g.name&&r.name===f.name)
      if(row){if(f.unit!==row.unit)return '包含不同单位，按原值和原单位显示'}
      else if(!((g.name==='源'&&f.name==='流量')||(g.name==='流量'&&f.name==='流量'))||f.value!==null&&f.value!=='')return '包含自定义或高级参数'
    }
  }
  return ''
}
export function setCompactCell(draft:GridDraft,index:number,rowIndex:number,value:string){
  if(index<0||index>4||compactIssue(draft))return
  const row=compactRows[rowIndex];if(!row)return
  let step=compactColumns(draft)[index]
  if(!step){
    if(value==='')return
    step={key:uid(),step_id:null,step_kind:'other',step_name:null,plan_step_id:null,
      parameter_snapshot:{step_type:'other',temperature:{value:null,unit:'°C'},groups:compactRows.map(r=>({name:r.group,fields:[{name:r.name,value:null,unit:r.unit}]}))}}
    draft.steps.push(step)
    const node=stepNode(step.key);node.id=`compact-slot-${index+1}-${uid()}`
    const nodes=compactNodes(draft);nodes.push(node)
    const positions=compactColumns(draft)
    nodes.sort((a,b)=>positions.findIndex(s=>s?.key===a.step_id)-positions.findIndex(s=>s?.key===b.step_id))
    draft.steps.sort((a,b)=>positions.indexOf(a)-positions.indexOf(b))
  }
  let group=step.parameter_snapshot.groups.find(g=>g.name===row.group)
  if(!group){group={name:row.group,fields:[]};step.parameter_snapshot.groups.push(group)}
  let field=group.fields.find(f=>f.name===row.name)
  if(!field){field={name:row.name,value:null,unit:row.unit};group.fields.push(field)}
  field.value=value===''?null:value
}
