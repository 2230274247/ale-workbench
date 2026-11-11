<script setup lang="ts">
// 统一导入中心：上传 → 审查建议 → 确认保存；结果就地显示。
// 技术字段（parser / original_only / needs_confirmation / warnings code）一律映射为中文文案；
// 功能不削弱：仍可修改样品 / 执行 / 阶段 / 单位 / 重复原因，且只提交勾选项。
import {ref,reactive,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {useRoute,useRouter,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router'
import {ElMessageBox} from 'element-plus'
import PageHeading from '../components/PageHeading.vue'
import ImportAnalysis from '../components/ImportAnalysis.vue'
import StatePanel from '../components/StatePanel.vue'
import {api,multipart,errorText,ApiError} from '../api'
import {useAuth} from '../auth'
import {stages,json,positiveId} from '../measurements/model'
import {blankChoice,canImport} from '../imports/model'
import type {Job,Item,Choice} from '../imports/model'
const auth=useAuth(),route=useRoute(),router=useRouter()
const jobs=ref<any[]>([]),total=ref(0),page=ref(1),job=ref<Job|null>(null),files=ref<File[]>([]),busy=ref(false),loading=ref(false),error=ref(''),listError=ref(''),dirty=ref(false),result=ref<any>(null),replay=ref<any>(null),choices=reactive<Record<number,Choice>>({}),lookup=reactive<Record<number,any>>({}),lookupBusy=ref(false)
const step=ref(1),expanded=reactive<Record<number,boolean>>({}),failure=ref<{reason:string;hint:string}|null>(null)
// 反馈就地展示：错误 / 失败 / 成功结果紧贴当前步骤的提交区，并在出现时滚动到可见区域，
// 避免用户滚动到页面顶部才能看到结果（第四轮第 7 项交互修复）。
const feedbackEl=ref<HTMLElement|null>(null),resultEl=ref<HTMLElement|null>(null)
async function focusFeedback(){await nextTick();const el=feedbackEl.value??resultEl.value;if(el)el.scrollIntoView({block:'center',behavior:'smooth'})}
let internalNavigation=false
const owner=auth.user?.user_id, ownerEpoch=auth.sessionEpoch
const currentSession=()=>!!auth.user && auth.sessionEpoch===ownerEpoch
const key=(id:number)=>`ale:imports:${owner}:${id}`
const selected=computed(()=>job.value?.items.filter(i=>i.status==='pending'&&choices[i.item_id]?.selected) || [])
const blocked=computed(()=>busy.value || loading.value || !!replay.value || !auth.canWrite)
const readinessAttempted=ref(false)
type ReadinessIssue={item:Item;field:string;message:string}
// 仅校验用户本次勾选的文件，不从文件名推定科学阶段或序号。
const readinessIssues=computed<ReadinessIssue[]>(()=>selected.value.flatMap(item=>{
  const c=choices[item.item_id],issues:ReadinessIssue[]=[]
  const add=(field:string,message:string)=>issues.push({item,field,message:`${item.filename}：${message}`})
  if(!c.action)add('action','请选择处理动作。')
  if(c.action!=='import')return issues
  if(!c.sample_id)add('sample','请选择样品，可按样品编码、名称或批次搜索。')
  else if(String(lookup[item.item_id]?.sample?.sample_id)!==c.sample_id)add('sample','样品关联仍在加载或加载失败，请等待加载完成或重新选择样品。')
  if(!c.stage)add('stage','请选择测量阶段；请依据实际测量情况人工确认，系统不会按文件名推定。')
  if(c.stage_seq!==''&&(!/^\d+$/.test(c.stage_seq)||Number(c.stage_seq)>4294967295))add('sequence','阶段序号须为 0–4294967295 整数。')
  return issues
}))
const visibleReadinessIssues=computed(()=>readinessAttempted.value?readinessIssues.value:[])
async function focusReadiness(issue:ReadinessIssue){
  await nextTick()
  const card=document.querySelector<HTMLElement>(`[data-testid="import-item-${issue.item.item_id}"]`)
  const field=card?.querySelector<HTMLElement>(`[data-readiness-field="${issue.field}"]`)
  const control=field?.matches('input')?field:field?.querySelector<HTMLElement>('[role="combobox"],input,textarea,button')
  control?.focus({preventScroll:true})
  ;(field??card)?.scrollIntoView({block:'center',behavior:'instant'})
}

// 中文文案映射：界面不暴露解析器、状态码与警告 code。
const statusText:Record<string,string>={parsed:'识别完成',needs_confirmation:'需要人工确认',original_only:'仅保留原件',rejected:'已拒绝',draft:'草稿（仍有待核对）',completed:'已完成'}
const itemStatusText:Record<string,string>={pending:'待核对（暂存）',imported:'已导入',original_only:'仅保留原件',skipped:'已跳过'}
const actionText:Record<string,string>={import:'导入正式测量',original_only:'仅保存原件',skip:'跳过'}
const warningText:Record<string,string>={
  aoi_unit_unconfirmed:'AOI 角度单位未确认：原始值保留，角度暂不写入',
  lbh_unit_unconfirmed:'LBH 语义与单位待确认：原始值保留',
  unrecognised_sheet:'存在未识别的表：仅在原件中保留',
  negative_value:'存在负值：已保留待复核',
  zip_batch_unsupported:'ZIP 批量预览不支持：请保留原件',
  no_verified_spectrum:'未发现可信光谱数据',
  xml_schema_unverified:'XML 结构未经验证：仅保留原件',
  ole_format_unverified:'旧版 XLS 专有格式不支持：仅保留原件',
  unsupported_content:'没有可用的解析器：仅保留原件',
  duplicate_headers:'存在重复表头：需人工确认',
  missing_or_unknown_unit_column:'缺少或未知的单位列：需人工确认',
  invalid_model_parameter:'模型参数无效：该点不参与统计',
  invalid_numeric:'数值无效：原始值保留',
  invalid_unsigned_integer:'需要无符号 32 位整数',
  db_decimal_confirmation_required:'数据库精度无法精确表示：未做四舍五入',
  duplicate_point_no:'点号重复：全部保留待确认',
  no_points:'没有测量行',
  untrusted_formula:'公式结果不可信：原始值保留但不参与计算',
  office_lock_file:'Office 临时锁文件被拒绝',
  file_size_limit:'文件超过预览大小限制',
  expanded_size_limit:'解压后超过预览大小限制',
  parser_timeout:'解析超时：仅保留原件',
  parser_worker_failed:'解析进程异常：仅保留原件',
  invalid_file:'文件无法解析：仅保留原件',
}
const text=(map:Record<string,string>,value:unknown,fallback:string)=>map[String(value)] ?? (value?`${fallback}（${value}）`:fallback)
const issues=(list:any[]|undefined)=>Array.from(new Set((list??[]).map(issue=>text(warningText,issue?.code??issue,'需要人工确认'))))
const itemBlocking=(item:Item)=>issues([...(item.parse_result?.blocking_issues??[]),...(item.parse_result?.blocks??[]).flatMap((b:any)=>b.blocking_issues??[])])
const itemWarnings=(item:Item)=>issues([...(item.parse_result?.warnings??[]),...(item.parse_result?.blocks??[]).flatMap((b:any)=>b.warnings??[])])
function stageHint(item:Item){const n=item.filename;const before=/initial|before|初始|前测/i.test(n),after=/after|cycles|后测|处理后/i.test(n);return before===after?'':before?'initial':'after_ale'}
function acceptStage(item:Item){const hint=stageHint(item);if(hint){choices[item.item_id].stage=hint;associationChanged(choices[item.item_id])}}
const suggestions=(item:Item):any[]=>item.suggestions?.samples??[]
function cardNotes(item:Item){
  const notes:string[]=[]
  if(item.parse_result?.status==='needs_confirmation')notes.push('识别结果需要人工确认')
  const blocking=itemBlocking(item)
  if(blocking.length)notes.push(`阻断项：${blocking.join('；')}`)
  if(!canImport(item))return notes;
  if(!suggestions(item).length)notes.push('未找到文件名候选，请按样品名称、编码或批次搜索选择')
  else if(suggestions(item).length>1)notes.push(`有 ${suggestions(item).length} 个候选样品，存在歧义，请人工确认`)
  else if(!suggestions(item)[0]?.batch_hint_match)notes.push('候选样品与文件名批次提示不一致，请核对')
  return notes
}
function persist(){ if(!currentSession()||!job.value)return;try{ localStorage.setItem(key(job.value.job_id),JSON.stringify({choices,replay:replay.value})) }catch{error.value='浏览器无法保存本地核对表单，请勿关闭页面。任务仍可从服务器恢复。'} }
function edited(){dirty.value=true;persist()}
watch(choices,()=>{if(job.value)persist()},{deep:true})
async function list(){listError.value='';try{const e=await api<any[]>('/imports',{query:{page:page.value,size:10}});jobs.value=e.data;total.value=e.meta?.total||0}catch(e){listError.value=errorText(e)}}
// options.step：读取任务后的落点步骤。提交成功后的重读必须保持在第 4 步「结果」，
// 否则结果页只在极短时间内可见，用户会被退回第 2 步而看不到成功/失败明细（第四轮第 7 项）。
async function load(id:number,options?:{step?:number}){readinessAttempted.value=false;loading.value=true;error.value='';failure.value=null;try{const next=(await api<Job>(`/imports/${id}`)).data;job.value=next;Object.keys(choices).forEach(k=>delete choices[Number(k)]);Object.keys(lookup).forEach(k=>delete lookup[Number(k)]);Object.keys(expanded).forEach(k=>delete expanded[Number(k)]);let saved:any;try{saved=JSON.parse(localStorage.getItem(key(id))||'null')}catch{};next.items.forEach(i=>choices[i.item_id]=i.status==='pending'?{...blankChoice(),selected:true,action:canImport(i)?'import':'original_only',...saved?.choices?.[i.item_id]}:blankChoice());replay.value=saved?.replay||null;dirty.value=false;autofill();next.items.filter(i=>i.status==='pending'&&choices[i.item_id].sample_id).forEach(i=>void verify(i));step.value=options?.step??2}catch(e){error.value=errorText(e)}finally{loading.value=false}}
// 唯一自动候选自动填：只有一个候选样品（且该候选只有一次执行）时预填，避免手填数据库 ID 导致 404。
function autofill(){for(const item of job.value?.items??[]){
 if(item.status!=='pending'||!canImport(item))continue
 const c=choices[item.item_id],list=suggestions(item)
 if(!c.sample_id){
  if(positiveId(route.query.sample_id,'sample_id'))c.sample_id=String(route.query.sample_id)
  else if(list.length===1&&list[0].evidence==='exact_code_or_label')c.sample_id=String(list[0].sample_id)
 }
 if(!c.process_id&&route.query.process_id)c.process_id=String(route.query.process_id)
 // A unique filename candidate is still a suggestion; submission is the explicit approval.
}}
async function open(id:number){if(busy.value)return;if(dirty.value && !await leave())return;dirty.value=false;await router.replace({query:{...route.query,job:id}});if(job.value?.job_id!==id)await load(id)}
function pick(e:Event){files.value=Array.from((e.target as HTMLInputElement).files||[]);dirty.value=!!files.value.length}
async function upload(){if(blocked.value)return;error.value='';if(!files.value.length||files.value.length>20){error.value='请选择 1–20 个文件。';return}if(files.value.some(f=>f.size>20*1024*1024)||files.value.reduce((n,f)=>n+f.size,0)>100*1024*1024){error.value='单文件最多 20 MiB，总计最多 100 MiB。';return}busy.value=true;try{const form=new FormData();files.value.forEach(f=>form.append('files[]',f,f.name));const e=await multipart<Job>('/imports/preview',form);files.value=[];dirty.value=false;internalNavigation=true;await router.replace({query:{...route.query,job:e.data.job_id}});internalNavigation=false;await load(e.data.job_id);await list()}catch(e){error.value=errorText(e)+' 上传响应不确定时，请刷新任务列表查找刚建立的任务。'}finally{busy.value=false}}
function associationChanged(c:Choice){c.confirm_associations=false;edited()}
function chooseAction(item:Item,value:Choice['action']){const c=choices[item.item_id];c.action=value;if(value==='original_only'){c.sample_id='';c.process_id='';c.pair_measurement_id='';delete lookup[item.item_id];}associationChanged(c)}
const sampleOptions=ref<any[]>([]),sampleSearchBusy=ref(false)
let sampleSearchVersion=0
async function searchSamples(keyword=''){
  const version=++sampleSearchVersion;sampleSearchBusy.value=true
  try{const out=await api<any[]>('/imports/options/samples',{query:{keyword,size:100}});if(version===sampleSearchVersion)sampleOptions.value=out.data}
  catch(e){if(version===sampleSearchVersion)error.value=errorText(e)}finally{if(version===sampleSearchVersion)sampleSearchBusy.value=false}
}
async function verify(i:Item){
  const c=choices[i.item_id],sid=c.sample_id
  if(!sid){delete lookup[i.item_id];return}
  lookupBusy.value=true
  try{const out=(await api<any>(`/imports/options/samples/${sid}`)).data;if(c.sample_id!==sid)return;if(job.value?.items.some(item=>item.item_id===i.item_id)&&choices[i.item_id]===c){lookup[i.item_id]=out;if(c.process_id&&!out.processes.some((p:any)=>String(p.process_id)===c.process_id))c.process_id=''}}
  catch(e){if(c.sample_id===sid){delete lookup[i.item_id];error.value=errorText(e)}}finally{lookupBusy.value=false}
}
function sampleChanged(i:Item){const c=choices[i.item_id];c.process_id=route.query.process_id?String(route.query.process_id):'';c.pair_measurement_id='';delete lookup[i.item_id];associationChanged(c);void verify(i)}
function useCandidate(i:Item,s:any){const c=choices[i.item_id];c.sample_id=String(s.sample_id);sampleChanged(i)}
const sampleLabel=(s:any)=>`${s.sample_code}${s.display_label?' · '+s.display_label:''} · ${s.batch_code||'所选批次'}`
const associationLabel=(i:Item)=>lookup[i.item_id]?.sample?.sample_code||suggestions(i).find((s:any)=>String(s.sample_id)===choices[i.item_id].sample_id)?.sample_code||'未选择'
const processLabel=(i:Item)=>lookup[i.item_id]?.processes?.find((p:any)=>String(p.process_id)===choices[i.item_id].process_id)?.process_code||'未关联执行'
async function removeJob(id:number,version:number){
  if(blocked.value)return
  try{await ElMessageBox.confirm('删除此暂存任务及无引用临时文件？已生成正式测量或归档原件的任务不能删除。','删除暂存任务',{confirmButtonText:'删除任务',cancelButtonText:'保留',type:'warning'})}catch{return}
  busy.value=true;error.value=''
  try{await api(`/imports/${id}`,{method:'DELETE',query:{expected_row_version:version}});localStorage.removeItem(key(id));if(job.value?.job_id===id){job.value=null;dirty.value=false;result.value=null;replay.value=null;step.value=1;internalNavigation=true;await router.replace({query:{...route.query,job:undefined}});internalNavigation=false}await list()}
  catch(e){error.value=errorText(e);void focusFeedback()}finally{busy.value=false}
}
function body(){return {expected_row_version:job.value!.row_version,items:selected.value.map(i=>{const c=choices[i.item_id];if(!c.action)throw Error(`${i.filename}：请选择处理动作。`);const out:any={item_id:i.item_id,action:c.action};if(c.action==='skip')return out;if(c.action==='original_only'){if(c.notes.trim())out.notes=c.notes.trim();return out;}for(const k of ['sample_id','process_id','optical_model_id'] as const){const v=positiveId(c[k],k);if(v)out[k]=v}if(c.pair_measurement_id.startsWith('item:'))out.pair_item_id=positiveId(c.pair_measurement_id.slice(5),'前测文件');else if(c.pair_measurement_id)out.pair_measurement_id=positiveId(c.pair_measurement_id,'前测配对');if(c.action==='import'){if(!canImport(i))throw Error(`${i.filename} 无可导入测点或存在阻断。`);if(!out.sample_id||!c.stage)throw Error(`${i.filename}：请选择样品与测量阶段。`);if(c.stage_seq!==''&&(!/^\d+$/.test(c.stage_seq)||Number(c.stage_seq)>4294967295))throw Error('阶段序号须为 0–4294967295 整数。');out.stage=c.stage;if(c.measured_at)out.measured_at=new Date(c.measured_at).toISOString();if(c.stage_seq!=='')out.stage_seq=Number(c.stage_seq);out.confirm_units=true;if(c.measurement_code.trim())out.measurement_code=c.measurement_code.trim();if(c.stage==='initial'&&(out.pair_measurement_id||out.pair_item_id))throw Error('初始测量不能选择前测配对。')}if(out.sample_id){if(String(lookup[i.item_id]?.sample?.sample_id)!==c.sample_id)throw Error(`${i.filename}：样品关联仍在加载或加载失败，请重新选择样品。`)}out.confirm_associations=true;out.confirm_duplicate=c.confirm_duplicate;if(c.confirm_duplicate){if(!c.duplicate_reason.trim())throw Error('确认重复时须填写原因。');out.duplicate_reason=c.duplicate_reason.trim()}if(c.notes.trim())out.notes=c.notes.trim();return out})}}
function failureHint(status:number){
  if(status===409)return '任务版本或内容状态已变化：请返回第 2 步重新读取任务核对；若为重复内容，请勾选「允许重复导入」并填写原因后重试。'
  if(status===422)return '有字段未通过校验：请返回第 2 步检查样品、执行、阶段、阶段序号与各项确认。'
  if(status===403)return '当前账户无权提交：请联系管理员确认角色权限。'
  return '结果尚不确定：可点击「结果不确定，原样重试」保持请求不变重试，或重新读取任务核对服务器状态。'
}
async function confirm(retry=false){if(busy.value||!auth.canWrite||!job.value)return;error.value='';failure.value=null;let request:any;try{request=retry?replay.value:body();if(!request?.items?.length)throw Error('请勾选至少一个待处理文件。');}catch(e){if(e!=='cancel'&&e!=='close'){error.value=errorText(e);void focusFeedback()}return}busy.value=true;replay.value=request;persist();try{result.value=(await api<any>(`/imports/${job.value.job_id}/confirm`,{method:'POST',body:request})).data;replay.value=null;dirty.value=false;persist();step.value=4;await load(job.value.job_id,{step:4});await list();void focusFeedback()}catch(e){const message=errorText(e);if(e instanceof ApiError&&e.status>=400&&e.status<500){replay.value=null;persist();failure.value={reason:message,hint:failureHint(e.status)}}else{failure.value={reason:message,hint:failureHint(0)}}error.value='';void focusFeedback()}finally{busy.value=false}}
async function leave(){if(!currentSession())return true;if(busy.value)return false;if(!dirty.value)return true;try{await ElMessageBox.confirm('核对选择已尝试保存在此浏览器。未上传文件离开后需要重新选择。是否离开？','离开导入核对',{confirmButtonText:'离开',cancelButtonText:'继续编辑'});return true}catch{return false}}
function beforeUnload(e:BeforeUnloadEvent){if(dirty.value||busy.value){e.preventDefault();e.returnValue=''}}
function goStep(value:number){
  if(busy.value)return
  if(value===3&&job.value&&step.value<=3){
    if(blocked.value)return
    readinessAttempted.value=true
    if(!selected.value.length){error.value='请勾选至少一个待处理文件。';step.value=2;void focusFeedback();return}
    const issue=readinessIssues.value[0]
    if(issue){step.value=2;void focusReadiness(issue);return}
    error.value='';step.value=3
  }else if(value<step.value)step.value=value
}
onBeforeRouteLeave(leave);onBeforeRouteUpdate(async(to,from)=>internalNavigation||to.query.job===from.query.job||await leave())
watch(()=>route.query.job,()=>{const id=Number(route.query.job);if(id>0&&job.value?.job_id!==id)load(id)})
onMounted(()=>{list();searchSamples();if(Number(route.query.job)>0)load(Number(route.query.job));window.addEventListener('beforeunload',beforeUnload)});onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload))
</script>
<template><div data-testid="imports-page">
<PageHeading title="统一导入中心" description="上传 → 审查关联建议 → 确认保存。候选依据会显示，阶段由你确认；执行可留空，不按文件名推断科研事实。"/>
<el-steps :active="Math.min(step-1,2)" finish-status="success" align-center class="import-steps"><el-step title="上传"/><el-step title="审查关联建议"/><el-step title="确认保存"/></el-steps>
<section v-if="step===1" class="panel panel-body import-section" data-testid="import-step1">
<p v-if="route.query.sample_id" class="field-hint">从样品详情发起，上传后将带入该样品供审核。</p>
<label for="import-files">选择原始文件（可多选）</label><input id="import-files" data-testid="import-files" type="file" multiple :disabled="blocked" @change="pick">
<p class="field-hint">{{ files.length }} 个待上传 · 单文件 ≤20 MiB，合计 ≤100 MiB，最多 20 个。</p><el-button type="primary" data-testid="upload-preview" :disabled="blocked||!files.length" :loading="busy" @click="upload">上传并审查</el-button>
<StatePanel v-if="error" title="上传未完成" :description="error" tone="error"/>
<details><summary>恢复我的暂存任务（{{ total }}）</summary><el-alert v-if="listError" :title="listError" type="error"/><el-button @click="list">刷新任务列表</el-button><p v-for="j in jobs" :key="j.job_id"><el-button :data-testid="`open-job-${j.job_id}`" :disabled="busy||loading" @click="open(j.job_id)">打开任务 {{ j.job_id }} · {{ text(statusText,j.status,'待处理') }}</el-button><el-button v-if="auth.canWrite" :disabled="blocked" @click="removeJob(j.job_id,j.row_version)">删除暂存任务</el-button></p><el-pagination v-model:current-page="page" :page-size="10" :total="total" layout="prev,pager,next" @current-change="list"/></details>
</section>
<section v-if="job&&step===2" data-testid="import-job" class="import-section">
<p v-if="lookupBusy" role="status">正在核对样品与执行…</p><p class="field-hint">厚度 nm，真实 X/Y mm；异常点与原值保留，默认纳入统计。阶段序号由系统分配，不代表工艺顺序或循环数。</p>
<article v-for="item in job.items" :key="item.item_id" class="panel panel-body import-item" :data-testid="`import-item-${item.item_id}`">
<header><div class="import-card-head"><h3>{{ item.filename }}</h3><p class="import-card-line">{{ text(statusText,item.parse_result?.status,'待识别') }} · {{ item.parse_result?.blocks?.reduce((n:number,b:any)=>n+(b.points?.length||0),0)||0 }} 测点 · 均值 {{ item.parse_result?.blocks?.[0]?.statistics?.thickness_nm?.mean??'无法计算' }} nm</p><p v-if="cardNotes(item).length" class="field-hint">{{ cardNotes(item).join('；') }}</p></div><label v-if="item.status==='pending'"><input v-model="choices[item.item_id].selected" type="checkbox" :data-testid="`select-${item.item_id}`" @change="edited"> 本次处理</label></header>
<template v-if="item.status==='pending'">
<el-radio-group v-model="choices[item.item_id].action" :disabled="blocked" @change="(v:any)=>chooseAction(item,v as Choice['action'])"><el-radio-button v-if="canImport(item)" value="import">导入测量</el-radio-button><el-radio-button value="original_only">仅归档原件</el-radio-button><el-radio-button value="skip">跳过</el-radio-button></el-radio-group>
<div v-if="choices[item.item_id].action==='import'" class="form-grid" style="margin-top:12px">
<el-form-item label="将归到样品" data-readiness-field="sample" required><el-select v-model="choices[item.item_id].sample_id" filterable remote :remote-method="searchSamples" :loading="sampleSearchBusy" aria-label="导入样品" @change="sampleChanged(item)"><el-option v-if="lookup[item.item_id]" :value="String(lookup[item.item_id].sample.sample_id)" :label="sampleLabel(lookup[item.item_id].sample)"/><el-option v-for="s in sampleOptions.filter(s=>String(s.sample_id)!==choices[item.item_id].sample_id)" :key="s.sample_id" :value="String(s.sample_id)" :label="sampleLabel(s)"/></el-select><p class="field-hint"><el-button v-for="s in suggestions(item)" :key="s.sample_id" link @click="useCandidate(item,s)">建议 {{ s.sample_code }}（{{ s.evidence==='exact_code_or_label'?'编号出现在文件名':'文件数字与小样尾号相符，仅供核对' }}）</el-button></p></el-form-item>
<el-form-item label="测量阶段" data-readiness-field="stage" required><el-select v-model="choices[item.item_id].stage" aria-label="测量阶段" @change="associationChanged(choices[item.item_id])"><el-option v-for="(v,k) in stages" :key="k" :label="v" :value="k"/></el-select><el-button v-if="stageHint(item)" link @click="acceptStage(item)">核对后采用文件名建议：{{stages[stageHint(item)]}}</el-button></el-form-item>
<el-form-item label="已确认的前测（可空）"><el-select v-model="choices[item.item_id].pair_measurement_id" clearable aria-label="前测配对"><el-option v-for="b in job.items.filter(b=>b.item_id!==item.item_id&&choices[b.item_id]?.selected&&choices[b.item_id]?.action==='import'&&choices[b.item_id]?.sample_id===choices[item.item_id].sample_id&&choices[b.item_id]?.stage==='initial'&&b.parse_result?.blocks?.length===1)" :key="`item-${b.item_id}`" :label="`本次上传：${b.filename}（初始测量）`" :value="`item:${b.item_id}`"/><el-option v-for="m in lookup[item.item_id]?.baseline_measurements??[]" :key="m.measurement_id" :label="m.measurement_code" :value="String(m.measurement_id)"/></el-select></el-form-item><el-form-item label="实验执行（可选）"><el-select v-model="choices[item.item_id].process_id" clearable aria-label="导入执行" @change="associationChanged(choices[item.item_id])"><el-option v-for="p in lookup[item.item_id]?.processes??[]" :key="p.process_id" :label="p.process_code" :value="String(p.process_id)"/></el-select></el-form-item>
</div>
<details v-if="choices[item.item_id].action==='import'"><summary>高级核查：模型、测量时间与重复导入</summary><p class="field-hint">模型未知仍可独立绘图，不能据此计算可信前后变化。前测配对必须依据实际记录手选，不自动配对。</p><div class="form-grid"><el-form-item label="光学模型（可空）"><el-select v-model="choices[item.item_id].optical_model_id" clearable aria-label="光学模型" @change="associationChanged(choices[item.item_id])"><el-option v-for="m in item.suggestions?.optical_models??[]" :key="m.model_id" :label="m.model_name||m.model_code" :value="String(m.model_id)"/></el-select></el-form-item><el-form-item label="实际测量时间（可选，用于确认处理间隔）"><el-date-picker v-model="choices[item.item_id].measured_at" type="datetime" aria-label="实际测量时间" placeholder="未知留空，不使用上传时间替代"/></el-form-item><el-form-item label="阶段技术序号（默认自动）"><el-input v-model="choices[item.item_id].stage_seq" aria-label="阶段序号" placeholder="自动分配"/></el-form-item><el-form-item label="测量编号（默认自动）"><el-input v-model="choices[item.item_id].measurement_code" aria-label="测量编码" maxlength="80"/></el-form-item></div><label><input v-model="choices[item.item_id].confirm_duplicate" type="checkbox">允许相同内容创建独立重测</label><el-input v-if="choices[item.item_id].confirm_duplicate" v-model="choices[item.item_id].duplicate_reason" aria-label="重复导入原因" placeholder="重复导入原因（必填）"/><el-input v-model="choices[item.item_id].notes" aria-label="导入备注" placeholder="备注（可选）"/></details>
</template>
<p v-else>已处理：{{ text(itemStatusText,item.status,'已处理') }}</p>
<details><summary>测点、原值与图表（按需展开）</summary><ImportAnalysis :item="item" :job-version="job.row_version" v-if="expanded[item.item_id]"/><el-button v-else @click="expanded[item.item_id]=true">读取原始图表</el-button><p v-if="itemWarnings(item).length" class="field-hint">{{ itemWarnings(item).join('；') }}</p><p v-if="itemBlocking(item).length" class="danger-text">{{ itemBlocking(item).join('；') }}</p><p class="hash">SHA256 {{ item.sha256 }}</p><details><summary>解析依据与保留原值</summary><pre>{{ json(item.parse_result) }}</pre></details></details>
</article>
<div v-if="visibleReadinessIssues.length" class="panel panel-body" role="alert"><p v-for="issue in visibleReadinessIssues" :key="`${issue.item.item_id}-${issue.field}`"><button class="readiness-link" @click="focusReadiness(issue)">{{ issue.message }} 点击修复</button></p></div>
<div class="import-submit"><span>所选 {{ selected.length }} 项；其余保留待核对</span><el-button :disabled="blocked||!selected.length" @click="goStep(3)">下一步：确认提交</el-button></div>
</section>
<section v-if="job&&step===3" class="panel panel-body import-section">
<h2>确认保存</h2><p>点击“确认所选并提交”表示已核对以下样品、阶段、可选执行及内容单位（厚度 nm、坐标 mm）。文件名建议尚需你审核；未选文件继续暂存。</p>
<el-table :data="selected"><el-table-column prop="filename" label="文件" min-width="160"/><el-table-column label="归属" min-width="160"><template #default="{row}">{{ choices[row.item_id].action==='import'?associationLabel(row):'仅原件 / 跳过' }}<div>{{ processLabel(row) }}</div></template></el-table-column><el-table-column label="阶段" min-width="120"><template #default="{row}">{{ stages[choices[row.item_id].stage]||'不适用' }}</template></el-table-column></el-table>
<el-button :disabled="busy" @click="step=2">返回修改</el-button><el-button type="primary" data-testid="import-step3-submit" :disabled="blocked||!selected.length" :loading="busy" @click="confirm()">确认所选并提交</el-button>
</section>
<section v-if="step===4" ref="resultEl" class="panel panel-body import-section" data-testid="confirm-results"><h2>保存结果</h2><template v-if="result"><el-alert type="success" :closable="false" data-testid="import-result-banner" :title="`已处理 ${result.items.length} 个文件，剩余 ${result.pending_count} 项`"/><div v-for="r in result.items" :key="r.item_id"><p>{{ job?.items.find(i=>i.item_id===r.item_id)?.filename }} · {{ text(actionText,r.action,'已处理') }}</p><router-link v-for="id in r.measurement_ids" :key="id" :to="{path:'/measurements',query:{id}}">查看正式测量 </router-link><p v-if="r.warnings?.length" class="field-hint">{{ r.warnings.join('；') }}</p></div></template><router-link v-if="route.query.sample_id" :to="{path:'/samples',query:{sample_id:route.query.sample_id}}"><el-button>返回样品详情查看结果</el-button></router-link><el-button @click="step=2">继续核对剩余文件</el-button></section>
<div v-if="(error||failure)&&step!==1" ref="feedbackEl" class="panel panel-body import-feedback" data-testid="import-feedback"><StatePanel tone="error" title="操作未完成" :description="error||failure?.reason"><p>{{ failure?.hint }}</p><el-button v-if="replay" data-testid="retry-confirm" @click="confirm(true)">使用原请求核对结果</el-button></StatePanel></div>
</div></template>
<style scoped>
.import-steps{margin-bottom:22px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-panel);padding:18px 12px}
.import-section{margin-bottom:22px}.import-item{margin-top:18px}.import-item header{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}.import-item h3{overflow-wrap:anywhere;margin-bottom:6px}
.import-card-head{min-width:0;flex:1}
.import-card-line{margin:2px 0;font-size:13px;color:var(--muted);overflow-wrap:anywhere}
.import-card-line .el-tag{margin-right:8px}
.hash{font-size:12px;overflow-wrap:anywhere;color:var(--muted)}
details{margin:14px 0}summary{cursor:pointer;font-weight:600;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;background:var(--soft);padding:14px;font-size:12px}
.import-fieldset{border:1px solid var(--line);border-radius:6px;padding:18px;margin-top:18px;min-width:0}
.import-fieldset legend{font-weight:600;padding:0 6px}
.import-check{display:flex;align-items:flex-start;gap:9px;margin:16px 0;font-size:13px}
.candidate{border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:16px}.candidate span{font-size:12px;margin-left:10px}
.import-submit{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;background:var(--surface);border:1px solid var(--line);padding:16px}
.import-feedback{margin:18px 0 12px}
.readiness-link{color:var(--danger,#b42318);background:transparent;border:0;padding:5px 0;text-align:left;font:inherit;cursor:pointer;overflow-wrap:anywhere;text-decoration:underline}
.import-feedback ul{padding-left:20px}
.import-feedback :deep(.state-panel){margin:0}
.import-result-row{border-bottom:1px solid var(--line);padding:12px 0}
input[type=file]{display:block;max-width:100%;margin:12px 0}.import-section h2{font-size:20px}
fieldset:disabled{opacity:.7;pointer-events:none}
@media(max-width:760px){fieldset{padding:12px}.import-item{padding:16px}.candidate span{display:block;margin:8px 0}.import-submit{position:static}.import-steps{padding:12px 6px}}
</style>
