<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorText } from '../api'
import { useAuth } from '../auth'
import { cleanNumbers, display, edit, fresh, step, uid } from '../quick/model'
import './mobile.css'

const route = useRoute(), router = useRouter(), auth = useAuth()
const codes = ['A', 'B', 'C'] as const
const form = ref<any>(fresh()), saved = ref<any>(null), baseProgram = ref<any>(null)
const sources = ref<any[]>([]), materials = ref<any[]>([])
const delta = reactive<Record<string, string>>({ A: '', B: '', C: '' })
const busy = ref(false), loading = ref(true), error = ref(''), message = ref('')
const rangePattern = /^([-+]?\d+(?:\.\d+)?)\s*[-–~]\s*([-+]?\d+(?:\.\d+)?)$/
const singlePattern = /^[-+]?(?:\d+\.?\d*|\.\d+)?$/

function blank() {
  const value = fresh()
  value.program.groups = [{ group_id: uid(), code: 'A', repeat_count: null, steps: [step(), step(), step()] }]
  return value
}
function ensure() {
  const groups = form.value.program.groups
  if (!groups.length) groups.push({ group_id: uid(), code: 'A', repeat_count: null, steps: [] })
  while (groups[0].steps.length < 3) groups[0].steps.push(step())
}
const slots = computed(() => codes.map((code, index) => ({ code, index, st: form.value.program.groups[0].steps[index] })))
const extras = computed(() => {
  const g = form.value.program.groups[0]
  const moreSteps = Math.max(0, (g?.steps?.length || 0) - 3)
  const moreGroups = Math.max(0, form.value.program.groups.length - 1)
  return { moreSteps, moreGroups }
})
const r0 = computed(() => form.value.results?.[0] || {})
const derived = computed(() => {
  const a = r0.value.thickness_before_nm, b = r0.value.thickness_after_nm, n = Number(r0.value.effective_cycles)
  if (a === null || a === '' || b === null || b === '' || a === undefined || b === undefined) return { loss: null, epc: null }
  const loss = Number(a) - Number(b)
  const epc = n > 0 ? loss * 10 / n : null
  return { loss: Number.isFinite(loss) ? loss : null, epc: epc !== null && Number.isFinite(epc) ? epc : null }
})
const quality = [
  { value: 'unreviewed', label: '待复核' },
  { value: 'approved', label: '有效' },
  { value: 'excluded', label: '排除' },
]

