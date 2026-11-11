<script setup lang="ts">
import { computed, ref, reactive, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LayoutDashboard, Layers3, Microscope, UsersRound, FlaskConical, PanelLeftClose, Menu, ChevronDown, KeyRound, LogOut, ShieldCheck, MessageSquareText, ChartNoAxesCombined, ClipboardList, History, UploadCloud, ScanLine, FolderArchive, Gauge, Activity } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuth } from '../auth'
import { api, errorText } from '../api'
import AIAssistant from './AIAssistant.vue'
import { purposeNames } from '../sessionTypes'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const mobile = ref(false)
const collapsed = ref(false)
const passwordOpen = ref(false)
const busy = ref(false)
const err = ref('')
const mobileToggle = ref<HTMLButtonElement | null>(null)
const sidebar = ref<HTMLElement | null>(null)
const navScroll = ref<HTMLElement | null>(null)
const mainContent = ref<HTMLElement | null>(null)
const password = reactive({ old_password: '', new_password: '', confirm: '' })
const assistant = ref<InstanceType<typeof AIAssistant>>()
const assistantOpen = ref(false)
const assistantBlocked = ref(false)
const narrow = ref(window.matchMedia('(max-width: 760px)').matches)
const groupIds = ['workplace', 'materials', 'experiments', 'analysis', 'admin'] as const
type GroupId = typeof groupIds[number]
// Accordion state: at most one explicitly opened group. The group that owns the
// current page is always expanded on top of it, so the active item never hides.
const openGroup = ref<GroupId | null>(null)
const railMode = computed(() => collapsed.value && !narrow.value)

const navGroups = computed(() => [
  { id: 'workplace' as const, label: '工作空间', icon: LayoutDashboard, items: [
    { path: '/quick', label: '实验快录', icon: ClipboardList },
    { path: '/quick-history', label: '实验历史', icon: History },
    { path: '/quick-dataset', label: '数据集中心', icon: ChartNoAxesCombined },
    { path: '/quick-templates', label: '工艺模板', icon: FlaskConical },
    { path: '/quick-lab', label: 'AI 实验室', icon: Activity },
    { path: '/professional', label: '专业模式', icon: LayoutDashboard },
  ] },
  { id: 'materials' as const, label: '材料管理', icon: Layers3, items: [
    { path: '/batches', label: '批次管理', icon: Layers3 },
    { path: '/samples', label: '样品管理', icon: Microscope },
    ...(auth.canWrite ? [{ path: '/chemistry', label: '化学体系', icon: FlaskConical }] : []),
  ] },
  { id: 'experiments' as const, label: '实验管理', icon: FlaskConical, items: [
    { path: '/plans', label: '实验计划', icon: ClipboardList },
    { path: '/processes', label: '实验执行', icon: Activity },
    { path: '/sample-history', label: '样品科研履历', icon: History },
  ] },
  { id: 'analysis' as const, label: '数据分析', icon: ChartNoAxesCombined, items: [
    { path: '/imports', label: '统一导入中心', icon: UploadCloud },
    { path: '/measurements', label: '正式测量', icon: ScanLine },
    { path: '/source-files', label: '原始文件档案', icon: FolderArchive },
    // Main plots task owns /analysis. Enable only after its real route exists.
    ...(router.getRoutes().some(r => r.path === '/analysis') ? [{ path: '/analysis', label: '数据可视化', icon: ChartNoAxesCombined }] : []),
    { path: '/instruments/ellipsometry', label: '仪器数据入口', icon: Gauge },
  ] },
  ...(auth.isAdmin ? [{ id: 'admin' as const, label: '管理设置', icon: ShieldCheck, items: [
    { path: '/users', label: '成员与权限', icon: UsersRound },
    { path: '/ai-settings', label: 'AI 设置', icon: ShieldCheck },
  ] }] : []),
])

function isActive(path: string) {
  return route.path === path || (path !== '/' && route.path.startsWith(`${path}/`)) || (path.startsWith('/instruments/') && route.path.startsWith('/instruments/'))
}

