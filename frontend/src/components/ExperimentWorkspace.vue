<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import ExperimentResults from './ExperimentResults.vue'
import CycleSummary from './CycleSummary.vue'
import PageHeading from './PageHeading.vue'
import FormSection from './FormSection.vue'
import StatePanel from './StatePanel.vue'
import ExperimentFields from './ExperimentFields.vue'
import SamplePicker from './SamplePicker.vue'
import ProcessGrid from './ProcessGrid.vue'
import LifecycleDialog from './LifecycleDialog.vue'
import WorkflowProgress from './WorkflowProgress.vue'
import {gridDraft,gridPayload,clearFlowRepeats,stepNode,type ProcessFlow,type FlowNode,type GridDraft,type GridStep} from '../experiments/processGrid'
import { api, ApiError, errorText } from '../api'
import { useAuth } from '../auth'
import { type Row, type Field, planFields, processFields, planStatuses, modes, bindingFields, label, display, blank, payload, useDraftGuard, planStepDraft, defaultSnapshot, copySnapshot } from '../experiments/model'
const props=defineProps<{kind:'plans'|'processes'}>()
const auth=useAuth(),route=useRoute(),router=useRouter()
const isPlan=computed(()=>props.kind==='plans'),noun=computed(()=>isPlan.value?'实验计划':'实验执行'),idKey=computed(()=>isPlan.value?'plan_id':'process_id'),fields=computed(()=>isPlan.value?planFields:processFields)
const gridOpen=ref(false),gridSaving=ref(false),gridError=ref(''),gridConflict=ref(false),grid=ref<GridDraft>({steps:[],process_flow:{version:1,total_cycles:null,children:[]}}),gridBaseline=ref('')
async function renameExecution(){
 if(!detail.value||!writable.value||saving.value)return
 let value:string
 try{value=(await ElMessageBox.prompt('修改业务执行编号，历史仍按内部主键关联。','修改执行编号',{inputValue:detail.value.process_code,inputValidator:v=>!!v?.trim()&&v.trim().length<=64||'请输入 1–64 字符',confirmButtonText:'保存编号',cancelButtonText:'取消'})).value}catch{return}
 saving.value=true;detailError.value=''
 try{detail.value=(await api<Row>(`/processes/${detail.value.process_id}`,{method:'PATCH',body:{process_code:value.trim(),expected_row_version:detail.value.row_version}})).data;await load();ElMessage.success('执行编号已保存并记入审计')}catch(e){detailError.value=errorText(e)}finally{saving.value=false}
}
const rows=ref<Row[]>([]),total=ref(0),page=ref(1),size=ref(20),loading=ref(false),error=ref('')
const filters=reactive<Row>({keyword:'',status:'',priority:'',batch_id:'',plan_id:'',process_mode:'',log_status:'',date_from:'',date_to:'',include_voided:false})
const detail=ref<Row|null>(null),detailLoading=ref(false),detailError=ref(''),selectedId=ref<number|null>(null)
const editor=ref(false),creating=ref(false),form=ref<Row>({}),saving=ref(false),formError=ref(''),conflict=ref(false)
const childOpen=ref(false),childKind=ref<'binding'>('binding'),childId=ref<number|null>(null),childForm=ref<Row>({}),childError=ref(''),childConflict=ref(false)
// 单条绑定的样品也改由可搜索选择器挑选，不再手填样品 ID（第四轮第 4 项）。
const lookup=reactive<Record<string,Row[]>>({batches:[],plans:[],tools:[]}),lookupError=ref('')
const relationKeys=['batch_id','plan_id','tool_id']
const inputFields=computed(()=>fields.value.filter(f=>!relationKeys.includes(f.key)))
const childSampleId=ref<number|null>(null)
// 化学体系属于「执行」而不是「步骤」（契约：仅 Process/ProcessCreate/ProcessUpdate 有 chemistry_system_id），
// 因此选择器放在执行编辑抽屉，绝不写入步骤请求体，否则 extra='forbid' 会返回 422。
const formChemistry=ref<number|null>(null)
const selectedSamples=ref<number[]>([])
const bindingOpen=ref(false),bindingIds=ref<number[]>([]),bindingCommon=ref<Row>({}),bindingError=ref(''),bindingConflict=ref(false)
const draftFlow=ref<ProcessFlow|null>(null)
const draftSteps=ref<Row[]>([])
const planSteps=ref<Row[]>([]),mappingLoading=ref(false),mappingError=ref(''),planDetail=ref<Row|null>(null),inherited=ref(false)
const chemistrySystems=ref<Row[]>([]),chemistryLoading=ref(false),chemistryError=ref('')
const baselines=reactive({parent:'',child:'',binding:''})
const parentSnapshot=()=>JSON.stringify([form.value,selectedSamples.value,draftSteps.value,draftFlow.value,formChemistry.value])
const childSnapshot=()=>JSON.stringify([childForm.value,childSampleId.value])
const bindingSnapshot=()=>JSON.stringify([bindingIds.value,bindingCommon.value])
const dirty=()=>gridOpen.value&&JSON.stringify(grid.value)!==gridBaseline.value||editor.value&&parentSnapshot()!==baselines.parent||childOpen.value&&childSnapshot()!==baselines.child||bindingOpen.value&&bindingSnapshot()!==baselines.binding
const guard=useDraftGuard(dirty,()=>saving.value||gridSaving.value)
const writable=computed(()=>auth.canWrite&&!detail.value?.quick_record_url&&(creating.value||!!detail.value&&(auth.isAdmin||(isPlan.value?detail.value.owner_user_id:detail.value.operator_user_id)===auth.user?.user_id)))
const lifecycleOpen=ref(false)
const workflow=ref<Row|null>(null),workflowLoading=ref(false),workflowError=ref('')
let workflowSequence=0
async function loadWorkflow(id:number){
  const seq=++workflowSequence,kind=props.kind
  workflow.value=null;workflowLoading.value=true;workflowError.value=''
  try{const r=await api<Row>('/workflow/state',{query:{[kind==='plans'?'plan_id':'process_id']:id}});if(seq===workflowSequence&&selectedId.value===id&&props.kind===kind)workflow.value=r.data}
  catch(e){if(seq===workflowSequence)workflowError.value=errorText(e)}
  finally{if(seq===workflowSequence)workflowLoading.value=false}
}
async function continueWorkflow(stage:number){
  if(!detail.value||saving.value||gridSaving.value||!await guard.discard())return
  await router.push({path:'/experiments/new',query:{[idKey.value]:detail.value[idKey.value],stage}})
}
async function openLifecycle(){
  if(!detail.value||!writable.value||saving.value||gridSaving.value||!await guard.discard())return
  lifecycleOpen.value=true
}
async function lifecycleApplied(action:string){
  if(action==='delete'){++detailSequence;++workflowSequence;detail.value=null;selectedId.value=null;workflow.value=null}
  else await refreshDetail()
  await load();void loadLookups();ElMessage.success(`${noun.value}生命周期操作已完成`)
}
const childFields=computed<Field[]>(()=>bindingFields.filter(f=>f.key!=='sample_id'))
const boundSampleIds=computed(()=>new Set<number>((detail.value?.samples??[]).map((s:Row)=>s.sample_id)))
let listSequence=0,detailSequence=0
function draftToGrid():GridDraft{
  const steps:GridStep[]=draftSteps.value.map((s:Row,i:number)=>({key:`draft-${i+1}`,step_id:null,step_kind:s.step_kind||'other',step_name:s.step_name??null,parameter_snapshot:s.parameter_snapshot?copySnapshot(s.parameter_snapshot):defaultSnapshot(s.step_name||label(s.step_kind)),plan_step_id:s.plan_step_id??null,step_note:s.step_note??null}))
  if(!draftFlow.value)return {steps,process_flow:{version:1,total_cycles:null,children:steps.map(s=>stepNode(s.key))}}
  const flow=JSON.parse(JSON.stringify(draftFlow.value)) as ProcessFlow
  const byIndex=new Map<number,string>(steps.map((s,i)=>[i+1,s.key]))
  const referenced=new Set<string>()
  const visit=(nodes:FlowNode[])=>nodes.forEach(n=>{if(n.kind==='step'){const index=Number(String(n.step_id).replace('index:',''));const key=byIndex.get(index);if(key){n.step_id=key;referenced.add(key)}}else visit(n.children)})
  visit(flow.children)
  // Columns added in the grid after inheritance are appended to the explicit order.
  for(const s of steps)if(!referenced.has(s.key))flow.children.push(stepNode(s.key))
  return {steps,process_flow:flow}
}
function gridToDraft(draft:GridDraft){
  const order:string[]=[];const visit=(nodes:FlowNode[])=>nodes.forEach(n=>{if(n.kind==='step'){if(n.step_id!=null)order.push(String(n.step_id))}else visit(n.children)});visit(draft.process_flow.children)
  const byKey=new Map(draft.steps.map(s=>[s.key,s]))
  const steps:Row[]=[]
  for(const key of order){const s=byKey.get(key);if(!s)continue;steps.push({step_index:steps.length+1,step_kind:s.step_kind,step_name:s.step_name?.trim()||null,plan_step_id:s.plan_step_id,step_note:s.step_note??null,custom_parameters:null,parameter_snapshot:JSON.parse(JSON.stringify(s.parameter_snapshot))})}
  draftSteps.value=steps
  
  // Creation API addresses draft steps as index:1, index:2, …; keep that contract.
  const indexByKey=new Map(steps.map((s,i)=>[order[i]??'',`index:${i+1}`]))
  const flow=JSON.parse(JSON.stringify(draft.process_flow)) as ProcessFlow
  const rewrite=(nodes:FlowNode[])=>nodes.forEach(n=>{if(n.kind==='step'){const mapped=indexByKey.get(String(n.step_id));if(mapped)n.step_id=mapped}else rewrite(n.children)})
  rewrite(flow.children)
  draftFlow.value=flow
}
const planOptions=computed<{id:number;label:string}[]>(()=>(planSteps.value.length?planSteps.value:(planDetail.value?.steps??[])).map((s:Row)=>({id:s.step_id,label:`${s.step_index} · ${s.step_name||s.parameter_snapshot?.step_type||label(s.step_kind)} · #${s.step_id}`})))
async function openGrid(){
  if(creating.value){grid.value=draftToGrid()}
  else{if(!detail.value||!await guard.discard())return;grid.value=gridDraft(detail.value,isPlan.value);if(!isPlan.value)await loadPlanSteps()}
  gridBaseline.value=JSON.stringify(grid.value);gridError.value='';gridConflict.value=false;gridOpen.value=true
}
async function closeGrid(done?:()=>void){if(gridSaving.value)return;if(JSON.stringify(grid.value)!==gridBaseline.value){try{await ElMessageBox.confirm('流程网格尚未保存，确定放弃修改？','未保存的修改',{confirmButtonText:'放弃修改',cancelButtonText:'继续编辑'})}catch{return}}gridOpen.value=false;done?.()}
async function saveGrid(){
  if(gridSaving.value||gridConflict.value)return
  if(creating.value){gridToDraft(grid.value);gridBaseline.value=JSON.stringify(grid.value);gridOpen.value=false;ElMessage.success(`流程网格已加入创建草稿，保存${noun.value}时一起提交`);return}
  if(!detail.value)return
  gridError.value=''
  try{const body={...gridPayload(grid.value),expected_row_version:detail.value.row_version};gridSaving.value=true;const r=await api<Row>(`/${props.kind}/${detail.value[idKey.value]}/process-grid`,{method:'PUT',body});detail.value=r.data;gridOpen.value=false;ElMessage.success('流程与步骤参数已一起保存');void loadWorkflow(detail.value![idKey.value]);void load()}catch(e){gridError.value=errorText(e);if(e instanceof ApiError&&e.status===409)gridConflict.value=true}finally{gridSaving.value=false}
}
async function load(){const seq=++listSequence;loading.value=true;error.value='';try{const query:Row={page:page.value,size:size.value,keyword:filters.keyword,batch_id:filters.batch_id,include_voided:filters.include_voided};if(isPlan.value)Object.assign(query,{status:filters.status,priority:filters.priority});else Object.assign(query,{plan_id:filters.plan_id,process_mode:filters.process_mode,log_status:filters.log_status,date_from:filters.date_from?new Date(filters.date_from).toISOString():null,date_to:filters.date_to?new Date(filters.date_to).toISOString():null});const r=await api<Row[]>(`/${props.kind}`,{query});if(seq===listSequence){rows.value=r.data;total.value=r.meta?.total??0}}catch(e){if(seq===listSequence)error.value=errorText(e)}finally{if(seq===listSequence)loading.value=false}}
function search(){page.value=1;void load()}
async function fetchDetail(id:number){const seq=++detailSequence;selectedId.value=id;detailLoading.value=true;detailError.value='';try{const r=await api<Row>(`/${props.kind}/${id}`);if(seq===detailSequence){detail.value=r.data;void loadWorkflow(id)}return r.data}catch(e){if(seq===detailSequence)detailError.value=errorText(e);throw e}finally{if(seq===detailSequence)detailLoading.value=false}}
async function openDetail(id:number){if(!await guard.discard())return;editor.value=false;childOpen.value=false;bindingOpen.value=false;detail.value=null;try{await fetchDetail(id)}catch{} }
async function refreshDetail(){if(selectedId.value)try{await fetchDetail(selectedId.value)}catch{}}
async function loadChemistry(){if(chemistryLoading.value)return;chemistryError.value='';chemistryLoading.value=true;try{chemistrySystems.value=(await api<Row[]>('/chemistry-systems',{query:{size:200,status:'active'}})).data}catch(e){chemistryError.value=errorText(e)}finally{chemistryLoading.value=false}}
async function edit(){if(!detail.value||!writable.value||!await guard.discard())return;creating.value=false;form.value=blank(fields.value,detail.value);selectedSamples.value=[];draftSteps.value=[];inherited.value=false;formChemistry.value=isPlan.value?null:(detail.value.chemistry_system_id??null);if(!isPlan.value)void loadChemistry();baselines.parent=parentSnapshot();conflict.value=false;formError.value='';editor.value=true}
// 计划详情「发起执行」进入时，按第四轮契约第 6 节继承计划步骤骨架与样品范围，绝不复制计划参数值。
async function create(){if(!auth.canWrite||!await guard.discard())return;creating.value=true;selectedId.value=null;form.value=blank(fields.value,isPlan.value?{status:'draft',priority:'normal'}:{process_mode:'other',is_independent_run:true,log_status:'unknown',plan_id:route.query.plan_id?Number(route.query.plan_id):'',batch_id:route.query.batch_id?Number(route.query.batch_id):''});selectedSamples.value=!isPlan.value&&route.query.sample_id?[Number(route.query.sample_id)]:[];draftSteps.value=[];draftFlow.value=null;planDetail.value=null;inherited.value=false;formError.value='';conflict.value=false;formChemistry.value=null;editor.value=true;if(!isPlan.value){if(!chemistrySystems.value.length)await loadChemistry();if(form.value.plan_id)await inheritPlan(Number(form.value.plan_id));if(form.value.batch_id||form.value.plan_id)await loadPlanSteps()};baselines.parent=parentSnapshot()}
async function inheritPlan(planId:number){
  inherited.value=false
  try{
    const plan=(await api<Row>(`/plans/${planId}`)).data
    planDetail.value=plan
    if(plan.batch_id&&!form.value.batch_id)form.value.batch_id=plan.batch_id
    if(!creating.value||isPlan.value)return
    draftSteps.value=(plan.steps??[]).map(planStepDraft)
    draftFlow.value=plan.process_flow?clearFlowRepeats(JSON.parse(JSON.stringify(plan.process_flow))):null
    if(draftFlow.value){const indices=new Map<number,string>((plan.steps??[]).map((s:Row,i:number)=>[s.step_id,`index:${i+1}`]));const visit=(nodes:FlowNode[])=>nodes.forEach(n=>{if(n.kind==='step')n.step_id=indices.get(Number(n.step_id))!;else visit(n.children)});visit(draftFlow.value.children)}
    planSteps.value=plan.steps??[]
    inherited.value=true
    ElMessage.success(`已从计划继承 ${draftSteps.value.length} 个步骤骨架与样品范围，请填写实际发生情况`)
  }catch(e){formError.value=`计划读取失败：${errorText(e)}`}
}
async function closeEditor(done?:()=>void){if(await guard.discard()){editor.value=false;done?.()}}
async function reloadParent(){if(saving.value||creating.value)return;try{await fetchDetail(selectedId.value!);conflict.value=false;formError.value='已刷新父记录版本，当前输入已保留。请核对最新详情与输入后再次保存。'}catch{}}
async function loadPlanSteps(){planSteps.value=[];mappingError.value='';const planId=editor.value?form.value.plan_id:detail.value?.plan_id;if(!planId)return;mappingLoading.value=true;try{const plan=(await api<Row>(`/plans/${planId}`)).data;planSteps.value=plan.steps??[];if(!planDetail.value||planDetail.value.plan_id!==plan.plan_id)planDetail.value=plan}catch(e){mappingError.value=errorText(e)}finally{mappingLoading.value=false}}
async function save(){if(saving.value||!auth.canWrite||conflict.value)return;formError.value='';try{const body=payload(fields.value.filter(f=>creating.value||!['plan_code','process_code'].includes(f.key)),form.value);if(isPlan.value&&body.planned_start&&body.planned_end&&body.planned_start>body.planned_end)throw new Error('计划结束日期不能早于开始日期');if(!isPlan.value&&body.started_at&&body.ended_at&&body.started_at>body.ended_at)throw new Error('执行结束时间不能早于开始时间');if(creating.value&&!isPlan.value){body.samples=[...new Set(selectedSamples.value)].map(sample_id=>({sample_id}));body.steps=draftSteps.value;if(draftFlow.value)body.process_flow=draftFlow.value}if(!isPlan.value)body.chemistry_system_id=formChemistry.value??null;if(!isPlan.value&&creating.value)body.process_mode='other';if(!creating.value)body.expected_row_version=detail.value!.row_version;const planGrid=creating.value&&isPlan.value&&(draftSteps.value.length||draftFlow.value)?draftToGrid():null;
// Validate before POST. PlanCreate only accepts basic fields; the existing grid API
// saves the draft under the newly created parent's row version.
const planGridBody=planGrid?gridPayload(planGrid):null;
saving.value=true;const r=await api<Row>(creating.value?`/${props.kind}`:`/${props.kind}/${selectedId.value}`,{method:creating.value?'POST':'PATCH',body});detail.value=r.data;selectedId.value=r.data[idKey.value];editor.value=false;creating.value=false;
if(planGrid&&planGridBody){
  try{detail.value=(await api<Row>(`/plans/${r.data.plan_id}/process-grid`,{method:'PUT',body:{...planGridBody,expected_row_version:r.data.row_version}})).data}
  catch(e){
    // Never repeat the parent POST after a partial success. Keep every grid input
    // and the original CAS version; an uncertain response cannot overwrite newer work.
    grid.value=planGrid;gridBaseline.value='';gridOpen.value=true;gridConflict.value=e instanceof ApiError&&e.status===409;
    gridError.value=`计划 ${r.data.plan_code}（#${r.data.plan_id}）基本信息已创建，流程保存失败：${errorText(e)}。网格草稿已保留；请重试保存流程，不要重复创建计划。若提示版本冲突，请核对详情中的已保存流程。`;
    void load();return
  }
}
void loadWorkflow(r.data[idKey.value]);ElMessage.success('已保存');void load();if(!isPlan.value&&route.query.create==='1')void router.replace({path:route.path,query:{[idKey.value]:r.data[idKey.value]}})}catch(e){formError.value=errorText(e);if(e instanceof ApiError&&e.status===409)conflict.value=true}finally{saving.value=false}}
async function newChild(_kind:'binding',row?:Row){if(saving.value||!auth.canWrite||!await guard.discard())return;childKind.value='binding';childId.value=row?.process_sample_id??null;childError.value='';childConflict.value=false;childForm.value=blank(bindingFields,row??{});childSampleId.value=row?.sample_id??null;baselines.child=childSnapshot();childOpen.value=true}
function removeDraftStep(index:number){draftFlow.value=null;draftSteps.value.splice(index,1);draftSteps.value.forEach((step,i)=>{step.step_index=i+1})}
async function closeChild(done?:()=>void){if(saving.value)return;if(childSnapshot()!==baselines.child){try{await ElMessageBox.confirm('样品绑定尚未保存，确定放弃？','未保存的修改',{type:'warning',confirmButtonText:'放弃修改',cancelButtonText:'继续编辑'})}catch{return}}childOpen.value=false;done?.()}
function bindingBody(){const body=payload(childFields.value,childForm.value);if(!childId.value){if(!childSampleId.value)throw new Error('请选择要绑定的样品');body.sample_id=childSampleId.value}return body}
async function saveChild(){if(saving.value||childConflict.value||!auth.canWrite)return;childError.value='';try{const body=bindingBody();if(childId.value)body.expected_row_version=detail.value!.row_version;
const path=childId.value?`/process-samples/${childId.value}`:`/${props.kind}/${selectedId.value}/samples`;saving.value=true;await api(path,{method:childId.value?'PATCH':'POST',body});childOpen.value=false;await fetchDetail(selectedId.value!);void load();ElMessage.success('已保存，父记录版本已刷新')}catch(e){childError.value=errorText(e);if(e instanceof ApiError&&e.status===409)childConflict.value=true}finally{saving.value=false}}
async function reloadChildVersion(){if(saving.value)return;try{await fetchDetail(selectedId.value!);childConflict.value=false;childError.value='已刷新父记录版本，保留当前输入；请核对最新详情后重试。'}catch{}}
async function removeChild(_kind:'binding',row:Row){if(!auth.canWrite||saving.value)return;try{await ElMessageBox.confirm('确定解除绑定？已有历史或映射依赖的记录可能无法删除。','解除绑定确认',{type:'warning',confirmButtonText:'确认解除',cancelButtonText:'取消'});saving.value=true;await api(`/process-samples/${row.process_sample_id}`,{method:'DELETE',query:{expected_row_version:detail.value!.row_version}});await fetchDetail(selectedId.value!);void load()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(errorText(e))}finally{saving.value=false}}
async function openBindingBatch(){if(saving.value||!auth.canWrite||!await guard.discard())return;bindingIds.value=[];bindingCommon.value={chamber_position:'',o3_pre_cycles:'',hf_tma_repeats:'',full_ale_cycles:'',is_control:false,sample_role_note:''};bindingError.value='';bindingConflict.value=false;baselines.binding=bindingSnapshot();bindingOpen.value=true}
async function closeBinding(done?:()=>void){if(saving.value)return;if(bindingSnapshot()!==baselines.binding){try{await ElMessageBox.confirm('样品绑定尚未保存，确定放弃？','未保存的修改',{type:'warning',confirmButtonText:'放弃修改',cancelButtonText:'继续编辑'})}catch{return}}bindingOpen.value=false;done?.()}
async function recoverBindingConflict(){
  if(saving.value||!detail.value)return
  const processId=detail.value.process_id
  saving.value=true
  try{
    const latest=await fetchDetail(processId)
    const bound=new Set<number>((latest.samples??[]).map((s:Row)=>s.sample_id))
    const previous=bindingIds.value.length
    bindingIds.value=bindingIds.value.filter(id=>!bound.has(id))
    bindingConflict.value=false
    bindingError.value=`已刷新执行详情，移除 ${previous-bindingIds.value.length} 份已绑定样品；其余选择和公共属性已保留，请核对后提交。`
  }catch(e){bindingError.value=`刷新失败：${errorText(e)}；输入已保留，请重试。`}
  finally{saving.value=false}
}
async function saveBindingBatch(){if(saving.value||bindingConflict.value||!auth.canWrite||!detail.value)return;bindingError.value='';try{if(!bindingIds.value.length)throw new Error('请先选择至少一份样品');const body:Row={sample_ids:bindingIds.value.filter((id,i,ids)=>ids.indexOf(id)===i&&!boundSampleIds.value.has(id))};if(!body.sample_ids.length)throw new Error('所选样品均已绑定，请刷新列表');for(const key of ['chamber_position','full_ale_cycles','sample_role_note']){const value=bindingCommon.value[key];if(key==='full_ale_cycles'&&value!==''&&value!==undefined&&value!==null){const count=Number(value);if(!Number.isInteger(count)||count<0||count>4294967295)throw new Error('样品完整 ALE 循环数须为 0–4294967295 整数');body[key]=count}else body[key]=value===''||value===undefined?null:value}body.is_control=!!bindingCommon.value.is_control;saving.value=true;await api(`/processes/${detail.value.process_id}/samples/batch`,{method:'POST',body});bindingOpen.value=false;await fetchDetail(detail.value.process_id);void load();ElMessage.success('已批量绑定样品；绑定不等于装载，请到样品历史记录装载/卸载')}catch(e){bindingError.value=errorText(e);if(e instanceof ApiError&&e.status===409)bindingConflict.value=true}finally{saving.value=false}}
function history(sample:Row){void router.push({path:'/sample-history',query:{sample_id:sample.sample_id,process_id:selectedId.value}})}
const participationLabels:Record<string,string>={unloaded:'已取出',loaded:'已装入未取出',not_recorded:'未记录装卸'}
function eventNode(event:Row|null|undefined){if(!event)return '未记录';if(event.step_index!=null)return `步骤 ${event.step_index}`;return event.event_at?display(event.event_at):'已记录'}
function sampleDetail(sample:Row){void router.push({path:'/samples',query:{sample_id:sample.sample_id,batch_id:sample.batch_id}})}
const selectedRows=ref<Row[]>([]),batchCleanupOpen=ref(false),batchCleanupRows=ref<Row[]>([]),batchCleanupError=ref(''),batchCleanupBusy=ref(false),batchCleanupResult=ref<Row[]>([])
function onSelection(rows:Row[]){selectedRows.value=rows}
async function openLifecycleFromRow(row:Row){if(!auth.canWrite||saving.value||gridSaving.value||!await guard.discard())return;await openDetail(row[idKey.value]);if(writable.value)lifecycleOpen.value=true}
async function prepareBatchCleanup(){
  if(!auth.canWrite||batchCleanupBusy.value)return
  if(!selectedRows.value.length){ElMessage.warning('请先勾选要清理的草稿记录。');return}
  batchCleanupBusy.value=true;batchCleanupError.value='';batchCleanupResult.value=[]
  try{
    const checked=[]
    for(const row of [...selectedRows.value]){
      const result=await api<Row>(`/lifecycle/${props.kind}/${row[idKey.value]}/impact`)
      checked.push({row,impact:result.data})
    }
    batchCleanupRows.value=checked;batchCleanupOpen.value=true
  }catch(e){batchCleanupError.value=errorText(e)}finally{batchCleanupBusy.value=false}
}
async function applyBatchCleanup(){
  if(batchCleanupBusy.value)return
  const eligible=batchCleanupRows.value.filter(item=>item.impact.delete_permitted&&(item.impact.actions||[]).includes('delete'))
  if(!eligible.length)return
  batchCleanupBusy.value=true;batchCleanupError.value='';const results=[]
  for(const item of eligible){
    try{
      await api(`/lifecycle/${props.kind}/${item.row[idKey.value]}/apply`,{method:'POST',body:{action:'delete',expected_row_version:item.impact.row_version,preview_token:item.impact.preview_token,operation_id:crypto.randomUUID(),reason:'批量清理未使用草稿'}})
      results.push({code:item.row[isPlan.value?'plan_code':'process_code'],ok:true,message:'已删除'})
    }catch(e){results.push({code:item.row[isPlan.value?'plan_code':'process_code'],ok:false,message:errorText(e)})}
  }
  batchCleanupResult.value=results
  const done=results.filter(r=>r.ok).length
  ElMessage.success(`批量清理完成：${done}/${eligible.length} 条已删除；其余记录保留并显示原因。`)
  batchCleanupOpen.value=false;selectedRows.value=[];await load();await loadLookups()
  if(detail.value&&results.some(r=>r.code===detail.value![isPlan.value?'plan_code':'process_code']&&r.ok)){detail.value=null;selectedId.value=null}
  batchCleanupBusy.value=false
}
function runPlan(){if(saving.value)return;void router.push({path:'/processes',query:{create:'1',plan_id:detail.value!.plan_id,batch_id:detail.value!.batch_id??undefined}})}
function stepTitle(step:Row){return `${step.step_index} · ${step.step_name||step.parameter_snapshot?.step_type||label(step.step_kind)}`}

