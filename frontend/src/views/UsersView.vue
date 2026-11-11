<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { UserPlus, MailPlus, RefreshCw, Search, Copy, UsersRound } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import type { SessionUser as User, AccountPurpose } from '../sessionTypes'
import { purposeNames } from '../sessionTypes'
import PageHeading from '../components/PageHeading.vue'
import FormSection from '../components/FormSection.vue'
interface Invitation { invitation_id:number;id?:number;role:string;account_purpose?:AccountPurpose;status?:string;expires_at:string;created_at:string;used_at?:string;revoked_at?:string;used_by_user_id?:number }
const router=useRouter(),auth=useAuth(),tab=ref('users'),users=ref<User[]>([]),invitations=ref<Invitation[]>([]),loading=ref(false),err=ref(''),total=ref(0),inviteTotal=ref(0),invitePage=ref(1)
const filters=reactive({keyword:'',role:'',status:'',page:1,size:20}),roleNames:Record<string,string>={admin:'管理员',operator:'研究人员',viewer:'只读成员'}
const drawer=ref(false),editUser=ref<User|null>(null),saving=ref(false),formError=ref(''),userForm=reactive({username:'',password:'',display_name:'',email:'',role:'operator',account_purpose:'research' as AccountPurpose,status:'active',notes:''})
const inviteOpen=ref(false),inviteRole=ref('operator'),hours=ref(72),inviteCode=ref(''),inviteError=ref(''),inviteBusy=ref(false),resetOpen=ref(false),resetUser=ref<User|null>(null),newPassword=ref(''),resetError=ref('')
const invitePurpose=ref<AccountPurpose>('research')
watch(()=>userForm.role,role=>{if(role==='admin')userForm.account_purpose='management'})
const date=(s?:string)=>s?new Date(s).toLocaleString('zh-CN',{hour12:false}):'—'
let loadSequence=0
const isSelf=computed(()=>!!editUser.value && editUser.value.user_id===auth.user?.user_id)
const resetBusy=ref(false),disabling=ref<number|null>(null),revoking=ref<number|null>(null)
const usernamePattern='^[A-Za-z][A-Za-z0-9_.-]{2,63}$'
const usernameHint='3–64 位，以字母开头，可包含字母、数字、下划线、点和短横线。'
function validPassword(value:string){return value.length>=8 && value.length<=128}
function validEmail(value:string){return !value || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)}
function closeDrawer(done:()=>void){if(!saving.value)done()}
// 弹窗未保存修改保护（第四轮第 6 项）：邀请码只显示一次，重置密码框内的输入同理；
// 点遮罩或按 Esc 关闭前先确认，避免静默丢失。
async function closeInvite(done:()=>void){
  if(inviteBusy.value)return
  if(inviteCode.value){
    try{await ElMessageBox.confirm('邀请码只显示一次，关闭后无法再次查看。确定关闭？','未保存的修改',{type:'warning',confirmButtonText:'放弃修改',cancelButtonText:'继续编辑'})}catch{return}
  }
  done()
}
async function closeReset(done:()=>void){
  if(resetBusy.value)return
  if(newPassword.value){
    try{await ElMessageBox.confirm('新密码尚未设置，确定放弃？','未保存的修改',{type:'warning',confirmButtonText:'放弃修改',cancelButtonText:'继续编辑'})}catch{return}
  }
  done()
}
async function load(){
 const sequence=++loadSequence,currentTab=tab.value
 const query=currentTab==='users'?{...filters}:{page:invitePage.value,size:20}
 loading.value=true;err.value=''
 try{
  if(currentTab==='users'){
   const r=await api<User[]>('/users',{query})
   if(sequence!==loadSequence || currentTab!==tab.value)return
   users.value=r.data;total.value=r.meta?.total??r.data.length
  }else{
   const r=await api<Invitation[]>('/invitations',{query})
   if(sequence!==loadSequence || currentTab!==tab.value)return
   invitations.value=r.data;inviteTotal.value=r.meta?.total??r.data.length
  }
 }catch(e){if(sequence===loadSequence && currentTab===tab.value)err.value=errorText(e)}
 finally{if(sequence===loadSequence)loading.value=false}
}
function search(){filters.page=1;load()}
function openUser(u:User|null){if(saving.value)return;editUser.value=u;Object.assign(userForm,{username:'',password:'',display_name:'',email:'',role:'operator',account_purpose:'research' as AccountPurpose,status:'active',notes:''},u??{});formError.value='';drawer.value=true}
async function saveUser(){
 if(saving.value)return
 formError.value=''
 if(!editUser.value && !new RegExp(usernamePattern).test(userForm.username)){formError.value=`用户名：${usernameHint}`;return}
 if(!editUser.value && !validPassword(userForm.password)){formError.value='初始密码须为 8–128 位。';return}
 if(!validEmail(userForm.email)){formError.value='请输入有效的邮箱地址。';return}
 if(userForm.role==='admin')userForm.account_purpose='management'
 saving.value=true
 try{
  const body=editUser.value?{display_name:userForm.display_name,email:userForm.email,...(isSelf.value?{}:{role:userForm.role,status:userForm.status}),account_purpose:userForm.account_purpose,notes:userForm.notes}:{...userForm,email:userForm.email||undefined}
  await api(`/users${editUser.value?`/${editUser.value.user_id}`:''}`,{method:editUser.value?'PATCH':'POST',body})
  drawer.value=false;ElMessage.success('成员已保存')
  if(isSelf.value)await auth.me()
  await load()
 }catch(e){formError.value=errorText(e)}finally{saving.value=false}
}
async function disable(u:User){
 if(disabling.value!==null || u.user_id===auth.user?.user_id || u.status!=='active')return
 disabling.value=u.user_id
 try{
  await ElMessageBox.confirm(`停用“${u.display_name||u.username}”后，该成员将无法登录。`,'停用成员',{confirmButtonText:'确认停用',cancelButtonText:'取消',type:'warning'})
  await api(`/users/${u.user_id}`,{method:'DELETE'});ElMessage.success('成员已停用');await load()
 }catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(errorText(e))}finally{disabling.value=null}
}
function openInvite(){if(inviteBusy.value)return;inviteCode.value='';inviteError.value='';inviteRole.value='operator';invitePurpose.value='research';hours.value=72;inviteOpen.value=true}
async function createInvite(){
 if(inviteBusy.value || inviteCode.value)return
 inviteError.value=''
 if(!Number.isInteger(hours.value) || hours.value<1 || hours.value>168){inviteError.value='有效时长须为 1–168 小时的整数。';return}
 inviteBusy.value=true
 try{const r=await api<Invitation & {invite_code:string}>('/invitations',{method:'POST',body:{role:inviteRole.value,account_purpose:invitePurpose.value,expires_in_hours:hours.value}});inviteCode.value=r.data.invite_code;if(tab.value==='invitations')await load()}catch(e){inviteError.value=errorText(e)}finally{inviteBusy.value=false}
}
async function copy(){try{await navigator.clipboard.writeText(inviteCode.value);ElMessage.success('邀请码已复制')}catch{ElMessage.info('请选中邀请码并手动复制。')}}
async function revoke(i:Invitation){
 const id=i.invitation_id??i.id
 if(revoking.value!==null || id===undefined || inviteState(i)!=='待使用')return
 revoking.value=id
 try{await ElMessageBox.confirm('撤销后，该邀请码将无法用于注册。','撤销邀请',{confirmButtonText:'撤销邀请',cancelButtonText:'取消',type:'warning'});await api(`/invitations/${id}`,{method:'DELETE'});ElMessage.success('邀请已撤销');await load()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(errorText(e))}finally{revoking.value=null}
}
function inviteState(i:Invitation){if(i.revoked_at||i.status==='revoked')return '已撤销';if(i.used_at||i.used_by_user_id||i.status==='used')return '已使用';if(new Date(i.expires_at).getTime()<Date.now()||i.status==='expired')return '已过期';return '待使用'}
function openReset(u:User){if(resetBusy.value)return;resetUser.value=u;newPassword.value='';resetError.value='';resetOpen.value=true}
async function resetPassword(){
 if(resetBusy.value || !resetUser.value)return
 resetError.value=''
 if(!validPassword(newPassword.value)){resetError.value='新密码须为 8–128 位。';return}
 resetBusy.value=true
 try{await api(`/users/${resetUser.value.user_id}/password`,{method:'PUT',body:{new_password:newPassword.value}});resetOpen.value=false;newPassword.value='';ElMessage.success('密码已重置');if(resetUser.value.user_id===auth.user?.user_id){auth.clear();await router.replace('/login')}}catch(e){resetError.value=errorText(e)}finally{resetBusy.value=false}
}
onBeforeUnmount(()=>{loadSequence++})
onMounted(load)
</script>
<template><div><PageHeading title="成员与邀请" description="邀请课题组成员，按研究职责分配权限与维护账户。"><template #actions><el-button @click="openUser(null)"><UserPlus :size="16" />直接创建</el-button><el-button type="primary" @click="openInvite"><MailPlus :size="16" />邀请成员</el-button></template></PageHeading><el-alert v-if="err" :title="err" class="inline-error" type="error" :closable="false" show-icon />
 <section class="panel"><div class="tabs-panel"><el-tabs v-model="tab" @tab-change="load"><el-tab-pane label="课题组成员" name="users" /><el-tab-pane label="邀请记录" name="invitations" /></el-tabs></div>
 <form v-if="tab==='users'" class="toolbar" @submit.prevent="search"><el-input v-model="filters.keyword" class="search-input" placeholder="搜索用户名、显示名称" clearable aria-label="搜索成员"><template #prefix><Search :size="16" /></template></el-input><el-select v-model="filters.role" clearable placeholder="全部角色" class="filter-select" @change="search"><el-option v-for="(label,value) in roleNames" :key="value" :label="label" :value="value" /></el-select><el-select v-model="filters.status" clearable placeholder="全部状态" class="filter-select" @change="search"><el-option label="正常" value="active" /><el-option label="已停用" value="disabled" /></el-select><el-button native-type="submit">查询</el-button><span class="spacer"></span><el-button circle aria-label="刷新成员" :loading="loading" @click="load"><RefreshCw :size="16" /></el-button></form>
 <div v-else class="toolbar"><span class="muted" style="font-size:12px">邀请码仅在创建时显示一次，请及时复制并妥善发送。</span><span class="spacer"></span><el-button circle aria-label="刷新邀请" :loading="loading" @click="load"><RefreshCw :size="16" /></el-button></div>
 <div class="table-wrap"><el-table v-if="tab==='users'" :data="users" v-loading="loading"><el-table-column label="成员" min-width="170"><template #default="{row}"><strong>{{row.display_name||row.username}}</strong><div class="table-sub">{{row.username}} {{row.user_id===auth.user?.user_id?'（我）':''}}</div></template></el-table-column><el-table-column prop="email" label="邮箱" min-width="180"><template #default="{row}">{{row.email||'—'}}</template></el-table-column><el-table-column label="角色" min-width="110"><template #default="{row}"><el-tag :type="row.role==='admin'?'warning':'info'">{{roleNames[row.role]}}</el-tag></template></el-table-column><el-table-column label="账户用途" min-width="110"><template #default="{row}">{{purposeNames[row.account_purpose as AccountPurpose]||'未标注'}}</template></el-table-column><el-table-column label="状态" min-width="90"><template #default="{row}"><el-tag :type="row.status==='active'?'success':'info'">{{row.status==='active'?'正常':'已停用'}}</el-tag></template></el-table-column><el-table-column label="创建时间" min-width="165"><template #default="{row}">{{date(row.created_at)}}</template></el-table-column><el-table-column label="操作" min-width="190" fixed="right"><template #default="{row}"><div class="table-actions"><el-button link type="primary" @click="openUser(row)">编辑</el-button><el-button link type="primary" @click="openReset(row)">重置密码</el-button><el-button v-if="row.status==='active'&&row.user_id!==auth.user?.user_id" link type="danger" :loading="disabling===row.user_id" :disabled="disabling!==null" @click="disable(row)">停用</el-button></div></template></el-table-column><template #empty><div class="empty-state"><UsersRound class="empty-icon" :size="32" /><h3>{{err?'加载失败':'暂无匹配成员'}}</h3><p>调整筛选条件，或邀请新的课题组成员。</p></div></template></el-table>
 <el-table v-else :data="invitations" v-loading="loading"><el-table-column label="邀请 ID" min-width="110"><template #default="{row}">#{{row.invitation_id??row.id}}</template></el-table-column><el-table-column label="授予角色" min-width="130"><template #default="{row}">{{roleNames[row.role]||row.role}}</template></el-table-column><el-table-column label="账户用途" min-width="110"><template #default="{row}">{{purposeNames[row.account_purpose as AccountPurpose]||'未标注'}}</template></el-table-column><el-table-column label="状态" min-width="100"><template #default="{row}"><el-tag :type="inviteState(row)==='待使用'?'success':'info'">{{inviteState(row)}}</el-tag></template></el-table-column><el-table-column label="有效期至" min-width="175"><template #default="{row}">{{date(row.expires_at)}}</template></el-table-column><el-table-column label="创建时间" min-width="175"><template #default="{row}">{{date(row.created_at)}}</template></el-table-column><el-table-column label="操作" min-width="100" fixed="right"><template #default="{row}"><el-button v-if="inviteState(row)==='待使用'" link type="danger" :loading="revoking===(row.invitation_id??row.id)" :disabled="revoking!==null" @click="revoke(row)">撤销邀请</el-button><span v-else class="muted">—</span></template></el-table-column><template #empty><div class="empty-state"><MailPlus class="empty-icon" :size="32" /><h3>{{err?'加载失败':'尚无邀请记录'}}</h3><p>创建邀请码，让研究人员加入您的课题组。</p><el-button type="primary" plain @click="openInvite">邀请成员</el-button></div></template></el-table></div>
 <div class="pagination"><span>共 {{tab==='users'?total:inviteTotal}} 条记录</span><el-pagination v-if="tab==='users'" v-model:current-page="filters.page" :page-size="20" :total="total" layout="prev,pager,next" @current-change="load" /><el-pagination v-else v-model:current-page="invitePage" :page-size="20" :total="inviteTotal" layout="prev,pager,next" @current-change="load" /></div></section>
 <el-drawer v-model="drawer" :title="editUser?'编辑成员':'直接创建成员'" size="min(540px,100vw)" :before-close="closeDrawer" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
  <el-alert v-if="formError" :title="formError" type="error" :closable="false" class="drawer-alert" />
  <el-form id="member-form" label-position="top" :disabled="saving" @submit.prevent="saveUser">
   <FormSection title="账户信息" description="设置登录账户与成员联系方式。">
    <el-form-item label="用户名" required><el-input v-model="userForm.username" :disabled="!!editUser" required minlength="3" maxlength="64" :pattern="editUser?undefined:usernamePattern" :title="usernameHint" autocomplete="off" /><p v-if="!editUser" class="field-hint">{{usernameHint}}</p></el-form-item>
    <el-form-item v-if="!editUser" label="初始密码" required><el-input v-model="userForm.password" type="password" show-password required minlength="8" maxlength="128" autocomplete="new-password" /><p class="field-hint">密码长度为 8–128 位。</p></el-form-item>
    <el-form-item label="显示名称"><el-input v-model="userForm.display_name" maxlength="100" /></el-form-item>
    <el-form-item label="邮箱"><el-input v-model="userForm.email" type="email" autocomplete="email" /></el-form-item>
   </FormSection>
   <FormSection title="权限与状态" description="按成员职责设置访问权限。">
    <el-form-item label="角色"><el-select v-model="userForm.role" :disabled="isSelf"><el-option v-for="(label,value) in roleNames" :key="value" :label="label" :value="value" /></el-select><p class="field-hint">研究人员可维护本人数据；只读成员可查看授权范围内的数据。</p></el-form-item>
    <el-form-item label="账户用途"><el-select v-model="userForm.account_purpose" :disabled="userForm.role==='admin'"><el-option v-for="(label,value) in purposeNames" :key="value" :label="label" :value="value" /></el-select><p class="field-hint">管理员固定为管理账户；用途用于辨识账户，不改变数据权限或环境。</p></el-form-item>
    <el-form-item v-if="editUser" label="账户状态"><el-select v-model="userForm.status" :disabled="isSelf"><el-option label="正常" value="active" /><el-option label="已停用" value="disabled" /></el-select><p class="field-hint">{{isSelf?'不能更改自己的角色或账户状态。':'已停用成员可选择“正常”并保存，恢复登录。'}}</p></el-form-item>
   </FormSection>
   <FormSection title="补充信息"><el-form-item label="备注"><el-input v-model="userForm.notes" type="textarea" :rows="3" maxlength="20000" /></el-form-item></FormSection>
  </el-form>
  <template #footer><div class="form-footer"><el-button :disabled="saving" @click="drawer=false">取消</el-button><el-button type="primary" native-type="submit" form="member-form" :loading="saving">保存成员</el-button></div></template>
 </el-drawer>
 <el-dialog v-model="inviteOpen" title="邀请课题组成员" width="min(480px,94vw)" :before-close="closeInvite" :close-on-press-escape="!inviteBusy" :show-close="!inviteBusy" :close-on-click-modal="!inviteBusy" destroy-on-close><el-alert v-if="inviteError" :title="inviteError" type="error" :closable="false" /><template v-if="inviteCode"><el-alert title="邀请码仅显示一次。请立即复制，并发送给受邀成员。" type="success" :closable="false" /><p class="invitation-code">{{inviteCode}}</p><p class="field-hint">受邀成员在登录页选择“邀请注册”，填写此邀请码即可加入。</p><div class="form-footer"><el-button :disabled="inviteBusy" @click="inviteOpen=false">完成</el-button><el-button type="primary" @click="copy"><Copy :size="16" />复制邀请码</el-button></div></template><el-form v-else label-position="top" :disabled="inviteBusy" @submit.prevent="createInvite"><el-form-item label="成员角色"><el-select v-model="inviteRole"><el-option label="研究人员 · 可维护本人数据" value="operator" /><el-option label="只读成员 · 仅查看" value="viewer" /></el-select></el-form-item><el-form-item label="账户用途"><el-select v-model="invitePurpose"><el-option v-for="(label,value) in purposeNames" :key="value" :label="label" :value="value" /></el-select></el-form-item><el-form-item label="有效时长 / 小时"><el-input-number v-model="hours" :min="1" :max="168" :precision="0" /></el-form-item><p class="field-hint">每个邀请码仅可使用一次，默认 72 小时内有效。</p><div class="form-footer"><el-button :disabled="inviteBusy" @click="inviteOpen=false">取消</el-button><el-button type="primary" native-type="submit" :loading="inviteBusy">生成邀请码</el-button></div></el-form></el-dialog>
 <el-dialog v-model="resetOpen" title="重置成员密码" width="min(440px,94vw)" :before-close="closeReset" :close-on-click-modal="!resetBusy" :close-on-press-escape="!resetBusy" :show-close="!resetBusy" destroy-on-close><p class="muted">为 {{resetUser?.display_name||resetUser?.username}} 设置新的登录密码。</p><el-alert v-if="resetError" :title="resetError" type="error" :closable="false" /><el-form label-position="top" :disabled="resetBusy" @submit.prevent="resetPassword"><el-form-item label="新密码" required><el-input v-model="newPassword" type="password" show-password required minlength="8" maxlength="128" autocomplete="new-password" /></el-form-item><div class="form-footer"><el-button :disabled="resetBusy" @click="resetOpen=false">取消</el-button><el-button native-type="submit" type="primary" :loading="resetBusy">重置密码</el-button></div></el-form></el-dialog>
</div></template>