function activeGroup(): GroupId | null {
  return navGroups.value.find(group => group.items.some(item => isActive(item.path)))?.id ?? null
}

function isExpanded(id: GroupId) {
  return railMode.value || openGroup.value === id || activeGroup() === id
}

function groupLabel(group: { id: GroupId; label: string; items: { path: string }[] }) {
  return `${isExpanded(group.id) ? '收起' : '展开'}${group.label}`
}

// Store UI preferences only; an account switch always starts by clearing in-memory state.
const preferenceKey = computed(() => auth.user ? `ale:nav:v1:user:${auth.user.user_id}` : null)
watch(preferenceKey, key => {
  collapsed.value = false
  openGroup.value = null
  if (!key) return
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) || 'null')
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return
    // New shape: {collapsed, openGroup, groups}. Old shape only had groups with
    // false = expanded; the first such group becomes the accordion selection.
    const value = saved as { collapsed?: unknown; groups?: unknown; openGroup?: unknown }
    if (typeof value.collapsed === 'boolean') collapsed.value = value.collapsed
    const stored = typeof value.openGroup === 'string' && (groupIds as readonly string[]).includes(value.openGroup)
      ? value.openGroup as GroupId : null
    let legacy: GroupId | null = null
    if (value.groups && typeof value.groups === 'object' && !Array.isArray(value.groups)) {
      const groups = value.groups as Record<string, unknown>
      legacy = groupIds.find(id => groups[id] === false) ?? null
    }
    openGroup.value = stored ?? legacy
  } catch { /* Malformed or unavailable storage must not block navigation. */ }
}, { immediate: true, flush: 'sync' })

function persistNav() {
  if (!preferenceKey.value) return
  const active = activeGroup()
  const groups: Record<string, boolean> = {}
  // Keep the legacy folded map meaningful for older builds: false = expanded.
  groupIds.forEach(id => { groups[id] = !(id === openGroup.value || id === active) })
  try {
    localStorage.setItem(preferenceKey.value, JSON.stringify({ collapsed: collapsed.value, openGroup: openGroup.value, groups }))
  } catch { /* Private mode / quota: keep session preferences. */ }
}

function toggleGroup(id: GroupId) {
  if (activeGroup() === id) { openGroup.value = id; persistNav(); return }
  openGroup.value = openGroup.value === id ? null : id
  persistNav()
}

function toggleSidebar() {
  collapsed.value = !collapsed.value
  persistNav()
  nextTick(() => requestAnimationFrame(scrollActiveIntoView))
}

// One scroll container only: keep the active link inside the visible band.
function scrollActiveIntoView() {
  const container = navScroll.value
  if (!container) return
  const item = container.querySelector<HTMLElement>('[aria-current="page"]')
  if (!item) return
  const box = container.getBoundingClientRect()
  const rect = item.getBoundingClientRect()
  if (rect.top < box.top + 4) container.scrollTop -= box.top + 4 - rect.top
  else if (rect.bottom > box.bottom - 4) container.scrollTop += rect.bottom - box.bottom + 4
}

watch(() => route.fullPath, () => {
  const focusWasInSidebar = mobile.value && !!sidebar.value?.contains(document.activeElement)
  closeMobileNav()
  if (focusWasInSidebar) nextTick(() => mainContent.value?.focus())
  const active = activeGroup()
  if (active && openGroup.value !== active) { openGroup.value = active; persistNav() }
  nextTick(() => requestAnimationFrame(scrollActiveIntoView))
})

function showAssistant() { closeMobileNav(); void assistant.value?.show() }
function onResize() {
  narrow.value = window.matchMedia('(max-width: 760px)').matches
  if (!narrow.value) closeMobileNav()
  nextTick(() => requestAnimationFrame(scrollActiveIntoView))
}

async function openMobileNav() {
  mobile.value = true
  await nextTick()
  scrollActiveIntoView()
  sidebar.value?.querySelector<HTMLElement>('a[aria-current="page"]')?.focus()
}

