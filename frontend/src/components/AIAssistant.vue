<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { MessageSquareText, X, RotateCcw } from 'lucide-vue-next'
import { useAuth } from '../auth'
import { api, ApiError } from '../api'
type Context = {kind: 'sample'|'batch'|'plan'|'process'|'measurement'|'none'; id?: number}
type Source = {kind:string;id:number;href:string}
type Result = {status:'completed'|'failed'|'pending';conversation_id?:string;answer?:string|null;sources:Source[];tool_trace:{tool:string;status:string;sources:Source[];read_only:boolean;result_bytes:number;origin?:'current_context'|'prior_plan'|'model'}[];usage?:{charged_cost:string;currency:string;charged_tokens:number;prompt_tokens:number;completion_tokens:number;cache_hit_tokens:number;cache_miss_tokens:number;provider_calls:number;estimated:boolean};recovery?:{recovered:boolean;reconciliation_required:boolean};error?:{code:string};replayed?:boolean}
type RequestAccount={request_id:string;status:string;lease_expires_at?:string;usage_estimated:boolean;charged_cost:string;charged_tokens:number;reconciled:boolean;recovery?:{at?:string;unknown_calls?:number}}
type Body = {request_id:string;conversation_id?:string;message:string;context:Context}
type Turn = {body:Body;result?:Result;state:'sending'|'unknown'|'failed'|'pending'|'completed';notice?:string;account?:RequestAccount}
const auth=useAuth(),route=useRoute(),open=ref(false),consent=ref(false),includeContext=ref(false),question=ref(''),conversation=ref<string>(),turns=ref<Turn[]>([]),busy=ref(false),status=ref<{enabled:boolean;configured:boolean}|null>(null),statusError=ref(false),log=ref<HTMLElement>(),trigger=ref<HTMLButtonElement>()
const props = defineProps<{ navigationOpen?: boolean }>()
const emit = defineEmits<{ 'open-change': [value: boolean]; 'blocked-change': [value: boolean] }>()
const obstructed = ref(true)
const externalModal = ref(false)
let observer: MutationObserver | undefined
let frame = 0
let opener: HTMLElement | null = null
let disposed = false
function visible(element: Element) {
  const rect = element.getBoundingClientRect()
  const style = getComputedStyle(element)
  return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden'
}
function scanPlacement() {
  frame = 0
  if (disposed) return
  // Include overlays during enter/leave transitions and drawers with modal=false.
  externalModal.value = Array.from(document.querySelectorAll('.el-overlay, .el-dialog, .el-drawer, .el-message-box, [aria-modal="true"], dialog[open]'))
    .some(el => !el.matches('.ai-drawer') && !el.closest('.ai-drawer') && !el.querySelector('.ai-drawer') && visible(el))
  const right = window.innerWidth - 24, bottom = window.innerHeight - 24
  // Reserve the complete launcher footprint even while it is hidden.
  const overlap = Array.from(document.querySelectorAll('.page-main button, .page-main a, .page-main input, .page-main select, .page-main textarea, .page-main .el-select, .page-main .el-table, .page-main [data-testid="scientific-plot"], .form-footer, [data-bottom-actions]'))
    .some(el => {
      if (!visible(el)) return false
      const r = el.getBoundingClientRect()
      return r.left < right + 8 && r.right > right - 160 && r.top < bottom + 8 && r.bottom > bottom - 56
    })
  obstructed.value = externalModal.value || overlap || window.innerWidth <= 760 || window.innerHeight < 560 || !!props.navigationOpen
  if (externalModal.value && open.value) open.value = false
}
function schedulePlacement() { if (!disposed && !frame) frame = requestAnimationFrame(scanPlacement) }
watch(() => props.navigationOpen, schedulePlacement)
watch(open, value => { emit('open-change', value); schedulePlacement() })
watch(externalModal, value => emit('blocked-change', value))
onMounted(() => {
  scanPlacement()
  observer = new MutationObserver(schedulePlacement)
  observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style', 'hidden', 'open', 'aria-hidden', 'aria-modal'] })
  window.addEventListener('resize', schedulePlacement)
  window.addEventListener('scroll', schedulePlacement, true)
  document.addEventListener('transitionend', schedulePlacement, true)
  document.addEventListener('animationend', schedulePlacement, true)
})
onBeforeUnmount(() => {
  disposed = true
  observer?.disconnect()
  cancelAnimationFrame(frame)
  window.removeEventListener('resize', schedulePlacement)
  window.removeEventListener('scroll', schedulePlacement, true)
  document.removeEventListener('transitionend', schedulePlacement, true)
  document.removeEventListener('animationend', schedulePlacement, true)
})
function restoreFocus() {
  scanPlacement()
  if (externalModal.value) return
  const target = opener?.isConnected && visible(opener) ? opener : document.querySelector<HTMLElement>('.header-assistant')
  target?.focus()
}
defineExpose({ show })
let epoch=0
const labels:Record<string,string>={sample:'样品',batch:'批次',plan:'计划',process:'执行',measurement:'测量',source_file:'原始文件',transition:'流转历史'}
const context=computed<Context>(()=>{
  const map:Record<string,[Context['kind'],string]>={'/samples':['sample','sample_id'],'/batches':['batch','batch_id'],'/plans':['plan','plan_id'],'/processes':['process','process_id'],'/measurements':['measurement','id']}
  const entry=map[route.path];if(!entry||route.query.create==='1')return {kind:'none'}
  const raw=route.query[entry[1]]??(entry[0]==='measurement'?route.query.measurement_id:undefined)
  if(typeof raw!=='string'||!/^[1-9]\d*$/.test(raw)||!Number.isSafeInteger(Number(raw)))return {kind:'none'}
  return {kind:entry[0],id:Number(raw)}
})
watch(()=>route.fullPath,()=>{includeContext.value=false})
const unresolved=computed(()=>turns.value.some(t=>['unknown','pending','sending'].includes(t.state)))
const available=computed(()=>status.value?.enabled&&status.value.configured)
function trusted(s:Source){const routes:Record<string,[string,string]>={sample:['samples','sample_id'],batch:['batches','batch_id'],plan:['plans','plan_id'],process:['processes','process_id'],measurement:['measurements','id'],source_file:['source-files','id'],transition:['sample-history','sample_id']};const r=routes[s.kind];return !!r&&Number.isSafeInteger(s.id)&&s.id>0&&s.href===`/${r[0]}?${r[1]}=${s.id}`}
function safeSources(s:Source[]|undefined){return (s??[]).filter(trusted)}
function reason(code?:string){return ({provider_insufficient_balance:'模型服务余额不足，请管理员核对服务商账户余额。',provider_auth_failed:'模型服务认证失败，请管理员检查 API Key、余额、模型权限及配置。',provider_permission_denied:'模型服务拒绝访问，请管理员核对模型权限。',provider_rate_limited:'模型服务限流或额度不足，请管理员核对余额和调用额度。',provider_parameter_invalid:'模型服务参数不兼容，请管理员检查配置。',provider_rejected:'模型服务拒绝请求，请管理员检查 API Key、余额、模型权限及配置。',provider_connect_failed:'无法连接模型服务，请稍后由你手动重试。',authorization_changed:'账户权限或记录已变化，请重新登录并核对记录。',configuration_changed:'AI 配置已变化，请核对设置后重新提问。',evidence_unavailable:'旧请求缺少可验证证据，答案已隐藏；原请求未重复计费。',request_recovered:'中断请求已恢复，未重新调用模型。未知费用仍保守记账，可由管理员凭账单核对；可以开始新会话。',request_in_progress:'请求仍在处理中。请使用原请求查询结果。',ai_unavailable:'AI 暂时不可用，科学记录功能仍可正常使用。',tool_round_limit:'已达到只读查询轮数上限，请缩小问题范围。',turn_time_limit:'请求达到时间限制，请缩小问题范围。'} as Record<string,string>)[code??'']??'请求未完成，请管理员检查模型服务、额度和配置；问题已保留。'}
async function loadStatus(){const ticket=epoch;try{const {data}=await api<{enabled:boolean;configured:boolean}>('/ai/status');if(ticket!==epoch)return;status.value=data;statusError.value=false}catch{if(ticket===epoch){status.value=null;statusError.value=true}}}
function reset(){epoch++;turns.value=[];conversation.value=undefined;question.value='';consent.value=false;includeContext.value=false;busy.value=false;status.value=null;statusError.value=false}
watch(()=>[auth.sessionEpoch,auth.user?.user_id,auth.user?.role,auth.dataScope],()=>{reset();open.value=false;if(auth.user)void loadStatus()},{immediate:true})
onBeforeUnmount(reset)
async function show(){scanPlacement();if(externalModal.value)return;opener=document.activeElement instanceof HTMLElement?document.activeElement:null;open.value=true;void loadStatus()}
function close(){open.value=false}
function fresh(){if(busy.value||unresolved.value)return;reset();void loadStatus()}
function originLabel(origin?:string){return ({current_context:'当前页面记录',prior_plan:'既往查询重新读取',model:'模型发起查询'} as Record<string,string>)[origin??'']??'查询来源未标记'}
async function lookup(t:Turn){
 if(busy.value)return
 const ticket=epoch;busy.value=true;t.notice=''
 try{const {data}=await api<RequestAccount>(`/ai/requests/${t.body.request_id}`);if(ticket!==epoch)return;t.account=data
  if(data.status==='pending'){t.state='pending';t.notice='原请求仍在处理，执行期限见状态详情；可继续查询原 ID。'}
  else if(data.recovery||data.status==='failed'){t.state='failed';t.notice=data.recovery?reason('request_recovered'):'原请求已终结。可开始新会话；重新提问将创建新请求。'}
  else {busy.value=false;await deliver(t);return}
 }catch(e){if(ticket!==epoch)return;if(e instanceof ApiError&&e.status===404){busy.value=false;await deliver(t);return}t.notice='无法查询原请求状态，请保留原 ID 后重试；未创建新请求。'}finally{if(ticket===epoch)busy.value=false}
}
async function deliver(t:Turn){
  if(busy.value||!consent.value)return
  const ticket=epoch;busy.value=true;t.state='sending';t.notice=''
  try{const {data}=await api<Result>('/ai/chat',{method:'POST',body:t.body});if(ticket!==epoch)return
    t.result=data;if(data.recovery?.recovered)t.notice=reason('request_recovered');conversation.value=data.conversation_id??conversation.value;t.state=data.status
    if(data.error)t.notice=reason(data.error.code)
  }catch(e){if(ticket!==epoch)return
    const known=e instanceof ApiError&&e.status>=400&&e.status<500
    t.state=known?'failed':'unknown'
    t.notice=known?(e instanceof ApiError&&e.status===429?'已达到调用次数、预算或 Token 上限，请联系管理员调整或等待额度恢复。':e instanceof ApiError&&e.status===409?'AI 未配置、已停用或会话存在待处理请求。请核对状态。':'请求被拒绝，请检查登录状态和输入。'):'连接中断，是否已计费未知。请保留原请求 ID 查询，不要重复提交。'
  }finally{if(ticket===epoch){busy.value=false;await nextTick();log.value?.scrollTo({top:log.value.scrollHeight})}}
}
async function send(){if(!question.value.trim()||!consent.value||!available.value||busy.value||unresolved.value)return;const t:Turn={body:{request_id:crypto.randomUUID(),...(conversation.value?{conversation_id:conversation.value}:{}),message:question.value.trim(),context:includeContext.value?{...context.value}:{kind:'none'}},state:'sending'};turns.value.push(t);question.value='';await deliver(turns.value[turns.value.length-1]!)}
async function retry(t:Turn){if(t.state!=='failed'||busy.value||unresolved.value)return;const copy:Turn={body:{...t.body,request_id:crypto.randomUUID(),...(conversation.value?{conversation_id:conversation.value}:{})},state:'sending'};turns.value.push(copy);await deliver(turns.value[turns.value.length-1]!)}
</script>
<template>
  <button v-show="!open && !obstructed" ref="trigger" class="ai-launch" type="button" :aria-expanded="open" aria-controls="ai-research-drawer" @click="show"><MessageSquareText :size="18"/>研究助手</button>
  <el-drawer v-model="open" id="ai-research-drawer" title="研究助手" size="min(480px, 100vw)" :modal="true" :show-close="false" :with-header="true" class="ai-drawer" @closed="restoreFocus">
    <template #header><div class="ai-heading"><div><strong>研究助手</strong><span>只读检索 · 来源可核对</span></div><button aria-label="关闭研究助手" class="ai-icon" @click="close"><X :size="20"/></button></div></template>
    <div class="ai-content">
      <div class="ai-notice">每轮重新读取你有权查看的记录。服务端最多参考最近两轮问题（每轮1000字）和四个既往查询，并按当前权限重新读取记录，支持“刚才那个样品”等追问；旧模型回答不会发送给模型。助手不能修改实验数据。</div>
      <div v-if="!available" class="ai-warning" role="status">{{ statusError?'AI 状态暂时无法获取。':'AI 尚未配置或未启用。' }} 实验记录页面可继续使用。<button @click="loadStatus">刷新状态</button><router-link v-if="auth.isAdmin" to="/ai-settings" @click="close">打开 AI 设置</router-link></div>
      <div ref="log" class="ai-log" aria-live="polite" aria-label="本次会话">
        <div v-if="!turns.length" class="ai-empty"><MessageSquareText :size="30"/><h3>从一条可核对的记录开始</h3><p>例如：总结当前样品有哪些测量记录，并指出缺失的信息。</p></div>
        <article v-for="t in turns" :key="t.body.request_id" class="ai-turn">
          <div class="ai-question"><strong>你</strong><p>{{t.body.message}}</p><small>{{t.body.context.kind==='none'?'未附带页面记录':`${labels[t.body.context.kind]} #${t.body.context.id}`}}</small></div>
          <div class="ai-answer"><strong>研究助手</strong><p v-if="t.result?.answer" class="ai-plain">{{t.result.answer}}</p><p v-if="t.state==='sending'">正在只读核对记录…</p><p v-if="t.notice" role="status">{{t.notice}}</p>
            <div class="ai-sources"><router-link v-for="s in safeSources(t.result?.sources)" :key="s.href" :to="s.href" @click="close">{{labels[s.kind]}} #{{s.id}}</router-link></div>
            <details v-if="t.result?.tool_trace?.length"><summary>查看只读查询（{{t.result.tool_trace.length}}）</summary><div v-for="(tool,i) in t.result.tool_trace" :key="i" class="ai-tool"><span>{{tool.tool}} · {{tool.status==='completed'?'已完成':'无授权结果'}} · 只读 · {{tool.result_bytes}} 字节 · {{originLabel(tool.origin)}}</span><router-link v-for="s in safeSources(tool.sources)" :key="s.href" :to="s.href" @click="close">{{labels[s.kind]}} #{{s.id}}</router-link></div></details>
            <small>请求 ID：{{t.body.request_id}}</small><small v-if="t.result?.usage">本地{{t.result.usage.estimated?'保守估算':'估算'}} {{t.result.usage.charged_cost}} {{t.result.usage.currency}} · {{t.result.usage.charged_tokens}} Token</small>
            <details v-if="t.result?.usage"><summary>查看本次用量</summary><p>输入 {{t.result.usage.prompt_tokens}} / 输出 {{t.result.usage.completion_tokens}} Token；缓存命中 {{t.result.usage.cache_hit_tokens}} / 未命中 {{t.result.usage.cache_miss_tokens}}；服务商调用 {{t.result.usage.provider_calls}} 次。</p><p>{{t.result.usage.estimated?'包含未知费用的保守估算':'按服务商返回 Token 与配置价格估算'}}，本地估算不等于服务商账单。</p></details><details v-if="t.account" open><summary>原请求状态</summary><p>{{t.account.status==='pending'?'处理中':t.account.recovery?'中断已恢复':'已终结'}}；执行期限 {{t.account.lease_expires_at??'未提供'}}；{{t.account.reconciled?'账务已核对':t.account.usage_estimated?'费用未知，保守记账':'已记录用量'}}：{{t.account.charged_cost}}（原请求币种） / {{t.account.charged_tokens}} Token。</p></details>
            <button v-if="['unknown','pending'].includes(t.state)" :disabled="busy" @click="lookup(t)">使用原请求 ID 查询结果</button>
            <template v-if="t.state==='failed'"><p class="ai-retry-note">重新提问将生成新请求 ID，可能再次计费；此前请求的服务商实际费用可能未知。</p><button :disabled="busy||unresolved||!consent" @click="retry(t)"><RotateCcw :size="13"/>重新提问（新请求）</button></template>
          </div>
        </article>
      </div>
      <form class="ai-compose" @submit.prevent="send">
        <label class="ai-check"><input v-model="consent" type="checkbox" :disabled="busy"/>允许本次会话发送问题和最小记录摘要给已配置模型服务</label>
        <p class="ai-disclosure">将外发本轮问题、有限的既往问题及重新查询的最小记录元数据；不发送原始文件或文件内容。请勿在问题中填写密钥或无关敏感信息。</p>
        <label class="ai-check"><input v-model="includeContext" type="checkbox" :disabled="context.kind==='none'||busy"/>{{context.kind==='none'?'当前页面没有选定记录':`附带当前${labels[context.kind]} #${context.id}`}}</label>
        <label for="ai-question" class="ai-input-label">你的问题</label><textarea id="ai-question" v-model="question" rows="3" maxlength="4000" placeholder="输入问题，可追问刚才的样品" :disabled="busy"/>
        <div class="ai-compose-actions"><button type="button" :disabled="busy||unresolved" @click="fresh">新会话</button><small>{{question.length}} / 4000</small><button class="ai-send" type="submit" :disabled="!consent||!available||busy||unresolved||!question.trim()">{{busy?'核对中…':'发送问题'}}</button></div>
      </form>
    </div>
  </el-drawer>
