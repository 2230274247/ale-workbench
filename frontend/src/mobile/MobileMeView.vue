<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorText } from '../api'
import { useAuth } from '../auth'
import { purposeNames } from '../sessionTypes'
import './mobile.css'

const auth = useAuth(), router = useRouter()
const error = ref(''), busy = ref(false)
const scopeLabel = (scope?: string) => ({ all: '全部授权数据', own: '仅本人数据', shared: '共享数据' } as Record<string, string>)[scope || ''] || '—'
async function logout() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    await auth.logout()
    await router.replace('/m/login')
  } catch (e) { error.value = errorText(e) } finally { busy.value = false }
}
const env = auth.environment
</script>

<template>
  <div>
    <p v-if="error" class="m-error-box" role="alert">{{ error }}</p>
    <section class="m-card">
      <h2>{{ auth.user?.display_name || auth.user?.username }}</h2>
      <p class="m-sub">{{ auth.user?.username }} · {{ auth.user?.account_purpose ? purposeNames[auth.user.account_purpose] : '用途未标注' }}</p>
      <dl style="margin:0;font-size:13.5px;display:grid;gap:6px">
        <div><span class="m-hint">数据范围：</span>{{ scopeLabel(auth.dataScope) }}<template v-if="auth.isAdmin && auth.dataScope === 'all'">（管理员）</template></div>
        <div><span class="m-hint">环境：</span>{{ env ? `${env.label} · ${env.name === 'testing' ? '测试环境' : '生产环境'}` : '未标注' }}</div>
        <div><span class="m-hint">权限：</span>{{ auth.canWrite ? '可录入与修改' : '只读账户' }}</div>
      </dl>
    </section>

    <section class="m-card">
      <h2>数据与安全</h2>
      <p class="m-sub">手机版与电脑版共用同一账户与同一份数据；手机上保存的记录会实时出现在电脑版历史中。原始文件、修订与删除等高风险操作仍建议在电脑版完成。</p>
      <div class="m-btns stack">
        <router-link to="/quick" class="m-field" style="gap:0"><button style="width:100%">切换到电脑版</button></router-link>
        <router-link to="/m/dataset" class="m-field" style="gap:0"><button style="width:100%" class="ghost">导入 / 导出数据</button></router-link>
        <button :disabled="busy" @click="logout">{{ busy ? '正在退出…' : '退出登录' }}</button>
      </div>
    </section>

    <p class="m-hint" style="text-align:center;padding:8px 0 0">ALE 实验工作台 · 移动网页版</p>
  </div>
</template>
