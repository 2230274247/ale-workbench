<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ElMessage} from 'element-plus'
import WorkflowProgress from '../components/WorkflowProgress.vue'
import ProcessGrid from '../components/ProcessGrid.vue'
import SamplePicker from '../components/SamplePicker.vue'
import ExperimentFields from '../components/ExperimentFields.vue'
import QuickBatchCreate from '../components/QuickBatchCreate.vue'
import {suggestedCodes,usedSampleCodes} from '../experiments/sampleCodes'
import {api,ApiError,errorText} from '../api'
import {useAuth} from '../auth'
import {type Row,processFields,blank,payload,useDraftGuard} from '../experiments/model'
import {gridDraft,gridPayload,type GridDraft} from '../experiments/processGrid'
const route=useRoute(),router=useRouter(),auth=useAuth()
const active=ref(0),busy=ref(false),error=ref(''),loaded=ref(false)
const state=ref<Row>({plan:null,process:null,stages:[],measurements:[]})
const plan=computed<Row|null>(()=>state.value.plan),run=computed<Row|null>(()=>state.value.process)
const mode=ref('new'),planChoice=ref<number|null>(null),resumeChoice=ref<number|null>(null)
const plans=ref<Row[]>([]),runs=ref<Row[]>([]),batches=ref<Row[]>([])
const goal=ref(''),title=ref(''),batch=ref<number|null>(null),samples=ref<number[]>([]),sampleCount=ref(1),sampleLabel=ref('')
const processForm=ref<Row>({}),matrix=ref<GridDraft>(gridDraft({})),actual=ref<GridDraft>(gridDraft({}))
const baseline=ref(''),internalNav=ref(false)
// One frozen payload per logical create. A lost response must reuse its original code.
const planIntent=ref<Row|null>(null),processIntent=ref<Row|null>(null)
const sampleDraft=ref<Row[]>([])
const samplePrefix=ref('')
function batchCreated(b:Row){batches.value=[b,...batches.value];batch.value=b.batch_id}
async function previewSamples(){await task(async()=>{
 if(!batch.value)throw Error('请先选择或新建批次')
 const prefix=samplePrefix.value.trim()||batches.value.find(b=>b.batch_id===batch.value)?.batch_code
 if(!prefix)throw Error('请填写样品编号前缀')
 if(!Number.isInteger(sampleCount.value)||sampleCount.value<1||sampleCount.value>50)throw Error('一次可创建 1–50 份样品')
 sampleDraft.value=suggestedCodes(prefix,sampleCount.value,await usedSampleCodes(batch.value,prefix)).map((code,i)=>({sample_code:code,display_label:sampleLabel.value?`${sampleLabel.value}-${i+1}`:null}))
})}
watch([batch,sampleCount,samplePrefix,sampleLabel],()=>{if(!sampleIntent.value)sampleDraft.value=[]})
const sampleIntent=ref<{batchId:number;prefix:string;items:Row[];attempted:boolean;requestKey:string}|null>(null)
const createCode=(prefix:string)=>`${prefix}-${crypto.randomUUID().replaceAll('-','')}`
const pendingIdentity=computed(()=>[!plan.value&&planIntent.value?.plan_code,!run.value&&processIntent.value?.process_code,sampleIntent.value?.prefix].filter(Boolean).join('、'))
const executionFields=processFields.filter(f=>['process_code','started_at','ended_at','log_status'].includes(f.key))
const actualFields=processFields.filter(f=>['r1_temp_c','r2_temp_c','n2_flow_sccm','full_ale_cycles'].includes(f.key))
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value))
const edits=()=>({goal:{goal:goal.value,title:title.value,batch:batch.value},samples:samples.value,
 execution:blank(executionFields,processForm.value),fields:blank(actualFields,processForm.value),matrix:matrix.value,actual:actual.value})
