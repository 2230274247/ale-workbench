<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import { api, errorText } from '../api'
import * as echarts from 'echarts/core'
import { LineChart, ScatterChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, ScatterChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, ToolboxComponent, CanvasRenderer])

type XAxisKey = 'temperature_r1_c' | 'pressure_pa' | 'effective_cycles' | 'thickness_before_nm'

interface Row {
  process_code?: string
  material: string
  equipment: string
  temperature_r1_c: number | null
  pressure_pa: number | null
  effective_cycles: number | null
  thickness_before_nm: number | null
  thickness_after_nm: number | null
  epc_a_per_cycle: number | null
  uniformity_pct: number | null
  quality_status: string
}

const loading = ref(false)
const error = ref('')
const rows = ref<Row[]>([])
const summary = ref<any>({})
const training = ref<any>({})

const xAxis = ref<XAxisKey>('temperature_r1_c')
const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | undefined

const xAxisOptions: { key: XAxisKey; label: string }[] = [
  { key: 'temperature_r1_c', label: '温度 R1 (°C)' },
  { key: 'pressure_pa', label: '腔体压力 (Pa)' },
  { key: 'effective_cycles', label: '有效循环 (cycle)' },
  { key: 'thickness_before_nm', label: '实验前膜厚 (nm)' },
]

const seriesData = computed(() => {
  const key = xAxis.value
  const pts = rows.value
    .filter(r => r[key] != null && r.epc_a_per_cycle != null)
    .map(r => ({ name: r.material || '未确认', value: [r[key] as number, r.epc_a_per_cycle as number], cycles: r.effective_cycles }))
  const byMaterial = new Map<string, typeof pts>()
  for (const p of pts) {
    if (!byMaterial.has(p.name)) byMaterial.set(p.name, [])
    byMaterial.get(p.name)!.push(p)
  }
  return [...byMaterial.entries()].map(([name, arr]) => ({ name, type: 'scatter', data: arr }))
})

