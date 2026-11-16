<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, apiBlob, errorText, multipart } from '../api'
import { display } from '../quick/model'
import './mobile.css'

const busy = ref(false), error = ref(''), info = ref('')
const materials = ref<any[]>([])
const preview = ref<any>(null), confirmed = ref(false), fileInput = ref<HTMLInputElement>()
const readiness = ref<any>(null)
const materialName = (id: string) => materials.value.find(m => m.material_id === id)?.canonical_name || id

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await fn() } catch (e) { error.value = errorText(e) } finally { busy.value = false }
}
async function download(format: 'xlsx' | 'json') {
  await action(async () => {
    const { blob, filename } = await apiBlob(`/quick/dataset/download?format=${format}`)
    save(blob, filename)
    info.value = `已生成 ${filename}。主表 33 列，源的完整参数与明细表一并导出。`
  })
}
async function template() {
  await action(async () => {
    const { blob, filename } = await apiBlob('/quick/batch/template')
    save(blob, filename)
    info.value = `已下载 ${filename}（33 列，含反应物C）。`
  })
}
async function upload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  await action(async () => {
    const fd = new FormData(); fd.append('file', file)
    preview.value = (await multipart<any>('/quick/batch/preview', fd)).data
    confirmed.value = false
    const p = preview.value
    info.value = `${file.name}：识别「${p.sheet}」第 ${p.header_row} 行表头，匹配 ${p.matched_columns} 列；${p.row_count} 行可导入，${p.errors.length} 行有问题，${p.skipped.length} 行跳过。`
  })
  if (fileInput.value) fileInput.value.value = ''
}
async function confirm() {
  await action(async () => {
    const res = await api<any>('/quick/batch/confirm', { method: 'POST', body: { rows: preview.value.rows, expected_sha256: preview.value.expected_sha256, confirm: true } })
    const created = (res.data.created_materials || []).join('、')
    info.value = `已导入 ${res.data.count} 条实验记录${created ? `，并新增材料：${created}` : ''}。`
    preview.value = null; confirmed.value = false
  })
}
async function check() {
  await action(async () => { readiness.value = (await api<any>('/quick/dataset/readiness')).data })
}
const canConfirm = computed(() => !!preview.value && !!confirmed.value && preview.value.row_count > 0 && preview.value.errors.length === 0)
onMounted(async () => {
  try { materials.value = (await api<any[]>('/quick/materials')).data } catch { /* 材料仅用于显示名称 */ }
})
</script>

<template>
  <div>
    <p v-if="error" class="m-error-box" role="alert">{{ error }}</p>
    <p v-if="info" class="m-note" role="status">{{ info }}</p>

    <section class="m-card">
      <h2>导出</h2>
      <p class="m-sub">按当前账户可见数据导出；手机上生成文件后可直接分享或用 WPS 打开。</p>
      <div class="m-btns">
        <button class="primary" :disabled="busy" @click="download('xlsx')">导出 33 列 XLSX</button>
        <button :disabled="busy" @click="download('json')">导出完整 JSON</button>
      </div>
    </section>

    <section class="m-card">
      <h2>批量导入</h2>
      <p class="m-sub">可直接上传你原有的记录表：自动识别表头行，列顺序/空格/全角符号不影响，汇总行自动跳过。上传后先预览，再确认入库。</p>
      <div class="m-btns">
        <button :disabled="busy" @click="template">下载标准模板</button>
        <label class="m-field" style="gap:0">
          <span class="m-hint" style="margin-bottom:6px">选择 xlsx</span>
          <input ref="fileInput" type="file" accept=".xlsx,.xlsm" :disabled="busy" @change="upload">
        </label>
      </div>
      <div v-if="preview">
        <p class="m-sub" style="margin-top:12px">来源：{{ preview.sheet }} · 第 {{ preview.header_row }} 行表头</p>
        <p v-for="e in preview.errors" :key="e" class="m-warn">{{ e }}</p>
        <p v-for="s in preview.skipped" :key="s" class="m-hint">{{ s }}</p>
        <p v-if="preview.new_materials?.length" class="m-warn">将自动新增材料：{{ preview.new_materials.map((m: any) => m.canonical_name).join('、') }}</p>
        <table class="m-preview-table">
          <thead><tr><th>行</th><th>日期</th><th>材料</th><th>A/B/C</th><th>EPC</th></tr></thead>
          <tbody>
            <tr v-for="r in preview.rows" :key="r._line">
              <td>{{ r._line }}</td>
              <td>{{ r.experiment_date }}</td>
              <td>{{ r._material_name || materialName(r.material_id) }}</td>
              <td>{{ (r.program?.groups?.[0]?.steps || []).map((s: any) => s.source_label || '—').join('/') }}</td>
              <td>{{ display(r.results?.[0]?.thickness_before_nm) }}→{{ display(r.results?.[0]?.thickness_after_nm) }}</td>
            </tr>
          </tbody>
        </table>
        <label class="m-check"><input v-model="confirmed" type="checkbox">我已核对字段、单位与材料，确认导入</label>
        <div class="m-btns">
          <button class="primary" :disabled="busy || !canConfirm" @click="confirm">确认入库</button>
          <button :disabled="busy" @click="preview = null; confirmed = false">取消</button>
        </div>
      </div>
    </section>

    <section class="m-card">
      <h2>数据体检</h2>
      <p class="m-sub">检查可训练性、缺失字段与口径一致性；只读检查，不改动数据。</p>
      <div class="m-btns one">
        <button :disabled="busy" @click="check">开始体检</button>
      </div>
      <div v-if="readiness" style="margin-top:12px">
        <div class="m-kpis">
          <div class="m-kpi"><span>可训练结果行</span><strong>{{ display(readiness.eligible_count) }}</strong></div>
          <div class="m-kpi"><span>结果行总数</span><strong>{{ display((readiness.rows || []).length) }}</strong></div>
        </div>
        <p class="m-hint">训练状态：{{ readiness.training_status }} · 单位审计：{{ readiness.unit_audit?.status }}</p>
        <p v-if="(readiness.row_issues || []).length" class="m-warn">有 {{ readiness.row_issues.length }} 条结果存在待核对项（源映射、单位、均匀性定义或原报告 EPC 差异），请在电脑版逐项查看。</p>
        <p v-else class="m-hint">未发现逐行阻塞问题。</p>
        <p v-for="tip in readiness.recommendations || []" :key="tip" class="m-hint">· {{ tip }}</p>
      </div>
    </section>

    <p class="m-footer-links"><router-link to="/m/quick">回到快录</router-link><router-link to="/m/history">查看历史</router-link></p>
  </div>
</template>
