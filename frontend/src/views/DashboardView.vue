<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { ArrowRight, RefreshCw, FlaskConical, ClipboardCheck, Activity, FileClock, AlertTriangle, Layers3, Microscope, ScanLine, ClipboardList, ListChecks, Database, CircleCheck, ChevronRight } from 'lucide-vue-next'
import PageHeading from '../components/PageHeading.vue'
import StatePanel from '../components/StatePanel.vue'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import type { DashboardSummary } from '../contracts'

// The endpoint already returns plan_count; the generated contract type predates it.
type Summary = DashboardSummary & { plan_count?: number }
type Query = Record<string, string | number>

type TodoItem = {
  kind: string
  entity_id: number
  code: string | null
  title: string
  detail: string
  status: string
  severity?: string
  updated_at: string
  path: string | null
  query: Query | null
}
type TodoPayload = {
  generated_at: string
  total: number
  counts: Record<string, number>
  items: TodoItem[]
}
type ExperimentItem = {
  kind: 'plan' | 'process'
  entity_id: number
  code: string
  title: string
  status: string
  updated_at: string
  archived?: boolean
  path: string
  query: Query
  continue_path: string
  continue_query: Query
  continue_label: string
  can_continue: boolean
}
type ExperimentPayload = { generated_at: string; items: ExperimentItem[] }
type DataItem = {
  kind: 'import_job' | 'measurement' | 'source_file'
  entity_id: number
  code: string | null
  title: string
  status: string
  stage?: string
  sample_id?: number
  size_bytes?: number | null
  hint: string | null
  occurred_at: string
  path: string
  query: Query
}
type DataPayload = { generated_at: string; items: DataItem[] }

type SectionState<T> = { data: T | null; loading: boolean; error: string; loaded: boolean }

const auth = useAuth()
const summary = ref<Summary | null>(null)
const todo = ref<SectionState<TodoPayload>>({ data: null, loading: false, error: '', loaded: false })
const experiments = ref<SectionState<ExperimentPayload>>({ data: null, loading: false, error: '', loaded: false })
const recentData = ref<SectionState<DataPayload>>({ data: null, loading: false, error: '', loaded: false })
const summaryLoading = ref(false)
const summaryError = ref('')
const todoFilter = ref<'all' | string>('all')

const greeting = computed(() => `${auth.user?.display_name || auth.user?.username || '研究成员'}，今天从待办和最近记录继续。`)
const stats = computed(() => {
  const s = summary.value
  return [
    { key: 'batch_count', label: '批次', icon: Layers3, to: '/batches', value: s?.batch_count, note: '按沉积批次组织记录' },
    { key: 'sample_count', label: '样品', icon: Microscope, to: '/samples', value: s?.sample_count, note: '母片、整片与小样' },
    { key: 'plan_count', label: '实验计划', icon: ClipboardList, to: '/plans', value: s?.plan_count, note: '计划与执行分离' },
    { key: 'process_count', label: '实验执行', icon: Activity, to: '/processes', value: s?.process_count, note: '当前可见的执行记录' },
    { key: 'measurement_count', label: '当前测量', icon: ScanLine, to: '/measurements', value: s?.measurement_count, note: '仅当前有效测量' },
  ]
})
const kindMeta: Record<string, { label: string; icon: unknown; tone: string }> = {
  plan_without_process: { label: '计划待执行', icon: ClipboardCheck, tone: 'plan' },
  process_log: { label: '执行待补齐', icon: Activity, tone: 'process' },
  import_pending: { label: '导入待确认', icon: FileClock, tone: 'import' },
  import_failure: { label: '导入失败', icon: AlertTriangle, tone: 'danger' },
  measurement_review: { label: '测量待复核', icon: ScanLine, tone: 'measure' },
  issue: { label: '未关闭问题', icon: ClipboardList, tone: 'issue' },
}
const dataMeta: Record<string, { label: string; icon: unknown }> = {
  import_job: { label: '导入任务', icon: FileClock },
  measurement: { label: '测量', icon: ScanLine },
  source_file: { label: '原始文件', icon: Database },
}
const statusLabel: Record<string, string> = {
  draft: '草稿', approved: '已批准', running: '进行中', completed: '已完成', abandoned: '已放弃', archived: '已归档',
  ok: '完整', partial: '部分', aborted: '中止', unknown: '未知',
  suspect: '疑似异常', abnormal: '异常', excluded: '已排除',
  pending: '待处理', parsed: '已解析', failed: '失败', ignored: '已忽略',
  imported: '已导入', original_only: '仅保留原件', skipped: '已跳过',
}
const visibleTodo = computed(() => {
  const items = todo.value.data?.items ?? []
  return todoFilter.value === 'all' ? items : items.filter(item => item.kind === todoFilter.value)
})
const todoFilters = computed(() => {
  const counts = todo.value.data?.counts ?? {}
  return [{ key: 'all', label: '全部', count: todo.value.data?.total ?? 0 },
    ...Object.keys(kindMeta).filter(key => (counts[key] ?? 0) > 0).map(key => ({ key, label: kindMeta[key].label, count: counts[key] }))]
})