async function load() {
  loading.value = true; error.value = ''
  try {
    const r = await api<any>('/epc/results')
    rows.value = r.data.rows ?? []
    summary.value = r.data.summary ?? {}
    training.value = r.data.training ?? {}
    await nextTick()
    renderChart()
  } catch (e) { error.value = errorText(e) } finally { loading.value = false }
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const opts = xAxisOptions.find(o => o.key === xAxis.value)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.seriesName}<br/>${opts?.label}: ${p.value[0]}<br/>EPC: ${p.value[1]} Å/cycle` },
    legend: { type: 'scroll', top: 0 },
    grid: { left: 60, right: 20, top: 40, bottom: 50 },
    xAxis: { type: 'value', name: opts?.label ?? '', scale: true },
    yAxis: { type: 'value', name: 'EPC (Å/cycle)', scale: true },
    dataZoom: [{ type: 'inside' }],
    toolbox: { feature: { saveAsImage: {} } },
    series: seriesData.value,
  }, { notMerge: true })
}

function onAxisChange() { renderChart() }
function onResize() { chart?.resize() }

const beforeN = ref<number | null>(null)
const afterN = ref<number | null>(null)
const cyclesN = ref<number | null>(null)
const calcResult = ref<any>(null)
const calcError = ref('')
async function calc() {
  calcError.value = ''; calcResult.value = null
  if (beforeN.value == null || afterN.value == null || !cyclesN.value) { calcError.value = '请填写膜厚前后与有效循环次数。'; return }
  try { const r = await api<any>('/epc/calculator', { query: { before_nm: beforeN.value, after_nm: afterN.value, cycles: cyclesN.value } }); calcResult.value = r.data } catch (e) { calcError.value = errorText(e) }
}

const p = ref({ r1_c: null as number | null, n2_sccm: null as number | null, pressure_pa: null as number | null, effective_cycles: null as number | null, before_nm: null as number | null })
const predResult = ref<any>(null)
const predError = ref('')
async function predict() {
  predError.value = ''; predResult.value = null
  const q: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(p.value)) if (v != null) q[k] = v
  if (Object.keys(q).length === 0) { predError.value = '请至少填写一个工艺参数。'; return }
  try { const r = await api<any>('/epc/predict', { query: q }); predResult.value = r.data } catch (e) { predError.value = errorText(e) }
}

onMounted(() => { load(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h1>EPC 预测与结果可视化</h1>
        <p class="sub">EPC = Etch Per Cycle（每循环刻蚀量，Å/cycle）。原始量测、确定性派生值与模型预测分开呈现。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="cards">
      <el-card shadow="never"><div class="stat"><span class="num">{{ summary.epc_count ?? 0 }}</span><span class="lbl">有 EPC 的结果条数</span></div></el-card>
      <el-card shadow="never"><div class="stat"><span class="num">{{ summary.epc_mean != null ? Number(summary.epc_mean).toFixed(3) : '—' }}</span><span class="lbl">EPC 均值 (Å/cycle)</span></div></el-card>
      <el-card shadow="never"><div class="stat"><span class="num">{{ summary.epc_min != null ? Number(summary.epc_min).toFixed(3) : '—' }}</span><span class="lbl">最小 / {{ summary.epc_max != null ? Number(summary.epc_max).toFixed(3) : '—' }}</span></div></el-card>
      <el-card shadow="never"><div class="stat"><span class="num">{{ training.eligible_count ?? 0 }}</span><span class="lbl">已确认可训练条数</span></div></el-card>
    </div>

    <el-alert v-if="training.total_rows != null" type="warning" :closable="false" show-icon class="mb"
      :title="`当前可训练 ${training.eligible_count} / ${training.total_rows} 条。预测仅使用已确认可训练的数据，数据不足时不会生成预测指标。`" />

    <el-card shadow="never" class="mb">
      <template #header>
        <div class="card-head"><span>EPC 结果分布</span>
          <el-select v-model="xAxis" size="small" style="width: 180px" @change="onAxisChange">
            <el-option v-for="o in xAxisOptions" :key="o.key" :label="o.label" :value="o.key" />
          </el-select>
        </div>
      </template>
      <div ref="chartEl" class="chart" role="img" aria-label="EPC 结果散点图"></div>
      <p v-if="!rows.length && !loading" class="empty">当前筛选范围内没有含 EPC 的结果。</p>
    </el-card>

    <div class="two-col">
      <el-card shadow="never">
        <template #header><div class="card-head"><span>EPC 确定性计算</span></div></template>
        <el-form label-width="130px" size="small">
          <el-form-item label="膜厚前 (nm)"><el-input-number v-model="beforeN" :min="0" controls-position="right" /></el-form-item>
          <el-form-item label="膜厚后 (nm)"><el-input-number v-model="afterN" :min="0" controls-position="right" /></el-form-item>
          <el-form-item label="有效循环 (cycle)"><el-input-number v-model="cyclesN" :min="1" controls-position="right" /></el-form-item>
          <el-form-item><el-button type="primary" @click="calc">计算</el-button></el-form-item>
        </el-form>
        <el-alert v-if="calcResult" type="success" :closable="false" show-icon>
          <template #title>EPC = {{ Number(calcResult.epc_a_per_cycle).toFixed(4) }} Å/cycle（净减薄 {{ Number(calcResult.thickness_loss_nm).toFixed(4) }} nm）</template>
        </el-alert>
        <el-alert v-if="calcError" type="error" :title="calcError" show-icon />
      </el-card>

      <el-card shadow="never">
        <template #header><div class="card-head"><span>EPC 预测（透明模型）</span></div></template>
        <el-form label-width="150px" size="small">
          <el-form-item label="温度 R1 (°C)"><el-input-number v-model="p.r1_c" controls-position="right" /></el-form-item>
          <el-form-item label="N₂ (sccm)"><el-input-number v-model="p.n2_sccm" controls-position="right" /></el-form-item>
          <el-form-item label="腔体压力 (Pa)"><el-input-number v-model="p.pressure_pa" controls-position="right" /></el-form-item>
          <el-form-item label="有效循环 (cycle)"><el-input-number v-model="p.effective_cycles" :min="0" controls-position="right" /></el-form-item>
          <el-form-item label="实验前膜厚 (nm)"><el-input-number v-model="p.before_nm" :min="0" controls-position="right" /></el-form-item>
          <el-form-item><el-button type="primary" @click="predict">预测</el-button></el-form-item>
        </el-form>
        <el-alert v-if="predResult?.status === 'ok'" type="success" :closable="false" show-icon>
          <template #title>预测 EPC ≈ {{ Number(predResult.predicted_epc_a_per_cycle).toFixed(4) }} Å/cycle（模型 n={{ predResult.model.n }}，R²={{ predResult.model.r_squared != null ? Number(predResult.model.r_squared).toFixed(3) : '—' }}）</template>
        </el-alert>
        <el-alert v-else-if="predResult" type="warning" :closable="false" show-icon :title="predResult.message" />
        <el-alert v-if="predError" type="error" :title="predError" show-icon />
      </el-card>
    </div>

    <el-card shadow="never" class="mb">
      <template #header><div class="card-head"><span>结果明细（前 200 条）</span></div></template>
      <el-table :data="rows.slice(0, 200)" size="small" max-height="420">
        <el-table-column prop="process_code" label="实验编号" min-width="110" />
        <el-table-column prop="material" label="材料" min-width="90" />
        <el-table-column prop="equipment" label="设备" min-width="100" />
        <el-table-column prop="effective_cycles" label="有效循环" min-width="90" />
        <el-table-column label="膜厚前/后 (nm)" min-width="150">
          <template #default="{ row }">{{ row.thickness_before_nm }} → {{ row.thickness_after_nm }}</template>
        </el-table-column>
        <el-table-column label="EPC (Å/cycle)" min-width="120">
          <template #default="{ row }"><strong>{{ row.epc_a_per_cycle != null ? Number(row.epc_a_per_cycle).toFixed(3) : '—' }}</strong></template>
        </el-table-column>
        <el-table-column prop="uniformity_pct" label="均匀性 (%)" min-width="100" />
        <el-table-column prop="quality_status" label="质量状态" min-width="90" />
      </el-table>
    </el-card>
  </section>
</template>

<style scoped>
.page { padding: 20px; max-width: 1280px; margin: 0 auto; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-head h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: #64748b; margin: 0; font-size: 13px; }
.mb { margin-bottom: 16px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat { display: flex; flex-direction: column; gap: 4px; }
.stat .num { font-size: 26px; font-weight: 600; color: #4f46e5; }
.stat .lbl { font-size: 12px; color: #64748b; }
.card-head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
.chart { height: 340px; width: 100%; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.empty { color: #94a3b8; text-align: center; padding: 20px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
</style>
