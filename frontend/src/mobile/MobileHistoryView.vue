<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorText } from '../api'
import { display } from '../quick/model'
import './mobile.css'

interface RunResult { result_id: string; alias: string; material_name: string | null; effective_cycles: number | null; thickness_before_nm: number | null; thickness_after_nm: number | null; epc_a_per_cycle: number | null; quality_status: string }
interface RunItem { run_id: number; process_code: string; experiment_date: string; daily_no: number; state: string; external_experiment_id: string | null; results: RunResult[] }

const items = ref<RunItem[]>([]), total = ref(0), page = ref(1), busy = ref(false), loading = ref(true), error = ref('')
const query = ref('')
const filtered = computed(() => {
  const key = query.value.trim().toLowerCase()
  if (!key) return items.value
  return items.value.filter(run => [run.process_code, run.experiment_date, run.external_experiment_id, ...run.results.map(r => r.alias)].some(v => String(v ?? '').toLowerCase().includes(key)))
})
async function load(reset = true) {
  if (busy.value) return
  busy.value = true
  if (reset) page.value = 1
  error.value = ''
  try {
    const { data } = await api<any>('/quick/runs', { query: { page: page.value } })
    items.value = reset ? data.items : [...items.value, ...data.items]
    total.value = data.total
    page.value = Number(data.page || page.value)
  } catch (e) { error.value = errorText(e) } finally { busy.value = false; loading.value = false }
}
const more = computed(() => items.value.length < total.value)
const qualityLabel = (value: string) => value === 'approved' ? '有效' : value === 'excluded' ? '排除' : '待复核'
onMounted(() => load())
</script>

<template>
  <div>
    <p v-if="error" class="m-error-box" role="alert">{{ error }}</p>
    <label class="m-field" style="margin-bottom:12px">
      <span>筛选（实验ID / 日期 / 样品）</span>
      <input v-model="query" placeholder="输入关键字">
    </label>
    <p class="m-sub">共 {{ total }} 次运行 · 当前显示 {{ filtered.length }} 条</p>
    <p v-if="loading" class="m-note">正在读取…</p>
    <p v-else-if="!filtered.length" class="m-empty">暂无记录。到「快录」新建一条，或在「数据集」批量导入。</p>
    <div class="m-list">
      <router-link v-for="run in filtered" :key="run.run_id" class="m-item" :to="`/m/quick?run=${run.run_id}`">
        <h3>{{ run.experiment_date }} · 第 {{ run.daily_no }} 次<span>{{ run.state === 'draft' ? '草稿' : '已记录' }}</span></h3>
        <p class="m-hint" style="margin:2px 0 0">{{ run.process_code }}<template v-if="run.external_experiment_id"> · 原表ID {{ run.external_experiment_id }}</template></p>
        <dl v-for="r in run.results" :key="r.result_id">
          <div><dt>样品</dt> <dd>{{ r.alias }}</dd></div>
          <div><dt>材料</dt> <dd>{{ r.material_name || '—' }}</dd></div>
          <div><dt>循环</dt> <dd>{{ display(r.effective_cycles) }}</dd></div>
          <div><dt>EPC</dt> <dd>{{ r.epc_a_per_cycle === null ? '—' : Number(r.epc_a_per_cycle).toFixed(3) }}</dd></div>
          <div><dt>前→后</dt> <dd>{{ display(r.thickness_before_nm) }} → {{ display(r.thickness_after_nm) }}</dd></div>
          <div><dt>质量</dt> <dd>{{ qualityLabel(r.quality_status) }}</dd></div>
        </dl>
        <p v-if="!run.results.length" class="m-hint">无结果行 · 只有参数草稿，点击补充膜厚</p>
      </router-link>
    </div>
    <div v-if="more" class="m-btns one" style="margin-top:14px">
      <button class="ghost" :disabled="busy" @click="page += 1; load(false)">{{ busy ? '读取中…' : '加载更多' }}</button>
    </div>
    <p class="m-footer-links"><router-link to="/m/quick">回到快录</router-link><router-link to="/m/dataset">导入 / 导出</router-link></p>
  </div>
</template>
