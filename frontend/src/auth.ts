import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api, setAccessToken, refreshAccess, sessionEpoch, beginSession, assertSession } from './api'
import type { SessionUser, SessionCurrentUser, SessionEnvironment } from './sessionTypes'
export const useAuth = defineStore('auth', () => {
  const user=ref<SessionUser|null>(null), permissions=ref<string[]>([]), dataScope=ref('own'), ready=ref(false)
  const environment=ref<SessionEnvironment|null>(null)
  const isAdmin=computed(()=>user.value?.role==='admin')
  const canWrite=computed(()=>['admin','operator'].includes(user.value?.role ?? ''))
  let restoring:Promise<void>|null=null
  function clear(expected=sessionEpoch.value) {
    if(expected!==sessionEpoch.value)return
    const owner=user.value?.user_id
    beginSession()
    user.value=null; permissions.value=[]; dataScope.value='own'; environment.value=null; ready.value=true
    // Import review choices/replay are session drafts; server jobs remain available.
    try { for(const key of Object.keys(localStorage)) if(key.startsWith(`ale:imports:${owner}:`))localStorage.removeItem(key) } catch {}
  }
  async function me(epoch=sessionEpoch.value) {
    const {data}=await api<SessionCurrentUser>('/auth/me'); assertSession(epoch)
    user.value=data.user; permissions.value=data.permissions; dataScope.value=data.data_scope ?? 'own'; environment.value=data.environment ?? null
  }
  async function login(body:{username:string;password:string}) {
    clear(); const epoch=sessionEpoch.value
    try {
      const {data}=await api<{token:{access_token:string};user:SessionUser}>('/auth/login',{method:'POST',body})
      assertSession(epoch); setAccessToken(data.token.access_token)
      await me(epoch); assertSession(epoch); ready.value=true
    } catch(e) { clear(epoch); throw e }
  }
  async function restore() {
    if(ready.value)return
    if(restoring)return restoring
    const epoch=sessionEpoch.value
    const pending=(async()=>{
      try { if(await refreshAccess(epoch))await me(epoch) } catch { clear(epoch) }
      finally { if(epoch===sessionEpoch.value)ready.value=true }
    })()
    restoring=pending
    try { await pending } finally { if(restoring===pending)restoring=null }
  }
  async function logout() {
    const epoch=sessionEpoch.value
    try { await api('/auth/logout',{method:'POST',body:{}}); return true }
    catch { return false }
    finally { clear(epoch) }
  }
  return {user,permissions,dataScope,environment,sessionEpoch,ready,isAdmin,canWrite,me,login,restore,clear,logout}
})
