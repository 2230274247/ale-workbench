<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, FlaskConical, ShieldCheck } from 'lucide-vue-next'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
const router=useRouter(),route=useRoute(),auth=useAuth(), mode=ref<'login'|'register'|'setup'>('login'),needsSetup=ref(false),checking=ref(true),busy=ref(false),error=ref(''),notice=ref('')
const form=reactive({username:'',password:'',display_name:'',email:'',invite_code:'',setup_code:''})
async function check(){if(busy.value)return;checking.value=true;error.value='';try{needsSetup.value=(await api<{needs_setup:boolean}>('/auth/setup-status')).data.needs_setup;mode.value=needsSetup.value?'setup':'login'}catch(e){error.value=errorText(e)}finally{checking.value=false}}
onMounted(check)
const usernamePattern='^[A-Za-z][A-Za-z0-9_.-]{2,63}$'
const usernameHint='3–64 位，以字母开头，可包含字母、数字、下划线、点和短横线。'
async function submit(){
 if(busy.value || checking.value)return
 error.value='';notice.value=''
 if(mode.value!=='login' && !new RegExp(usernamePattern).test(form.username)){error.value=`用户名：${usernameHint}`;return}
 if(form.password.length>128 || form.password.length<(mode.value==='login'?1:8)){error.value=mode.value==='login'?'密码长度须为 1–128 位。':'设置密码须为 8–128 位。';return}
 busy.value=true
 try{
 if(mode.value==='login'){await auth.login({username:form.username,password:form.password});await router.replace(route.path.startsWith('/m')?'/m/quick':'/')}
 else {await api(mode.value==='setup'?'/auth/setup':'/auth/register',{method:'POST',body:mode.value==='setup'?{username:form.username,password:form.password,display_name:form.display_name,setup_code:form.setup_code}:{username:form.username,password:form.password,display_name:form.display_name,email:form.email||undefined,invite_code:form.invite_code}});needsSetup.value=false;mode.value='login';form.password='';form.setup_code='';form.invite_code='';notice.value='账户已创建，请使用新账户登录。'}
}catch(e){error.value=errorText(e)}finally{busy.value=false}}
function switchMode(){if(busy.value || checking.value)return;mode.value=mode.value==='login'?'register':'login';error.value='';notice.value='';form.password=''}
</script>
<template>
 <main class="auth-page">
  <section class="auth-story" aria-label="ALE 实验工作台">
   <a class="brand auth-brand" href="/login"><span class="brand-mark"><FlaskConical :size="22" /></span><span>ALE<span class="brand-sub">实验工作台</span></span></a>
   <div class="story-copy"><p class="story-caption">原子层刻蚀研究</p><h1>从每一片样品，<br>到可追溯的发现。</h1><p>在同一工作空间中，记录批次与样品，<br>让实验数据始终有据可循。</p></div>
   <div class="wafer-scene" aria-hidden="true"><div class="wafer-orbit orbit-one"></div><div class="wafer-orbit orbit-two"></div><div class="wafer"><div class="wafer-grid"></div><span v-for="n in 9" :key="n" class="wafer-point" :style="{left: `${25+(n-1)%3*25}%`,top:`${25+Math.floor((n-1)/3)*25}%`}"></span><div class="wafer-notch"></div></div><span class="wafer-annotation">样品 · 工艺 · 测量</span></div>
   <p class="auth-footer">ALE Research Workspace <span>严谨记录，持续探索</span></p>
  </section>
  <section class="auth-panel"><div class="login-card">
   <div class="mobile-brand"><FlaskConical /> ALE 实验工作台</div>
   <span class="secure-label"><ShieldCheck :size="16" /> 课题组协作空间</span>
   <h2>{{ mode==='setup'?'初始化工作空间':mode==='register'?'接受邀请':'欢迎回来' }}</h2>
   <p class="muted">{{mode==='setup'?'使用初始化访问码，创建首位管理员。':mode==='register'?'使用管理员提供的邀请码加入课题组。':'登录以继续管理您的实验记录。'}}</p>
   <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="form-alert" />
   <el-alert v-if="notice" :title="notice" type="success" show-icon :closable="false" class="form-alert" />
   <div v-if="checking" class="checking">正在检查工作空间…</div>
   <el-form v-else :model="form" :disabled="busy" label-position="top" @submit.prevent="submit">
    <el-form-item v-if="mode==='setup'" label="初始化访问码" required><el-input v-model="form.setup_code" type="password" show-password autocomplete="off" required maxlength="256" placeholder="由系统部署人员提供" /></el-form-item>
    <el-form-item v-if="mode==='register'" label="邀请码" required><el-input v-model="form.invite_code" autocomplete="off" required maxlength="64" placeholder="请输入有效邀请码" /></el-form-item>
    <el-form-item label="用户名" required><el-input v-model="form.username" autocomplete="username" required maxlength="64" :minlength="mode==='login'?1:3" :pattern="mode==='login'?undefined:usernamePattern" :title="mode==='login'?undefined:usernameHint" placeholder="请输入用户名" /><p v-if="mode!=='login'" class="field-hint">{{usernameHint}}</p></el-form-item>
    <el-form-item v-if="mode!=='login'" label="显示名称" required><el-input v-model="form.display_name" required maxlength="100" placeholder="您的姓名" /></el-form-item>
    <el-form-item v-if="mode==='register'" label="邮箱（选填）"><el-input v-model="form.email" type="email" autocomplete="email" placeholder="name@lab.org" /></el-form-item>
    <el-form-item :label="mode==='login'?'密码':'设置密码'" required><el-input v-model="form.password" type="password" show-password :autocomplete="mode==='login'?'current-password':'new-password'" required :minlength="mode==='login'?1:8" maxlength="128" placeholder="请输入密码" /><p v-if="mode!=='login'" class="field-hint">密码长度为 8–128 位。</p></el-form-item>
    <el-button class="auth-submit" type="primary" native-type="submit" :loading="busy">{{mode==='setup'?'创建管理员':mode==='register'?'注册并加入':'登录工作台'}}<ArrowRight v-if="!busy" :size="17" /></el-button>
   </el-form>
   <p v-if="!needsSetup && !checking" class="auth-switch">{{mode==='login'?'已收到课题组邀请？':'已有账户？'}}<button :disabled="busy" @click="switchMode">{{mode==='login'?'邀请注册':'返回登录'}}</button></p>
   <el-button v-if="error&&checking===false" text :disabled="busy" @click="check">重新检查服务</el-button>
   <p class="privacy-note">账户与数据访问权限由课题组管理员管理。</p>
  </div></section>
 </main>
</template>
