import { computed, onBeforeUnmount, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuth } from '../auth'
export type Row = Record<string, any>
export interface Field { key:string; label:string; type?:'text'|'textarea'|'id'|'count'|'decimal'|'date'|'datetime'|'bool'|'select'; options?:string[]; required?:boolean; max?:number }
export const planStatuses=['draft','approved','running','completed','abandoned','archived']
export const modes=['full_cycle','pre_expose_then_react','hf_only','o3_only','tma_only','plasma','deposition','other']
export const stepKinds=['o2_plasma','o3_purge','hf_purge','tma_purge','purge','wait','other']
export const speciesRoles=['precursor','reactant','purge','carrier','other']
export const chemistryStatuses=['active','superseded','experimental']
export const events=['receive','cut','load','unload','measure','process','quarantine','dispose']
export const sampleStatuses=['available','in_process','quarantined','consumed','lost']
export const labels:Record<string,string>={draft:'草稿',approved:'已批准',running:'执行中',completed:'已完成',abandoned:'已放弃',archived:'已归档',active:'启用',inactive:'停用',superseded:'已归档（被取代）',experimental:'试验中',high:'高',normal:'普通',low:'低',full_cycle:'完整循环',pre_expose_then_react:'预暴露后反应',hf_only:'仅 HF',o3_only:'仅 O₃',tma_only:'仅 TMA',plasma:'等离子体',deposition:'沉积',other:'其他',ok:'完整',partial:'部分',aborted:'中止',unknown:'未知',o2_plasma:'O₂ 等离子体',o3_purge:'O₃ / 吹扫',hf_purge:'HF / 吹扫',tma_purge:'TMA / 吹扫',purge:'吹扫',wait:'等待',receive:'接收',cut:'切割',load:'装载',unload:'卸载',measure:'测量',process:'工艺观察',quarantine:'隔离',dispose:'处置',available:'可用',in_process:'加工中',quarantined:'已隔离',consumed:'已消耗',lost:'遗失',precursor:'前驱体',reactant:'反应物',carrier:'载气'}
export const label=(value:unknown)=>labels[String(value)]??String(value??'未知')
// User-facing empty text: the underlying value stays NULL; only the label changes.
export const display=(value:unknown)=>value===null||value===undefined||value===''?'未记录':typeof value==='boolean'?(value?'是':'否'):typeof value==='object'?JSON.stringify(value):label(value)
export const dateText=(v:unknown)=>v?new Date(String(v).match(/Z$|[+-]\d\d:\d\d$/)?String(v):`${v}Z`).toLocaleString('zh-CN',{hour12:false}):'事件时间未知'
export const planFields:Field[]=[{key:'plan_code',label:'计划编码',required:true,max:64},{key:'title',label:'计划标题',required:true,max:255},{key:'batch_id',label:'批次 ID（可空）',type:'id'},{key:'status',label:'计划状态',type:'select',options:planStatuses,required:true},{key:'priority',label:'优先级',type:'select',options:['high','normal','low'],required:true},{key:'planned_start',label:'计划开始日期',type:'date'},{key:'planned_end',label:'计划结束日期',type:'date'},{key:'objective',label:'研究目标',type:'textarea'},{key:'hypothesis',label:'研究假设',type:'textarea'},{key:'design_note',label:'设计说明',type:'textarea'},{key:'notes',label:'备注',type:'textarea'}]
export const processFields:Field[]=[{key:'process_code',label:'执行编码',required:true,max:64},{key:'plan_id',label:'关联计划 ID（可空）',type:'id'},{key:'batch_id',label:'批次 ID（应匹配计划及样品）',type:'id'},{key:'tool_id',label:'设备 ID（可空）',type:'id'},{key:'r1_temp_c',label:'R1 温度（°C）',type:'decimal'},{key:'r2_temp_c',label:'R2 温度（°C）',type:'decimal'},{key:'n2_flow_sccm',label:'N₂ 流量（sccm）',type:'decimal'},{key:'full_ale_cycles',label:'完整 ALE 循环数',type:'count'},{key:'started_at',label:'开始时间（本地时间，可空）',type:'datetime'},{key:'ended_at',label:'结束时间（本地时间，可空）',type:'datetime'},{key:'co_etch_group',label:'共刻蚀组',max:64},{key:'is_independent_run',label:'独立执行',type:'bool'},{key:'log_status',label:'日志状态',type:'select',options:['ok','partial','aborted','unknown'],required:true},{key:'notes',label:'备注',type:'textarea'}]
export const parameterFields:Field[]=[{key:'chemistry',label:'化学体系',max:64},{key:'recipe_id',label:'配方 ID',type:'id'},{key:'cycles',label:'循环数',type:'count'},{key:'cumulative_cycles',label:'累计循环数',type:'count'},{key:'duration_s',label:'持续时间（s）',type:'decimal'},{key:'pulse_s',label:'脉冲（s）',type:'decimal'},{key:'purge_s',label:'吹扫（s）',type:'decimal'},{key:'wait_s',label:'等待（s）',type:'decimal'},{key:'actual_temp_c',label:'温度（°C）',type:'decimal'},{key:'delta_p',label:'压差（见压差单位）',type:'decimal'},{key:'delta_p_unit',label:'压差单位',type:'select',options:['kPa','Pa','mTorr']},{key:'o3_delta_p_kpa',label:'O₃ 压差（kPa）',type:'decimal'},{key:'hf_delta_p_pa',label:'HF 压差（Pa）',type:'decimal'},{key:'tma_delta_p_pa',label:'TMA 压差（Pa）',type:'decimal'},{key:'o3_generator_o2_flow_set_sccm',label:'O₃ 发生器 O₂ 设定流量（sccm）',type:'decimal'},{key:'o3_generator_o2_flow_measured_sccm',label:'O₃ 发生器 O₂ 测量流量（sccm）',type:'decimal'},{key:'o3_concentration',label:'O₃ 浓度（原始记录值，接口未定义单位）',type:'decimal'},{key:'o2_plasma_w',label:'O₂ 等离子体功率（W）',type:'decimal'},{key:'o2_plasma_sccm',label:'O₂ 等离子体流量（sccm）',type:'decimal'},{key:'o2_plasma_pa',label:'O₂ 等离子体压力（Pa）',type:'decimal'}]
export const stepFields:Field[]=[{key:'step_index',label:'步骤序号（从 1 开始）',type:'id',required:true},{key:'step_kind',label:'步骤类型',type:'select',options:stepKinds,required:true},{key:'step_name',label:'步骤名称（可空）',max:128},{key:'step_note',label:'步骤说明（可空）',type:'textarea'}]
export const bindingFields:Field[]=[{key:'sample_id',label:'样品 ID',type:'id',required:true},{key:'chamber_position',label:'腔体位置',max:64},{key:'full_ale_cycles',label:'样品完整 ALE 循环数',type:'count'},{key:'is_control',label:'对照样品',type:'bool'},{key:'sample_role_note',label:'样品角色备注',type:'textarea'}]
export function blank(fields:Field[],source:Row={}):Row { return Object.fromEntries(fields.map(f=>[f.key,source[f.key]??(f.type==='bool'?false:'')])) }
export function payload(fields:Field[],form:Row):Row { const result:Row={}; for(const f of fields){ const v=form[f.key]; if(f.required&&(v===null||v===undefined||String(v).trim()===''))throw new Error(`请填写${f.label}`); if(v===''||v===undefined||v===null){result[f.key]=null;continue} if(f.type==='id'||f.type==='count'){if(!/^\d+$/.test(String(v))||!Number.isSafeInteger(Number(v))||Number(v)<(f.type==='id'?1:0)||Number(v)>4294967295)throw new Error(`${f.label}需要有效整数`);result[f.key]=Number(v)}else if(f.type==='decimal'){if(!/^-?\d+(\.\d+)?$/.test(String(v)))throw new Error(`${f.label}请填写普通十进制字符串`);result[f.key]=String(v)}else if(f.type==='datetime'){result[f.key]=new Date(v).toISOString()}else result[f.key]=v } return result }
// 步骤扩展（第四轮契约第 5 节）：step_name 为自定义步骤名；custom_parameters 为自定义键值参数。
// 未提交 custom_parameters 时接口保持原值，因此仅在用户实际编辑后才发送该字段。
export interface CustomParameter { key:string; value:string; unit:string; note:string }
export const newCustomParameter=():CustomParameter=>({key:'',value:'',unit:'',note:''})
export function customParameterRows(source:unknown):CustomParameter[] {
  if(!source||typeof source!=='object')return []
  return Object.entries(source as Row).map(([key,raw])=>{
    const entry=raw&&typeof raw==='object'?raw as Row:{value:raw}
    const value=entry.value
    return {key,value:value===null||value===undefined?'':String(value),unit:entry.unit==null?'':String(entry.unit),note:entry.note==null?'':String(entry.note)}
  })
}
export function customParameterPayload(rows:CustomParameter[]):Row|null {
  const out:Row={}
  for(const row of rows){
    const key=row.key.trim()
    if(!key&&!row.value.trim()&&!row.unit.trim()&&!row.note.trim())continue
    if(!key)throw new Error('自定义参数需要填写参数名称')
    if(key.length>64)throw new Error(`自定义参数名称「${key}」超过 64 个字符`)
    if(out[key])throw new Error(`自定义参数名称「${key}」重复`)
    if(row.unit.trim().length>24)throw new Error(`自定义参数「${key}」的单位超过 24 个字符`)
    if(row.note.trim().length>255)throw new Error(`自定义参数「${key}」的说明超过 255 个字符`)
    out[key]={value:row.value.trim(),unit:row.unit.trim()||null,note:row.note.trim()||null}
  }
  if(Object.keys(out).length>32)throw new Error('自定义参数最多 32 项')
  return Object.keys(out).length?out:null
}
// 计划步骤 → 实际步骤草稿映射（第四轮契约第 6 节）：只建立对应关系，绝不复制计划参数值。
export function planStepDraft(step:Row):Row {
  const parameters=customParameterRows(step.custom_parameters)
  return {
    step_index:step.step_index,
    step_kind:step.step_kind??'other',
    step_name:step.step_name??'',
    plan_step_id:step.step_id,
    step_note:`计划步骤映射：#${step.step_id}（计划值不复制，实际值请独立填写）`,
    custom_parameters:Object.fromEntries(parameters.map(row=>[row.key,{value:'',unit:row.unit||null,note:null}])),
    parameter_snapshot:clearSnapshotValues(step.parameter_snapshot??legacySnapshot(step,true)),
  }
}
export function useDraftGuard(dirty:()=>boolean,busy:()=>boolean){const baseline=ref('');const isDirty=computed(dirty);async function discard(){if(!useAuth().user)return true;if(busy())return false;if(!dirty())return true;try{await ElMessageBox.confirm('输入尚未保存，确定放弃这些修改？','未保存的修改',{confirmButtonText:'放弃修改',cancelButtonText:'继续编辑',type:'warning'});return true}catch{return false}}const unload=(e:BeforeUnloadEvent)=>{if(dirty()||busy()){e.preventDefault();e.returnValue=''}};window.addEventListener('beforeunload',unload);onBeforeUnmount(()=>window.removeEventListener('beforeunload',unload));onBeforeRouteLeave(discard);onBeforeRouteUpdate(discard);return{baseline,isDirty,discard}}

