<script setup lang="ts">
import {computed,ref,watch,nextTick,onMounted,onBeforeUnmount} from 'vue'
import {useRoute,useRouter,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router'
import {ElMessageBox} from 'element-plus'
import {api,multipart,apiBlob,ApiError,errorText} from '../api'
import {useAuth} from '../auth'
import QuickNumber from '../components/QuickNumber.vue'
import QuickProgramEditor from '../components/QuickProgramEditor.vue'
import QuickSourceSelect from '../components/QuickSourceSelect.vue'
import {fresh,result,edit,uid,derive,display,cleanNumbers,today,fieldName} from '../quick/model'
import '../quick/quick.css'
const route=useRoute(),router=useRouter(),auth=useAuth()
let internalNavigation=false
const form=ref<any>(fresh()),saved=ref<any>(null),baseline=ref(''),ready=ref(false),busy=ref(false),loading=ref(true),message=ref(''),error=ref('')
const materials=ref<any[]>([]),history=ref<any[]>([]),templates=ref<any[]>([]),picker=ref(''),sourceNote=ref(''),mode=ref('manual'),newMaterial=ref(''),templateName=ref('')
const structureOpen=ref(false),structureEditor=ref<InstanceType<typeof QuickProgramEditor>>()
const sources=ref<any[]>([]),newSource=ref(''),sourceFeedback=ref('')
const sourceNames=computed(()=>sources.value.map(source=>source.canonical_name))
const preview=ref<any>(null),mapping=ref<any[]>([]),confirmed=ref(false),fileInput=ref<HTMLInputElement>(),revisions=ref<any[]>([])
const timeStart=ref(''),timeEnd=ref(''),endDate=ref(''),crossDay=ref(false)
const fields=[['pulse_ms','Pulse (ms)'],['purge_s','Purge (s)'],['wait_s','Wait (s)']]
const deltaDrafts=ref<Record<string,string>>({})
const deltaPattern=/^([-+]?\d+(?:\.\d+)?)\s*[-–~]\s*([-+]?\d+(?:\.\d+)?)$/
const singlePattern=/^[-+]?(?:\d+\.?\d*|\.\d+)?$/
function deltaPText(s:any){const draft=deltaDrafts.value[s.step_id];if(draft!==undefined)return draft;if(s.delta_p_pa_min!=null&&s.delta_p_pa_max!=null)return `${s.delta_p_pa_min}–${s.delta_p_pa_max}`;return s.delta_p_pa??''}
function deltaPInvalid(s:any){const t=String(deltaPText(s)).trim();if(!t)return false;const m=t.match(deltaPattern);if(m)return Number(m[1])>Number(m[2]);return !singlePattern.test(t)}
function deltaPApply(s:any,text:string){
 s.enabled=true
 const t=String(text??'').trim(),m=t.match(deltaPattern)
 if(m&&Number(m[1])<=Number(m[2])){s.delta_p_pa=null;s.delta_p_pa_min=m[1];s.delta_p_pa_max=m[2];return}
 if(!m&&singlePattern.test(t)){s.delta_p_pa=t||null;s.delta_p_pa_min=null;s.delta_p_pa_max=null}
}
function deltaPInput(s:any,event:Event){const text=(event.target as HTMLInputElement).value;deltaDrafts.value[s.step_id]=text;deltaPApply(s,text)}
function deltaPBlur(s:any,event:Event){const text=(event.target as HTMLInputElement).value;deltaPApply(s,text);if(deltaPInvalid(s)){deltaDrafts.value[s.step_id]=text;return}delete deltaDrafts.value[s.step_id]}
const processTimeS=computed(()=>{const a=form.value.started_at,b=form.value.ended_at;if(!a||!b)return null;const seconds=(new Date(b).getTime()-new Date(a).getTime())/1000;return Number.isFinite(seconds)&&seconds>0?seconds:null})
const etchRate=computed(()=>{const t=processTimeS.value,r=form.value.results?.[0];if(!t||!r)return null;const a=Number(r.thickness_before_nm),b=Number(r.thickness_after_nm);if(!Number.isFinite(a)||!Number.isFinite(b))return null;return (a-b)*60/t})
const dirty=computed(()=>(ready.value&&JSON.stringify(form.value)!==baseline.value)||(structureOpen.value&&!!structureEditor.value?.hasChanges))
const canSave=computed(()=>auth.canWrite&&ready.value&&!busy.value&&!loading.value)
async function action(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){error.value=e instanceof ApiError&&e.fields.length?`请核对以下字段：${e.fields.map(item=>fieldName(item.field,form.value)).join('、')}。当前输入已保留。`:errorText(e)}finally{busy.value=false}}
async function catalog(){const [m,s]=await Promise.all([api<any[]>('/quick/materials'),api<any[]>('/quick/sources')]);materials.value=m.data;sources.value=s.data}
async function addSource(){await action(async()=>{const {data}=await api<any>('/quick/sources',{method:'POST',body:{canonical_name:newSource.value}});if(!sources.value.some(source=>source.source_id===data.source_id))sources.value.push(data);sources.value.sort((a,b)=>a.canonical_name.localeCompare(b.canonical_name));newSource.value='';sourceFeedback.value=`已添加源 ${data.canonical_name}，可在步骤下拉框中选择。`})}
async function addMaterial(name:string){await action(async()=>{const {data}=await api<any>('/quick/materials',{method:'POST',body:{canonical_name:name}});await catalog();form.value.material_id=data.material_id;newMaterial.value=''})}
async function number(){if(saved.value)return;try{form.value.daily_no=(await api<any>('/quick/next-number',{query:{experiment_date:form.value.experiment_date}})).data.daily_no}catch(e){error.value=errorText(e)}}
function readTime(){
 const local=(iso:any)=>iso?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(iso)):''
 const start=local(form.value.started_at),end=local(form.value.ended_at);timeStart.value=start.slice(11,16);timeEnd.value=end.slice(11,16);endDate.value=end.slice(0,10)||form.value.experiment_date;crossDay.value=!!end&&end.slice(0,10)!==form.value.experiment_date
}
function writeTime(){form.value.started_at=timeStart.value?`${form.value.experiment_date}T${timeStart.value}:00+08:00`:null;form.value.ended_at=timeEnd.value?`${crossDay.value?endDate.value:form.value.experiment_date}T${timeEnd.value}:00+08:00`:null}
async function load(){ready.value=false;loading.value=true;error.value='';try{await catalog();const id=Number(route.query.run);if(id){saved.value=(await api<any>(`/quick/runs/${id}`)).data;form.value=edit(saved.value);readTime();message.value=`已保存记录 · ${saved.value.process_code} · 版本 ${saved.value.version}`}else{saved.value=null;form.value=fresh();message.value='';sourceNote.value='';await number();timeStart.value='';timeEnd.value='';crossDay.value=false;endDate.value=today()}preview.value=null;revisions.value=[];baseline.value=JSON.stringify(form.value);ready.value=true}catch(e){error.value=errorText(e)}finally{loading.value=false}}
async function confirmLeave(){if(internalNavigation)return true;if(structureOpen.value&&structureEditor.value?.hasChanges){if(!await structureEditor.value.askDiscard())return false;structureOpen.value=false}if(!dirty.value)return true;try{await ElMessageBox.confirm('有尚未保存的修改，离开会丢失当前输入。','离开未保存页面',{confirmButtonText:'放弃并离开',cancelButtonText:'继续编辑',type:'warning'});return true}catch{return false}}
onBeforeRouteLeave(confirmLeave)
onBeforeRouteUpdate(confirmLeave)
function beforeUnload(e:BeforeUnloadEvent){if(dirty.value){e.preventDefault();e.returnValue=''}}
onMounted(()=>{void load();window.addEventListener('beforeunload',beforeUnload)})
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',beforeUnload)})
watch(()=>route.query.run,()=>{if(!busy.value&&!internalNavigation)void load()})
async function save(state='recorded',continueAfter=false){
 if(!canSave.value)return
 await action(async()=>{
  writeTime();await nextTick()
  const invalid=Array.from(document.querySelectorAll<HTMLElement>('.quick-record [aria-invalid="true"]')).find(el=>!el.closest('.el-dialog')&&el.getClientRects().length>0);if(invalid){invalid.focus();throw new Error('请修正标出的数字；输入内容已保留。')}
  if(state==='recorded'&&!form.value.material_id){document.getElementById('quick-material')?.focus();throw new Error('请选择材料，或先保存草稿。')}
  const payload=cleanNumbers(JSON.parse(JSON.stringify(form.value)));payload.state=state
  if(payload.started_at&&payload.ended_at&&new Date(payload.ended_at)<new Date(payload.started_at))throw new Error('结束时间早于开始时间，请明确选择跨日和结束日期。')
  const path='/quick/runs'+(saved.value?'/'+saved.value.run_id:'')
  const {data}=await api<any>(path,{method:saved.value?'PUT':'POST',body:payload})
  saved.value=data;form.value=edit(data);baseline.value=JSON.stringify(form.value);message.value=`已保存 · ${new Date().toLocaleTimeString('zh-CN')} · ${data.process_code}`
  await router.replace({path:'/quick',query:{run:data.run_id}})
  if(continueAfter)await reuse(data,true)
 })
 if(error.value){await nextTick();const invalid=Array.from(document.querySelectorAll<HTMLElement>('.quick-record [aria-invalid="true"]')).find(el=>!el.closest('.el-dialog')&&el.getClientRects().length>0);invalid?.focus()}
}
async function choices(kind:string){await action(async()=>{if(kind==='template'){templates.value=(await api<any[]>('/quick/templates')).data}else history.value=(await api<any>('/quick/runs')).data.items;picker.value=kind})}
async function reuse(run:any,continuing=false){
 const next=edit(run);next.idempotency_key=uid();next.expected_version=null;next.state='draft';next.experiment_date=today();next.started_at=null;next.ended_at=null;next.note='';next.previous_run_id=continuing?run.run_id:null
 next.program.groups.forEach((g:any)=>{g.group_id=uid();g.steps.forEach((s:any)=>s.step_id=uid())})
 next.results=run.results.map((r:any,i:number)=>({...result(),alias:r.alias,material_id:r.material_id,effective_cycles:r.effective_cycles,thickness_before_nm:continuing?r.thickness_after_nm:null,before_origin:continuing&&r.thickness_after_nm!==null?'carried_forward':'unknown',carried_from_result_id:continuing?r.result_id:null}))
 message.value='';saved.value=null;form.value=next;timeStart.value='';timeEnd.value='';crossDay.value=false;endDate.value=today();await number();picker.value='';sourceNote.value=continuing?'连续下一段：前膜厚仅承接参考，非本次实测。':'复制独立工艺快照：结果和连续关联已清空。';preview.value=null
 baseline.value='';internalNavigation=true;await router.replace({path:'/quick'});await nextTick();internalNavigation=false
}
async function useHistory(run:any){if(!await confirmLeave())return;await reuse(run)}
async function last(){await choices('history');if(history.value.length)await useHistory(history.value[0]);else message.value='暂无历史参数，请先保存一条记录。';picker.value=''}
async function useTemplate(t:any){if(!await confirmLeave())return;const empty=fresh();empty.program=JSON.parse(JSON.stringify(t.snapshot.program));empty.environment=JSON.parse(JSON.stringify(t.snapshot.environment));empty.material_id=t.snapshot.material_id;empty.program.groups.forEach((g:any)=>{g.group_id=uid();g.steps.forEach((s:any)=>s.step_id=uid())});message.value='';form.value=empty;saved.value=null;await number();baseline.value='';sourceNote.value=`已加载模板：${t.name}（版本 ${t.version}）`;picker.value='';internalNavigation=true;await router.replace({path:'/quick'});await nextTick();internalNavigation=false}
async function saveTemplate(){if(!saved.value||dirty.value){error.value='请先保存当前记录，再保存为模板。';return}await action(async()=>{await api('/quick/templates',{method:'POST',body:{run_id:saved.value.run_id,name:templateName.value}});templateName.value='';message.value='工艺模板已保存，只包含参数快照。'})}
async function upload(event:Event){const file=(event.target as HTMLInputElement).files?.[0];if(!file)return;if(!saved.value||dirty.value){error.value='请先保存当前记录，再上传 Excel 补录。';return}await action(async()=>{const fd=new FormData();fd.append('file',file);preview.value=(await multipart<any>(`/quick/runs/${saved.value.run_id}/preview`,fd)).data;confirmed.value=false;mapping.value=preview.value.blocks.map((_:any,i:number)=>({block_index:i,result_id:'',field:'thickness_after_nm'}))});if(fileInput.value)fileInput.value.value=''}
function importedValue(index:number){return preview.value.blocks[index].statistics?.thickness_nm?.mean??null}
function oldValue(m:any){return form.value.results.find((r:any)=>r.result_id===m.result_id)?.[m.field]??null}
async function importConfirm(){await action(async()=>{const mappings=mapping.value.filter(m=>m.result_id);if(!mappings.length)throw new Error('请为至少一个量测块选择结果行。');await api(`/quick/imports/${preview.value.token}/confirm`,{method:'POST',body:{expected_version:saved.value.version,mappings,confirm_conflicts:confirmed.value}});await load();message.value='Excel 补录已确认，原手记保留在修订历史。'})}
async function versions(){await action(async()=>{revisions.value=(await api<any[]>(`/quick/runs/${saved.value.run_id}/revisions`)).data})}
async function downloadOriginal(token:string){await action(async()=>{const {blob,filename}=await apiBlob(`/quick/imports/${token}/original`);const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
function draftDownload(){const url=URL.createObjectURL(new Blob([JSON.stringify(form.value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='ale-unsaved-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function archiveThis(){if(!saved.value)return;const restoring=!!saved.value.archived;await action(async()=>{await api(`/quick/runs/${saved.value.run_id}/${restoring?'restore':'archive'}`,{method:'POST'});await load();message.value=restoring?'已恢复。':'已归档，可在数据集中心恢复。'})}
async function removeThis(){if(!saved.value)return;try{await ElMessageBox.confirm(`永久删除「${saved.value.process_code}」？记录与结果将从数据库移除，不可撤销。`,'请确认',{type:'warning',confirmButtonText:'确认删除',cancelButtonText:'取消'})}catch{return};await action(async()=>{await api(`/quick/runs/${saved.value.run_id}`,{method:'DELETE'});internalNavigation=true;await router.replace({path:'/quick'});await nextTick();internalNavigation=false;message.value='已删除。'})}
</script>
<template>
 <div class="quick-record quick-page" :aria-busy="busy||loading">
  <header class="quick-heading"><div><p class="eyebrow">ALE WORKBENCH / V2.2</p><h1>新建实验记录</h1><p>极简记录 · 先记参数，量测结果可稍后补录</p></div><span class="state-chip">{{dirty?'未保存':saved?'已保存 · '+(saved.state==='draft'?'草稿':'记录'):'空白记录'}}</span></header>
  <div role="status" aria-live="polite" class="quick-status">{{busy?'正在处理，请稍候…':dirty?(sourceNote||'有未保存的修改，请保存记录。'):message||sourceNote||'新建空记录：步骤数值为空，示例不会自动作为实际工艺。'}}</div>
  <div v-if="error" role="alert" class="quick-error">{{error}}<div class="quick-actions"><button @click="error=''">继续编辑</button><button @click="draftDownload">下载当前输入</button><button :disabled="busy" @click="load">重新加载记录</button></div></div>
  <div v-if="loading" role="status">正在从数据库读取记录…</div>
  <fieldset v-else-if="ready" class="quick-form-controls" :disabled="busy">
  <div class="quick-actions"><button :disabled="!canSave" @click="last">沿用上次参数</button><button :disabled="!canSave" @click="choices('history')">从历史复制</button><button :disabled="!canSave" @click="choices('template')">选择模板</button><RouterLink to="/professional">专业模式</RouterLink></div>
  <section class="quick-card" aria-labelledby="identity-title"><h2 id="identity-title">实验信息</h2>
   <div class="quick-grid three"><label>实验日期<input v-model="form.experiment_date" type="date" @change="number();writeTime()"></label><QuickNumber v-model="form.daily_no" label="当日第几次" :min="1" :max="1000000" integer/><label>材料<select aria-label="材料" id="quick-material" v-model="form.material_id"><option :value="null">请选择材料（草稿可空）</option><option v-for="m in materials" :key="m.material_id" :value="m.material_id">{{m.canonical_name}}</option></select></label></div>
   <div class="quick-grid two"><label>外部实验ID<input v-model="form.external_experiment_id" aria-label="外部实验ID" placeholder="对应 Excel 的实验ID，不覆盖系统编号"></label><label>批次ID<input v-model="form.external_batch_id" aria-label="批次ID" placeholder="物理批次标识，纯文本"></label></div>
   <p class="quick-help">系统内部编号由工作台生成并保持不变；这里填写的标识仅用于与 Excel 对照，不作为主键或去重依据。</p>
   <p class="quick-help">当天序号仅用于记录顺序，不是物理批次。材料别名和沉积方式不同的薄膜不会自动合并。</p>
   <div class="quick-actions"><label class="grow">搜索 / 自定义材料<input aria-label="搜索 / 自定义材料" v-model="newMaterial" list="quick-material-list" placeholder="输入规范名，可选已有或新增"><datalist id="quick-material-list"><option v-for="m in materials" :key="m.material_id">{{m.canonical_name}}</option></datalist></label><button :disabled="!canSave||!newMaterial.trim()" @click="addMaterial(newMaterial)">选择或新增材料</button></div>
   <div class="quick-grid two"><label>开始时间<input v-model="timeStart" type="time" @change="writeTime"></label><label>结束时间<input v-model="timeEnd" type="time" @change="writeTime"></label></div>
   <label class="check-line"><input v-model="crossDay" type="checkbox" @change="writeTime">结束时间跨日（Asia/Hong_Kong，UTC+8）</label><label v-if="crossDay">结束日期<input v-model="endDate" type="date" @change="writeTime"></label>
   <label>实验目的 / 过程 / 备注<textarea v-model="form.note" rows="3" placeholder="例如：100 cycles；保留多行说明"/></label>
  </section>
  <section class="quick-card" aria-labelledby="program-title"><div class="quick-heading"><h2 id="program-title">实验参数</h2><button :disabled="!canSave" @click="structureOpen=true">编辑工艺结构</button></div>
   <div class="quick-actions"><label class="grow">添加 / 自定义源<input v-model="newSource" aria-label="添加 / 自定义源" maxlength="128" placeholder="例如 HF、TMA，输入实际源名称"></label><button :disabled="!canSave||!newSource.trim()" @click="addSource">添加源</button></div><p v-if="sourceFeedback" role="status" class="quick-help">{{sourceFeedback}}</p>
   <div v-for="g in form.program.groups" :key="g.group_id" class="quick-group"><h3>{{g.code}} 组</h3><QuickNumber v-model="g.repeat_count" :label="g.code+' 组循环次数'" :min="0" :max="1000000" integer/>
    <p class="quick-help">选择实际使用的前驱体或气体，例如 HF、TMA。Pulse 和 Purge 分别保存，空白列不计为执行步骤。</p>
    <div class="quick-scroll" tabindex="0" :aria-label="g.code+' 组参数表，可横向滚动'"><table class="quick-matrix"><caption class="sr-only">{{g.code}} 组工艺步骤，源与数值按列整体移动</caption><thead class="sr-only"><tr><th scope="col">参数</th><th v-for="(s,si) in g.steps" :key="s.step_id" scope="col">步骤 {{Number(si)+1}}</th></tr></thead><tbody>
     <tr><th scope="row">源</th><td v-for="(s,si) in g.steps" :key="s.step_id"><QuickSourceSelect :id="'src-'+s.step_id" :name="`${g.code} 组 #${Number(si)+1} 源`" :options="sourceNames" :disabled="busy" v-model="s.source_label" @update:model-value="s.enabled=true"/></td></tr>
     <tr v-for="field in fields" :key="field[0]"><th scope="row">{{field[1]}}</th><td v-for="(s,si) in g.steps" :key="s.step_id"><QuickNumber v-model="s[field[0]!]" @update:model-value="s.enabled=true" :label="`${g.code} 组 #${Number(si)+1} ${field[1]}`" :min="0" :max="100000000"/></td></tr>
     <tr><th scope="row">ΔP (Pa)</th><td v-for="(s,si) in g.steps" :key="s.step_id"><input :aria-label="`${g.code} 组 #${Number(si)+1} ΔP (Pa)，可填单值或波动区间 70–100`" :aria-invalid="deltaPInvalid(s)" :value="deltaPText(s)" @input="deltaPInput(s,$event)" @blur="deltaPBlur(s,$event)"><span v-if="deltaPInvalid(s)" class="field-error">请填单值或区间（下限不大于上限）</span></td></tr>
    </tbody></table></div>
   </div>

   <div class="quick-grid three environment"><QuickNumber v-model="form.environment.r1_temperature_c" label="R1 (°C)" :min="-273.15" :max="3000" :decimals="2"/><QuickNumber v-model="form.environment.r2_temperature_c" label="R2 (°C)" :min="-273.15" :max="3000" :decimals="2"/><QuickNumber v-model="form.environment.n2_flow_sccm" label="N₂ (sccm)" :min="0" :max="1000000" :decimals="3"/></div>
   <div class="quick-grid three"><QuickNumber v-model="form.environment.chamber_pressure_pa" label="腔体绝对压力 (Pa)" :min="0"/><label>设备 / 腔体<input v-model="form.environment.equipment" aria-label="设备/腔体"></label><label>工艺类型<select v-model="form.environment.process_type" aria-label="工艺类型"><option :value="null">未标注</option><option>Thermal ALE</option><option>Plasma ALE</option><option>其他</option></select></label></div>
   <div class="quick-grid three"><QuickNumber v-model="form.environment.rf_icp_power_w" label="RF/ICP 功率 (W)" :min="0"/><QuickNumber v-model="form.environment.bias_power_w" label="Bias 功率 (W)" :min="0"/><div class="quick-metrics"><div><span>总工艺时间 (s)</span><strong>{{display(processTimeS)}}</strong></div><div><span>刻蚀速率 (nm/min)</span><strong>{{display(etchRate)}}</strong></div></div></div>
   <p class="quick-help">总工艺时间与刻蚀速率按起止时间、膜厚自动推算，属派生值、不写入数据库；R2 非必填，导出 Excel 时温度列只写 R1。ΔP 可填单值或波动区间（如 70–100）。</p>
   <details><summary>更多参数与模板</summary><label>沉积方式 / 薄膜属性<input v-model="form.environment.film_context"></label><div class="quick-actions"><label class="grow">模板名称<input v-model="templateName"></label><button :disabled="!canSave||!templateName.trim()||!saved||dirty" @click="saveTemplate">保存成模板</button></div><p class="quick-help">先保存记录，再保存参数模板。模板不包含膜厚、文件或连续关联。</p></details>
  </section>
  <section class="quick-card" aria-labelledby="results-title"><h2 id="results-title">实验结果</h2><div class="quick-tabs" role="group" aria-label="结果录入方式"><button :aria-pressed="mode==='manual'" @click="mode='manual'">手动填写</button><button :aria-pressed="mode==='excel'" @click="mode='excel'">上传 Excel</button><button :aria-pressed="mode==='later'" @click="mode='later'">本次暂无结果，稍后补录</button></div>
   <p v-if="mode==='later'" class="quick-help">可先保存现有参数。已输入的膜厚保留，稍后从历史打开补录。</p>
   <template v-for="(r,ri) in form.results" :key="r.result_id"><article class="quick-result" :aria-label="`膜厚测量 ${Number(ri)+1}`"><h3>{{form.results.length===1?'膜厚测量':`膜厚测量 · ${r.alias||'未命名样品'}`}}</h3><div class="quick-grid two"><label>样品标识<input v-model="r.alias" :aria-label="`膜厚测量 ${Number(ri)+1} 样品标识`"></label><label>薄膜材料<select :aria-label="`膜厚测量 ${Number(ri)+1} 薄膜材料`" v-model="r.material_id"><option :value="null">沿用本次实验材料</option><option v-for="m in materials" :key="m.material_id" :value="m.material_id">{{m.canonical_name}}</option></select></label></div>
    <div class="quick-grid three"><QuickNumber v-model="r.thickness_before_nm" label="刻蚀前膜厚 (nm)" :name="`膜厚测量 ${Number(ri)+1} 刻蚀前膜厚 (nm)`" :min="0"/><QuickNumber v-model="r.thickness_after_nm" label="刻蚀后膜厚 (nm)" :name="`膜厚测量 ${Number(ri)+1} 刻蚀后膜厚 (nm)`" :min="0"/><QuickNumber v-model="r.effective_cycles" label="本段有效循环次数" :name="`膜厚测量 ${Number(ri)+1} 本段有效循环次数`" :min="0" integer/></div>
    <p v-if="r.before_origin==='carried_forward'" class="quick-warning">来自上次量测的参考值 / 非本次实测。中间处理未知时不能视为同一表面状态。{{saved?.results[ri]?.reference_needs_review?'前段已修订，请重新核对参考膜厚。':''}}</p>
    <div class="quick-grid two"><label>前膜厚来源<select :aria-label="`膜厚测量 ${Number(ri)+1} 前膜厚来源`" v-model="r.before_origin"><option value="unknown">未知 / 待核对</option><option value="measured">本次实验前实测</option><option v-if="r.carried_from_result_id" value="carried_forward">上一段参考值</option></select></label><label>数据性质<select :aria-label="`膜厚测量 ${Number(ri)+1} 数据性质`" v-model="r.data_nature"><option value="unknown_legacy">未知 / 遗留待审核</option><option value="real_experiment">真实实验（本人确认）</option><option value="synthetic">合成 / 软件验收数据</option></select></label></div>
    <div class="quick-grid two"><label>结果标签<select :aria-label="`膜厚测量 ${Number(ri)+1} 结果标签`" v-model="r.result_label"><option :value="null">未标注</option><option>刻蚀</option><option>沉积</option><option>无明显变化</option><option>异常</option></select></label><label>用于建模<select :aria-label="`膜厚测量 ${Number(ri)+1} 用于建模`" v-model="r.use_for_model_override"><option :value="null">按系统判定</option><option :value="true">是（人工覆盖）</option><option :value="false">否（人工覆盖）</option></select></label></div>
    <div class="quick-metrics"><div><span>表观净减薄 Δt (nm)</span><strong>{{display(derive(r).loss)}}</strong></div><div><span>自动计算 EPC (Å/cycle)</span><strong>{{display(derive(r).epc)}}</strong></div><div><span>累计有效循环</span><strong>{{saved&&!dirty?display(saved.results[ri]?.cumulative_cycles):'待保存核算'}}</strong></div></div>
    <p v-if="derive(r).epc===null" class="quick-help">请填写前后膜厚及大于 0 的本段有效循环数；未知时不显示为零。</p><p v-else class="quick-help">EPC = 10 ×（前 − 后）/ 本段有效循环；负值表示表观增厚。</p>
    <p v-if="form.program.groups.length===1&&form.program.outer_cycles!=null&&form.program.outer_cycles!==''&&form.program.groups[0].repeat_count!=null&&form.program.groups[0].repeat_count!==''&&r.effective_cycles!=null&&r.effective_cycles!==''&&Number(r.effective_cycles)!==Number(form.program.outer_cycles)*Number(form.program.groups[0].repeat_count)" class="quick-warning">程序循环与有效循环不一致，请核实周期口径；不会自动修改。</p>
    <details><summary>均匀性、质量审核与来源</summary><div class="quick-grid two"><QuickNumber v-model="r.uniformity_pct" label="膜厚均匀性 (%)" :name="`膜厚测量 ${Number(ri)+1} 膜厚均匀性 (%)`" :min="0"/><label>均匀性定义<input v-model="r.uniformity_definition" :aria-label="`膜厚测量 ${Number(ri)+1} 均匀性定义`" placeholder="未知可空，但训练会警告"></label><QuickNumber v-model="r.reported_epc" label="原报告 EPC (Å/cycle)" :name="`膜厚测量 ${Number(ri)+1} 原报告 EPC (Å/cycle)`"/><label>质量状态<select :aria-label="`膜厚测量 ${Number(ri)+1} 质量状态`" v-model="r.quality_status"><option value="unreviewed">未审核</option><option value="approved">已审核</option><option value="excluded">排除</option></select></label></div><button v-if="r.source" :disabled="busy" @click="downloadOriginal(r.source.token)">下载校验原件</button><pre tabindex="0" v-if="r.source">{{JSON.stringify(r.source,null,2)}}</pre><p v-if="Number(saved?.results[ri]?.reported_epc_difference) !== 0 && saved?.results[ri]?.reported_epc_difference != null" class="quick-warning">原报告与重算 EPC 差异：{{saved.results[ri].reported_epc_difference}}</p></details>
   </article></template><button @click="form.results.push({...result(),alias:'样品'+(form.results.length+1)})">＋ 添加测量样品</button>
   <div v-if="mode==='excel'" class="quick-import"><h3>量测 Excel 补录</h3><p>支持现有 Eoptics 量测工作簿。竞赛参数表不作为量测原件解析。请先保存记录，再上传；预览不会更改正式结果。</p><label>选择量测文件<input ref="fileInput" type="file" accept=".xlsx" :disabled="!canSave||!saved||dirty" @change="upload"></label>
    <div v-if="preview"><p>{{preview.filename}} · 单位 nm · SHA-256 {{preview.sha256}}</p><div v-for="(m,i) in mapping" :key="i" class="quick-card"><h4>量测块 {{i+1}}</h4><pre tabindex="0">{{JSON.stringify(preview.blocks[i].metadata,null,2)}}</pre><p>解析均值 {{importedValue(i)}} nm · 目标运行 {{saved.process_code}}</p><div class="quick-grid two"><label>量测块 {{i+1}} 目标结果<select :aria-label="`量测块 ${i+1} 目标结果`" v-model="m.result_id"><option value="">暂不导入此块</option><option v-for="r in form.results" :key="r.result_id" :value="r.result_id">{{r.alias}}</option></select></label><label>量测块 {{i+1}} 目标阶段<select :aria-label="`量测块 ${i+1} 目标阶段`" v-model="m.field"><option value="thickness_after_nm">刻蚀后</option><option value="thickness_before_nm">刻蚀前</option></select></label></div><p>当前手记：{{oldValue(m)??'未知'}} nm → Excel：{{importedValue(i)}} nm；差值：{{oldValue(m)===null?'—':display(Number(importedValue(i))-Number(oldValue(m)))}} nm</p></div><label class="check-line"><input v-model="confirmed" type="checkbox">我已逐项核对映射、单位和差异，确认覆盖当前值并保留旧修订</label><div class="quick-actions"><button class="primary" :disabled="!canSave||!confirmed" @click="importConfirm">确认补录</button><button :disabled="busy" @click="preview=null">取消上传预览</button></div></div>
   </div>
  </section>
  <section v-if="saved" class="quick-card"><div class="quick-actions"><RouterLink :to="'/processes?process_id='+saved.run_id">查看关联专业执行</RouterLink><button :disabled="busy" @click="versions">查看修订历史</button><button v-if="!saved.archived" :disabled="busy" @click="archiveThis">归档此记录</button><button v-else :disabled="busy" @click="archiveThis">恢复此记录</button><button :disabled="busy" @click="removeThis">删除此记录</button></div><details v-for="v in revisions" :key="v.revision_id"><summary>版本 {{v.version}} · {{v.reason}} · {{v.created_at}}</summary><pre tabindex="0">{{JSON.stringify(v.snapshot,null,2)}}</pre></details></section>
  <footer class="quick-save"><span>{{busy?'保存 / 处理过程中…':dirty?'未保存的修改':saved?'数据库记录已读取':'空白记录尚未入库'}}</span><button :disabled="!canSave" @click="save('draft')">保存草稿</button><button class="primary" :disabled="!canSave" @click="save('recorded')">{{busy?'保存中…':'保存记录'}}</button><button :disabled="!canSave" @click="save('recorded',true)">保存并继续下一段</button></footer>
  </fieldset>
  <QuickProgramEditor ref="structureEditor" v-model="structureOpen" :program="form.program" :sources="sourceNames" @apply="form.program=$event"/>
  <el-dialog :model-value="!!picker" title="选择工艺来源" width="min(680px, 94vw)" @close="picker=''" :close-on-click-modal="false"><div v-if="picker==='template'"><p v-if="!templates.length">暂无已保存模板。请保存记录后在“更多参数与模板”中创建。</p><button v-for="t in templates" :key="t.template_id" class="pick-item" @click="useTemplate(t)">{{t.name}} · 版本 {{t.version}}</button></div><div v-else><p v-if="!history.length">暂无记录。</p><button v-for="r in history" :key="r.run_id" class="pick-item" @click="useHistory(r)">{{r.experiment_date}} · 第 {{r.daily_no}} 次 · {{r.material_name||'未选材料'}} · {{r.note||r.process_code}}</button></div><template #footer><button @click="picker=''">取消</button></template></el-dialog>
 </div>
</template>