function relationName(kind:string,id:unknown){if(!id)return '未关联';const key=kind==='plans'?'plan_id':kind==='tools'?'tool_id':'batch_id';const row=lookup[kind]?.find(r=>r[key]===Number(id));return row?(kind==='plans'?`${row.plan_code} · ${row.title}`:kind==='tools'?`${row.tool_code} · ${row.tool_name}`:`${row.batch_code}${row.batch_name?' · '+row.batch_name:''}`):`当前关联 #${id}`}
const availablePlans=computed(()=>lookup.plans!.filter(p=>!form.value.batch_id||!p.batch_id||p.batch_id===Number(form.value.batch_id)))
async function loadLookups(){lookupError.value='';await Promise.all(['batches','plans','tools'].map(async kind=>{try{const all:Row[]=[];let page=1;while(true){const r=await api<Row[]>(`/${kind}`,{query:{page,size:200}});all.push(...r.data);if(!r.meta?.has_next)break;page++}lookup[kind]=all}catch(e){lookupError.value=`关联选项加载失败：${errorText(e)}`}}))}
async function selectPlan(value:unknown){if(creating.value&&draftSteps.value.length){try{await ElMessageBox.confirm('切换计划会重建初始步骤骨架，当前实际步骤草稿将被替换。','切换计划',{confirmButtonText:'重建步骤',cancelButtonText:'保留当前计划'})}catch{form.value.plan_id=planDetail.value?.plan_id??null;return}}planSteps.value=[];planDetail.value=null;inherited.value=false;if(creating.value){draftSteps.value=[];draftFlow.value=null}if(!value)return;const plan=lookup.plans!.find(p=>p.plan_id===Number(value));if(plan?.batch_id){form.value.batch_id=plan.batch_id;selectedSamples.value=[]}if(creating.value){draftSteps.value=[];await inheritPlan(Number(value))}else await loadPlanSteps()}
function selectBatch(){selectedSamples.value=[];if(form.value.plan_id&&!availablePlans.value.some(p=>p.plan_id===Number(form.value.plan_id))){form.value.plan_id=null;planSteps.value=[];planDetail.value=null;inherited.value=false;if(creating.value)draftSteps.value=[]}}