// Generic snapshots are copied on application; template IDs never enter records.
export interface ParameterField { name:string; value:string|null; unit:string|null }
export interface ParameterGroup { name:string; fields:ParameterField[] }
export interface ParameterSnapshot { step_type:string; temperature:{value:string|null;unit:string}; groups:ParameterGroup[] }
export function defaultSnapshot(type='通用步骤'):ParameterSnapshot {
  return {step_type:type,temperature:{value:null,unit:'°C'},groups:[
    {name:'源',fields:[{name:'名称',value:null,unit:null},{name:'流量',value:null,unit:'sccm'}]},
    ...['脉冲','吹扫','等待'].map(name=>({name,fields:[{name:'时长',value:null,unit:name==='脉冲'?'ms':'s'}]})),
    {name:'压差',fields:[{name:'压差',value:null,unit:'Pa'}]},
    {name:'流量',fields:[{name:'流量',value:null,unit:'sccm'}]},
  ]}
}
export const copySnapshot=(snapshot:ParameterSnapshot):ParameterSnapshot=>JSON.parse(JSON.stringify(snapshot))
export function clearSnapshotValues(snapshot:ParameterSnapshot):ParameterSnapshot {
  const copy=copySnapshot(snapshot);copy.temperature.value=null
  copy.groups.forEach(group=>group.fields.forEach(field=>field.value=null));return copy
}
export function snapshotPayload(snapshot:ParameterSnapshot):ParameterSnapshot {
  const copy=copySnapshot(snapshot)
  const name=(value:string,what:string)=>{const v=value.trim();if(!v||v.length>128)throw new Error(`${what}需要 1–128 个字符`);return v}
  const value=(v:string|null)=>{if(v!==null&&v.length>2000)throw new Error('参数值最多 2000 个字符');return v?.trim()||null}
  const unit=(v:string|null)=>{if(v!==null&&v.trim().length>32)throw new Error('单位最多 32 个字符');return v?.trim()||null}
  copy.step_type=name(copy.step_type,'步骤类型');copy.temperature.value=value(copy.temperature.value)
  copy.temperature.unit=unit(copy.temperature.unit)||'°C'
  if(copy.groups.length>32)throw new Error('参数组最多 32 组')
  const groups=new Set<string>()
  for(const group of copy.groups){group.name=name(group.name,'参数组名称');if(groups.has(group.name))throw new Error('参数组名称重复');groups.add(group.name)
    if(group.fields.length>64)throw new Error('每组最多 64 个字段');const names=new Set<string>()
    for(const field of group.fields){field.name=name(field.name,'字段名称');if(names.has(field.name))throw new Error('同组字段名称重复');names.add(field.name);field.value=value(field.value);field.unit=unit(field.unit)}
  }
  return copy
}
export function legacySnapshot(step:Row,planned=false):ParameterSnapshot {
  const snapshot=defaultSnapshot(step.step_name||label(step.step_kind)||'通用步骤')
  const p=planned?step.planned_parameters??{}:step
  snapshot.temperature.value=p.actual_temp_c==null?null:String(p.actual_temp_c)
  snapshot.groups=[]
  const mappings:[string,[string,string,string|null][]][]=[
    ['源',[['chemistry','名称',null],['recipe_id','配方 ID',null]]],
    ['循环',[['cycles','循环数',null],['cumulative_cycles','累计循环数',null]]],
    ['持续时间',[['duration_s','时长（原始字段 s）','s']]],
    // Legacy physical columns are fixed seconds; the original unit is stated so a
    // later snapshot in ms/µs is not mistaken for the same quantity.
    ['脉冲',[['pulse_s','时长（原始字段 s）','s']]],['吹扫',[['purge_s','时长（原始字段 s）','s']]],['等待',[['wait_s','时长（原始字段 s）','s']]],
    ['压差',[['delta_p','压差',p.delta_p_unit??null],['o3_delta_p_kpa','O₃ 压差','kPa'],['hf_delta_p_pa','HF 压差','Pa'],['tma_delta_p_pa','TMA 压差','Pa']]],
    ['O₃ 发生器',[['o3_generator_o2_flow_set_sccm','O₂ 设定流量','sccm'],['o3_generator_o2_flow_measured_sccm','O₂ 测量流量','sccm'],['o3_concentration','O₃ 浓度（原记录未定义单位）',null]]],
    ['O₂ 等离子体',[['o2_plasma_w','功率','W'],['o2_plasma_sccm','流量','sccm'],['o2_plasma_pa','压力','Pa']]],
  ]
  for(const [groupName,fields] of mappings){const values=fields.filter(([key])=>p[key]!=null).map(([key,name,unit])=>({name,value:String(p[key]),unit}));if(values.length)snapshot.groups.push({name:groupName,fields:values})}
  const custom=customParameterRows(step.custom_parameters)
  if(custom.length)snapshot.groups.push({name:'历史自定义参数',fields:custom.map(r=>({name:r.key,value:r.value||null,unit:r.unit||null}))})
  return snapshot
}