async function loadSummary() {
  if (summaryLoading.value) return
  summaryLoading.value = true
  summaryError.value = ''
  try { summary.value = (await api<Summary>('/dashboard/summary')).data }
  catch (e) { summaryError.value = errorText(e) }
  finally { summaryLoading.value = false }
}

async function loadSection<T>(target: { value: SectionState<T> }, path: string, query: Record<string, unknown> = {}) {
  if (target.value.loading) return
  target.value.loading = true
  target.value.error = ''
  try {
    target.value.data = (await api<T>(path, { query })).data
    target.value.loaded = true
  } catch (e) {
    target.value.error = errorText(e)
  } finally {
    target.value.loading = false
  }
}

const loadTodo = () => loadSection(todo, '/dashboard/todo', { limit: 20 })
const loadExperiments = () => loadSection(experiments, '/dashboard/recent-experiments', { limit: 8 })
const loadRecentData = () => loadSection(recentData, '/dashboard/recent-data', { limit: 8 })

async function loadAll() {
  await Promise.all([loadSummary(), loadTodo(), loadExperiments(), loadRecentData()])
}

function date(value?: string | null) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function size(value?: number | null) {
  if (value === null || value === undefined) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

onMounted(loadAll)
</script>

<template>
  <div class="dashboard-view">
    <PageHeading title="工作台概览" :description="greeting">
      <template #actions>
        <el-button :loading="summaryLoading || todo.loading || experiments.loading || recentData.loading" @click="loadAll">
          <RefreshCw :size="15" aria-hidden="true" />刷新概览
        </el-button>
      </template>
    </PageHeading>

    <section class="start-experiment" aria-labelledby="start-experiment-title">
      <div class="start-copy">
        <span class="start-kicker">开始新实验</span>
        <h2 id="start-experiment-title">记录实验，回看结果，准备下一步。</h2>
        <p>从一项新实验开始，或在下方继续已有记录。</p>
      </div>
      <router-link to="/experiments/new" class="start-action">
        <FlaskConical :size="20" aria-hidden="true" />
        <span>开始新实验</span>
        <ArrowRight :size="18" aria-hidden="true" />
      </router-link>
    </section>

    <section class="panel dashboard-section" aria-labelledby="todo-title" :aria-busy="todo.loading">
      <div class="panel-title">
        <div class="section-heading">
          <h2 id="todo-title">今日工作与待办</h2>
          <span v-if="todo.data" class="section-count">{{ todo.data.total }} 项</span>
        </div>
        <el-button text :loading="todo.loading" @click="loadTodo"><RefreshCw :size="14" aria-hidden="true" />刷新</el-button>
      </div>
      <div class="panel-body">
        <StatePanel v-if="todo.error" title="待办加载失败" :description="todo.error" tone="error">
          <el-button :loading="todo.loading" @click="loadTodo">重试待办</el-button>
        </StatePanel>
        <template v-else>
          <div v-if="todo.loading && !todo.loaded" class="section-skeleton" role="status" aria-label="正在加载待办"><el-skeleton :rows="4" animated /></div>
          <StatePanel v-else-if="todo.loaded && !todo.data?.items.length" title="今天没有待办" description="当前没有待执行的计划、待补齐的执行日志、待确认的导入、待复核的测量或未关闭的问题。可以开始一项新实验。" tone="empty">
            <router-link to="/experiments/new" class="el-button el-button--primary">开始新实验</router-link>
          </StatePanel>
          <template v-else-if="todo.data?.items.length">
            <div class="todo-filters" role="group" aria-label="按类型筛选待办">
              <button v-for="filter in todoFilters" :key="filter.key" type="button" class="todo-filter" :class="{ active: todoFilter === filter.key }" :aria-pressed="todoFilter === filter.key" @click="todoFilter = filter.key">{{ filter.label }}<span>{{ filter.count }}</span></button>
            </div>
            <p v-if="!visibleTodo.length" class="field-hint">该类型下没有待办。</p>
            <ul class="todo-list">
              <li v-for="item in visibleTodo" :key="`${item.kind}-${item.entity_id}`" class="todo-item" :class="`tone-${kindMeta[item.kind]?.tone ?? 'plan'}`">
                <span class="todo-icon"><component :is="kindMeta[item.kind]?.icon ?? ClipboardList" :size="18" aria-hidden="true" /></span>
                <div class="todo-content">
                  <div class="todo-line"><span class="todo-kind">{{ kindMeta[item.kind]?.label ?? item.kind }}</span><strong>{{ item.title }}</strong><code v-if="item.code && item.code !== item.title">{{ item.code }}</code></div>
                  <p>{{ item.detail }}</p>
                  <time :datetime="item.updated_at">{{ date(item.updated_at) }}</time>
                </div>
                <router-link v-if="item.path && item.query" :to="{ path: item.path, query: item.query }" class="todo-action" :aria-label="`处理 ${item.title}`">去处理<ChevronRight :size="15" aria-hidden="true" /></router-link>
                <span v-else class="todo-action muted" aria-label="该记录暂无独立页面">问题台账记录</span>
              </li>
            </ul>
          </template>
        </template>
      </div>
    </section>

    <div class="dashboard-columns">
      <section class="panel dashboard-section" aria-labelledby="recent-experiments-title" :aria-busy="experiments.loading">
        <div class="panel-title">
          <div class="section-heading"><h2 id="recent-experiments-title">最近实验</h2><span v-if="experiments.data" class="section-count">{{ experiments.data.items.length }} 条</span></div>
          <el-button text :loading="experiments.loading" @click="loadExperiments"><RefreshCw :size="14" aria-hidden="true" />刷新</el-button>
        </div>
        <div class="panel-body">
          <StatePanel v-if="experiments.error" title="最近实验加载失败" :description="experiments.error" tone="error">
            <el-button :loading="experiments.loading" @click="loadExperiments">重试最近实验</el-button>
          </StatePanel>
          <template v-else>
            <div v-if="experiments.loading && !experiments.loaded" class="section-skeleton" role="status" aria-label="正在加载最近实验"><el-skeleton :rows="4" animated /></div>
            <StatePanel v-else-if="experiments.loaded && !experiments.data?.items.length" title="还没有实验记录" description="创建实验计划后会在这里显示，可一键继续。" tone="empty">
              <router-link to="/plans" class="el-button">前往实验计划</router-link>
            </StatePanel>
            <ul v-else class="record-list">
              <li v-for="item in experiments.data?.items" :key="`${item.kind}-${item.entity_id}`" class="record-item">
                <span class="record-icon"><component :is="item.kind === 'plan' ? ClipboardList : Activity" :size="18" aria-hidden="true" /></span>
                <div class="record-content">
                  <div class="record-line"><span class="record-kind">{{ item.kind === 'plan' ? '计划' : '执行' }}</span><router-link :to="{ path: item.path, query: item.query }" class="record-title">{{ item.title }}</router-link></div>
                  <p><code v-if="item.code !== item.title">{{ item.code }}</code> {{ statusLabel[item.status] ?? item.status }}<span v-if="item.archived" class="record-archived">已归档</span><time :datetime="item.updated_at">{{ date(item.updated_at) }}</time></p>
                </div>
                <router-link v-if="item.can_continue" :to="{ path: item.continue_path, query: item.continue_query }" class="record-action">{{ item.continue_label }}<ArrowRight :size="14" aria-hidden="true" /></router-link>
                <router-link v-else :to="{ path: item.path, query: item.query }" class="record-action">查看<ArrowRight :size="14" aria-hidden="true" /></router-link>
              </li>
            </ul>
          </template>
        </div>
      </section>

      <section class="panel dashboard-section" aria-labelledby="recent-data-title" :aria-busy="recentData.loading">
        <div class="panel-title">
          <div class="section-heading"><h2 id="recent-data-title">最近数据</h2><span v-if="recentData.data" class="section-count">{{ recentData.data.items.length }} 条</span></div>
          <el-button text :loading="recentData.loading" @click="loadRecentData"><RefreshCw :size="14" aria-hidden="true" />刷新</el-button>
        </div>
        <div class="panel-body">
          <StatePanel v-if="recentData.error" title="最近数据加载失败" :description="recentData.error" tone="error">
            <el-button :loading="recentData.loading" @click="loadRecentData">重试最近数据</el-button>
          </StatePanel>
          <template v-else>
            <div v-if="recentData.loading && !recentData.loaded" class="section-skeleton" role="status" aria-label="正在加载最近数据"><el-skeleton :rows="4" animated /></div>
            <StatePanel v-else-if="recentData.loaded && !recentData.data?.items.length" title="还没有数据记录" description="导入文件、登记测量或上传原始文件后，这里会显示最新数据与真实的质量提示。" tone="empty">
              <router-link to="/imports" class="el-button">前往导入中心</router-link>
            </StatePanel>
            <ul v-else class="record-list">
              <li v-for="item in recentData.data?.items" :key="`${item.kind}-${item.entity_id}`" class="record-item">
                <span class="record-icon"><component :is="dataMeta[item.kind]?.icon ?? Database" :size="18" aria-hidden="true" /></span>
                <div class="record-content">
                  <div class="record-line"><span class="record-kind">{{ dataMeta[item.kind]?.label }}</span><router-link :to="{ path: item.path, query: item.query }" class="record-title">{{ item.title }}</router-link></div>
                  <p>{{ statusLabel[item.status] ?? item.status }}<span v-if="item.stage"> · {{ item.stage }}</span><span v-if="item.size_bytes">{{ ' · ' + size(item.size_bytes) }}</span><time :datetime="item.occurred_at">{{ date(item.occurred_at) }}</time></p>
                  <p v-if="item.hint" class="record-hint"><AlertTriangle :size="13" aria-hidden="true" />{{ item.hint }}</p>
                </div>
                <router-link :to="{ path: item.path, query: item.query }" class="record-action">查看<ArrowRight :size="14" aria-hidden="true" /></router-link>
              </li>
            </ul>
          </template>
        </div>
      </section>
    </div>

    <section class="panel dashboard-section" aria-labelledby="stats-title" :aria-busy="summaryLoading">
      <div class="panel-title">
        <div class="section-heading"><h2 id="stats-title">科研统计概览</h2><span v-if="summary" class="section-count">当前可见范围</span></div>
        <el-button text :loading="summaryLoading" @click="loadSummary"><RefreshCw :size="14" aria-hidden="true" />刷新</el-button>
      </div>
      <div class="panel-body">
        <StatePanel v-if="summaryError" title="统计加载失败" :description="summaryError" tone="error">
          <p v-if="summary" class="field-hint">下方保留上次成功获取的统计，可能尚未包含最新变更。</p>
          <el-button :loading="summaryLoading" @click="loadSummary">重试统计</el-button>
        </StatePanel>
        <div v-if="summaryLoading && !summary" class="stats-grid" role="status" aria-label="正在加载统计">
          <div v-for="stat in stats" :key="stat.key" class="stat-card" aria-hidden="true"><el-skeleton :rows="2" animated /></div>
        </div>
        <div v-else-if="summary" class="stats-grid">
          <router-link v-for="stat in stats" :key="stat.key" :to="stat.to" class="stat-card" :aria-label="`${stat.label} ${stat.value ?? 0}，前往列表`">
            <div class="stat-top"><span>{{ stat.label }}</span><component :is="stat.icon" :size="19" aria-hidden="true" /></div>
            <div class="stat-number">{{ stat.value?.toLocaleString('zh-CN') ?? '—' }}</div>
            <div class="stat-note">{{ stat.note }}</div>
          </router-link>
        </div>
        <p v-if="summary?.generated_at" class="field-hint dashboard-updated">
          统计更新于 <time :datetime="summary.generated_at">{{ date(summary.generated_at) }}</time>，数据以当前账户的可见范围为准。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.start-experiment{padding:24px;background:#f8fafc;border:1px solid #d5e1e7;border-radius:14px;box-shadow:5px 5px 18px #c7d3dc45,-4px -4px 14px #fff}.start-experiment h2{font-size:22px;line-height:1.5;color:var(--ink,#203a4b)}.start-experiment .start-kicker{color:#14606a}.start-experiment p{color:var(--muted,#536b7d)}.start-action{box-shadow:3px 4px 10px #087f8c26;transition:box-shadow .16s,transform .16s}.start-action:active{transform:translateY(1px);box-shadow:inset 2px 2px 5px #043c4860}.record-item{border:1px solid var(--line);border-radius:9px;padding:14px;margin:10px 0;background:#f8fafc;transition:border-color .16s,background-color .16s}.record-item:hover,.record-item:focus-within{border-color:#8eb6c0;background:#f0f7f8}.record-action,.todo-action{min-height:40px;display:inline-flex;align-items:center}.stat-card{padding:16px 18px;box-shadow:inset 2px 2px 6px #d4dfe650,inset -2px -2px 6px #fff;background:#edf3f6}.stat-number{font-size:25px}.dashboard-section{margin-bottom:20px}.section-count,.todo-content time,.record-content time,.stat-note{color:#536b7d}@media(max-width:760px){.start-experiment{padding:18px}.start-experiment h2{font-size:19px}.record-item{padding:12px;flex-wrap:wrap}.record-content{min-width:0;flex:1}.record-action{margin-left:auto}.stat-card{padding:14px}.stat-number{font-size:24px}}@media(prefers-reduced-motion:reduce){.start-action,.record-item{transition:none;transform:none}}
</style>