async function nextNumber() {
  if (saved.value) return
  try { form.value.daily_no = (await api<any>('/quick/next-number', { query: { experiment_date: form.value.experiment_date } })).data.daily_no } catch { /* 次序由服务端最终确定 */ }
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const [m, s] = await Promise.all([api<any[]>('/quick/materials'), api<any[]>('/quick/sources')])
    materials.value = m.data; sources.value = s.data
    const id = Number(route.query.run)
    if (id) {
      const run = (await api<any>(`/quick/runs/${id}`)).data
      saved.value = run
      form.value = edit(run)
      baseProgram.value = JSON.parse(JSON.stringify(run.program || {}))
      ensure()
      codes.forEach(code => {
        const st = form.value.program.groups[0].steps[codes.indexOf(code)]
        delta[code] = st.delta_p_pa_min !== null && st.delta_p_pa_max !== null && st.delta_p_pa_min !== undefined && st.delta_p_pa_max !== undefined
          ? `${st.delta_p_pa_min}–${st.delta_p_pa_max}` : (st.delta_p_pa ?? '')
      })
      message.value = `已载入 ${run.process_code} · 版本 ${run.version}`
    } else {
      saved.value = null; baseProgram.value = null
      form.value = blank(); codes.forEach(code => { delta[code] = '' })
      message.value = ''
      await nextNumber()
    }
  } catch (e) { error.value = errorText(e) } finally { loading.value = false }
}
function applyDelta(st: any, text: string) {
  const value = String(text ?? '').trim()
  if (!value) { st.delta_p_pa = null; st.delta_p_pa_min = null; st.delta_p_pa_max = null; return null }
  const match = value.match(rangePattern)
  if (match) {
    if (Number(match[1]) > Number(match[2])) return `下限大于上限 ${value}`
    st.delta_p_pa = null; st.delta_p_pa_min = match[1]; st.delta_p_pa_max = match[2]; return null
  }
  if (singlePattern.test(value)) { st.delta_p_pa = value; st.delta_p_pa_min = null; st.delta_p_pa_max = null; return null }
  return `格式应为单值或 70–100，收到 ${value}`
}
async function save(state: 'draft' | 'recorded') {
  if (busy.value) return
  error.value = ''
  if (!auth.canWrite) { error.value = '当前账户为只读权限，无法保存记录。'; return }
  if (!form.value.experiment_date) { error.value = '请选择实验日期。'; return }
  if (state === 'recorded' && !form.value.material_id) { error.value = '请选择薄膜材料，或先存为草稿。'; return }
  const group = form.value.program.groups[0]
  const problems: string[] = []
  slots.value.forEach(({ code, st }) => {
    if (!st) return
    const bad = applyDelta(st, delta[code])
    if (bad) problems.push(`${code} 源 ΔP ${bad}`)
    st.enabled = !!(st.source_label || st.pulse_ms !== null || st.purge_s !== null || st.wait_s !== null || st.delta_p_pa !== null || st.delta_p_pa_min !== null)
  })
  if (problems.length) { error.value = problems.join('；'); return }
  group.repeat_count = form.value.results?.[0]?.effective_cycles ?? null
  busy.value = true
  try {
    const payload = cleanNumbers(JSON.parse(JSON.stringify(form.value)))
    payload.state = state
    if (baseProgram.value?.groups?.length) {
      // 手机端只编辑第一组前 3 步；其余组与步骤原样带回，避免覆盖电脑端录入的结构。
      const merged = JSON.parse(JSON.stringify(baseProgram.value))
      const target = merged.groups[0]
      target.repeat_count = payload.program.groups[0].repeat_count
      codes.forEach((_, index) => {
        const edited = payload.program.groups[0].steps[index]
        if (!edited) return
        if (target.steps[index]) target.steps[index] = edited
        else target.steps.push(edited)
      })
      payload.program = merged
    }
    const path = '/quick/runs' + (saved.value ? `/${saved.value.run_id}` : '')
    const { data } = await api<any>(path, { method: saved.value ? 'PUT' : 'POST', body: payload })
    saved.value = data
    form.value = edit(data)
    baseProgram.value = JSON.parse(JSON.stringify(data.program || {}))
    ensure()
    message.value = `已保存 · ${data.process_code} · ${new Date().toLocaleTimeString('zh-CN')}`
    await router.replace({ path: '/m/quick', query: { run: data.run_id } })
  } catch (e) { error.value = errorText(e) } finally { busy.value = false }
}
function reset() {
  if (busy.value) return
  void router.replace({ path: '/m/quick' }).then(() => {
    saved.value = null; baseProgram.value = null; form.value = blank(); codes.forEach(code => { delta[code] = '' })
    message.value = '已清空，可录入下一条实验。'; void nextNumber()
  })
}
onMounted(load)
</script>