async function routeEntry(){if(route.query.create==='1'&&!isPlan.value)await create();else if(route.query[idKey.value])await openDetail(Number(route.query[idKey.value]));if(route.query.plan_id&&!isPlan.value&&route.query.create!=='1')filters.plan_id=route.query.plan_id;void load()}
watch(()=>route.fullPath,routeEntry)
onMounted(()=>{void loadLookups();void routeEntry()})
</script>
<template><div class="experiment-workspace">
<PageHeading :title="noun" :description="isPlan?'组织研究目标、计划步骤及预期参数，再选择样品创建一次或多次执行。':'记录独立填写的实际条件与步骤。同一计划可多次执行，一次执行可绑定多份样品。'"><template #actions><el-button :loading="loading" @click="load">刷新</el-button><el-button v-if="auth.canWrite" type="primary" @click="create">新建{{ noun }}</el-button></template></PageHeading>
<p v-if="!auth.canWrite" class="readonly-note">当前为只读账户，可查看计划、执行和样品历史。</p>
<section class="panel"><form class="toolbar" @submit.prevent="search"><el-input v-model="filters.keyword" class="search-input" placeholder="搜索编码 / 计划标题" aria-label="关键词" clearable /><el-select v-model="filters.batch_id" filterable clearable class="filter-select" placeholder="全部批次" aria-label="批次"><el-option v-for="b in lookup.batches" :key="b.batch_id" :value="b.batch_id" :label="relationName('batches',b.batch_id)" /></el-select>
<template v-if="isPlan"><el-select v-model="filters.status" class="filter-select" clearable placeholder="计划状态" aria-label="计划状态"><el-option v-for="s in planStatuses" :key="s" :value="s" :label="label(s)" /></el-select><el-select v-model="filters.priority" class="filter-select" clearable placeholder="优先级" aria-label="优先级"><el-option v-for="s in ['high','normal','low']" :key="s" :value="s" :label="label(s)" /></el-select></template>
<template v-else><el-select v-model="filters.plan_id" filterable clearable class="filter-select" placeholder="全部计划" aria-label="计划"><el-option v-for="p in lookup.plans.filter(p=>!filters.batch_id||p.batch_id===Number(filters.batch_id))" :key="p.plan_id" :value="p.plan_id" :label="relationName('plans',p.plan_id)" /></el-select><el-select v-model="filters.process_mode" class="filter-select" clearable placeholder="执行模式" aria-label="执行模式"><el-option v-for="s in modes" :key="s" :value="s" :label="label(s)" /></el-select><el-select v-model="filters.log_status" class="filter-select" clearable placeholder="日志状态" aria-label="日志状态"><el-option v-for="s in ['ok','partial','aborted','unknown']" :key="s" :value="s" :label="label(s)" /></el-select><el-date-picker v-model="filters.date_from" type="datetime" placeholder="开始时间下限" aria-label="开始时间下限" /><el-date-picker v-model="filters.date_to" type="datetime" placeholder="开始时间上限" aria-label="开始时间上限" /></template><el-checkbox v-model="filters.include_voided" data-testid="include-voided" @change="search">包含已作废</el-checkbox><el-button native-type="submit" :loading="loading">筛选</el-button><el-button v-if="auth.canWrite" data-testid="batch-cleanup-open" :disabled="!selectedRows.length||batchCleanupBusy" :loading="batchCleanupBusy" @click="prepareBatchCleanup">批量清理未使用草稿</el-button></form>
<StatePanel v-if="error" title="列表加载失败" :description="error" tone="error"><el-button @click="load">重试</el-button></StatePanel>
<div v-else class="table-wrap" v-loading="loading"><el-table :data="rows" empty-text="暂无记录，调整筛选或创建记录" @selection-change="onSelection"><el-table-column type="selection" width="44" /><el-table-column :label="isPlan?'计划编码':'执行编码'" min-width="180"><template #default="{row}"><el-button link type="primary" @click="openDetail(row[idKey])">{{ row[isPlan?'plan_code':'process_code'] }}</el-button><div>{{ row.title }}</div></template></el-table-column><el-table-column label="状态 / 模式" min-width="140"><template #default="{row}">{{ label(row[isPlan?'status':'process_mode']) }}<div v-if="!isPlan" class="table-sub">日志：{{ label(row.log_status) }}</div><el-tag v-if="row.voided_at" type="danger">已作废</el-tag><el-tag v-if="!isPlan&&row.archived_at" type="info" data-testid="process-archived-badge">已归档</el-tag></template></el-table-column><el-table-column label="批次" min-width="160"><template #default="{row}">{{ relationName('batches',row.batch_id) }}</template></el-table-column><el-table-column :prop="isPlan?'priority':'plan_id'" :label="isPlan?'优先级':'计划'" min-width="100"><template #default="{row}">{{ isPlan?display(row.priority):relationName('plans',row.plan_id) }}</template></el-table-column><el-table-column label="操作" min-width="170"><template #default="{row}"><el-button link type="primary" @click="openDetail(row[idKey])">查看详情</el-button><el-button v-if="auth.canWrite" link type="primary" :disabled="saving||gridSaving" @click="openLifecycleFromRow(row)">生命周期</el-button></template></el-table-column></el-table></div>
<div class="pagination"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[10,20,50,100]" :total="total" layout="prev, pager, next, sizes" @current-change="load" @size-change="search" /></div></section>
<section v-if="selectedId" class="panel experiment-detail"><div class="panel-title"><h2>实验详情</h2><el-button :disabled="saving" :loading="detailLoading" @click="refreshDetail">刷新详情</el-button></div><div class="panel-body"><el-skeleton v-if="detailLoading" :rows="7" animated /><StatePanel v-else-if="detailError" title="详情加载失败" :description="detailError" tone="error"><el-button @click="refreshDetail">重试详情</el-button></StatePanel><template v-else-if="detail">
<div class="detail-title"><h2>{{ isPlan?detail.title:(detail.plan?.title||detail.process_code) }}</h2><el-button v-if="!isPlan&&writable" :disabled="saving" @click="renameExecution">修改执行编号</el-button><el-tag v-if="!isPlan&&detail.archived_at" type="info" data-testid="process-detail-archived-badge">已归档</el-tag><el-tag v-if="isPlan" :type="detail.status==='archived'?'info':'success'">{{ label(detail.status) }}</el-tag><el-button v-if="writable" type="primary" @click="edit">编辑基本信息</el-button><el-button v-if="isPlan&&auth.canWrite" @click="runPlan">选样品并创建执行</el-button><el-tag v-if="detail.voided_at" type="danger" data-testid="detail-voided-badge">已作废</el-tag><el-button v-if="writable" data-testid="lifecycle-open" :disabled="saving||gridSaving" @click="openLifecycle">生命周期 / 删除影响</el-button></div>
<p v-if="isPlan&&detail.status==='archived'" class="readonly-note">该计划已归档：历史与关联执行保留，可继续查看；如需重新启用请打开生命周期预览并恢复。</p>
<p v-if="!isPlan&&detail.archived_at" class="readonly-note" data-testid="process-archived-time">归档时间：{{ display(detail.archived_at) }}。历史记录与关联保留，日志状态：{{ label(detail.log_status) }}。</p>
<p v-if="isPlan">研究目的：{{detail.objective||'未记录'}}</p><p v-if="isPlan">复盘备注：{{detail.notes||'尚未记录复盘；系统不自动生成科学结论'}}</p><p v-if="!isPlan&&detail.plan">研究目的：{{detail.plan.objective||'未记录'}} · 计划日期 {{detail.plan.planned_start||'未记录'}}</p><div v-if="detail.quick_record_url" class="readonly-note">此执行使用极简快录参数与匿名结果；请在<RouterLink :to="detail.quick_record_url">实验快录中查看完整步骤、结果及修订</RouterLink>。此处保留原执行身份与专业信息。</div><ExperimentResults v-else :runs="isPlan?detail.processes:[detail]" :writable="auth.canWrite"/>
<details><summary>继续记录与基本信息、技术溯源</summary><FormSection title="实验进度" description="状态来自已保存数据，点击节点继续记录。">
<div data-testid="detail-workflow" class="detail-workflow">
<el-skeleton v-if="workflowLoading" :rows="2" animated />
<StatePanel v-else-if="workflowError" title="实验进度加载失败" :description="workflowError" tone="error"><el-button @click="loadWorkflow(selectedId!)">重试进度</el-button></StatePanel>
<template v-else-if="workflow"><WorkflowProgress :active="-1" :stages="workflow.stages" :disabled="saving||gridSaving" @select="continueWorkflow" /><el-button data-testid="workflow-continue" :disabled="saving||gridSaving" @click="continueWorkflow(Math.max(0,workflow.stages.findIndex((s:Row)=>s.status!=='saved')))">继续记录实验</el-button></template>
</div></FormSection>
<dl class="detail-grid"><div v-for="f in fields" :key="f.key"><dt>{{ f.label }}</dt><dd>{{ relationKeys.includes(f.key)?relationName(f.key==='plan_id'?'plans':f.key==='tool_id'?'tools':'batches',detail[f.key]):display(detail[f.key]) }}</dd></div></dl>
</details><FormSection :title="isPlan?'计划步骤与计划参数':'实际步骤与实际参数'" :description="isPlan?'以下为计划条件，不能视为实际测量。步骤与参数统一在流程网格中维护；已被执行映射的步骤由接口保护。':'以下为实际记录。步骤与参数统一在流程网格中维护；映射计划步骤不会复制计划值。'"><el-button v-if="writable" type="primary" data-testid="edit-process-grid" :disabled="saving" @click="openGrid">编辑流程网格</el-button><ProcessGrid :model-value="gridDraft(detail,isPlan)" :planned="isPlan" readonly /><StatePanel v-if="!detail.steps?.length" title="尚无步骤" description="在流程网格中添加步骤列。" />
<details v-if="detail.steps?.length"><summary>步骤说明与计划映射溯源</summary><div class="step-summary-list" data-testid="step-summary-list"><h4>步骤说明与计划映射</h4><article v-for="s in detail.steps" :key="s.step_id" class="experiment-step step-summary"><div class="experiment-step-title"><strong>{{ stepTitle(s) }} <small>步骤 #{{ s.step_id }} · {{ label(s.step_kind) }}</small></strong><span v-if="!isPlan">映射计划步骤：{{ s.plan_step_id?`#${s.plan_step_id}`:'未映射' }}</span></div><p class="field-hint">{{ s.step_note||'未填写步骤说明' }}</p></article></div></details></FormSection>
<FormSection v-if="isPlan" title="此计划的执行" description="同一个计划可以创建多次执行。"><p v-if="!detail.processes?.length" class="field-hint">尚无执行。</p><router-link v-for="p in detail.processes" :key="p.process_id" class="workflow-link" :to="{path:'/processes',query:{process_id:p.process_id}}">{{ p.process_code }} · {{ label(p.process_mode) }}</router-link></FormSection>
<details v-if="!isPlan"><summary>参与样品管理与原始装卸记录</summary><FormSection title="样品绑定与装卸" description="绑定仅表示参与此次执行，不等于装载。请到样品历史分别追加 load / unload；同一样品可参与多次执行。"><el-button v-if="writable" data-testid="batch-bind-open" :disabled="saving" @click="openBindingBatch">批量绑定样品</el-button><el-button v-if="writable" :disabled="saving" @click="newChild('binding')">绑定单个样品（可附加逐条差异）</el-button><StatePanel v-if="!detail.samples?.length" title="尚未绑定样品" description="先绑定样品，再为它记录实际装载和卸载。" /><article v-for="s in detail.samples" :key="s.process_sample_id" class="experiment-step"><div class="experiment-step-title"><strong>{{ s.sample?.sample_code || `样品 #${s.sample_id}` }}</strong><el-tag>{{ label(s.sample?.status) }}</el-tag><span>{{ s.batch?.batch_code ? `批次 ${s.batch.batch_code}` : '批次未记录' }}</span><el-tag :type="s.participation_status==='unloaded'?'success':'info'">{{ participationLabels[s.participation_status]||s.participation_status }}</el-tag><el-tag v-if="s.execution_evidence==='not_confirmed'" type="warning">仅绑定，未确认处理</el-tag><el-tag v-if="s.execution_evidence==='voided'" type="danger">执行已作废，不计累计</el-tag><el-button type="primary" link @click="sampleDetail(s)">查看样品详情</el-button><el-button type="primary" link @click="history(s)">完整科研履历 / 装卸记录</el-button><template v-if="writable"><el-button link :disabled="saving" @click="newChild('binding',s)">编辑绑定</el-button><el-button link type="danger" :disabled="saving" @click="removeChild('binding',s)">解除绑定</el-button></template></div><dl class="parameter-grid"><div><dt>本次循环</dt><dd>{{ s.cycles_confirmed ? s.full_ale_cycles : '未确认' }}<span v-if="!s.cycles_confirmed&&s.full_ale_cycles!=null">（填写值 {{s.full_ale_cycles}}，未计入累计）</span></dd></div><div><dt>按体系累计</dt><dd><CycleSummary :summary="{recorded_cycles:s.cumulative_recorded_cycles,recorded_participations:s.cumulative_participations-s.cumulative_missing_participations,missing_participations:s.cumulative_missing_participations,cycle_groups:s.cycle_groups}"/></dd></div><div><dt>装载节点</dt><dd>{{ eventNode(s.load_event) }}</dd></div><div><dt>取出节点</dt><dd>{{ eventNode(s.unload_event) }}</dd></div><div><dt>测量记录</dt><dd>{{ s.measurement_count }} 条<span v-if="s.measurements?.length">：<router-link v-for="m in s.measurements" :key="m.measurement_id" :to="{path:'/measurements',query:{id:m.measurement_id}}">{{m.measurement_code}} </router-link></span></dd></div><div v-for="f in bindingFields.filter(f=>f.key!=='sample_id'&&f.key!=='full_ale_cycles')" :key="f.key"><dt>{{ f.label }}</dt><dd>{{ display(s[f.key]) }}</dd></div></dl></article></FormSection></details>
</template></div></section>
<el-dialog v-model="batchCleanupOpen" title="批量清理未使用草稿" width="min(760px,96vw)" append-to-body destroy-on-close>
<el-alert v-if="batchCleanupError" :title="batchCleanupError" type="error" :closable="false" />
<p class="field-hint">只处理后端影响预览判定为可删除的未使用草稿；有测量、流转、原件、共享引用或其他依赖的记录会保留，并显示原因。</p>
<el-table :data="batchCleanupRows" data-testid="batch-cleanup-table"><el-table-column label="记录" min-width="150"><template #default="{ row }">{{ row.row[isPlan?'plan_code':'process_code'] }}</template></el-table-column><el-table-column label="影响预览" min-width="220"><template #default="{ row }"><el-tag :type="row.impact.delete_permitted?'success':'info'">{{ row.impact.delete_permitted?'可删除':'保留' }}</el-tag><div class="table-sub">{{ row.impact.delete_permitted?'无依赖未使用草稿':`关联 ${row.impact.dependencies_total_visible} 项；状态或权限不允许删除` }}</div></template></el-table-column></el-table>
<template #footer><div class="form-footer"><el-button :disabled="batchCleanupBusy" @click="batchCleanupOpen=false">取消</el-button><el-button type="danger" data-testid="batch-cleanup-apply" :loading="batchCleanupBusy" :disabled="!batchCleanupRows.some(item=>item.impact.delete_permitted&&(item.impact.actions||[]).includes('delete'))" @click="applyBatchCleanup">确认删除符合条件的草稿</el-button></div></template>
</el-dialog>
<LifecycleDialog v-model="lifecycleOpen" :kind="kind" :id="selectedId" :row-version="detail?.row_version" :code="detail?.[isPlan?'plan_code':'process_code']" @applied="lifecycleApplied" />
<el-drawer v-model="editor" :title="`${creating?'创建':'编辑'}${noun}`" size="min(820px,100vw)" :before-close="closeEditor" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close><el-alert v-if="formError" :title="formError" type="error" :closable="false" class="drawer-alert" /><el-alert v-if="conflict" title="记录版本或依赖冲突，输入已保留。请刷新版本并核对最新详情后再保存。" type="warning" :closable="false"><el-button @click="reloadParent">刷新版本并保留输入</el-button></el-alert><el-form label-position="top" @submit.prevent="save"><FormSection title="基本信息" :description="isPlan?'计划日期可以未知。计划信息与实际执行记录分别维护。':'时间和数值可空，未填写即保持为空；十进制数使用普通字符串。'"><ExperimentFields :fields="inputFields.filter(f=>creating||!['plan_code','process_code'].includes(f.key))" :model="form" :disabled="saving" /><el-alert v-if="lookupError" :title="lookupError" type="error" :closable="false"><el-button @click="loadLookups">重试关联选项</el-button></el-alert><div class="form-grid"><el-form-item label="批次（可空）"><el-select v-model="form.batch_id" filterable clearable :disabled="saving" @change="selectBatch"><el-option v-if="form.batch_id&&!lookup.batches.some(b=>b.batch_id===Number(form.batch_id))" :value="form.batch_id" :label="relationName('batches',form.batch_id)" /><el-option v-for="b in lookup.batches" :key="b.batch_id" :value="b.batch_id" :label="relationName('batches',b.batch_id)" /></el-select></el-form-item><template v-if="!isPlan"><el-form-item label="关联计划（可空）"><el-select v-model="form.plan_id" filterable clearable :disabled="saving" @change="selectPlan"><el-option v-if="form.plan_id&&!availablePlans.some(p=>p.plan_id===Number(form.plan_id))" :value="form.plan_id" :label="relationName('plans',form.plan_id)" /><el-option v-for="p in availablePlans" :key="p.plan_id" :value="p.plan_id" :label="relationName('plans',p.plan_id)" /></el-select></el-form-item><el-form-item label="设备（可空）"><el-select v-model="form.tool_id" filterable clearable :disabled="saving"><el-option v-if="form.tool_id&&!lookup.tools.some(t=>t.tool_id===Number(form.tool_id))" :value="form.tool_id" :label="relationName('tools',form.tool_id)" /><el-option v-for="t in lookup.tools" :key="t.tool_id" :value="t.tool_id" :label="relationName('tools',t.tool_id)" /></el-select></el-form-item></template></div></FormSection>
<FormSection v-if="!isPlan" title="化学体系（可选）" description="关联「化学体系」页维护的体系；未选择表示未维护。化学体系属于整条执行记录，与单个步骤无关。"><p v-if="chemistryError" class="field-hint danger-text" role="alert">化学体系加载失败：{{ chemistryError }} <el-button link type="primary" @click="loadChemistry">重试</el-button></p><el-select v-else v-model="formChemistry" clearable :loading="chemistryLoading" :disabled="saving" placeholder="未选择化学体系" style="width:100%" data-testid="process-chemistry"><el-option v-for="system in chemistrySystems" :key="system.system_id" :value="system.system_id" :label="`${system.system_code} · ${system.system_name}`" /></el-select><p class="field-hint">不选择即保持为空；已有历史执行里的化学体系关联不会被改写。</p></FormSection>
<FormSection v-if="creating&&isPlan" title="计划步骤与参数（可选）" description="先编排流程草稿；保存时创建计划基本信息，再保存流程。若流程保存失败，保留草稿并单独重试，不会重复创建计划。"><el-button :disabled="saving" data-testid="create-process-grid" @click="openGrid">编辑流程网格</el-button><p v-if="!draftSteps.length" class="field-hint">尚未添加计划步骤。</p><p v-for="(s,i) in draftSteps" :key="i" class="field-hint">{{ stepTitle(s) }}</p></FormSection><template v-if="creating&&!isPlan"><el-alert v-if="inherited" data-testid="plan-inherit-note" type="info" :closable="false" title="已从计划继承步骤与样品范围，请填写实际发生情况" description="计划参数值不会被复制：只继承步骤结构与计划映射，实际值与重复次数保持未记录，请在流程网格中独立填写。" />
<FormSection title="选择参与样品（支持多选）" description="从真实样品列表搜索选择，可排除已绑定的样品。绑定不等于装载，请到样品历史记录装载/卸载。"><SamplePicker v-model="selectedSamples" :batch-id="form.batch_id||null" :disabled="saving" placeholder="按编码 / 显示编号搜索样品" /><p class="field-hint">样品候选按计划批次自动加载，默认不勾选；同一执行不能重复绑定同一样品。</p></FormSection><FormSection title="实际步骤（可选）" description="步骤与参数统一在流程网格中维护；从计划继承时只复制结构，实际值与重复次数保持未记录。"><el-button v-if="auth.canWrite" :disabled="saving" data-testid="create-process-grid" @click="openGrid">编辑流程网格</el-button><p v-if="!draftSteps.length" class="field-hint">尚未添加实际步骤；保存执行后也可继续编辑流程网格。</p><p v-for="(s,i) in draftSteps" :key="i" class="field-hint">{{ stepTitle(s) }} · 映射计划步骤 {{ s.plan_step_id?`#${s.plan_step_id}`:'未映射' }}</p></FormSection></template></el-form><template #footer><div class="form-footer"><el-button :disabled="saving" @click="closeEditor()">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving||conflict" @click="save">保存{{ noun }}</el-button></div></template></el-drawer>
<el-dialog v-model="gridOpen" class="process-grid-dialog" :title="isPlan?'计划流程网格':'实际流程网格'" width="min(1380px,98vw)" top="3vh" :before-close="closeGrid" :close-on-click-modal="false" :close-on-press-escape="!gridSaving" :show-close="!gridSaving" destroy-on-close append-to-body><el-alert v-if="gridError" :title="gridError" type="error" :closable="false"/><el-alert v-if="gridConflict" title="版本或历史依赖冲突，网格输入已保留。关闭后刷新详情、核对最新流程再编辑。" type="warning" :closable="false"/><ProcessGrid v-model="grid" :planned="isPlan" :plan-options="isPlan?[]:planOptions" :disabled="gridSaving"/><template #footer><el-button :disabled="gridSaving" @click="closeGrid()">取消</el-button><el-button type="primary" data-testid="save-process-grid" :loading="gridSaving" :disabled="gridSaving||gridConflict" @click="saveGrid">保存流程与参数</el-button></template></el-dialog>
<el-dialog v-model="childOpen" title="样品绑定" width="min(800px,96vw)" :before-close="closeChild" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close append-to-body><el-alert v-if="childError" :title="childError" type="error" :closable="false" /><el-alert v-if="childConflict" title="输入已保留。刷新父版本后核对再重试；历史依赖冲突可能需要调整操作。" type="warning" :closable="false"><el-button @click="reloadChildVersion">刷新父版本并保留输入</el-button></el-alert><el-form label-position="top"><ExperimentFields :fields="childFields" :model="childForm" :disabled="saving" /><FormSection v-if="!childId" title="选择要绑定的样品" description="从真实样品列表搜索选择；已绑定的样品不可重复选择。绑定不等于装载，请到样品历史记录装载/卸载。"><SamplePicker v-model="childSampleId" :batch-id="detail?.batch_id??null" :exclude-ids="[...boundSampleIds]" :multiple="false" :disabled="saving" placeholder="按编码 / 显示编号搜索样品" testid="child-sample-picker" /></FormSection><p v-else class="field-hint">样品不可更改；如需更换请先解除绑定，再重新绑定。</p></el-form><template #footer><el-button :disabled="saving" @click="closeChild()">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving||childConflict" @click="saveChild">保存</el-button></template></el-dialog>
<el-dialog v-model="bindingOpen" title="批量绑定样品" width="min(760px,96vw)" :before-close="closeBinding" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close append-to-body data-testid="batch-bind-dialog"><el-alert v-if="bindingError" :title="bindingError" type="error" :closable="false" /><el-alert v-if="bindingConflict" title="绑定冲突，输入已保留。刷新执行详情后核对样品与版本再重试。" type="warning" :closable="false"><el-button data-testid="binding-conflict-recover" :loading="saving" @click="recoverBindingConflict">刷新执行详情并保留输入</el-button></el-alert><el-form label-position="top"><FormSection title="选择样品（支持多选）" description="从真实样品列表选择，已绑定的样品不可重复选择。绑定不等于装载，请到样品历史记录装载/卸载。"><SamplePicker v-model="bindingIds" :batch-id="detail?.batch_id??null" :exclude-ids="[...boundSampleIds]" :disabled="saving" placeholder="按编码 / 显示编号搜索样品" /><p class="field-hint">公共附加字段对每条绑定相同；单条差异请在绑定后用「编辑绑定」修改。</p></FormSection>
<FormSection title="公共绑定属性（可选）" description="未填写即保持为空；对照样品与角色备注用于区分实验角色。"><div class="form-grid"><el-form-item label="腔体位置"><el-input v-model="bindingCommon.chamber_position" maxlength="64" :disabled="saving" /></el-form-item><el-form-item label="对照样品"><el-switch v-model="bindingCommon.is_control" :disabled="saving" /></el-form-item><el-form-item label="样品完整 ALE 循环数"><el-input v-model="bindingCommon.full_ale_cycles" inputmode="numeric" :disabled="saving" /></el-form-item><el-form-item label="样品角色备注" class="span-2"><el-input v-model="bindingCommon.sample_role_note" type="textarea" :rows="2" maxlength="20000" :disabled="saving" /></el-form-item></div></FormSection></el-form><template #footer><el-button :disabled="saving" @click="closeBinding()">取消</el-button><el-button type="primary" data-testid="batch-bind-submit" :loading="saving" :disabled="saving||bindingConflict||!bindingIds.length" @click="saveBindingBatch">绑定所选样品</el-button></template></el-dialog>
</div></template>
<style scoped>
.detail-workflow{min-width:0;max-width:100%;overflow:hidden}
.step-summary-list{margin-top:18px;border-top:1px solid var(--line);padding-top:12px}
.step-summary-list h4{margin:0 0 6px;font-size:14px}
.step-summary{padding:10px 0}
.step-summary .field-hint{margin:4px 0 0;white-space:pre-wrap}
</style>

<style>
.process-grid-dialog{display:flex;flex-direction:column;max-height:94dvh;margin-bottom:3vh;overflow:hidden}.process-grid-dialog>.el-dialog__header,.process-grid-dialog>.el-dialog__footer{flex-shrink:0}.process-grid-dialog>.el-dialog__body{min-height:0;overflow:auto;overscroll-behavior:contain}.process-grid-dialog .process-matrix{min-width:375px}
</style>

