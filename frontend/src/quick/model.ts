export const uid=()=>crypto.randomUUID()
export const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
export const step=()=>({step_id:uid(),source_label:'',enabled:false,pulse_ms:null,purge_s:null,wait_s:null,delta_p_pa:null,delta_p_pa_min:null,delta_p_pa_max:null})
export const group=(code='A')=>({group_id:uid(),code,repeat_count:100,steps:Array.from({length:5},step)})
export const result=()=>({result_id:uid(),alias:'样品1',material_id:null,effective_cycles:100,thickness_before_nm:null,thickness_after_nm:null,before_origin:'unknown',after_origin:'manual',carried_from_result_id:null,uniformity_pct:null,uniformity_definition:null,reported_epc:null,data_nature:'unknown_legacy',quality_status:'unreviewed',source:null,result_label:null,use_for_model_override:null})
export const fresh=():any=>({experiment_date:today(),daily_no:1,timezone:'Asia/Hong_Kong',material_id:null,started_at:null,ended_at:null,note:'',external_experiment_id:null,external_batch_id:null,state:'draft',program:{outer_cycles:1,groups:[group()]},environment:{r1_temperature_c:null,r2_temperature_c:null,n2_flow_sccm:null,chamber_pressure_pa:null,equipment:null,film_context:null,process_type:null,rf_icp_power_w:null,bias_power_w:null},results:[result()],previous_run_id:null,expected_version:null,idempotency_key:uid()})
export const resultKeys=Object.keys(result())
export function edit(run:any):any{
 const value=fresh();for(const key of Object.keys(value))if(key in run)value[key]=JSON.parse(JSON.stringify(run[key]))
 value.expected_version=run.version;value.idempotency_key=uid()
 value.results=run.results.map((r:any)=>Object.fromEntries(resultKeys.map(k=>[k,r[k]??null])))
 return value
}
export function derive(r:any){
 const a=r.thickness_before_nm,b=r.thickness_after_nm,n=r.effective_cycles
 if(a===null||a===''||b===null||b===''||![a,b].every(v=>Number.isFinite(Number(v))))return {loss:null,epc:null}
 const loss=Number(a)-Number(b);return {loss,epc:Number(n)>0&&Number.isFinite(Number(n))?loss*10/Number(n):null}
}
export const display=(v:any)=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:8})
export function fieldName(path:string,form:any){
 const names:Record<string,string>={experiment_date:'实验日期',daily_no:'当日第几次',material_id:'薄膜材料',started_at:'开始时间',ended_at:'结束时间',note:'实验备注',external_experiment_id:'外部实验ID',external_batch_id:'批次ID',state:'记录状态',outer_cycles:'外层总循环次数',code:'组名称',repeat_count:'组循环次数',source_label:'源',pulse_ms:'Pulse (ms)',purge_s:'Purge (s)',wait_s:'Wait (s)',delta_p_pa:'ΔP (Pa)',delta_p_pa_min:'ΔP 下限 (Pa)',delta_p_pa_max:'ΔP 上限 (Pa)',r1_temperature_c:'R1 (°C)',r2_temperature_c:'R2 (°C)',n2_flow_sccm:'N₂ (sccm)',chamber_pressure_pa:'腔体绝对压力 (Pa)',equipment:'设备/腔体',film_context:'薄膜属性',process_type:'工艺类型',rf_icp_power_w:'RF/ICP 功率 (W)',bias_power_w:'Bias 功率 (W)',alias:'样品标识',effective_cycles:'本段有效循环次数',thickness_before_nm:'刻蚀前膜厚 (nm)',thickness_after_nm:'刻蚀后膜厚 (nm)',uniformity_pct:'膜厚均匀性 (%)',uniformity_definition:'均匀性定义',reported_epc:'原报告 EPC',data_nature:'数据性质',quality_status:'质量状态',result_label:'结果标签',use_for_model_override:'用于建模覆盖'}
 const parts=path.split('.').filter(p=>p!=='body'),last=parts[parts.length-1]||'';let prefix=''
 const gi=parts.indexOf('groups');if(gi>=0&&parts[gi+1]!==undefined){const index=Number(parts[gi+1]);prefix=`${form.program.groups[index]?.code||index+1} 组 `;const si=parts.indexOf('steps');if(si>=0)prefix+=`第 ${Number(si+1)+1} 步 `}
 const ri=parts.indexOf('results');if(ri>=0)prefix=`膜厚测量 ${Number(parts[ri+1])+1} `
 return prefix+(names[last]??'数据字段')
}
export function cleanNumbers(body:any){
 const integers=new Set(['daily_no','outer_cycles','repeat_count','effective_cycles'])
 const convert=(obj:any,keys:string[])=>{for(const k of keys){if(obj[k]===''||obj[k]===undefined)obj[k]=null;else if(obj[k]!==null&&integers.has(k))obj[k]=Number(obj[k])}}
 const nullable=(obj:any,keys:string[])=>{for(const k of keys)if(obj[k]===''||obj[k]===undefined)obj[k]=null}
 convert(body,['daily_no']);nullable(body,['external_experiment_id','external_batch_id']);convert(body.program,['outer_cycles']);convert(body.environment,['r1_temperature_c','r2_temperature_c','n2_flow_sccm','chamber_pressure_pa','rf_icp_power_w','bias_power_w']);nullable(body.environment,['process_type','equipment','film_context'])
 for(const g of body.program.groups){convert(g,['repeat_count']);for(const s of g.steps)convert(s,['pulse_ms','purge_s','wait_s','delta_p_pa','delta_p_pa_min','delta_p_pa_max'])}
 for(const r of body.results){convert(r,['effective_cycles','thickness_before_nm','thickness_after_nm','uniformity_pct','reported_epc']);nullable(r,['result_label'])}
 return body
}