<template>
  <div>
    <p v-if="error" class="m-error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="m-note">正在读取材料、源与记录…</p>
    <p v-else-if="message" class="m-note" role="status">{{ message }}</p>

    <template v-if="!loading">
      <section class="m-card">
        <h2>基础信息</h2>
        <div class="m-row">
          <label class="m-field"><span>实验日期</span><input v-model="form.experiment_date" type="date" @change="nextNumber"></label>
          <label class="m-field"><span>当日第几次</span><input v-model.number="form.daily_no" type="number" inputmode="numeric" min="1"></label>
        </div>
        <div class="m-row one">
          <label class="m-field"><span>薄膜材料</span>
            <select v-model="form.material_id">
              <option :value="null">请选择材料</option>
              <option v-for="m in materials" :key="m.material_id" :value="m.material_id">{{ m.canonical_name }}</option>
            </select>
          </label>
        </div>
        <p v-if="!materials.length" class="m-hint">材料目录为空：请先在电脑版「实验快录」或材料管理中添加材料。</p>
        <div class="m-row">
          <label class="m-field"><span>外部实验ID（原表）</span><input v-model="form.external_experiment_id" placeholder="可留空"></label>
          <label class="m-field"><span>批次ID</span><input v-model="form.external_batch_id" placeholder="可留空"></label>
        </div>
      </section>

      <section class="m-card">
        <h2>工艺条件</h2>
        <div class="m-row">
          <label class="m-field"><span>设备 / 腔体</span><input v-model="form.environment.equipment" placeholder="如 负一楼"></label>
          <label class="m-field"><span>工艺类型</span>
            <select v-model="form.environment.process_type">
              <option :value="null">未标注</option>
              <option value="Thermal ALE">Thermal ALE</option>
              <option value="Plasma ALE">Plasma ALE</option>
            </select>
          </label>
        </div>
        <div class="m-row three">
          <label class="m-field"><span>R1 (°C)</span><input v-model="form.environment.r1_temperature_c" inputmode="decimal" type="number" step="any"></label>
          <label class="m-field"><span>腔压 (Pa)</span><input v-model="form.environment.chamber_pressure_pa" inputmode="decimal" type="number" step="any"></label>
          <label class="m-field"><span>N₂ (sccm)</span><input v-model="form.environment.n2_flow_sccm" inputmode="decimal" type="number" step="any"></label>
        </div>
        <div class="m-row">
          <label class="m-field"><span>RF/ICP 功率 (W)</span><input v-model="form.environment.rf_icp_power_w" inputmode="decimal" type="number" step="any"></label>
          <label class="m-field"><span>Bias 功率 (W)</span><input v-model="form.environment.bias_power_w" inputmode="decimal" type="number" step="any"></label>
        </div>
      </section>

      <section v-for="slot in slots" :key="slot.code" class="m-card">
        <div class="m-src-head"><strong>{{ slot.code }} 源</strong><span class="m-badge">与参数绑定</span></div>
        <div class="m-row one">
          <label class="m-field"><span>反应物</span>
            <select v-model="slot.st.source_label">
              <option value="">未使用</option>
              <option v-for="s in sources" :key="s.source_id" :value="s.canonical_name">{{ s.canonical_name }}</option>
            </select>
          </label>
        </div>
        <div class="m-row">
          <label class="m-field"><span>Pulse (ms)</span><input v-model="slot.st.pulse_ms" inputmode="decimal" type="number" step="any"></label>
          <label class="m-field"><span>ΔP (Pa)</span><input v-model="delta[slot.code]" inputmode="decimal" placeholder="单值或 70–100"></label>
        </div>
        <div class="m-row">
          <label class="m-field"><span>Purge (s)</span><input v-model="slot.st.purge_s" inputmode="decimal" type="number" step="any"></label>
          <label class="m-field"><span>Wait (s)</span><input v-model="slot.st.wait_s" inputmode="decimal" type="number" step="any"></label>
        </div>
      </section>

      <section class="m-card">
        <h2>循环与结果</h2>
        <div class="m-row">
          <label class="m-field"><span>本段有效循环</span><input v-model="r0.effective_cycles" inputmode="numeric" type="number" min="1"></label>
          <label class="m-field"><span>均匀性 (%)</span><input v-model="r0.uniformity_pct" inputmode="decimal" type="number" step="any"></label>
        </div>
        <div class="m-row">
          <label class="m-field"><span>刻蚀前膜厚 (nm)</span><input v-model="r0.thickness_before_nm" inputmode="decimal" type="number" step="any"></label>
          <label class="m-field"><span>刻蚀后膜厚 (nm)</span><input v-model="r0.thickness_after_nm" inputmode="decimal" type="number" step="any"></label>
        </div>
        <div class="m-kpis">
          <div class="m-kpi"><span>净减薄 (nm)</span><strong>{{ display(derived.loss) }}</strong></div>
          <div class="m-kpi"><span>EPC (Å/cycle)</span><strong>{{ derived.epc === null ? '—' : derived.epc.toFixed(3) }}</strong></div>
        </div>
        <div class="m-row">
          <label class="m-field"><span>数据质量</span>
            <select v-model="r0.quality_status">
              <option v-for="q in quality" :key="q.value" :value="q.value">{{ q.label }}</option>
            </select>
          </label>
          <label class="m-field"><span>样品标识</span><input v-model="r0.alias"></label>
        </div>
        <label class="m-check"><input v-model="r0.use_for_model_override" type="checkbox" :true-value="true" :false-value="null">用于建模（覆盖自动判定）</label>
        <div class="m-row one" style="margin-top:10px">
          <label class="m-field"><span>备注</span><textarea v-model="form.note" rows="2" placeholder="实验目的 / 异常 / 观察"></textarea></label>
        </div>
        <p v-if="extras.moreSteps || extras.moreGroups" class="m-warn">
          该记录含 {{ extras.moreGroups }} 个额外工艺组、{{ extras.moreSteps }} 个额外步骤：手机端只编辑 A/B/C 三步，其余结构保存时原样保留；如需修改请用电脑版。
        </p>
      </section>

      <div class="m-sticky-save">
        <button class="ghost" :disabled="busy" @click="save('draft')">{{ busy ? '处理中…' : '存草稿' }}</button>
        <button class="primary" :disabled="busy" @click="save('recorded')">保存记录</button>
      </div>
      <div class="m-btns one" style="margin-top:12px">
        <button :disabled="busy" class="ghost" @click="reset">清空，录入下一条</button>
      </div>
      <p class="m-footer-links"><router-link to="/m/history">查看历史记录</router-link><router-link to="/m/dataset">导入 / 导出</router-link></p>
    </template>
  </div>
</template>