</template>
<style scoped>
.ai-launch{position:fixed;right:24px;bottom:24px;z-index:20;display:flex;align-items:center;gap:8px;background:var(--navy);color:white;border:1px solid #426b7e;border-radius:24px;padding:12px 18px;box-shadow:0 4px 18px #142b4329}.ai-heading{display:flex;justify-content:space-between;align-items:center;width:100%;color:var(--ink)}.ai-heading strong{font-size:19px}.ai-heading span{display:block;font-size:12px;color:var(--muted);margin-top:3px}.ai-icon{border:0;background:none;color:var(--muted);padding:8px}.ai-content{height:100%;display:flex;flex-direction:column;min-height:0;gap:14px;font-size:13px}.ai-notice{border-left:3px solid var(--teal);padding:0 12px;color:var(--muted);font-size:12px;line-height:1.7}.ai-warning{background:#fff7e8;padding:12px;border:1px solid #e8d5ad;border-radius:6px}.ai-warning button,.ai-warning a{display:inline-block;margin:6px 10px 0 0;color:var(--teal)}.ai-log{flex:1;overflow:auto;min-height:90px}.ai-empty{padding:30px 15px;color:var(--muted);line-height:1.8}.ai-empty svg{color:var(--teal)}.ai-empty h3{color:var(--ink);margin:15px 0 8px}.ai-turn{margin:0 0 22px;overflow-wrap:anywhere}.ai-turn p{margin:6px 0;white-space:pre-wrap;line-height:1.8}.ai-question{background:var(--soft);padding:12px 15px;border-radius:8px}.ai-question small,.ai-answer small{font-size:11px;color:var(--muted);display:block;margin-top:7px}.ai-answer{padding:14px 3px}.ai-answer>strong{color:var(--teal)}.ai-sources{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}.ai-sources a,.ai-tool a{color:var(--teal);border:1px solid #b7d9dd;border-radius:4px;padding:3px 7px;font-size:12px}.ai-answer details{border-top:1px solid var(--line);padding:9px 0;color:var(--muted);font-size:12px}.ai-answer summary{cursor:pointer}.ai-tool{display:flex;flex-wrap:wrap;gap:6px;padding:8px 0}.ai-tool span{width:100%}.ai-compose{border-top:1px solid var(--line);padding-top:14px}.ai-check{display:flex;align-items:flex-start;gap:7px;line-height:1.6;font-size:12px;margin-bottom:8px}.ai-check input{accent-color:var(--teal);margin-top:3px}.ai-disclosure{font-size:11px;color:var(--muted);line-height:1.6;margin:5px 0 10px}.ai-input-label{display:block;font-size:12px;margin:10px 0 5px}.ai-compose textarea{resize:vertical;min-height:70px;max-height:160px;width:100%;border:1px solid var(--line);border-radius:6px;padding:9px;font:inherit;color:var(--ink)}.ai-compose-actions{display:flex;gap:10px;align-items:center;margin-top:9px}.ai-compose-actions small{margin-left:auto;color:var(--muted);font-size:11px}.ai-content button:not(.ai-icon){border:1px solid var(--line);background:white;border-radius:5px;padding:6px 10px;color:var(--teal);display:inline-flex;gap:5px;align-items:center}.ai-content .ai-send{background:var(--teal)!important;color:white!important}.ai-content button:disabled{opacity:.5}.ai-retry-note{font-size:11px;color:#94600c}@media(max-width:760px){.ai-launch{display:none}.ai-notice{font-size:11px}.ai-content{gap:10px}.ai-compose{padding-top:10px}}
</style>
<style>.ai-drawer .el-drawer__body{padding:16px 22px;overflow:hidden}.ai-drawer .el-drawer__header{padding:18px 22px}.ai-drawer .el-drawer__title{display:block}@media(max-height:700px){.ai-drawer .el-drawer__body{overflow:auto}.ai-drawer .ai-content{height:auto}.ai-drawer .ai-log{max-height:42vh;flex:none}}</style>
