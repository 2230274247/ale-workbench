<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { Plus, Search, RefreshCw } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, ApiError, errorText } from '../api'
import { useAuth } from '../auth'
import BatchCodeStatus from '../components/BatchCodeStatus.vue'
import SampleExperimentHistory from '../components/SampleExperimentHistory.vue'
import SampleResearchReview from '../components/SampleResearchReview.vue'
import PageHeading from '../components/PageHeading.vue'
import FormSection from '../components/FormSection.vue'
import StatePanel from '../components/StatePanel.vue'
import LifecycleDialog from '../components/LifecycleDialog.vue'
import {usedSampleCodes,suggestedCodes} from '../experiments/sampleCodes'
import type { Batch, Sample } from '../contracts'

type Row = Record<string, any>
type View = 'create' | 'edit' | 'detail'
const props = defineProps<{ kind: 'batches' | 'samples' }>()
const auth = useAuth()
const route = useRoute()
const router = useRouter()
const isBatch = computed(() => props.kind === 'batches')
const noun = computed(() => isBatch.value ? '批次' : '样品')
const idKey = computed(() => isBatch.value ? 'batch_id' : 'sample_id')
const codeKey = computed(() => isBatch.value ? 'batch_code' : 'sample_code')
const rows = ref<Row[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const drawer = ref(false)
const view = ref<View>('detail')
const selected = ref<Row>({})
const saving = ref(false)
const includeVoided = ref(false)
const includeArchived = ref(false)
const voidDialog = ref(false)
const voidTarget = ref<Row>({})
const voidReason = ref('')
const voidError = ref('')
const voidConflict = ref(false)
const voidHistory = ref<Row[]>([])
const voidHistoryOpen = ref(false)
const voidHistoryLoading = ref(false)
const voidHistoryError = ref('')
const owns = (row: Row) => auth.isAdmin || (auth.canWrite && row.owner_user_id === auth.user?.user_id)
// 生命周期与删除影响：所有计数来自后端真实查询，权限外依赖只显示通用提示。
const lifecycleOpen = ref(false)
const lifecycleTarget = ref<Row>({})
function openLifecycle(row: Row) {
  if (!auth.canWrite || !owns(row)) return
  lifecycleTarget.value = row
  lifecycleOpen.value = true
}
function lifecycleApplied(action: string, data: Row) {
  const labels: Record<string, string> = {
    archive: '已归档', archive_with_dependents: '已归档批次及所选未使用样品', void: '已作废',
    delete: '已删除', restore: '已恢复',
  }
  showFeedback(`${noun.value}“${data[codeKey.value] ?? lifecycleTarget.value[codeKey.value]}”${labels[action] ?? '已更新'}。`, 'success', data)
  if (action === 'delete' && selected.value[idKey.value] === lifecycleTarget.value[idKey.value]) drawer.value = false
  if (selected.value[idKey.value] === lifecycleTarget.value[idKey.value]) selected.value = { ...selected.value, ...data }
  void load()
}
const canVoid = (row: Row) => !isBatch.value && !row.voided_at && !row.archived_at && owns(row)
async function beginVoid(row: Row) {
  if (!canVoid(row) || saving.value || !(await confirmDiscard())) return
  voidReason.value = ''
  voidError.value = ''
  voidConflict.value = false
  try {
    const latest = (await api<Row>(`/samples/${row.sample_id}`)).data
    if (!canVoid(latest)) { await open(latest, 'detail', true); await load(); return }
    voidTarget.value = latest
    voidDialog.value = true
  } catch (cause) { showFeedback(`读取样品失败：${errorText(cause)}`, 'error', row) }
}
async function submitVoid() {
  if (saving.value || voidConflict.value || !canVoid(voidTarget.value)) return
  const reason = voidReason.value.trim()
  if (!reason) { voidError.value = '请填写作废原因。'; return }
  saving.value = true
  voidError.value = ''
  try {
    const result = await api<Row>(`/samples/${voidTarget.value.sample_id}/void`, {
      method: 'POST', body: { expected_row_version: voidTarget.value.row_version, reason },
    })
    voidDialog.value = false
    showFeedback(`样品“${result.data.sample_code}”已作废。记录和历史保留，编码不可复用，业务状态未改变。`, 'success', result.data)
    await open(result.data, 'detail', true)
    await load()
  } catch (cause) {
    voidConflict.value = cause instanceof ApiError && cause.status === 409
    voidError.value = `作废失败：${errorText(cause)}${voidConflict.value ? '。原因已保留，请重载核对后重试。' : ''}`
  } finally { saving.value = false }
}
async function reloadVoid() {
  try {
    const latest = (await api<Row>(`/samples/${voidTarget.value.sample_id}`)).data
    voidTarget.value = latest
    voidConflict.value = false
    if (latest.voided_at) { voidDialog.value = false; await open(latest, 'detail', true); await load() }
    else voidError.value = '已重载最新版本，作废原因已保留。请核对是否为误建且未使用的样品后重试。'
  } catch (cause) { voidError.value = errorText(cause) }
}
async function loadVoidHistory() {
  voidHistoryOpen.value = true
  voidHistoryLoading.value = true
  voidHistoryError.value = ''
  try {
    voidHistory.value = (await api<Row[]>('/transitions', { query: { sample_id: selected.value.sample_id, size: 100 } })).data
  } catch (cause) { voidHistoryError.value = errorText(cause) }
  finally { voidHistoryLoading.value = false }
}
const actionFeedback = ref<{ kind: string; message: string; tone: 'success' | 'error'; row: Row; shortcut: boolean } | null>(null)
const feedback = computed(() => actionFeedback.value?.kind === props.kind ? actionFeedback.value : null)
const canArchive = (row: Row) => isBatch.value && !row.archived_at && !row.voided_at
  && (auth.isAdmin || (auth.canWrite && row.owner_user_id === auth.user?.user_id))
function showFeedback(message: string, tone: 'success' | 'error', row: Row, shortcut = false) {
  actionFeedback.value = { kind: props.kind, message, tone, row, shortcut }
}
async function archiveBatch(row: Row) {
  if (!canArchive(row) || saving.value) return
  saving.value = true
  try {
    const latest = (await api<Row>(`/batches/${row.batch_id}`)).data
    if (!canArchive(latest)) {
      showFeedback(`批次“${latest.batch_code}”已归档，历史记录与关联关系保留。`, 'success', latest)
      if (selected.value.batch_id === latest.batch_id) selected.value = latest
      await load()
      return
    }
    try {
      await ElMessageBox.confirm(`确认归档批次“${latest.batch_code}”？归档后保留样品、实验计划、工艺执行及全部历史关联；业务状态保持不变。`, '归档批次', {
        type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '取消',
      })
    } catch { return }
    const result = await api<Row>(`/batches/${latest.batch_id}/archive`, {
      method: 'POST', body: { expected_row_version: latest.row_version },
    })
    if (selected.value.batch_id === latest.batch_id) selected.value = result.data
    showFeedback(`批次“${result.data.batch_code}”已归档。历史记录与关联关系已保留，业务状态未改变。`, 'success', result.data)
    await load()
  } catch (cause) {
    showFeedback(`归档失败：${errorText(cause)}${cause instanceof ApiError && cause.status === 409 ? '。请核对最新记录后重试，重试会重新读取版本。' : ''}`, 'error', row, true)
  } finally { saving.value = false }
}
const formError = ref('')
const conflict = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detailReady = ref(false)
const batchSamples = ref<Row[]>([])
const batchSamplesLoading = ref(false)
const batchSampleError = ref('')
const batchSampleTotal = ref(0)
const batchSamplePage = ref(1)
const batchOptions = ref<Batch[]>([])
const batchCache = reactive(new Map<number, Batch>())
const parentCache = new Map<number, Sample>()
const batchesLoading = ref(false)
const batchesError = ref('')
const parentOptions = ref<Sample[]>([])
const parentsLoading = ref(false)
const parentsError = ref('')
const filters = reactive({ keyword: '', status: '', batch_id: undefined as number | undefined, page: 1, size: 20, sort: '-created_at' })
const form = reactive<Row>({})
const fieldErrors = reactive<Record<string, string>>({})
const baseline = ref('')
let listRequest = 0
let detailRequest = 0
let batchRequest = 0
let parentRequest = 0
let childRequest = 0
let routeApproved = false
let active = true
let discardPrompt: Promise<boolean> | null = null

const batchStatus: Record<string, string> = { active: '进行中', archived: '已归档', quarantined: '已隔离' }
// 批量创建小样（第四轮契约第 1 节）：沉积批次 → 母片 → 小样。
// 手填数据库 ID 容易 404，因此母片从该批次的真实样品候选中选择。
const batchCreateOpen = ref(false)
const batchCreateTarget = ref<Row | null>(null)
const batchCreateError = ref('')
const batchCreating = ref(false)
const batchConflictCodes = ref<string[]>([])
const batchParents = ref<Row[]>([])
const batchParentsLoading = ref(false)
const batchParentsError = ref('')
const batchItems = ref<Row[]>([])
const batchBaseline = ref('')
const batchForm = reactive({
  parent_sample_id: undefined as number | undefined, count: 5, prefix: '', start: 1,
  pre_treatment: '', surface_state: '', size_desc: '', nominal_thickness_nm: '',
  exclude_from_analysis: false, exclude_reason: '',
})
let bulkParentRequest = 0
const bulkBatchId = ref<number>()
const inlineBatchOpen = ref(false)
const inlineBatchError = ref('')
const inlineBatchSaving = ref(false)
const inlineBatch = reactive({ batch_code: '', batch_name: '', material: 'PECVD SiNx:H' })
function openInlineBatch() {
  if (!auth.canWrite) return
  inlineBatchError.value = ''
  Object.assign(inlineBatch, { batch_code: '', batch_name: '', material: 'PECVD SiNx:H' })
  inlineBatchOpen.value = true
}
async function saveInlineBatch() {
  if (inlineBatchSaving.value) return
  const code = inlineBatch.batch_code.trim(), name = inlineBatch.batch_name.trim()
  if (!code || !name) { inlineBatchError.value = '请填写批次编号和批次名称。'; return }
  inlineBatchSaving.value = true; inlineBatchError.value = ''
  try {
    const result = await api<Row>('/batches', { method: 'POST', body: { batch_code: code, batch_name: name, material: inlineBatch.material.trim() || undefined } })
    const batch = result.data
    batchCache.set(batch.batch_id, batch as Batch)
    batchOptions.value = [batch as Batch, ...batchOptions.value.filter(item => item.batch_id !== batch.batch_id)]
    if (batchCreateOpen.value) {
      // Bulk creation: keep every existing row and attribute, only switch target.
      bulkBatchId.value = batch.batch_id
      batchCreateTarget.value = batch as Row
      batchForm.parent_sample_id = undefined; batchParents.value = []
      if(!batchForm.prefix.trim())batchForm.prefix = batch.batch_code
      if (!batchItems.value.length) buildBatchItems()
    } else {
      form.batch_id = batch.batch_id
      void suggestSingleCode()
    }
    inlineBatchOpen.value = false
    ElMessage.success(`批次“${batch.batch_code}”已创建并选中，已填写的样品内容保持不变。`)
  } catch (cause) { inlineBatchError.value = errorText(cause) } finally { inlineBatchSaving.value = false }
}
const occupiedCodes=ref(new Set<string>())
const batchSnapshot = () => JSON.stringify([batchForm, batchItems.value, batchCreateTarget.value?.batch_id ?? null])
const batchDirty = computed(() => batchCreateOpen.value && batchSnapshot() !== batchBaseline.value)
function buildBatchItems() {
  const count = Number(batchForm.count), start = Number(batchForm.start)
  if (!Number.isInteger(count) || count < 1 || count > 50 || !Number.isSafeInteger(start) || start < 0 || start > 999999) { batchCreateError.value = '片数须为 1–50 的整数，起始序号须为 0–999999 的整数。'; return }
  batchCreateError.value = ''
  const prefix = batchForm.prefix.trim()
  if(!prefix){batchItems.value=[];return}
  const previous = batchItems.value
  batchItems.value = Array.from({ length: count }, (_, index) => {
    const code = suggestedCodes(prefix,count,occupiedCodes.value,start)[index]!
    const sequence = code.slice(prefix.length+1)
    const kept = previous[index]
    return {
      sample_code: kept?.sample_code && kept.sequence === sequence && kept.prefix === prefix ? kept.sample_code : code,
      display_label: kept?.display_label && kept.sequence === sequence && kept.prefix === prefix ? kept.display_label : sequence,
      cut_position: kept?.cut_position ?? '',
      size_desc: kept?.size_desc ?? batchForm.size_desc,
      sequence, prefix,
    }
  })
}
async function openBatchCreate(batch: Row | null = null) {
  if (!auth.canWrite || !(await confirmDiscard())) return
  batchItems.value = []
  bulkBatchId.value = batch?.batch_id
  batchParents.value = []
  batchCreateTarget.value = batch
  batchCreateError.value = ''
  batchConflictCodes.value = []
  Object.assign(batchForm, {
    parent_sample_id: undefined, count: 5, prefix: batch ? batch.batch_code : '', start: 1,
    pre_treatment: '', surface_state: '', size_desc: '', nominal_thickness_nm: batch?.nominal_thickness_nm ?? '',
    exclude_from_analysis: false, exclude_reason: '',
  })
  if(batch)occupiedCodes.value=await usedSampleCodes(batch.batch_id,'')
  else occupiedCodes.value=new Set()
  buildBatchItems()
  batchBaseline.value = batchSnapshot()
  batchCreateOpen.value = true
  if (batch) void loadBatchParents()
  else void batches()
}
async function selectBulkBatch() {
  const id = bulkBatchId.value
  bulkParentRequest++; batchParents.value = []; batchForm.parent_sample_id = undefined
  batchCreateTarget.value = null
  if (!id) return
  try {
    await ensureBatch(id)
    if (bulkBatchId.value !== id || !active) return
    const batch = batchCache.get(id)
    if (!batch || !(auth.isAdmin || batch.owner_user_id === auth.user?.user_id)) { batchCreateError.value = '请选择本人归属的批次。'; return }
    batchCreateTarget.value = batch
    batchForm.prefix = batch.batch_code
    batchForm.nominal_thickness_nm = batch.nominal_thickness_nm ?? ''
    const used=await usedSampleCodes(id,'')
    if(bulkBatchId.value!==id||!active)return
    occupiedCodes.value=used
    batchItems.value = []; buildBatchItems()
    void loadBatchParents()
  } catch (cause) { batchCreateError.value = errorText(cause) }
}
async function loadBatchParents() {
  const batch = batchCreateTarget.value
  if (!batch) return
  const request = ++bulkParentRequest
  batchParentsLoading.value = true
  batchParentsError.value = ''
  try {
    const result = await api<Row[]>('/samples', { query: { batch_id: batch.batch_id, size: 200 } })
    if (!active || request !== bulkParentRequest || batchCreateTarget.value?.batch_id !== batch.batch_id) return
    const owner = batch.owner_user_id
    batchParents.value = result.data.filter(sample => sample.batch_id === batch.batch_id
      && !sample.voided_at && (owner == null || sample.owner_user_id === owner)
      && ['parent_wafer', 'full_wafer'].includes(sample.sample_type))
    batchParents.value.forEach(parent => parentCache.set(parent.sample_id, parent as Sample))
  } catch (cause) {
    if (request === bulkParentRequest) batchParentsError.value = errorText(cause)
  } finally {
    if (request === bulkParentRequest && batchCreateTarget.value?.batch_id === batch.batch_id) batchParentsLoading.value = false
  }
}
// 作为 el-dialog 的 before-close：点灰色遮罩或按 Esc 也会先经过未保存确认（第四轮第 6 项）。
async function closeBatchCreate(done?: () => void) {
  if (batchCreating.value) return
  if (batchDirty.value) {
    try {
      await ElMessageBox.confirm('批量创建内容尚未提交，确定放弃？', '未保存的修改', { type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' })
    } catch { return }
  }
  batchCreateOpen.value = false
  if (typeof done === 'function') done()
}
function validateBatchItems() {
  batchCreateError.value = ''
  batchConflictCodes.value = []
  if (!Number.isInteger(batchForm.count) || batchForm.count < 1 || batchForm.count > 50 || !Number.isSafeInteger(batchForm.start) || batchForm.start < 0 || batchForm.start > 999999 || batchItems.value.length !== batchForm.count) { batchCreateError.value = '请填写有效片数与起始序号，并重新生成预览。'; return false }
  const codes = new Set<string>()
  for (const [index, item] of batchItems.value.entries()) {
    const code = String(item.sample_code ?? '').trim()
    if (!code) { batchCreateError.value = `第 ${index + 1} 行缺少样品编码。`; return false }
    if (code.length > 64) { batchCreateError.value = `第 ${index + 1} 行样品编码超过 64 个字符。`; return false }
    if (codes.has(code)) { batchCreateError.value = `编号「${code}」在本次提交中重复。`; batchConflictCodes.value = [code]; return false }
    codes.add(code)
  }
  if (batchForm.exclude_from_analysis && !batchForm.exclude_reason.trim()) {
    batchCreateError.value = '勾选排除分析时必须填写排除原因。'; return false
  }
  if (batchForm.nominal_thickness_nm && !/^-?\d+(\.\d+)?$/.test(String(batchForm.nominal_thickness_nm))) {
    batchCreateError.value = '标称厚度请使用普通十进制格式，不支持科学计数法。'; return false
  }
  return true
}
async function submitBatchCreate() {
  const batch = batchCreateTarget.value
  if (!batch || batchCreating.value || !auth.canWrite) return
  if (!validateBatchItems()) return
  batchCreating.value = true
  batchConflictCodes.value = []
  try {
    const body: Row = {
      parent_sample_id: batchForm.parent_sample_id ?? null,
      items: batchItems.value.map(item => ({
        sample_code: String(item.sample_code).trim(),
        display_label: String(item.display_label ?? '').trim() || null,
        sample_type: 'coupon',
        cut_position: String(item.cut_position ?? '').trim() || null,
        size_desc: String(item.size_desc || batchForm.size_desc).trim() || null,
        surface_state: batchForm.surface_state.trim() || null,
        pre_treatment: batchForm.pre_treatment.trim() || null,
        nominal_thickness_nm: batchForm.nominal_thickness_nm === '' ? null : String(batchForm.nominal_thickness_nm),
        exclude_from_analysis: batchForm.exclude_from_analysis,
        exclude_reason: batchForm.exclude_from_analysis ? batchForm.exclude_reason.trim() : null,
        notes: null,
      })),
    }
    const result = await api<Row>(`/batches/${batch.batch_id}/samples/batch`, { method: 'POST', body })
    batchBaseline.value = batchSnapshot()
    batchCreateOpen.value = false
    ElMessage.success(`已创建 ${result.data?.count ?? body.items.length} 份小样`)
    await load()
    void router.push({ path: '/samples', query: { batch_id: batch.batch_id } })
  } catch (cause) {
    const message = errorText(cause)
    const hits = batchItems.value.map(item => String(item.sample_code).trim()).filter(code => code && message.includes(code))
    batchConflictCodes.value = hits
    batchCreateError.value = hits.length
      ? `提交被拒绝（整批不会部分创建）。冲突编号：${hits.join('、')}。请修改这些编号后重新提交。`
      : `提交被拒绝（整批不会部分创建）：${message}`
  } finally { batchCreating.value = false }
}const sampleStatus: Record<string, string> = { available: '可用', in_process: '处理中', consumed: '已耗用', lost: '丢失', quarantined: '已隔离' }
const types: Record<string, string> = { parent_wafer: '母片', full_wafer: '整片', coupon: '小样' }
const statuses = computed(() => isBatch.value ? batchStatus : sampleStatus)
const editable = computed(() => !selected.value.voided_at && owns(selected.value))
const decimalKeys = ['nominal_thickness_nm', 'deposit_set_temp_c', 'deposit_actual_temp_c']
const batchCreate = ['batch_code', 'batch_name', 'material', 'wafer_size', 'nominal_thickness_nm', 'deposit_date', 'deposit_set_temp_c', 'deposit_actual_temp_c', 'anomaly_flag', 'anomaly_note', 'status', 'notes']
const batchUpdate = ['batch_name', 'wafer_size', 'nominal_thickness_nm', 'deposit_set_temp_c', 'deposit_actual_temp_c', 'anomaly_flag', 'anomaly_note', 'status', 'notes']
const sampleCreate = ['sample_code', 'batch_id', 'parent_sample_id', 'sample_type', 'display_label', 'nominal_thickness_nm', 'size_desc', 'cut_position', 'surface_state', 'pre_treatment', 'status', 'exclude_from_analysis', 'exclude_reason', 'notes']
const sampleUpdate = ['sample_code', 'display_label', 'nominal_thickness_nm', 'size_desc', 'cut_position', 'surface_state', 'pre_treatment', 'status', 'exclude_from_analysis', 'exclude_reason', 'notes']
const formKeys = computed(() => isBatch.value ? (view.value === 'create' ? batchCreate : batchUpdate) : (view.value === 'create' ? sampleCreate : sampleUpdate))
const lengthLimits: Record<string, number> = {
  batch_code: 64, sample_code: 64, batch_name: 255, material: 128, wafer_size: 32,
  display_label: 128, size_desc: 64, cut_position: 128, surface_state: 128,
  pre_treatment: 255, anomaly_note: 20000, exclude_reason: 20000, notes: 20000,
}
const detailFields = computed(() => isBatch.value
  ? [['batch_name', '批次名称'], ['material', '材料'], ['wafer_size', '晶圆尺寸'], ['nominal_thickness_nm', '标称厚度 / nm'], ['deposit_date', '沉积日期'], ['deposit_set_temp_c', '设定温度 / ℃'], ['deposit_actual_temp_c', '实测温度 / ℃'], ['anomaly_flag', '异常批次'], ['anomaly_note', '异常说明']]
  : [['batch_code', '批次编码'], ['batch_id', '批次 ID'], ['sample_type', '样品类型'], ['parent_sample_id', '母片 ID'], ['display_label', '显示编号'], ['nominal_thickness_nm', '标称厚度 / nm'], ['size_desc', '尺寸描述'], ['cut_position', '切割位置'], ['surface_state', '表面状态'], ['pre_treatment', '前处理'], ['exclude_from_analysis', '排除分析'], ['exclude_reason', '排除原因']])
const dirty = computed(() => drawer.value && view.value !== 'detail' && detailReady.value && snapshot() !== baseline.value)
const canSave = computed(() => !saving.value && detailReady.value && !detailLoading.value && !detailError.value && !(conflict.value && view.value === 'edit') && (view.value === 'create' ? auth.canWrite : editable.value))
const selectedBatch = computed(() => batchCache.get(Number(form.batch_id)))
const date = (value: unknown) => value ? new Date(String(value)).toLocaleString('zh-CN', { hour12: false }) : '—'
const positiveId = (value: unknown) => {
  if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) return undefined
  const number = Number(value)
  return Number.isSafeInteger(number) ? number : undefined
}
function snapshot() {
  return JSON.stringify(formKeys.value.map(key => [key, form[key] ?? null]))
}
function clearErrors() {
  Object.keys(fieldErrors).forEach(key => delete fieldErrors[key])
  formError.value = ''
  conflict.value = false
}
function resetForm() {
  Object.keys(form).forEach(key => delete form[key])
  Object.assign(form, isBatch.value
    ? { batch_code: '', batch_name: '', material: 'PECVD SiNx:H', status: 'active', anomaly_flag: false }
    : { sample_code: '', batch_id: filters.batch_id, sample_type: 'coupon', status: 'available', exclude_from_analysis: false })
}
async function confirmDiscard(): Promise<boolean> {
  if (!auth.user) return true
  if (batchCreating.value) return false
  if (batchDirty.value) {
    try { await ElMessageBox.confirm('批量创建内容尚未提交，确定放弃？', '未保存的修改', { type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' }) } catch { return false }
    batchCreateOpen.value = false
  }
  if (drawer.value && saving.value) return false
  if (!dirty.value) return true
  if (!discardPrompt) {
    discardPrompt = ElMessageBox.confirm('有尚未保存的修改，离开后将丢失。是否放弃修改？', '未保存的修改', {
      type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑',
    }).then(() => true).catch(() => false).finally(() => { discardPrompt = null })
  }
  return (await discardPrompt) ?? false
}
async function beforeClose(done: () => void) {
  if (await confirmDiscard()) { invalidateDetail(); done(); clearDetailQuery() }
}
async function closeDrawer() {
  if (await confirmDiscard()) { invalidateDetail(); drawer.value = false; clearDetailQuery() }
}
function invalidateDetail() {
  detailRequest++
  childRequest++
  parentRequest++
}
function clearDetailQuery() {
  if (!route.query[idKey.value]) return
  const query = { ...route.query }
  delete query[idKey.value]
  void router.replace({ path: route.path, query })
}
async function load() {
  const request = ++listRequest
  const kind = props.kind
  loading.value = true
  error.value = ''
  try {
    const result = await api<Row[]>(`/${kind}`, { query: { ...filters, include_voided: includeVoided.value, ...(!isBatch.value ? { include_archived: includeArchived.value } : {}) } })
    if (request !== listRequest || !active) return
    rows.value = result.data
    total.value = result.meta?.total ?? result.data.length
  } catch (cause) {
    if (request === listRequest && active) error.value = errorText(cause)
  } finally {
    if (request === listRequest && active) loading.value = false
  }
}
function search() { filters.page = 1; void load() }
async function batches(keyword = '') {
  const request = ++batchRequest
  batchesLoading.value = true
  batchesError.value = ''
  try {
    const result = await api<Batch[]>('/batches', { query: { keyword, size: 50, page: 1 } })
    if (request !== batchRequest || !active) return
    result.data.forEach(batch => batchCache.set(batch.batch_id, batch))
    batchOptions.value = result.data
    if (selectedBatch.value && !result.data.some(batch => batch.batch_id === form.batch_id)) {
      batchOptions.value = [selectedBatch.value, ...result.data]
    }
  } catch (cause) {
    if (request === batchRequest && active) batchesError.value = errorText(cause)
  } finally {
    if (request === batchRequest && active) batchesLoading.value = false
  }
}
async function ensureBatch(id: number) {
  if (batchCache.has(id)) return
  const result = await api<Batch>(`/batches/${id}`)
  if (!active) return
  batchCache.set(id, result.data)
  batchOptions.value = [result.data, ...batchOptions.value.filter(batch => batch.batch_id !== id)]
}
async function parents(keyword = '') {
  const request = ++parentRequest
  const batchId = Number(form.batch_id)
  parentOptions.value = []
  parentsError.value = ''
  if (!batchId) { parentsLoading.value = false; return }
  parentsLoading.value = true
  try {
    await ensureBatch(batchId)
    const result = await api<Sample[]>('/samples', { query: { keyword, batch_id: batchId, size: 50, page: 1 } })
    if (request !== parentRequest || !active || form.batch_id !== batchId) return
    const owner = batchCache.get(batchId)?.owner_user_id
    parentOptions.value = result.data.filter(sample => sample.batch_id === batchId
      && !(sample as Row).voided_at && owner != null && sample.owner_user_id === owner && ['parent_wafer', 'full_wafer'].includes(sample.sample_type))
    parentOptions.value.forEach(parent => parentCache.set(parent.sample_id, parent))
    const chosen = parentCache.get(Number(form.parent_sample_id))
    if (chosen && !(chosen as Row).voided_at && chosen.batch_id === batchId && chosen.owner_user_id === owner
      && !parentOptions.value.some(parent => parent.sample_id === chosen.sample_id)) {
      parentOptions.value.unshift(chosen)
    }
  } catch (cause) {
    if (request === parentRequest && active) parentsError.value = errorText(cause)
  } finally {
    if (request === parentRequest && active) parentsLoading.value = false
  }
}
async function suggestSingleCode(){
  const id=Number(form.batch_id)
  if(!id||String(form.sample_code??'').trim())return
  try{
    await ensureBatch(id)
    const prefix=batchCache.get(id)?.batch_code
    if(!prefix)return
    const used=await usedSampleCodes(id,prefix)
    if(Number(form.batch_id)===id&&!String(form.sample_code??'').trim())form.sample_code=suggestedCodes(prefix,1,used)[0]
  }catch(cause){formError.value=errorText(cause)}
}
function changeBatch() {
  form.parent_sample_id = undefined
  parentOptions.value = []
  void parents()
  void suggestSingleCode()
}
async function create() {
  if (!auth.canWrite || !(await confirmDiscard())) return
  invalidateDetail()
  resetForm()
  selected.value = {}
  view.value = 'create'
  clearErrors()
  detailError.value = ''
  detailLoading.value = false
  detailReady.value = true
  parentOptions.value = []
  parentsError.value = ''
  drawer.value = true
  baseline.value = snapshot()
  if (!isBatch.value) { void batches(); if (form.batch_id) void parents() }
}
async function open(row: Row, mode: 'edit' | 'detail', approved = false) {
  if (!approved && !(await confirmDiscard())) return
  const request = ++detailRequest
  childRequest++
  const kind = props.kind
  const id = row[idKey.value]
  selected.value = row
  view.value = mode
  drawer.value = true
  clearErrors()
  detailError.value = ''
  detailReady.value = false
  detailLoading.value = true
  batchSamples.value = []
  batchSampleError.value = ''
  batchSampleTotal.value = 0
  try {
    const result = await api<Row>(`/${kind}/${id}`)
    if (request !== detailRequest || !active) return
    selected.value = result.data
    if (!isBatch.value && result.data.voided_at) view.value = 'detail'
    resetForm()
    Object.assign(form, result.data)
    detailReady.value = true
    baseline.value = snapshot()
    if (isBatch.value && mode === 'detail') { batchSamplePage.value = 1; void loadBatchSamples() }
  } catch (cause) {
    if (request === detailRequest && active) detailError.value = errorText(cause)
  } finally {
    if (request === detailRequest && active) detailLoading.value = false
  }
}
async function loadBatchSamples() {
  const request = ++childRequest
  const batchId = selected.value.batch_id
  batchSamplesLoading.value = true
  batchSampleError.value = ''
  try {
    const result = await api<Row[]>(`/batches/${batchId}/samples`, { query: { page: batchSamplePage.value, size: 10 } })
    if (request !== childRequest || !active) return
    batchSamples.value = result.data
    batchSampleTotal.value = result.meta?.total ?? result.data.length
  } catch (cause) {
    if (request === childRequest && active) batchSampleError.value = errorText(cause)
  } finally {
    if (request === childRequest && active) batchSamplesLoading.value = false
  }
}
function editDetail() {
  if (!editable.value || !detailReady.value || detailError.value) return
  resetForm()
  Object.assign(form, selected.value)
  view.value = 'edit'
  clearErrors()
  baseline.value = snapshot()
}
// 样品列表页选择批次后，可直接从筛选条件发起批量创建。
function batchForFilter() {
  const id = Number(filters.batch_id)
  return batchCache.get(id) ?? batchOptions.value.find(batch => batch.batch_id === id) ?? { batch_id: id, batch_code: `#${id}`, owner_user_id: auth.user?.user_id }
}
function validateField(key: string) {
  delete fieldErrors[key]
  const value = form[key]
  if (lengthLimits[key] && value != null && Array.from(String(value)).length > lengthLimits[key]!) {
    fieldErrors[key] = `最多 ${lengthLimits[key]} 个字符。`
  }
  const codeRequired = key === codeKey.value && (view.value === 'create' || !isBatch.value)
  const required = codeRequired
    || (view.value === 'create' && !isBatch.value && key === 'batch_id')
    || (view.value === 'create' && isBatch.value && key === 'material')
    || (isBatch.value && key === 'batch_name')
    || (!isBatch.value && key === 'exclude_reason' && form.exclude_from_analysis)
  if (required && (value == null || !String(value).trim())) fieldErrors[key] = '请填写此项。'
  if (decimalKeys.includes(key) && value !== '' && value != null) {
    const scale = key === 'nominal_thickness_nm' ? 3 : 2
    const wholeLimit = key === 'nominal_thickness_nm' ? 9 : 6
    const text = String(value)
    if (!/^-?\d+(\.\d+)?$/.test(text)) fieldErrors[key] = '请使用普通十进制格式，不支持科学计数法。'
    else {
      const [whole = '', fraction = ''] = text.replace(/^-/, '').split('.')
      if (fraction.length > scale || whole.replace(/^0+/, '').length > wholeLimit) {
        fieldErrors[key] = `最多 ${wholeLimit} 位整数、${scale} 位小数。`
      }
    }
  }
}
function validate() {
  Object.keys(fieldErrors).forEach(key => delete fieldErrors[key])
  formKeys.value.forEach(validateField)
  if (!isBatch.value && view.value === 'create') {
    if (!Number.isSafeInteger(form.batch_id) || form.batch_id <= 0) fieldErrors.batch_id = '请选择所属批次。'
    const parent = parentCache.get(Number(form.parent_sample_id))
    if (form.parent_sample_id != null && (!parent || parent.batch_id !== form.batch_id
      || selectedBatch.value?.owner_user_id == null || parent.owner_user_id !== selectedBatch.value.owner_user_id
      || !['parent_wafer', 'full_wafer'].includes(parent.sample_type))) {
      fieldErrors.parent_sample_id = '请重新选择同批次、同归属的母片或整片。'
    }
  }
  return Object.keys(fieldErrors).length === 0
}
async function save() {
  if (!canSave.value) return
  formError.value = ''
  if (!validate()) { formError.value = '请检查标出的字段。'; return }
  const body: Record<string, unknown> = {}
  for (const key of formKeys.value) {
    if (form[key] === undefined || form[key] === null) continue
    if (view.value === 'create' && form[key] === '') continue
    body[key] = decimalKeys.includes(key) ? (form[key] === '' ? null : String(form[key])) : form[key]
  }
  if (view.value === 'edit') body.expected_row_version = selected.value.row_version
  saving.value = true
  try {
    await api(`/${props.kind}${view.value === 'edit' ? `/${selected.value[idKey.value]}` : ''}`, {
      method: view.value === 'edit' ? 'PATCH' : 'POST', body,
    })
    baseline.value = snapshot()
    drawer.value = false
    invalidateDetail()
    clearDetailQuery()
    ElMessage.success(`${noun.value}已保存`)
    await load()
  } catch (cause) {
    conflict.value = cause instanceof ApiError && cause.status === 409
    formError.value = conflict.value
      ? `保存冲突：${errorText(cause)}。输入已保留。${view.value === 'edit' ? '请重载最新记录后重新编辑。' : '请检查编码是否重复后重试。'}`
      : errorText(cause)
  } finally { saving.value = false }
}
async function reloadConflict() {
  if (!(await confirmDiscard())) return
  await open(selected.value, 'edit', true)
}
async function remove(row: Row) {
  if (!auth.isAdmin || saving.value || (!isBatch.value && row.voided_at)) return
  try {
    await ElMessageBox.confirm(`确认删除${noun.value}“${row[codeKey.value]}”？关联约束可能阻止删除。`, '删除确认', {
      type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消',
    })
  } catch { return }
  saving.value = true
  try {
    await api(`/${props.kind}/${row[idKey.value]}`, { method: 'DELETE' })
    showFeedback(`${noun.value}“${row[codeKey.value]}”已删除。`, 'success', row)
    if (rows.value.length === 1 && filters.page > 1) filters.page--
    await load()
  } catch (cause) {
    showFeedback(`删除失败：${errorText(cause)}`, 'error', row, cause instanceof ApiError && cause.status === 409)
  } finally { saving.value = false }
}
function reset() {
  includeVoided.value = false
  includeArchived.value = false
  filters.keyword = ''
  filters.status = ''
  filters.batch_id = undefined
  filters.sort = '-created_at'
  search()
}
function sampleLink(sample: Row) {
  void router.push({ path: '/samples', query: { sample_id: sample.sample_id, batch_id: sample.batch_id ?? selected.value.batch_id } })
}
function batchLink(batchId: number) {
  void router.push({ path: '/batches', query: { batch_id: batchId } })
}
async function syncRoute() {
  const approved = routeApproved
  routeApproved = false
  filters.batch_id = !isBatch.value ? positiveId(route.query.batch_id) : undefined
  filters.page = 1
  void load()
  const id = positiveId(route.query[idKey.value])
  if (id) await open({ [idKey.value]: id }, 'detail', approved)
  else if (approved) { invalidateDetail(); drawer.value = false }
}
onBeforeRouteLeave(() => confirmDiscard())
onBeforeRouteUpdate(async () => {
  const allowed = await confirmDiscard()
  routeApproved = allowed
  return allowed
})
watch(() => [props.kind, route.query.batch_id, route.query.sample_id], () => { void syncRoute() })
watch(() => ({ ...form }), (next, previous) => {
  Object.keys(next).forEach(key => { if (next[key] !== previous[key] && fieldErrors[key]) validateField(key) })
})
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || saving.value || batchDirty.value || batchCreating.value) { event.preventDefault(); event.returnValue = '' }
}
onMounted(() => { void syncRoute(); if (!isBatch.value) void batches(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => {
  active = false
  bulkParentRequest++; listRequest++; batchRequest++; invalidateDetail()
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <div class="records-view">
    <PageHeading :title="`${noun}管理`" :description="isBatch ? '按沉积批次组织研究数据，保留材料、工艺条件与异常记录。' : '管理母片与小样，记录前处理、当前状态与分析排除依据。'">
      <template #actions>
        <el-button v-if="!isBatch && auth.canWrite" data-testid="sample-home-bulk" @click="openBatchCreate(filters.batch_id ? batchForFilter() : null)">批量创建小样</el-button>
        <el-button v-if="auth.canWrite" type="primary" @click="create"><Plus :size="16" />新建{{ noun }}</el-button>
      </template>
    </PageHeading>
    <div v-if="feedback" class="records-action-feedback" data-testid="records-action-feedback" role="status" aria-live="polite">
      <el-alert :title="feedback.message" :type="feedback.tone" :closable="false" show-icon />
      <el-button v-if="feedback.shortcut && canArchive(feedback.row)" data-testid="batch-archive-shortcut" :disabled="saving" @click="openLifecycle(feedback.row)">归档此批次并保留历史</el-button>
    </div>
    <section class="panel">
      <form class="toolbar" @submit.prevent="search">
        <el-input v-model="filters.keyword" class="search-input" :placeholder="`搜索${noun}编码${isBatch ? '、名称' : ''}`" maxlength="128" clearable aria-label="搜索关键词"><template #prefix><Search :size="16" /></template></el-input>
        <el-select v-model="filters.status" clearable placeholder="全部状态" class="filter-select" aria-label="筛选状态" @change="search"><el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" /></el-select>
        <el-select v-if="!isBatch" v-model="filters.batch_id" filterable remote :remote-method="batches" :loading="batchesLoading" clearable placeholder="全部批次" class="filter-select" aria-label="筛选批次" @change="search"><el-option v-for="batch in batchOptions" :key="batch.batch_id" :value="batch.batch_id" :label="batch.batch_code" /></el-select>
        <el-select v-model="filters.sort" class="filter-select" aria-label="排序" @change="search"><el-option label="最新创建" value="-created_at" /><el-option label="最早创建" value="created_at" /><el-option :label="`${noun}编码`" :value="isBatch ? 'batch_code' : 'sample_code'" /></el-select>
        <el-checkbox v-model="includeVoided" data-testid="include-voided" @change="search">包含已作废记录</el-checkbox>
        <el-checkbox v-if="!isBatch" v-model="includeArchived" data-testid="include-archived" @change="search">包含已归档样品</el-checkbox>
        <el-button native-type="submit">查询</el-button><el-button text @click="reset">重置</el-button>
        <span class="spacer"></span>
        <el-button circle aria-label="刷新列表" :loading="loading" @click="load"><RefreshCw :size="16" /></el-button>
      </form>
      <div v-if="!isBatch && batchesError" class="records-option-error" role="alert">批次选项加载失败：{{ batchesError }}<el-button link type="primary" @click="batches()">重试批次选项</el-button></div>
      <div class="records-list-summary" aria-live="polite">
        <span>{{ loading ? '正在加载记录…' : error ? '记录加载失败' : `共 ${total} 条${noun}记录` }}</span>
        <span v-if="!auth.canWrite" class="readonly-note">当前为只读权限，可查看记录和关联详情。</span>
        <span v-else-if="!auth.isAdmin" class="readonly-note">仅可编辑本人归属的记录。</span>
      </div>
      <div v-if="loading" class="records-skeleton" aria-label="正在加载列表"><el-skeleton :rows="6" animated /></div>
      <StatePanel v-else-if="error" title="列表加载失败" :description="error" tone="error"><el-button @click="load">重试加载列表</el-button></StatePanel>
      <StatePanel v-else-if="!rows.length" title="暂无匹配记录" :description="filters.keyword || filters.status || filters.batch_id ? '尝试调整筛选条件。' : auth.canWrite ? `创建${noun}，开始建立实验档案。` : '当前可见范围内没有记录，请联系管理员核对数据归属。'" tone="empty"><el-button v-if="auth.canWrite" type="primary" plain @click="create">新建{{ noun }}</el-button><el-button v-if="filters.keyword || filters.status || filters.batch_id" @click="reset">清除筛选</el-button></StatePanel>
      <div v-else class="table-wrap">
        <el-table :data="rows" :row-key="idKey" style="width: 100%">
          <el-table-column :label="`${noun}编码`" min-width="170"><template #default="{ row }"><el-button link class="table-code" @click="open(row, 'detail')">{{ row[codeKey] }}</el-button><div class="table-sub">{{ isBatch ? row.batch_name : row.display_label }}</div></template></el-table-column>
          <el-table-column v-if="isBatch" prop="material" label="材料" min-width="140" />
          <el-table-column v-else label="所属批次" min-width="125"><template #default="{ row }"><el-button link type="primary" @click="batchLink(row.batch_id)">{{ row.batch_code || `#${row.batch_id}` }}</el-button></template></el-table-column>
          <el-table-column v-if="!isBatch" label="类型" min-width="85"><template #default="{ row }">{{ types[row.sample_type] || row.sample_type }}</template></el-table-column>
          <el-table-column label="标称厚度 / nm" min-width="130"><template #default="{ row }">{{ row.nominal_thickness_nm ?? '—' }}</template></el-table-column>
          <el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag :type="['quarantined', 'lost'].includes(row.status) ? 'danger' : ['active', 'available'].includes(row.status) ? 'success' : 'info'" effect="light">{{ statuses[row.status] || row.status }}</el-tag><el-tag v-if="row.voided_at" data-testid="sample-voided-badge" type="danger" effect="plain">已作废</el-tag><el-tag v-if="isBatch && row.archived_at" data-testid="batch-archived-badge" type="info" effect="plain">已归档</el-tag><div v-if="row.anomaly_flag || row.exclude_from_analysis" class="table-sub danger-text">{{ isBatch ? '异常标记' : '排除分析' }}</div></template></el-table-column>
          <el-table-column label="创建时间" min-width="165"><template #default="{ row }"><span class="muted">{{ date(row.created_at) }}</span></template></el-table-column>
          <el-table-column label="操作" :min-width="250" fixed="right"><template #default="{ row }"><div class="table-actions"><el-button link type="primary" @click="open(row, 'detail')">详情</el-button><el-button v-if="owns(row)" :disabled="!!row.voided_at" link type="primary" @click="open(row, 'edit')">编辑</el-button><el-button v-if="canArchive(row)" data-testid="batch-archive" link type="primary" :disabled="saving" @click="openLifecycle(row)">归档</el-button><el-button v-if="canVoid(row)" data-testid="sample-void" link type="danger" :disabled="saving" @click="beginVoid(row)">作废</el-button><el-button v-if="auth.canWrite && owns(row)" data-testid="lifecycle-open" link type="primary" :disabled="saving" @click="openLifecycle(row)">生命周期</el-button><el-button v-if="auth.isAdmin" data-testid="record-delete" link type="danger" :disabled="saving || (!isBatch && !!row.voided_at)" @click="openLifecycle(row)">删除</el-button></div></template></el-table-column>
        </el-table>
      </div>
      <div class="pagination"><span>共 {{ total }} 条{{ noun }}记录</span><el-pagination v-model:current-page="filters.page" v-model:page-size="filters.size" :page-sizes="[10, 20, 50]" :total="total" :disabled="loading" layout="sizes, prev, pager, next" @size-change="search" @current-change="load" /></div>
    </section>

    <el-drawer v-model="drawer" :title="`${view === 'create' ? '新建' : view === 'edit' ? '编辑' : '查看'}${noun}`" size="min(760px, 100vw)" class="records-drawer" :before-close="beforeClose" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <div v-if="detailLoading" class="records-skeleton" aria-label="正在加载档案"><el-skeleton :rows="10" animated /></div>
      <StatePanel v-else-if="detailError" title="档案加载失败" :description="detailError" tone="error"><el-button @click="open(selected, view === 'edit' ? 'edit' : 'detail')">重试加载档案</el-button></StatePanel>
      <template v-else-if="detailReady">
        <div v-if="feedback" class="records-action-feedback" data-testid="records-detail-feedback" role="status" aria-live="polite">
          <el-alert :title="feedback.message" :type="feedback.tone" :closable="false" show-icon />
          <el-button v-if="feedback.shortcut && canArchive(feedback.row)" :disabled="saving" @click="openLifecycle(feedback.row)">归档此批次并保留历史</el-button>
        </div>
        <el-alert v-if="formError" class="drawer-alert" :title="formError" type="error" :closable="false" show-icon />
        <div v-if="conflict" class="records-conflict"><template v-if="view === 'edit'"><el-button type="warning" plain @click="reloadConflict">重载最新记录</el-button><span>重载前会确认放弃当前修改。</span></template><el-button v-else type="warning" plain :loading="loading" @click="load">重载列表核对编码</el-button></div>
        <template v-if="view === 'detail'">
          <div class="detail-title"><h2>{{ selected[codeKey] }}</h2><el-tag>{{ statuses[String(selected.status)] || selected.status }}</el-tag><el-tag v-if="selected.voided_at" data-testid="sample-detail-voided-badge" type="danger">已作废</el-tag><el-tag v-if="isBatch && selected.archived_at" data-testid="batch-detail-archived-badge" type="info">已归档</el-tag><el-tag v-if="!isBatch && selected.archived_at" data-testid="sample-detail-archived-badge" type="info">已归档</el-tag><el-button v-if="editable" type="primary" link :disabled="saving" @click="editDetail">编辑档案</el-button><el-button v-if="canVoid(selected)" data-testid="sample-detail-void" :disabled="saving" type="danger" plain @click="beginVoid(selected)">作废</el-button><el-button v-if="canArchive(selected)" data-testid="batch-detail-archive" :disabled="saving" @click="openLifecycle(selected)">归档</el-button><el-button v-if="auth.canWrite && owns(selected)" data-testid="lifecycle-detail-open" :disabled="saving" @click="openLifecycle(selected)">生命周期</el-button></div>
          <el-alert v-if="selected.voided_at" data-testid="sample-void-readonly" title="此样品已作废，仅可查看档案和历史；记录保留、编码不可复用、业务状态未改变。不能编辑、删除、绑定使用或作为上级样品。" type="warning" :closable="false" show-icon />
          <el-button v-if="selected.voided_at" type="primary" plain @click="loadVoidHistory">查看完整历史（只读）</el-button>
          <el-button v-if="!isBatch && !selected.voided_at" type="primary" plain @click="router.push({path:'/sample-history',query:{sample_id:selected.sample_id}})">查看科研履历 / 追加流转</el-button>
          <dl v-if="!isBatch" class="detail-grid"><div><dt>所属批次</dt><dd>{{ selected.batch_code }}</dd></div><div><dt>材料</dt><dd>{{ selected.batch?.material||'未记录' }}</dd></div><div><dt>当前状态</dt><dd>{{ sampleStatus[selected.status]||selected.status }}</dd></div><div><dt>标称厚度 / nm</dt><dd>{{ selected.nominal_thickness_nm??'未记录' }}</dd></div></dl>
          <dl v-if="isBatch" class="detail-grid">
            <div v-for="field in detailFields" :key="field[0]">
              <dt>{{ field[1] }}</dt>
              <dd v-if="!isBatch && ['batch_id', 'batch_code'].includes(field[0])"><el-button link type="primary" @click="batchLink(selected.batch_id)">{{ selected[field[0]] ?? `#${selected.batch_id}` }}</el-button></dd>
              <dd v-else-if="field[0] === 'parent_sample_id' && selected.parent_sample_id"><el-button link type="primary" @click="sampleLink({ sample_id: selected.parent_sample_id, batch_id: selected.batch_id })">#{{ selected.parent_sample_id }}</el-button></dd>
              <dd v-else>{{ field[0] === 'sample_type' ? types[String(selected[field[0]])] : typeof selected[field[0]] === 'boolean' ? (selected[field[0]] ? '是' : '否') : selected[field[0]] ?? '—' }}</dd>
            </div>
            <template v-if="selected.voided_at"><div><dt>作废时间</dt><dd>{{ date(selected.voided_at) }}</dd></div><div><dt>作废操作人 ID</dt><dd>{{ selected.voided_by_user_id }}</dd></div><div class="span-2"><dt>作废原因</dt><dd>{{ selected.void_reason }}</dd></div></template>
            <div v-if="selected.archived_at"><dt>归档时间</dt><dd>{{ date(selected.archived_at) }}</dd></div><div><dt>归属用户 ID</dt><dd>{{ selected.owner_user_id ?? '—' }}</dd></div><div><dt>创建时间</dt><dd>{{ date(selected.created_at) }}</dd></div><div><dt>更新时间</dt><dd>{{ date(selected.updated_at) }}</dd></div><div class="span-2"><dt>备注</dt><dd>{{ selected.notes || '—' }}</dd></div>
          </dl>
          <FormSection v-if="isBatch" title="批次内样品" description="层级：沉积批次 → 母片 → 小样。点击样品编码查看详情，保留当前批次筛选。">
            <el-button link type="primary" @click="router.push({ path: '/samples', query: { batch_id: selected.batch_id } })">查看完整列表</el-button>
            <el-button v-if="auth.canWrite && editable" data-testid="batch-create-open" type="primary" plain @click="openBatchCreate(selected)">批量创建小样</el-button>
            <div v-if="batchSamplesLoading" class="records-skeleton"><el-skeleton :rows="3" animated /></div>
            <StatePanel v-else-if="batchSampleError" title="批次内样品加载失败" :description="batchSampleError" tone="error"><el-button @click="loadBatchSamples">重试加载样品</el-button></StatePanel>
            <StatePanel v-else-if="!batchSamples.length" title="该批次暂无样品" description="新建样品时选择此批次即可建立关联。" tone="empty" />
            <el-table v-else :data="batchSamples"><el-table-column label="样品编码"><template #default="{ row }"><el-button link type="primary" @click="sampleLink(row)">{{ row.sample_code }}</el-button></template></el-table-column><el-table-column label="状态"><template #default="{ row }">{{ sampleStatus[row.status] || row.status }}</template></el-table-column><el-table-column label="排除分析"><template #default="{ row }">{{ row.exclude_from_analysis ? '是' : '否' }}</template></el-table-column></el-table>
            <el-pagination v-if="batchSampleTotal > 10 && !batchSampleError" v-model:current-page="batchSamplePage" :page-size="10" :total="batchSampleTotal" :disabled="batchSamplesLoading" layout="prev, pager, next" @current-change="loadBatchSamples" />
          </FormSection>
          <SampleExperimentHistory v-if="!isBatch" :sample="selected"/>
          <SampleResearchReview v-if="!isBatch" :sample="selected" :review="selected.research_review" :writable="auth.canWrite&&!selected.voided_at"/>
          <details v-if="!isBatch"><summary>更多样品属性与技术详情</summary>
          <dl class="detail-grid">
            <div v-for="field in detailFields" :key="field[0]">
              <dt>{{ field[1] }}</dt>
              <dd v-if="!isBatch && ['batch_id', 'batch_code'].includes(field[0])"><el-button link type="primary" @click="batchLink(selected.batch_id)">{{ selected[field[0]] ?? `#${selected.batch_id}` }}</el-button></dd>
              <dd v-else-if="field[0] === 'parent_sample_id' && selected.parent_sample_id"><el-button link type="primary" @click="sampleLink({ sample_id: selected.parent_sample_id, batch_id: selected.batch_id })">#{{ selected.parent_sample_id }}</el-button></dd>
              <dd v-else>{{ field[0] === 'sample_type' ? types[String(selected[field[0]])] : typeof selected[field[0]] === 'boolean' ? (selected[field[0]] ? '是' : '否') : selected[field[0]] ?? '—' }}</dd>
            </div>
            <template v-if="selected.voided_at"><div><dt>作废时间</dt><dd>{{ date(selected.voided_at) }}</dd></div><div><dt>作废操作人 ID</dt><dd>{{ selected.voided_by_user_id }}</dd></div><div class="span-2"><dt>作废原因</dt><dd>{{ selected.void_reason }}</dd></div></template>
            <div v-if="selected.archived_at"><dt>归档时间</dt><dd>{{ date(selected.archived_at) }}</dd></div><div><dt>归属用户 ID</dt><dd>{{ selected.owner_user_id ?? '—' }}</dd></div><div><dt>创建时间</dt><dd>{{ date(selected.created_at) }}</dd></div><div><dt>更新时间</dt><dd>{{ date(selected.updated_at) }}</dd></div><div class="span-2"><dt>备注</dt><dd>{{ selected.notes || '—' }}</dd></div>
          </dl>
          </details>
        </template>
        <el-form v-else id="records-editor" :model="form" label-position="top" :disabled="saving || !canSave" @submit.prevent="save">
          <p v-if="view === 'edit' && isBatch" class="readonly-note">批次编码与归属信息保持可追溯，不能在此修改。</p>
          <p v-if="view === 'edit' && !isBatch" class="readonly-note">样品编号可修改；历史测量、执行和流转仍按内部主键关联，不会因改名失效。</p>
          <FormSection title="基本信息" description="编码用于追溯，名称和显示编号用于日常识别。">
            <div class="form-grid">
              <el-form-item v-if="view === 'create' || (!isBatch && view === 'edit')" :label="isBatch ? `${noun}编码` : '样品编号'" required :error="fieldErrors[codeKey]"><el-input v-model="form[codeKey]" required maxlength="64" :placeholder="isBatch ? '例如 B01' : '例如 B01-S01'" @blur="validateField(codeKey)" /></el-form-item>
              <template v-if="isBatch">
                <el-form-item label="批次名称" required :error="fieldErrors.batch_name"><el-input v-model="form.batch_name" required maxlength="255" @blur="validateField('batch_name')" /></el-form-item>
                <el-form-item v-if="view === 'create'" label="材料" :error="fieldErrors.material"><el-input v-model="form.material" maxlength="128" @blur="validateField('material')" /></el-form-item>
                <el-form-item label="晶圆尺寸" :error="fieldErrors.wafer_size"><el-input v-model="form.wafer_size" placeholder="例如 4 inch" maxlength="32" /></el-form-item>
              </template>
              <el-form-item v-else label="显示编号" :error="fieldErrors.display_label"><el-input v-model="form.display_label" maxlength="128" /></el-form-item>
              <el-form-item label="标称厚度 / nm" :error="fieldErrors.nominal_thickness_nm"><el-input v-model="form.nominal_thickness_nm" inputmode="decimal" placeholder="例如 47.500" @blur="validateField('nominal_thickness_nm')" /><p class="field-hint">最多 9 位整数、3 位小数。</p></el-form-item>
              <el-form-item label="状态" :error="fieldErrors.status"><el-select v-model="form.status"><el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" /></el-select></el-form-item>
            </div>
          </FormSection>
          <BatchCodeStatus v-if="isBatch" :code="form.batch_code||''"/>
          <FormSection title="条件与来源" :description="isBatch ? '分别记录设定值和实测值，保留沉积条件。' : '记录批次、母片来源及样品处理条件。'">
            <div class="form-grid">
              <template v-if="isBatch">
                <el-form-item v-if="view === 'create'" label="沉积日期" :error="fieldErrors.deposit_date"><el-date-picker v-model="form.deposit_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" /></el-form-item>
                <el-form-item label="沉积设定温度 / ℃" :error="fieldErrors.deposit_set_temp_c"><el-input v-model="form.deposit_set_temp_c" inputmode="decimal" @blur="validateField('deposit_set_temp_c')" /></el-form-item>
                <el-form-item label="沉积实测温度 / ℃" :error="fieldErrors.deposit_actual_temp_c"><el-input v-model="form.deposit_actual_temp_c" inputmode="decimal" @blur="validateField('deposit_actual_temp_c')" /></el-form-item>
                <p class="field-hint span-2">温度最多 6 位整数、2 位小数；设定值与实测值分别保存。</p>
              </template>
              <template v-else>
                <el-form-item v-if="view === 'create'" label="所属批次" required :error="fieldErrors.batch_id"><div class="records-inline-row"><el-select v-model="form.batch_id" filterable remote :remote-method="batches" :loading="batchesLoading" placeholder="搜索批次" @change="changeBatch"><el-option v-for="batch in batchOptions" :key="batch.batch_id" :label="`${batch.batch_code} · ${batch.batch_name}`" :value="batch.batch_id" /></el-select><el-button data-testid="inline-batch-open" :disabled="saving" @click="openInlineBatch">新建批次</el-button></div><div v-if="batchesError" class="records-option-error" role="alert">{{ batchesError }}<el-button link type="primary" @click="batches()">重试批次选项</el-button></div></el-form-item>
                <el-form-item v-if="view === 'create'" label="样品类型" :error="fieldErrors.sample_type"><el-select v-model="form.sample_type"><el-option v-for="(label, value) in types" :key="value" :label="label" :value="value" /></el-select></el-form-item>
                <el-form-item v-if="view === 'create'" label="母片 / 上级样品（选填）" :error="fieldErrors.parent_sample_id"><el-select v-model="form.parent_sample_id" filterable remote :remote-method="parents" :loading="parentsLoading" clearable :disabled="!form.batch_id" placeholder="先选择批次，再搜索样品" @visible-change="(visible: boolean) => visible && parents()"><el-option v-for="parent in parentOptions" :key="parent.sample_id" :label="parent.sample_code" :value="parent.sample_id" /></el-select><p class="field-hint">仅显示同批次、同归属的母片或整片。</p><div v-if="parentsError" class="records-option-error" role="alert">{{ parentsError }}<el-button link type="primary" @click="parents()">重试母片选项</el-button></div></el-form-item>
                <el-form-item label="尺寸描述" :error="fieldErrors.size_desc"><el-input v-model="form.size_desc" maxlength="64" placeholder="例如 10 × 10 mm" /></el-form-item>
                <el-form-item label="切割位置" :error="fieldErrors.cut_position"><el-input v-model="form.cut_position" maxlength="128" /></el-form-item>
                <el-form-item label="表面状态" class="span-2" :error="fieldErrors.surface_state"><el-input v-model="form.surface_state" maxlength="128" /></el-form-item>
                <el-form-item label="前处理记录" class="span-2" :error="fieldErrors.pre_treatment"><el-input v-model="form.pre_treatment" type="textarea" :rows="3" maxlength="255" show-word-limit placeholder="记录清洗、预暴露等前处理条件" /></el-form-item>
              </template>
            </div>
          </FormSection>
          <FormSection title="分析范围" :description="isBatch ? '保留异常观察与说明，为后续分析提供依据。' : '明确样品是否纳入常规分析，并保留排除依据。'">
            <el-form-item :label="isBatch ? '异常批次' : '排除出常规分析'"><el-switch v-if="isBatch" v-model="form.anomaly_flag" /><el-switch v-else v-model="form.exclude_from_analysis" /></el-form-item>
            <el-form-item v-if="isBatch ? form.anomaly_flag : form.exclude_from_analysis" :label="isBatch ? '异常说明' : '排除原因'" :required="!isBatch" :error="fieldErrors[isBatch ? 'anomaly_note' : 'exclude_reason']"><el-input v-model="form[isBatch ? 'anomaly_note' : 'exclude_reason']" type="textarea" :rows="3" maxlength="20000" :required="!isBatch" :placeholder="isBatch ? '记录观察到的异常，避免仅凭文件名推断机理。' : '请具体说明为何排除该样品。'" @blur="validateField(isBatch ? 'anomaly_note' : 'exclude_reason')" /></el-form-item>
            <el-form-item label="备注" :error="fieldErrors.notes"><el-input v-model="form.notes" type="textarea" :rows="3" maxlength="20000" /></el-form-item>
          </FormSection>
        </el-form>
      </template>
      <template #footer>
        <div class="records-drawer-footer">
          <span class="records-save-hint" aria-live="polite">{{ saving ? '正在保存，请稍候…' : dirty ? '有未保存的修改' : '' }}</span>
          <el-button :disabled="saving" @click="closeDrawer">{{ view === 'detail' ? '关闭' : '取消' }}</el-button>
          <el-button v-if="view !== 'detail'" type="primary" :loading="saving" :disabled="!canSave" @click="save">保存{{ noun }}</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="inlineBatchOpen" title="新建批次" width="min(460px,94vw)" append-to-body :close-on-click-modal="!inlineBatchSaving" :close-on-press-escape="!inlineBatchSaving" :show-close="!inlineBatchSaving">
      <el-alert v-if="inlineBatchError" :title="inlineBatchError" type="error" :closable="false" />
      <el-form label-position="top" @submit.prevent="saveInlineBatch">
        <el-form-item label="批次编号" required><el-input v-model="inlineBatch.batch_code" maxlength="64" placeholder="例如 B01" /><BatchCodeStatus :code="inlineBatch.batch_code"/></el-form-item>
        <el-form-item label="批次名称" required><el-input v-model="inlineBatch.batch_name" maxlength="255" placeholder="例如 2026-10 沉积批次" /></el-form-item>
        <el-form-item label="材料"><el-input v-model="inlineBatch.material" maxlength="128" /></el-form-item>
        <p class="field-hint">创建后自动选中该批次，返回当前样品表单；已填写的样品内容不会丢失。</p>
      </el-form>
      <template #footer><div class="form-footer"><el-button :disabled="inlineBatchSaving" @click="inlineBatchOpen=false">取消</el-button><el-button type="primary" :loading="inlineBatchSaving" @click="saveInlineBatch">创建并选中</el-button></div></template>
    </el-dialog>

    <LifecycleDialog
      v-model="lifecycleOpen"
      :kind="props.kind"
      :id="lifecycleTarget[idKey] ?? null"
      :row-version="lifecycleTarget.row_version ?? null"
      :code="lifecycleTarget[codeKey] ?? ''"
      @applied="lifecycleApplied"
    />

    <el-dialog v-model="voidDialog" title="作废样品" width="min(560px, 96vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" data-testid="sample-void-dialog">
      <p>样品：{{ voidTarget.sample_code }}</p>
      <el-alert title="仅可作废误建且未使用的可用样品；已有科研、来源文件、子样品或实际流转关联时会拒绝。记录和历史保留，编码不可复用，业务状态不变。实际使用过的样品请隔离或排除分析。" type="warning" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="submitVoid"><el-form-item label="作废原因" required><el-input v-model="voidReason" type="textarea" :rows="3" maxlength="2000" show-word-limit :disabled="saving" aria-label="作废原因" /></el-form-item></el-form>
      <el-alert v-if="voidError" :title="voidError" type="error" :closable="false" role="alert" />
      <el-button v-if="voidConflict" :disabled="saving" @click="reloadVoid">重载样品并保留原因</el-button>
      <template #footer><el-button :disabled="saving" @click="voidDialog=false">取消</el-button><el-button type="danger" :loading="saving" :disabled="saving || voidConflict || !voidReason.trim()" @click="submitVoid">确认作废</el-button></template>
    </el-dialog>
    <el-dialog v-model="voidHistoryOpen" title="样品历史（只读）" width="min(720px, 96vw)" data-testid="void-history">
      <p>已作废样品的历史保留，仅供查看。</p>
      <el-skeleton v-if="voidHistoryLoading" :rows="3" animated />
      <StatePanel v-else-if="voidHistoryError" title="历史加载失败" :description="voidHistoryError" tone="error"><el-button @click="loadVoidHistory">重试</el-button></StatePanel>
      <el-table v-else :data="voidHistory"><el-table-column prop="transition_id" label="追加序号" /><el-table-column prop="event_type" label="事件" /><el-table-column label="状态"><template #default="{ row }">{{ row.from_status ? sampleStatus[row.from_status] : '初始' }} → {{ sampleStatus[row.to_status] }}</template></el-table-column><el-table-column label="事件时间"><template #default="{ row }">{{ date(row.event_at) }}</template></el-table-column></el-table>
    </el-dialog>
    <el-dialog v-model="batchCreateOpen" title="批量创建小样" width="min(920px, 96vw)" :before-close="closeBatchCreate" :close-on-click-modal="!batchCreating" :close-on-press-escape="!batchCreating" :show-close="!batchCreating" destroy-on-close data-testid="batch-create-dialog" @close="batchBaseline = batchSnapshot()">
      <p class="readonly-note">层级提示：沉积批次 → 母片 → 小样。小样归属继承批次；母片可空，但填写时必须属于该批次且为母片 / 整片。</p>
      <p v-if="batchCreateTarget" class="field-hint">目标批次：{{ batchCreateTarget.batch_code }} · {{ batchCreateTarget.batch_name || '未填写名称' }}（批次 #{{ batchCreateTarget.batch_id }}）</p>
      <el-alert v-if="batchCreateError" data-testid="batch-error" :title="batchCreateError" type="error" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="submitBatchCreate">
        <FormSection title="母片与数量" description="片数 1–50；默认使用批次编号加序号（如 S01-1），避开已有编号；确认前可逐行编辑。">
          <div class="form-grid">
            <el-form-item label="目标批次" required><div class="records-inline-row"><el-select v-model="bulkBatchId" filterable remote :remote-method="batches" :loading="batchesLoading" :disabled="batchCreating" aria-label="批量目标批次" placeholder="搜索并选择批次" @change="selectBulkBatch"><el-option v-for="batch in batchOptions.filter(b=>auth.isAdmin||b.owner_user_id===auth.user?.user_id)" :key="batch.batch_id" :value="batch.batch_id" :label="`${batch.batch_code} · ${batch.batch_name}`" /></el-select><el-button data-testid="bulk-inline-batch-open" :disabled="batchCreating" @click="openInlineBatch">新建批次</el-button></div><p v-if="batchesError" role="alert">{{batchesError}}<el-button link @click="batches()">重试</el-button></p></el-form-item>
            <el-form-item label="母片 / 整片（可空）"><el-select v-model="batchForm.parent_sample_id" filterable clearable :loading="batchParentsLoading" :disabled="batchCreating || !batchCreateTarget" placeholder="从该批次母片中选择（可留空）"><el-option v-for="parent in batchParents" :key="parent.sample_id" :value="parent.sample_id" :label="`${parent.sample_code} · ${types[parent.sample_type] || parent.sample_type}`" /></el-select><p v-if="batchParentsError" class="field-hint danger-text" role="alert">{{ batchParentsError }} <el-button link type="primary" @click="loadBatchParents">重试</el-button></p><p v-else class="field-hint">仅列出该批次同归属的母片 / 整片；未显示说明该批次还没有母片。</p></el-form-item>
            <el-form-item label="片数（1–50）"><el-input v-model.number="batchForm.count" inputmode="numeric" data-testid="batch-count" :disabled="batchCreating" @change="buildBatchItems" /></el-form-item>
            <el-form-item label="编号前缀"><el-input v-model="batchForm.prefix" maxlength="48" placeholder="例如 S01" :disabled="batchCreating" @change="buildBatchItems" /></el-form-item>
            <el-form-item label="起始序号"><el-input v-model.number="batchForm.start" inputmode="numeric" :disabled="batchCreating" @change="buildBatchItems" /></el-form-item>
          </div>
          <el-button :disabled="batchCreating" @click="buildBatchItems">按当前设置重新生成编号预览</el-button>
        </FormSection>
        <FormSection title="共同属性" description="对所有小样统一设置；留空保存为 NULL。">
          <div class="form-grid">
            <el-form-item label="前处理"><el-input v-model="batchForm.pre_treatment" maxlength="255" :disabled="batchCreating" placeholder="例如 清洗、预暴露" /></el-form-item>
            <el-form-item label="表面状态"><el-input v-model="batchForm.surface_state" maxlength="128" :disabled="batchCreating" /></el-form-item>
            <el-form-item label="尺寸描述"><el-input v-model="batchForm.size_desc" maxlength="64" :disabled="batchCreating" placeholder="例如 10 × 10 mm" /></el-form-item>
            <el-form-item label="标称厚度 / nm"><el-input v-model="batchForm.nominal_thickness_nm" inputmode="decimal" :disabled="batchCreating" placeholder="默认沿用批次厚度" /></el-form-item>
            <el-form-item label="排除分析"><el-switch v-model="batchForm.exclude_from_analysis" :disabled="batchCreating" /></el-form-item>
            <el-form-item v-if="batchForm.exclude_from_analysis" label="排除原因" required><el-input v-model="batchForm.exclude_reason" type="textarea" :rows="2" maxlength="20000" :disabled="batchCreating" /></el-form-item>
          </div>
        </FormSection>
        <FormSection title="编号预览（可逐行编辑）" description="display_label 为显示编号，cut_position 为切割位置；编码在系统内必须唯一。">
          <el-table :data="batchItems" max-height="320" data-testid="batch-preview">
            <el-table-column label="样品编码" min-width="170"><template #default="{ row }"><el-input v-model="row.sample_code" maxlength="64" :disabled="batchCreating" /><span v-if="batchConflictCodes.includes(String(row.sample_code).trim())" class="danger-text">冲突编号</span></template></el-table-column>
            <el-table-column label="显示编号" min-width="130"><template #default="{ row }"><el-input v-model="row.display_label" maxlength="128" :disabled="batchCreating" /></template></el-table-column>
            <el-table-column label="切割位置" min-width="140"><template #default="{ row }"><el-input v-model="row.cut_position" maxlength="128" :disabled="batchCreating" /></template></el-table-column>
            <el-table-column label="尺寸描述" min-width="140"><template #default="{ row }"><el-input v-model="row.size_desc" maxlength="64" :disabled="batchCreating" /></template></el-table-column>
          </el-table>
        </FormSection>
      </el-form>
      <template #footer>
        <el-button :disabled="batchCreating" @click="closeBatchCreate">取消</el-button>
        <el-button type="primary" data-testid="batch-submit" :loading="batchCreating" :disabled="batchCreating || !batchItems.length || !batchCreateTarget" @click="submitBatchCreate">提交创建 {{ batchItems.length }} 份小样</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.records-action-feedback { display: grid; gap: 10px; margin-bottom: 18px; overflow-wrap: anywhere; }
.records-action-feedback > .el-button { justify-self: start; max-width: 100%; white-space: normal; height: auto; min-height: 32px; }
.records-list-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 20px;
  padding: 0 22px 16px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.records-list-summary .readonly-note { margin: 0; }
.records-skeleton { padding: 24px; }
.records-option-error {
  width: 100%;
  padding: 8px 0;
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.toolbar + .records-option-error { padding: 0 22px 12px; }
.records-conflict {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.records-drawer-footer { display: flex; align-items: center; gap: 12px; width: 100%; }
.records-save-hint { flex: 1; min-width: 0; color: var(--el-text-color-secondary); font-size: 12px; }
.records-view :deep(.detail-grid dd) { white-space: pre-wrap; overflow-wrap: anywhere; }
:global(.records-drawer .el-drawer__body) { overflow-y: auto; }
:global(.records-drawer .el-drawer__footer) {
  flex-shrink: 0;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  padding: 16px 24px;
}
@media (max-width: 600px) {
  .records-list-summary { padding-inline: 16px; }
  :global(.records-drawer .form-grid), :global(.records-drawer .detail-grid) { grid-template-columns: minmax(0, 1fr); }
  :global(.records-drawer .span-2) { grid-column: 1; }
  .records-drawer-footer { gap: 8px; }
}
.records-inline-row { display: flex; gap: 8px; align-items: center; width: 100%; }
.records-inline-row :deep(.el-select) { flex: 1; min-width: 0; }
</style>