type Section=keyof ReturnType<typeof edits>
const snapshot=()=>JSON.stringify(edits())
const dirty=(key:Section)=>!!baseline.value&&JSON.stringify(edits()[key])!==JSON.stringify(JSON.parse(baseline.value)[key])
function restore(values:ReturnType<typeof edits>,keys:Section[]){
 for(const key of keys){
  if(key==='goal'){goal.value=values.goal.goal;title.value=values.goal.title;batch.value=values.goal.batch}
  else if(key==='samples')samples.value=values.samples
  else if(key==='execution'||key==='fields')Object.assign(processForm.value,values[key])
  else if(key==='matrix')matrix.value=values.matrix
  else actual.value=values.actual
 }
}
const guard=useDraftGuard(()=>loaded.value&&!internalNav.value&&(snapshot()!==baseline.value||!!pendingIdentity.value),()=>busy.value&&!internalNav.value)
const writable=computed(()=>auth.canWrite)
const planOptions=computed(()=>(plan.value?.steps??[]).map((s:Row)=>({id:s.step_id,label:`${s.step_index} · ${s.step_name||s.step_kind}`})))
function hydrate(){
 goal.value=plan.value?.objective??run.value?.notes??'';title.value=plan.value?.title??'';batch.value=run.value?.batch_id??plan.value?.batch_id??null
 mode.value=plan.value?'existing':run.value?'independent':'new';planChoice.value=plan.value?.plan_id??null
 samples.value=[];matrix.value=gridDraft(plan.value??run.value??{},!!plan.value);actual.value=gridDraft(run.value??{})
 processForm.value=blank([...executionFields,...actualFields],run.value??{log_status:'unknown'})
 baseline.value=snapshot();loaded.value=true
}
async function fetchState(saved:Section[]=[],preserve=true){const selection={mode:mode.value,choice:planChoice.value};const previous=clone(edits());const keep=preserve&&loaded.value?(Object.keys(previous) as Section[]).filter(key=>dirty(key)&&!saved.includes(key)):[];const query:Row={};if(route.query.process_id)query.process_id=route.query.process_id;if(route.query.plan_id)query.plan_id=route.query.plan_id
 state.value=(await api<Row>('/workflow/state',{query})).data;hydrate();restore(previous,keep);if(preserve&&!plan.value&&!run.value){mode.value=selection.mode;planChoice.value=selection.choice}
}
async function lookups(){const results=await Promise.all(['plans','processes','batches'].map(async path=>{const rows:Row[]=[];for(let page=1;;page++){const r=await api<Row[]>(`/${path}`,{query:{page,size:200}});rows.push(...r.data);if(!r.meta?.has_next)break}return rows}));[plans.value,runs.value,batches.value]=results as [Row[],Row[],Row[]]}
async function task(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){error.value=errorText(e);if(loaded.value)try{await fetchState()}catch{}}finally{busy.value=false}}
async function openSaved(query:Row){if(!await guard.discard())return;planIntent.value=null;processIntent.value=null;sampleIntent.value=null;await router.replace({path:'/experiments/new',query});await task(()=>fetchState([],false))}
async function reload(){if(!await guard.discard())return;await task(()=>fetchState([],false))}
async function adopt(p:Row|null,r:Row|null){state.value={...state.value,plan:p,process:r};internalNav.value=true;try{await router.replace({path:'/experiments/new',query:{...(r?{process_id:r.process_id}:p?{plan_id:p.plan_id}:{}),...(route.query.stage!==undefined?{stage:String(active.value)}:{})}})}finally{internalNav.value=false}await fetchState();await lookups()}
async function createRecord(kind:'plans'|'processes',body:Row){
 const intent=kind==='plans'?planIntent:processIntent
 if(!intent.value)intent.value={...body,[kind==='plans'?'plan_code':'process_code']:kind==='plans'?createCode('PL'):(processForm.value.process_code?.trim()||`EX-${new Date().toISOString().slice(0,10).replaceAll('-','')}-${crypto.randomUUID().slice(0,6)}`)}
 try{return (await api<Row>(`/workflow/${kind}`,{method:'POST',body:intent.value})).data}
 catch(e){throw Error(`${errorText(e)} 创建结果尚未确认；重试将使用同一编码 ${intent.value[kind==='plans'?'plan_code':'process_code']}。离开页面前请记下编码，可在计划 / 执行列表搜索核对。`)}
}
async function ensureRecord(){
 if(plan.value||run.value)return
 if(planIntent.value){await adopt(await createRecord('plans',{}),null);return}
 if(processIntent.value){await adopt(null,await createRecord('processes',{}));return}
 if(mode.value==='existing'){if(!planChoice.value)throw Error('请选择已有计划');const p=(await api<Row>(`/plans/${planChoice.value}`)).data;await adopt(p,null);return}
 if(mode.value==='independent'){await adopt(null,await createRecord('processes',{process_mode:'other',batch_id:batch.value,notes:goal.value||null}));return}
 if(!title.value.trim())throw Error('请填写计划标题')
 await adopt(await createRecord('plans',{title:title.value.trim(),objective:goal.value||null,batch_id:batch.value}),null)
}
async function ensureRun(){await ensureRecord();if(run.value)return;await adopt(plan.value,await createRecord('processes',{plan_id:plan.value!.plan_id,process_mode:'other'}))}
async function persistGoal(){if(!plan.value&&!run.value){await ensureRecord();if(!dirty('goal'))return}const p=plan.value;const r=run.value;await api(p?`/plans/${p.plan_id}`:`/processes/${r!.process_id}`,{method:'PATCH',body:p?{title:title.value.trim()||p.title,objective:goal.value||null,expected_row_version:p.row_version}:{notes:goal.value||null,expected_row_version:r!.row_version}});await fetchState(['goal']);ElMessage.success('研究目标已保存')}
async function saveGoal(){await task(persistGoal)}
async function persistMatrix(){
 const draft:GridDraft=JSON.parse(JSON.stringify(matrix.value))
 try{
  // Parent adoption hydrates saved state; always restore the submitted edit until PUT succeeds.
  try{await ensureRecord()}finally{matrix.value=draft}
  const p=plan.value??run.value!
  await api(`/${plan.value?'plans':'processes'}/${plan.value?p.plan_id:p.process_id}/process-grid`,{method:'PUT',body:{...gridPayload(draft),expected_row_version:p.row_version}})
  await fetchState(['matrix']);ElMessage.success('工艺矩阵已保存')
 }catch(e){matrix.value=draft;try{await fetchState()}catch{}throw Error(`${errorText(e)} 工艺矩阵尚未确认保存，已保留全部输入和未保存状态；请点击“保存工艺矩阵”重试${plan.value||run.value?'，将继续使用当前草稿，不会新建计划或执行':''}。`)}
}
async function saveMatrix(){await task(persistMatrix)}
async function persistSamples(){const ids=[...new Set(samples.value)];if(!ids.length)throw Error('请选择至少一份样品');await ensureRun();await api(`/processes/${run.value!.process_id}/samples/batch`,{method:'POST',body:{sample_ids:ids}});await fetchState(['samples']);ElMessage.success('所选样品已绑定')}
async function bindSamples(){await task(persistSamples)}
async function createSamples(){await task(async()=>{
 if(!sampleIntent.value){
  if(!batch.value)throw Error('创建样品前请选择批次')
  const count=sampleCount.value;if(!Number.isInteger(count)||count<1||count>50)throw Error('一次可创建 1–50 份样品')
  if(!sampleDraft.value.length)throw Error('请先预览并核对样品编号')
  const items=sampleDraft.value.map(item=>({...item,sample_code:item.sample_code.trim()}))
  if(items.some(item=>!item.sample_code)||new Set(items.map(item=>item.sample_code.toLowerCase())).size!==items.length)throw Error('样品编号不能为空或重复')
  const prefix=samplePrefix.value.trim()||batches.value.find(b=>b.batch_id===batch.value)?.batch_code||''
  sampleIntent.value={batchId:batch.value,prefix,items,attempted:false,requestKey:crypto.randomUUID()}
 }
 const intent=sampleIntent.value
 try{
  await ensureRun()
  let created:Row[]
  // The batch lock and audit receipt return this exact creation intent after
  // a lost response; matching a human code alone cannot prove ownership of it.
  intent.attempted=true
  const r=await api<Row>(`/batches/${intent.batchId}/samples/batch`,{method:'POST',body:{items:intent.items,request_key:intent.requestKey}})
  const rows=r.data.created
  if(!Array.isArray(rows)||rows.length!==intent.items.length)throw Error('样品创建响应不完整，请再次核对')
  created=rows
  samples.value=created.map((s:Row)=>s.sample_id);sampleIntent.value=null;sampleDraft.value=[]

 }catch(e){if(e instanceof ApiError&&[409,422].includes(e.status)){sampleIntent.value=null;throw Error(`${errorText(e)} 创建被拒绝，未重复编号；请保留输入修改编号或重新预览。`)}throw Error(`${errorText(e)} 样品任务 ${intent.prefix} 已保留；点击“核对上次样品创建结果”会沿用原请求回执，恢复同一次创建，不会重复建样。也可在样品列表搜索此编码前缀核对。`)}
 await persistSamples()
 ElMessage.success('样品已创建并绑定本次执行')
})}
async function persistExecution(){const body=payload(executionFields,processForm.value);await ensureRun();await api(`/processes/${run.value!.process_id}`,{method:'PATCH',body:{...body,expected_row_version:run.value!.row_version}});await fetchState(['execution']);ElMessage.success('执行记录已保存')}
async function saveExecution(){await task(persistExecution)}
async function persistActual(){const draft=JSON.parse(JSON.stringify(actual.value));const body=payload(actualFields,processForm.value);await ensureRun();const p=(await api<Row>(`/processes/${run.value!.process_id}`,{method:'PATCH',body:{...body,expected_row_version:run.value!.row_version}})).data;state.value.process=p;await api(`/processes/${p.process_id}/process-grid`,{method:'PUT',body:{...gridPayload(draft),expected_row_version:p.row_version}});await fetchState(['fields','actual']);ElMessage.success('实际参数与矩阵已保存')}
async function saveActual(){await task(persistActual)}
async function finish(){await task(async()=>{
 let stage=0
 try{
  if(!writable.value){if(!plan.value&&!run.value)throw Error('当前账户只读，请选择已有记录')}
  else{
   await ensureRecord()
   if(dirty('goal'))await persistGoal()
   stage=2;if(dirty('matrix'))await persistMatrix()
   stage=3;if(sampleIntent.value)throw Error('请先在参与样品阶段核对上次样品创建结果，再绑定所选样品')
   if(samples.value.length)await persistSamples()
   stage=4;if(dirty('execution'))await persistExecution()
   stage=5;if(dirty('fields')||dirty('actual'))await persistActual()
   await fetchState()
  }
  const target=run.value?{path:'/processes',query:{process_id:run.value.process_id}}:{path:'/plans',query:{plan_id:plan.value!.plan_id}}
  internalNav.value=true
  try{await router.push(target)}finally{internalNav.value=false}
 }catch(e){
  active.value=stage
  try{await fetchState()}catch{}
  throw Error(`${errorText(e)} 本次整理尚未结束，输入已保留；请修复当前阶段后重试。`)
 }
})}
// A route stage selects a view only; it never changes persisted progress facts.
function routeStage(value:unknown){return typeof value==='string'&&/^[0-6]$/.test(value)?Number(value):0}
function selectStage(i:number){if(Number.isInteger(i)&&i>=0&&i<=6)active.value=i}
watch(()=>route.query.stage,value=>{active.value=routeStage(value)},{immediate:true})
// Stage-only navigation must not rehydrate (and discard) unsaved field edits.
watch(()=>[route.query.plan_id,route.query.process_id],(ids,previous)=>{
 if(!internalNav.value&&ids.some((id,i)=>id!==previous[i])){planIntent.value=null;processIntent.value=null;sampleIntent.value=null;void task(()=>fetchState([],false))}
})
onMounted(()=>{void task(async()=>{await Promise.all([fetchState(),lookups()])})})
</script>
<template><div class="experiment-wizard" v-loading="busy">
<header class="wizard-heading"><div><h1>开始新实验</h1><p>从研究目标到测量结果，随时保存、继续记录。</p></div><el-button @click="reload">刷新已保存记录</el-button></header>
<section class="panel resume-panel"><label>继续已保存实验</label><el-select v-model="resumeChoice" filterable clearable aria-label="继续已保存执行" placeholder="选择执行草稿或历史执行"><el-option v-for="r in runs" :key="r.process_id" :value="r.process_id" :label="r.process_code" /></el-select><el-button :disabled="!resumeChoice||busy" @click="openSaved({process_id:resumeChoice})">继续执行</el-button><el-button :disabled="busy" @click="openSaved({})">开始另一实验</el-button></section>
<WorkflowProgress :active="active" :stages="state.stages" :disabled="busy" @select="selectStage" />
<el-alert v-if="error" :title="error" type="error" :closable="false" show-icon /><el-alert v-if="!writable" title="当前账户只读，可查看已有实验与保存状态。" type="info" :closable="false" />
<el-alert v-if="pendingIdentity" :title="`待确认创建编码：${pendingIdentity}。重试沿用原编码；离开页面前请记下编码，在计划 / 执行 / 样品列表搜索核对。`" type="warning" :closable="false" show-icon /><div class="saved-strip"><span v-if="plan">实验草稿已创建 · 计划已保存 {{ plan.plan_code }} · 版本 {{ plan.row_version }}</span><span v-if="run">实际执行记录已保存 {{ run.process_code }} · 版本 {{ run.row_version }}</span><router-link v-if="plan" :to="{path:'/plans',query:{plan_id:plan.plan_id}}">查看计划详情</router-link><router-link v-if="run" :to="{path:'/processes',query:{process_id:run.process_id}}">查看执行详情与历史</router-link><span v-if="!plan&&!run">尚未保存实验记录</span><span v-if="loaded&&snapshot()!==baseline">有未保存修改</span></div>
<p v-if="plan||run" class="saved-status">{{ state.measurements.length?'已有正式测量':'测量尚未导入' }} · 实验记录待完善；结束本次整理不会将实验标为完成。</p>
<section class="panel wizard-stage">
<template v-if="active===0"><h2>研究目标</h2><p>目标可留空。先选择计划方式并保存，即可关闭页面后继续。</p><el-form label-position="top"><el-form-item label="研究目标"><el-input v-model="goal" aria-label="研究目标" type="textarea" :rows="4" maxlength="20000" :disabled="!writable" /></el-form-item><el-form-item v-if="!run||plan" label="计划标题"><el-input v-model="title" aria-label="计划标题" maxlength="255" :disabled="!writable" /></el-form-item></el-form><el-button type="primary" :disabled="!writable" @click="saveGoal">保存目标与草稿</el-button></template>
<template v-else-if="active===1"><h2>选择计划</h2><template v-if="!plan&&!run"><el-radio-group v-model="mode" :disabled="!writable"><el-radio-button value="new">新建计划</el-radio-button><el-radio-button value="existing">使用已有计划</el-radio-button><el-radio-button value="independent">独立执行</el-radio-button></el-radio-group><el-form label-position="top"><el-form-item v-if="mode==='new'" label="计划标题"><el-input v-model="title" aria-label="计划标题" maxlength="255" /></el-form-item><el-form-item v-if="mode==='existing'" label="已有计划"><el-select v-model="planChoice" filterable aria-label="已有计划"><el-option v-for="p in plans" :key="p.plan_id" :value="p.plan_id" :label="`${p.plan_code} · ${p.title}`" /></el-select></el-form-item><el-form-item v-if="mode!=='existing'" label="批次（可选）"><el-select v-model="batch" clearable filterable aria-label="实验批次"><el-option v-for="b in batches" :key="b.batch_id" :value="b.batch_id" :label="b.batch_code" /></el-select></el-form-item></el-form><el-button type="primary" :disabled="!writable" @click="task(ensureRecord)">保存并建立草稿</el-button></template><template v-else><p>{{ plan?plan.title:'独立执行，无关联计划' }}</p><p>已保存的计划和执行均可继续；同一计划可创建多次执行。</p><el-button v-if="plan" :disabled="!writable" @click="openSaved({plan_id:plan.plan_id})">从此计划再建一次执行</el-button><p v-for="r in plan?.processes" :key="r.process_id"><el-button link @click="openSaved({process_id:r.process_id})">继续 {{ r.process_code }}</el-button></p></template></template>
<template v-else-if="active===2"><h2>{{ plan?'计划工艺矩阵':'独立执行工艺矩阵' }}</h2><p>步骤、分组、重复次数和参数一起保存。没有工艺步骤时可以跳过。</p><ProcessGrid v-model="matrix" :planned="!!plan||(!run&&mode!=='independent')" :readonly="!writable" :disabled="busy" /><el-button type="primary" :disabled="!writable" @click="saveMatrix">保存工艺矩阵</el-button></template>
<template v-else-if="active===3"><h2>参与样品</h2><p>一次执行支持多份样品；绑定后，装载和卸载仍在样品流转历史记录。</p><SamplePicker v-model="samples" :batch-id="batch" :exclude-ids="(run?.samples??[]).map((s:Row)=>s.sample_id)" :disabled="!writable||busy" /><el-button type="primary" :disabled="!writable||!samples.length" @click="bindSamples">绑定所选样品</el-button><div class="sample-create"><h3>新建 / 批量创建样品</h3><el-form label-position="top"><el-form-item label="样品所属批次"><el-select v-model="batch" :disabled="!!run?.batch_id||!!plan?.batch_id||!writable||!!sampleIntent" aria-label="样品所属批次" filterable><el-option v-for="b in batches" :key="b.batch_id" :value="b.batch_id" :label="b.batch_code" /></el-select></el-form-item><QuickBatchCreate v-if="writable&&!run?.batch_id&&!plan?.batch_id&&!sampleIntent" @created="batchCreated"/><p v-if="!batches.length" class="field-hint">暂无批次，请先在此新建批次，样品输入会保留。</p><el-form-item label="样品编号前缀（默认批次编号）"><el-input v-model="samplePrefix" aria-label="样品编号前缀" maxlength="55" :disabled="!writable||!!sampleIntent"/></el-form-item><el-form-item label="样品数量"><el-input-number v-model="sampleCount" :min="1" :max="50" :disabled="!writable||!!sampleIntent" aria-label="样品数量" /></el-form-item><el-form-item label="显示编号前缀（可选）"><el-input v-model="sampleLabel" maxlength="120" :disabled="!writable||!!sampleIntent" /></el-form-item></el-form><el-button :disabled="!writable||!!sampleIntent" @click="previewSamples">预览可用编号</el-button><el-table v-if="sampleDraft.length" :data="sampleDraft" data-testid="wizard-sample-preview" max-height="340"><el-table-column label="样品编号（可逐行编辑）"><template #default="{row,$index}"><el-input v-model="row.sample_code" :aria-label="`样品编号 ${$index+1}`" maxlength="64" :disabled="!!sampleIntent"/></template></el-table-column></el-table><el-button :disabled="!writable||(!sampleDraft.length&&!sampleIntent)" @click="createSamples">{{ sampleIntent?.attempted?'核对上次样品创建结果':'创建并关联本次执行' }}</el-button></div><p v-for="s in run?.samples" :key="s.sample_id">已绑定 {{ s.sample?.sample_code }} <router-link :to="{path:'/sample-history',query:{sample_id:s.sample_id,process_id:run?.process_id}}">装卸与历史</router-link></p></template>
<template v-else-if="active===4"><h2>执行记录</h2><p>保存执行草稿不代表已发生执行。填写真实开始 / 结束时间后，节点才显示已保存。</p><el-form label-position="top"><ExperimentFields :fields="executionFields" :model="processForm" :disabled="!writable||busy" /></el-form><el-button type="primary" :disabled="!writable" @click="saveExecution">保存执行记录</el-button></template>
<template v-else-if="active===5"><h2>实际参数</h2><p>计划执行只继承步骤结构和单位。所有实际值和重复次数独立填写。</p><el-button v-if="!run" :disabled="!writable" @click="task(ensureRun)">建立执行并载入空值步骤</el-button><template v-else><el-form label-position="top"><ExperimentFields :fields="actualFields" :model="processForm" :disabled="!writable||busy" /></el-form><ProcessGrid v-model="actual" :planned="false" :plan-options="planOptions" :readonly="!writable" :disabled="busy" /><el-button type="primary" :disabled="!writable" @click="saveActual">保存实际参数</el-button></template></template>
<template v-else><h2>测量与分析</h2><p>测量节点只依据本次执行及绑定样品的正式有效测量记录。打开页面不会改变状态。</p><div class="measurement-actions"><router-link :to="{path:'/imports',query:{process_id:run?.process_id}}">导入测量数据</router-link><router-link :to="{path:'/measurements',query:{process_id:run?.process_id}}">查看正式测量</router-link><router-link :to="{path:'/analysis',query:{process_id:run?.process_id}}">科研分析与配对</router-link></div><p v-if="!state.measurements.length">尚无本次执行的有效测量，可稍后继续。</p><p v-for="m in state.measurements" :key="m.measurement_id">{{ m.measurement_code }} · 样品 #{{ m.sample_id }} · {{ m.stage }}</p></template>
</section><footer class="wizard-footer"><el-button :disabled="active===0||busy" @click="selectStage(active-1)">上一阶段</el-button><span>状态来自已保存数据；任意节点均可直接打开。</span><el-button v-if="active<6" :disabled="busy" @click="selectStage(active+1)">下一阶段 / 跳过</el-button><el-button v-else type="primary" :disabled="busy||(!writable&&!plan&&!run)" :loading="busy" @click="finish">保存并查看实验</el-button></footer>
</div></template>
<style scoped>
.wizard-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.wizard-heading h1{margin:0;font-size:26px}.wizard-heading p,.wizard-stage>p{color:var(--text-secondary,#61736e)}.resume-panel{display:flex;align-items:center;gap:12px;padding:14px 18px}.resume-panel .el-select{width:300px}.saved-strip{display:flex;flex-wrap:wrap;gap:20px;font-size:12px;color:#526b5c;margin:14px 0}.wizard-stage{padding:24px;min-height:340px}.wizard-stage h2{font-size:20px;margin:0 0 12px}.wizard-stage .el-form{max-width:820px;margin:20px 0}.wizard-stage>.el-button{margin-top:18px}.sample-create{margin:24px 0;padding-top:18px;border-top:1px solid var(--line)}.measurement-actions{display:flex;flex-wrap:wrap;gap:24px;margin:24px 0}.wizard-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:20px}.wizard-footer span{font-size:12px;color:#61736e}@media(max-width:700px){.wizard-heading,.resume-panel{align-items:stretch;flex-direction:column}.resume-panel .el-select{width:100%}.wizard-stage{padding:16px}.wizard-footer span{display:none}}
</style>