function closeMobileNav(restoreFocus = false) {
  const focusWasInSidebar = mobile.value && !!sidebar.value?.contains(document.activeElement)
  mobile.value = false
  if (restoreFocus) mobileToggle.value?.focus()
  else if (focusWasInSidebar) nextTick(() => mainContent.value?.focus())
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && mobile.value && !passwordOpen.value) {
    event.preventDefault()
    closeMobileNav(true)
  }
}

function skipToContent() {
  closeMobileNav()
  mainContent.value?.focus()
}

function clearPassword() {
  Object.assign(password, { old_password: '', new_password: '', confirm: '' })
  err.value = ''
}

// 弹窗未保存修改保护（第四轮第 6 项）：修改密码弹窗可点遮罩或按 Esc 关闭，
// 但已经输入密码内容时必须先确认，避免静默清空输入。
async function closePassword(done?: () => void) {
  if (busy.value) return
  if (password.old_password || password.new_password || password.confirm) {
    try {
      await ElMessageBox.confirm('输入的密码尚未保存，确定放弃？', '未保存的修改', { type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' })
    } catch { return }
  }
  passwordOpen.value = false
  done?.()
}

async function command(value: string) {
  if (value === 'password') {
    if (busy.value) return
    clearPassword()
    passwordOpen.value = true
  } else if (value === 'logout') {
    try {
      const ended=await auth.logout()
      await nextTick()
      if(!auth.user) await router.replace('/login')
      if(!ended) ElMessage.warning('服务器退出未确认，本地会话已清理。')
    } catch (e) {
      ElMessage.error(errorText(e))
    }
  }
}

async function savePassword() {
  if (busy.value) return
  err.value = ''
  if (!password.old_password) {
    err.value = '请输入当前密码。'
    return
  }
  const length = Array.from(password.new_password).length
  if (length < 8 || length > 128) {
    err.value = '新密码长度应为 8–128 个字符。'
    return
  }
  if (password.new_password !== password.confirm) {
    err.value = '两次输入的新密码不一致。'
    return
  }
  busy.value = true
  try {
    await api('/auth/password', { method: 'PUT', body: { old_password: password.old_password, new_password: password.new_password } })
    passwordOpen.value = false
    clearPassword()
    auth.clear()
    await nextTick()
    await router.replace('/login')
    ElMessage.success('密码已修改，请重新登录')
  } catch (e) {
    err.value = errorText(e)
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onResize)
  nextTick(() => requestAnimationFrame(scrollActiveIntoView))
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': collapsed }">
    <a href="#main-content" class="skip-link" @click.prevent="skipToContent">跳转到主要内容</a>
    <button v-if="mobile" type="button" class="nav-scrim" aria-label="关闭导航" @click="closeMobileNav(true)"></button>
    <aside id="workspace-sidebar" ref="sidebar" class="sidebar" :class="{ 'mobile-open': mobile }" aria-label="研究空间导航">
      <router-link to="/" class="brand" aria-label="ALE 实验工作台首页" @click="closeMobileNav()"><span class="brand-mark"><FlaskConical :size="22" aria-hidden="true" /></span><span class="brand-text">ALE<span class="brand-sub">实验工作台</span></span></router-link>
      <div ref="navScroll" class="sidebar-scroll">
        <div class="nav-caption">研究空间</div>
        <nav id="workspace-nav" aria-label="主导航">
          <section v-for="group in navGroups" :key="group.id" class="nav-group" :class="{ 'is-current': group.items.some(item => isActive(item.path)) }" :aria-current="group.items.some(item => isActive(item.path)) ? 'true' : undefined" :aria-label="group.label">
            <div class="nav-group-heading">
              <button type="button" class="nav-group-toggle" :aria-label="groupLabel(group)" :title="group.label" :aria-expanded="isExpanded(group.id)" :aria-controls="`nav-group-${group.id}`" @click="toggleGroup(group.id)">
                <component :is="group.icon" :size="16" class="nav-group-icon" aria-hidden="true" />
                <span class="nav-group-label">{{ group.label }}</span>
                <ChevronDown :size="15" class="nav-group-chevron" :class="{ folded: !isExpanded(group.id) }" aria-hidden="true" />
              </button>
            </div>
            <div v-show="railMode || isExpanded(group.id)" :id="`nav-group-${group.id}`" class="nav-group-items" role="group" :aria-label="group.label">
              <router-link v-for="item in group.items" :key="item.path" :to="item.path" class="nav-item" :class="{ active: isActive(item.path) }" :aria-current="isActive(item.path) ? 'page' : undefined" :aria-label="item.label" :title="item.label" @click="closeMobileNav()">
                <component :is="item.icon" :size="19" aria-hidden="true" /><span>{{ item.label }}</span>
              </router-link>
              <button v-if="group.id === 'workplace'" type="button" class="nav-item nav-assistant" title="研究助手" aria-label="研究助手" :aria-expanded="assistantOpen" aria-controls="ai-research-drawer" :disabled="assistantBlocked" @click="showAssistant"><MessageSquareText :size="19" aria-hidden="true" /><span>研究助手</span></button>
            </div>
          </section>
        </nav>
      </div>
      <div class="sidebar-bottom">
        <div class="workspace-state"><span class="status-dot" aria-hidden="true"></span><span>实验记录，可追溯</span></div>
        <button type="button" class="collapse-button" :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'" :title="collapsed ? '展开侧边栏' : '折叠侧边栏'" :aria-expanded="!collapsed" aria-controls="workspace-nav" @click="toggleSidebar"><PanelLeftClose :size="18" aria-hidden="true" /><span>{{ collapsed ? '展开导航' : '收起导航' }}</span></button>
      </div>
    </aside>
    <div class="app-main">
      <header class="topbar">
        <div class="breadcrumb">
          <button ref="mobileToggle" type="button" class="mobile-toggle" :aria-label="mobile ? '关闭导航' : '打开导航'" :aria-expanded="mobile" aria-controls="workspace-sidebar" @click="mobile ? closeMobileNav(true) : openMobileNav()"><Menu :size="22" aria-hidden="true" /></button>
          <span class="muted">研究空间</span><span class="crumb-divider" aria-hidden="true">/</span><span>{{ route.meta.title }}</span>
        </div>
        <div class="session-identity" role="status" aria-label="当前会话标识">
          <span>{{auth.user?.account_purpose ? purposeNames[auth.user.account_purpose] : '用途未标注'}}</span>
          <span :title="auth.environment?.instance_id">{{auth.environment ? `${auth.environment.label} · ${auth.environment.name==='testing'?'测试环境':'生产环境'} · ${auth.environment.instance_id}` : '环境未标注'}}</span>
          <strong v-if="auth.isAdmin && auth.dataScope==='all'">管理员 · 全局数据视图</strong><span v-else>{{auth.dataScope==='all'?'全部授权数据':'仅本人数据'}}</span>
        </div>
        <div class="header-actions">
          <button type="button" class="header-assistant" title="研究助手" aria-label="研究助手" :aria-expanded="assistantOpen" aria-controls="ai-research-drawer" :disabled="assistantBlocked" @click="showAssistant"><MessageSquareText :size="18" aria-hidden="true" /><span>研究助手</span></button>
          <span class="scope-badge"><ShieldCheck :size="14" aria-hidden="true" />{{ ({ all: '全部数据', own: '我的数据', shared: '共享数据' } as Record<string, string>)[auth.dataScope] || auth.dataScope }}</span>
          <el-dropdown @command="command">
            <button type="button" class="user-menu" :aria-label="`${auth.user?.display_name || auth.user?.username || '当前账户'}，账户菜单`" aria-haspopup="menu"><span class="avatar" aria-hidden="true">{{ (auth.user?.display_name || auth.user?.username || 'U').slice(0, 1) }}</span><span class="user-name">{{ auth.user?.display_name || auth.user?.username }}</span><ChevronDown :size="14" aria-hidden="true" /></button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item command="password"><KeyRound :size="15" aria-hidden="true" /> 修改密码</el-dropdown-item><el-dropdown-item command="logout" divided><LogOut :size="15" aria-hidden="true" /> 退出登录</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </header>
      <main id="main-content" ref="mainContent" class="page-main" tabindex="-1"><router-view :key="route.path" /></main>
      <footer class="app-footer">ALE 实验工作台 <span>数据以当前账户的可见范围为准</span><router-link to="/m/quick" class="footer-mobile-link">手机版入口</router-link></footer>
    </div>
    <AIAssistant v-if="auth.user" ref="assistant" :navigation-open="mobile" @open-change="assistantOpen = $event" @blocked-change="assistantBlocked = $event" />
    <el-dialog v-model="passwordOpen" title="修改密码" width="min(460px, 94vw)" :before-close="closePassword" destroy-on-close :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @closed="clearPassword">
      <p id="password-requirements" class="field-hint">新密码须为 8–128 个字符。修改成功后需重新登录。</p>
      <el-alert v-if="err" :title="err" type="error" :closable="false" show-icon role="alert" />
      <el-form label-position="top" :aria-busy="busy" @submit.prevent="savePassword">
        <el-form-item label="当前密码" for="current-password" required><el-input id="current-password" v-model="password.old_password" type="password" show-password required :maxlength="128" :disabled="busy" autocomplete="current-password" /></el-form-item>
        <el-form-item label="新密码" for="new-password" required><el-input id="new-password" v-model="password.new_password" type="password" show-password required :minlength="8" :maxlength="128" :disabled="busy" autocomplete="new-password" aria-describedby="password-requirements" /></el-form-item>
        <el-form-item label="确认新密码" for="confirm-password" required><el-input id="confirm-password" v-model="password.confirm" type="password" show-password required :minlength="8" :maxlength="128" :disabled="busy" autocomplete="new-password" aria-describedby="password-requirements" /></el-form-item>
        <div class="form-footer"><el-button :disabled="busy" @click="closePassword()">取消</el-button><el-button type="primary" native-type="submit" :loading="busy" :disabled="busy">{{ busy ? '正在保存' : '保存密码' }}</el-button></div>
      </el-form>
    </el-dialog>
  </div>
</template>

<style scoped>
.session-identity{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:12px;max-width:55%;color:#465c68}.session-identity strong{color:#965708;background:#fff3d6;padding:2px 6px;border-radius:4px}@media(max-width:760px){.session-identity{max-width:48%;font-size:11px}}
.app-footer{color:#40586b}
.footer-mobile-link{color:#0b6d78;text-decoration:none;border-bottom:1px dashed #9cc2c6;padding-bottom:1px}
.footer-mobile-link:hover{color:#064f57;border-bottom-style:solid}
.topbar{height:auto;min-height:64px;flex-wrap:wrap;gap:8px;padding-block:10px}
.session-identity{min-width:0;overflow-wrap:anywhere}
/* One scroll container: the sidebar clips, .sidebar-scroll scrolls, nav never does. */
.sidebar{overflow:hidden}
.sidebar-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;scrollbar-gutter:stable;padding-bottom:8px}
.sidebar nav{overflow:visible;min-height:0}
.sidebar .brand{flex-shrink:0}
.sidebar-bottom{flex-shrink:0}
.nav-caption{padding:22px 12px 8px;color:#a8bbce;font-size:12px;letter-spacing:.6px}

.nav-group{margin:0 0 3px;border-radius:8px}
.nav-group-heading{margin:0}
.nav-group-toggle{display:flex;align-items:center;gap:10px;width:100%;min-height:44px;padding:11px 12px;background:transparent;border:0;border-radius:8px;color:#c9d9e6;font-size:13px;font-weight:650;letter-spacing:.4px;text-align:left;transition:background .15s,color .15s}
.nav-group-toggle:hover{background:#19354b;color:#fff}
.nav-group-toggle:focus-visible{outline:2px solid #8fe3dc;outline-offset:-2px}
.nav-group.is-current .nav-group-toggle{color:#eafaf7;background:#16394b;box-shadow:inset 2px 0 #72d3cf}
.nav-group-icon{flex:0 0 18px;color:#8fb3c6}
.nav-group.is-current .nav-group-icon{color:#7fded4}
.nav-group-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-group-chevron{flex-shrink:0;transition:transform .18s ease;color:#8fb3c6}
.nav-group-chevron.folded{transform:rotate(-90deg)}

.nav-group-items{display:flex;flex-direction:column;gap:2px;padding:1px 0 5px}
.nav-item{display:flex;align-items:center;gap:10px;min-height:42px;margin:0;padding:9px 12px 9px 40px;border-radius:7px;color:#c4d2df;font-size:13.5px;white-space:nowrap;transition:background .15s,color .15s}
.nav-item svg{flex:0 0 19px;color:#9db9cb;transition:color .15s}
.nav-item:hover{background:#1b3a52;color:#fff}
.nav-item:hover svg{color:#cfe9ea}
.nav-item:focus-visible{outline:2px solid #8fe3dc;outline-offset:-2px}
.nav-item.active{background:#205068;color:#fff;font-weight:600;box-shadow:inset 3px 0 #72d3cf}
.nav-item.active svg{color:#a9ece5}
.nav-assistant{border:0;background:transparent;color:inherit;width:100%;text-align:left}

/* Collapsed rail: icons only, all routes visible, accessible names from aria-label/title. */
.sidebar-collapsed .nav-group-heading{display:none}
.sidebar-collapsed .nav-group + .nav-group{border-top:1px solid #294054;margin-top:5px;padding-top:5px}
.sidebar-collapsed .nav-group-items{padding:0}
.sidebar-collapsed .nav-item{justify-content:center;padding:11px 0;min-height:44px;gap:0}
.sidebar-collapsed .nav-item span,.sidebar-collapsed .nav-group-label{display:none}
.sidebar-collapsed .nav-item.active{box-shadow:inset 0 0 0 2px #72d3cf}
.sidebar-collapsed .nav-caption{display:none}
.sidebar-collapsed .sidebar-scroll{padding-top:10px}

.header-assistant{display:flex;align-items:center;gap:6px;background:#f4f8fa;color:#16717b;border:1px solid #e4ebef;border-radius:5px;padding:7px 9px;font-size:12px}
.header-assistant:disabled,.nav-assistant:disabled{opacity:.5}
.workspace-state{margin-top:16px;margin-bottom:14px}
@media(max-width:760px){
  .app-main{transition:none}
  .sidebar{width:280px;padding:22px 14px}
  .sidebar-collapsed .nav-group-heading{display:block}
  .sidebar-collapsed .nav-group-toggle{justify-content:flex-start;padding:11px 12px;min-height:44px;gap:10px}
  .sidebar-collapsed .nav-group + .nav-group{border-top:0;margin-top:0;padding-top:0}
  .sidebar-collapsed .nav-group-items{padding:1px 0 5px}
  .sidebar-collapsed .nav-item{justify-content:flex-start;padding:9px 12px 9px 40px;min-height:42px;gap:10px}
  .sidebar-collapsed .nav-item span,.sidebar-collapsed .nav-group-label{display:inline}
  .sidebar-collapsed .nav-item.active{box-shadow:inset 3px 0 #72d3cf}
  .sidebar-collapsed .nav-caption{display:block}
  .header-assistant{padding:7px}
  .header-assistant span{display:none}
}
@media(prefers-reduced-motion:reduce){
  .sidebar,.nav-group-toggle,.nav-group-chevron,.nav-item,.nav-item svg{transition:none!important;animation:none!important}
}
</style>


