import { ref } from 'vue'
export interface Envelope<T> { code: number; message: string; data: T; request_id: string; timestamp: string; meta?: { page:number;size:number;total:number;total_pages:number;has_next:boolean;has_prev:boolean } }
export class ApiError extends Error { constructor(message:string, public requestId='', public status=0, public fields:{field:string;message:string}[]=[]) { super(message) } }
export const sessionEpoch = ref(0)
export class StaleSessionError extends ApiError { constructor() { super('会话已变更，请在当前账户重新操作。') } }
export function assertSession(epoch:number) { if(epoch!==sessionEpoch.value) throw new StaleSessionError() }
export function beginSession() { sessionEpoch.value++; token=''; refreshPromise=null; return sessionEpoch.value }
// Serialize cookie-mutating auth traffic so an old refresh cannot overwrite a newer login cookie.
let authQueue:Promise<unknown> = Promise.resolve()
function sessionFetch(url:string, init:RequestInit, epoch:number):Promise<Response> {
  const run=()=>{ assertSession(epoch); return fetch(url,init) }
  if(!['/api/v1/auth/login','/api/v1/auth/logout','/api/v1/auth/refresh'].includes(url)) return run()
  const pending=authQueue.then(run,run); authQueue=pending.catch(()=>{}); return pending
}
let token = ''
let refreshPromise: Promise<boolean> | null = null
let expired = () => {}
export function setAccessToken(value:string) { token = value }
export function onExpired(handler:()=>void) { expired = handler }
export async function refreshAccess(epoch=sessionEpoch.value):Promise<boolean> {
  assertSession(epoch)
  if (!refreshPromise) {
    const pending=(async () => {
      try {
        const r=await sessionFetch('/api/v1/auth/refresh',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'},epoch)
        assertSession(epoch)
        const e=await r.json(); assertSession(epoch)
        if(!r.ok || e.code!==0) return false
        const t=e.data.token ?? e.data; token=t.access_token; return !!token
      } catch(e) { assertSession(epoch); return false }
    })()
    refreshPromise=pending
    void pending.finally(()=>{if(refreshPromise===pending)refreshPromise=null}).catch(()=>{})
  }
  return refreshPromise
}
export async function api<T>(path:string, options:{method?:string;body?:unknown;query?:Record<string,unknown>} = {}, retry=true, epoch=sessionEpoch.value):Promise<Envelope<T>> {
  assertSession(epoch)
  const q = new URLSearchParams(); Object.entries(options.query ?? {}).forEach(([k,v]) => { if(v!==undefined && v!==null && v!=='') q.set(k,String(v)) })
  let response:Response
  try { response = await sessionFetch(`/api/v1${path}${q.size ? `?${q}` : ''}`, { method:options.method ?? 'GET', credentials:'same-origin', headers:{'Content-Type':'application/json', ...(token ? {Authorization:`Bearer ${token}`} : {})}, ...(options.body!==undefined ? {body:JSON.stringify(options.body)} : {}) },epoch); assertSession(epoch) } catch { assertSession(epoch); throw new ApiError('无法连接服务，请检查服务状态后重试。') }
  if(response.status === 401 && retry && !['/auth/login','/auth/register','/auth/setup','/auth/setup-status','/auth/refresh'].includes(path)) { if(await refreshAccess(epoch)) { assertSession(epoch); return api<T>(path,options,false,epoch) }; assertSession(epoch); expired(); throw new ApiError('登录已过期，请重新登录。','',401) }
  if(response.status===401 && !retry) { assertSession(epoch); expired(); throw new ApiError('登录已过期，请重新登录。','',401) }
  if(response.status === 204) return {code:0,message:"ok",data:null as T,request_id:response.headers.get("X-Request-ID")??"",timestamp:new Date().toISOString()}
  let e:Envelope<T>
  try { e = await response.json(); assertSession(epoch) } catch { assertSession(epoch); throw new ApiError(response.status>=500?'服务暂时不可用，请检查服务状态后重试。':'服务返回了无效响应，请稍后重试。','',response.status) }
  if(!response.ok || e.code !== 0) throw new ApiError(e.message === 'Run has recorded history; historical data cannot be overwritten' ? '执行已有流转历史，禁止修改执行、全部实际步骤及样品绑定的任何字段；刷新版本不能解除历史保护。' : e.message || '操作失败',e.request_id,response.status,Array.isArray((e.data as any)?.errors)?(e.data as any).errors:[])
  return e
}
export const errorText = (e:unknown) => e instanceof ApiError ? `${e.message}${e.requestId ? `（请求 ${e.requestId}）` : ''}` : e instanceof Error ? e.message : '操作失败，请重试。'

// FormData keeps the browser-generated multipart boundary. Replays reuse bytes after refresh.
async function binaryRequest(path:string, init:RequestInit, retry=true, epoch=sessionEpoch.value):Promise<Response> {
  assertSession(epoch)
  let response:Response
  try { response=await sessionFetch(`/api/v1${path}`,{...init,credentials:'same-origin',headers:{...init.headers,...(token?{Authorization:`Bearer ${token}`}:{})}},epoch); assertSession(epoch) }
  catch { assertSession(epoch); throw new ApiError('连接中断，请恢复任务并核对服务器结果后重试。') }
  if(response.status===401 && retry) { if(await refreshAccess(epoch)) { assertSession(epoch); return binaryRequest(path,init,false,epoch) }; assertSession(epoch); expired(); throw new ApiError('登录已过期，请重新登录。','',401) }
  if(response.status===401 && !retry) { assertSession(epoch); expired(); throw new ApiError('登录已过期，请重新登录。','',401) }
  if(!response.ok) { let e:any; try { e=await response.json() } catch {} assertSession(epoch); throw new ApiError(e?.message || '请求失败，请重试。',e?.request_id || '',response.status) }
  return response
}
export async function multipart<T>(path:string, body:FormData):Promise<Envelope<T>> {
  const epoch=sessionEpoch.value
  const response=await binaryRequest(path,{method:'POST',body},true,epoch)
  const result=await response.json(); assertSession(epoch)
  if(result.code!==0) throw new ApiError(result.message,result.request_id,response.status)
  return result
}
export async function apiBlob(path:string):Promise<{blob:Blob;filename:string}> {
  const epoch=sessionEpoch.value
  const response=await binaryRequest(path,{method:'GET'},true,epoch)
  const match=response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)
  let filename='original'; try { if(match) filename=decodeURIComponent(match[1]) } catch {}
  const blob=await response.blob(); assertSession(epoch)
  return {blob,filename}
}
export async function downloadSource(id:number,name?:string):Promise<void> {
  const epoch=sessionEpoch.value
  const {blob,filename}=await apiBlob(`/source-files/${id}/content`)
  assertSession(epoch)
  const url=URL.createObjectURL(blob), link=document.createElement('a')
  link.href=url;link.download=(name || filename).replace(/[\\/]/g,'_');link.click()
  setTimeout(()=>URL.revokeObjectURL(url),1000)
}
