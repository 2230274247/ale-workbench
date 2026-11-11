<script setup lang="ts">
// 化学体系管理：体系 CRUD、物质列表（含 role）、工艺模板（steps 数组：名称/kind/loop_count/参数行）。
// 契约见第四轮接口规范第 4 节；菜单仅管理员可见，其他角色可只读查看。
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, RefreshCw } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeading from '../components/PageHeading.vue'
import FormSection from '../components/FormSection.vue'
import StatePanel from '../components/StatePanel.vue'
import { api, ApiError, errorText } from '../api'
import { useAuth } from '../auth'
import { type Row, label, speciesRoles, chemistryStatuses, stepKinds } from '../experiments/model'

interface TemplateParameter { key: string; label: string; unit: string }
interface TemplateStep { name: string; kind: string; loop_count: string; parameters: TemplateParameter[] }
const auth = useAuth()
const systems = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const error = ref('')
const filters = reactive({ keyword: '', status: '' })
const detail = ref<Row | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const selectedId = ref<number | null>(null)
const saving = ref(false)
const formError = ref('')
const conflict = ref(false)
const createOpen = ref(false)
const systemForm = reactive<Row>({ system_code: '', system_name: '', description: '', status: 'active' })
const speciesForm = reactive<Row>({ species_code: '', species_name: '', formula: '', role: 'reactant', default_unit: '', notes: '' })
const speciesEditing = ref<number | null>(null)
const speciesOpen = ref(false)
const templateOpen = ref(false)
const templateEditing = ref<number | null>(null)
const templateForm = reactive<Row>({ template_code: '', template_name: '', description: '' })
const templateSteps = ref<TemplateStep[]>([])
let listSequence = 0, detailSequence = 0

const isAdmin = computed(() => auth.isAdmin)
// 后端 /chemistry-systems 的写入权限为 writer（管理员与实验员），可见范围按归属过滤，
// 只有删除体系需要管理员。前端与契约保持一致：实验员也能维护自己的化学体系。
const writable = computed(() => auth.canWrite)
const systemId = (row: Row | null) => Number(row?.chemistry_system_id ?? row?.system_id ?? row?.id ?? 0)
const speciesId = (row: Row) => Number(row?.species_id ?? row?.id ?? 0)
const templateId = (row: Row) => Number(row?.template_id ?? row?.id ?? 0)
const idOf = (row: Row) => systemId(row)
const templates = computed<Row[]>(() => detail.value?.templates ?? [])
const speciesList = computed<Row[]>(() => detail.value?.species ?? [])

// 弹窗未保存修改保护（第四轮第 6 项）：普通弹窗仍可点灰色遮罩或按 Esc 关闭，
// 但有未保存输入时必须先确认，不能静默丢弃用户填写的编号、名称和步骤。
const createBaseline = ref('')
const speciesBaseline = ref('')
const templateBaseline = ref('')
const createSnapshot = () => JSON.stringify(systemForm)
const speciesSnapshot = () => JSON.stringify(speciesForm)
const templateSnapshot = () => JSON.stringify([templateForm, templateSteps.value])
async function closeWithDiscard(model: { value: boolean }, dirty: boolean, message: string, done?: () => void) {
  if (saving.value) return
  if (dirty) {
    try {
      await ElMessageBox.confirm(message, '未保存的修改', { type: 'warning', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' })
    } catch { return }
  }
  model.value = false
  done?.()
}
const closeCreate = (done?: () => void) => closeWithDiscard(createOpen, createSnapshot() !== createBaseline.value, '化学体系表单尚未保存，确定放弃？', done)
const closeSpecies = (done?: () => void) => closeWithDiscard(speciesOpen, speciesSnapshot() !== speciesBaseline.value, '物质信息尚未保存，确定放弃？', done)
const closeTemplate = (done?: () => void) => closeWithDiscard(templateOpen, templateSnapshot() !== templateBaseline.value, '工艺模板尚未保存，确定放弃？', done)
function openCreate() {
  Object.assign(systemForm, { system_code: '', system_name: '', description: '', status: 'active' })
  formError.value = ''
  createBaseline.value = createSnapshot()
  createOpen.value = true
}

async function load() {
  const request = ++listSequence
  loading.value = true
  error.value = ''
  try {
    const result = await api<Row[]>('/chemistry-systems', { query: { page: page.value, size: size.value, keyword: filters.keyword, status: filters.status } })
    if (request !== listSequence) return
    systems.value = result.data
    total.value = result.meta?.total ?? result.data.length
  } catch (cause) {
    if (request === listSequence) error.value = errorText(cause)
  } finally {
    if (request === listSequence) loading.value = false
  }
}
function search() { page.value = 1; void load() }
async function openDetail(id: number) {
  const request = ++detailSequence
  selectedId.value = id
  detailLoading.value = true
  detailError.value = ''
  formError.value = ''
  conflict.value = false
  try {
    const result = await api<Row>(`/chemistry-systems/${id}`)
    if (request === detailSequence) detail.value = result.data
  } catch (cause) {
    if (request === detailSequence) detailError.value = errorText(cause)
  } finally {
    if (request === detailSequence) detailLoading.value = false
  }
}
async function refreshDetail() { if (selectedId.value) await openDetail(selectedId.value) }

async function createSystem() {
  if (saving.value || !writable.value) return
  formError.value = ''
  saving.value = true
  try {
    const body: Row = { system_code: systemForm.system_code.trim(), system_name: systemForm.system_name.trim(), description: systemForm.description.trim() || null, status: systemForm.status }
    if (!body.system_code || !body.system_name) throw new Error('请填写体系编码与名称')
    const result = await api<Row>('/chemistry-systems', { method: 'POST', body })
    createOpen.value = false
    Object.assign(systemForm, { system_code: '', system_name: '', description: '', status: 'active' })
    ElMessage.success('化学体系已创建')
    await load()
    await openDetail(systemId(result.data))
  } catch (cause) {
    formError.value = errorText(cause)
  } finally { saving.value = false }
}
async function patchSystem(patch: Row) {
  if (!detail.value || saving.value || !writable.value) return
  saving.value = true
  formError.value = ''
  try {
    const body = { ...patch, expected_row_version: detail.value.row_version }
    const result = await api<Row>(`/chemistry-systems/${systemId(detail.value)}`, { method: 'PATCH', body })
    detail.value = result.data
    conflict.value = false
    ElMessage.success('化学体系已更新')
    await load()
  } catch (cause) {
    conflict.value = cause instanceof ApiError && cause.status === 409
    formError.value = errorText(cause)
  } finally { saving.value = false }
}
async function archiveSystem() {
  if (!detail.value || saving.value || !writable.value) return
  try {
    await ElMessageBox.confirm('归档后该体系不再出现在启用列表；历史引用保留。确定归档？', '归档化学体系', { type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '取消' })
  } catch { return }
  await patchSystem({ status: 'superseded' })
}
async function removeSystem() {
  if (!detail.value || saving.value || !isAdmin.value) return
  try {
    await ElMessageBox.confirm('删除后无法恢复；被执行引用的体系会返回 409。确定删除？', '删除化学体系', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
  } catch { return }
  saving.value = true
  formError.value = ''
  try {
    await api(`/chemistry-systems/${systemId(detail.value)}`, { method: 'DELETE' })
    detail.value = null
    selectedId.value = null
    ElMessage.success('化学体系已删除')
    await load()
  } catch (cause) {
    formError.value = cause instanceof ApiError && cause.status === 409 ? `${errorText(cause)}（已被执行引用，请改用归档）` : errorText(cause)
  } finally { saving.value = false }
}
function openSpecies(row?: Row) {
  speciesEditing.value = row ? speciesId(row) : null
  Object.assign(speciesForm, row
    ? { species_code: row.species_code ?? '', species_name: row.species_name ?? '', formula: row.formula ?? '', role: row.role ?? 'other', default_unit: row.default_unit ?? '', notes: row.notes ?? '' }
    : { species_code: '', species_name: '', formula: '', role: 'reactant', default_unit: '', notes: '' })
  formError.value = ''
  speciesBaseline.value = speciesSnapshot()
  speciesOpen.value = true
}
async function saveSpecies() {
  if (!detail.value || saving.value || !writable.value) return
  saving.value = true
  formError.value = ''
  try {
    const body: Row = {
      species_code: speciesForm.species_code.trim(), species_name: speciesForm.species_name.trim(),
      formula: speciesForm.formula.trim() || null, role: speciesForm.role,
      default_unit: speciesForm.default_unit.trim() || null, notes: speciesForm.notes.trim() || null,
    }
    if (!body.species_code || !body.species_name) throw new Error('请填写物质编码与名称')
    if (speciesEditing.value) await api(`/species/${speciesEditing.value}`, { method: 'PATCH', body })
    else await api(`/chemistry-systems/${systemId(detail.value)}/species`, { method: 'POST', body })
    speciesOpen.value = false
    ElMessage.success('物质已保存')
    await refreshDetail()
  } catch (cause) {
    formError.value = errorText(cause)
  } finally { saving.value = false }
}
async function removeSpecies(row: Row) {
  if (saving.value || !writable.value) return
  try {
    await ElMessageBox.confirm(`确定删除物质「${row.species_code}」？模板参数中以文本保存的引用不会被强制修改。`, '删除确认', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
  } catch { return }
  saving.value = true
  try {
    await api(`/species/${speciesId(row)}`, { method: 'DELETE' })
    ElMessage.success('物质已删除')
    await refreshDetail()
  } catch (cause) { ElMessage.error(errorText(cause)) } finally { saving.value = false }
}
function blankStep(): TemplateStep { return { name: '', kind: 'other', loop_count: '', parameters: [{ key: '', label: '', unit: '' }] } }
function openTemplate(row?: Row) {
  templateEditing.value = row ? templateId(row) : null
  Object.assign(templateForm, row
    ? { template_code: row.template_code ?? '', template_name: row.template_name ?? '', description: row.description ?? '' }
    : { template_code: '', template_name: '', description: '' })
  templateSteps.value = row?.steps?.length
    ? row.steps.map((step: Row) => ({
      name: step.name ?? '', kind: step.kind ?? 'other', loop_count: step.loop_count == null ? '' : String(step.loop_count),
      parameters: (step.parameters ?? []).map((p: Row) => ({ key: p.key ?? '', label: p.label ?? '', unit: p.unit ?? '' })),
    }))
    : [blankStep()]
  formError.value = ''
  templateBaseline.value = templateSnapshot()
  templateOpen.value = true
}
function addStep() { templateSteps.value.push(blankStep()) }
function removeStep(index: number) { templateSteps.value.splice(index, 1) }
function moveStep(index: number, offset: number) {
  const next = index + offset
  if (next < 0 || next >= templateSteps.value.length) return
  const [step] = templateSteps.value.splice(index, 1)
  templateSteps.value.splice(next, 0, step)
}
function addParameter(step: TemplateStep) { step.parameters.push({ key: '', label: '', unit: '' }) }
function removeParameter(step: TemplateStep, index: number) { step.parameters.splice(index, 1) }
async function saveTemplate() {
  if (!detail.value || saving.value || !writable.value) return
  saving.value = true
  formError.value = ''
  try {
    const steps = templateSteps.value.map(step => {
      const name = step.name.trim()
      if (!name) throw new Error('每个步骤都需要填写名称')
      const loop = step.loop_count.trim()
      if (loop && (!/^\d+$/.test(loop) || Number(loop) < 1 || Number(loop) > 100000)) throw new Error(`步骤「${name}」的循环次数需为 1–100000 的整数`)
      const parameters = step.parameters.filter(p => p.key.trim() || p.label.trim() || p.unit.trim()).map(p => {
        const key = p.key.trim()
        if (!/^[A-Za-z0-9_]{1,64}$/.test(key)) throw new Error(`步骤「${name}」的参数标识只能使用字母、数字与下划线（≤64）`)
        if (!p.label.trim()) throw new Error(`步骤「${name}」的参数「${key}」需要填写中文标签`)
        if (p.label.trim().length > 64) throw new Error(`步骤「${name}」的参数标签超过 64 个字符`)
        if (p.unit.trim().length > 24) throw new Error(`步骤「${name}」的参数单位超过 24 个字符`)
        return { key, label: p.label.trim(), unit: p.unit.trim() || null }
      })
      return { name, kind: step.kind, loop_count: loop ? Number(loop) : null, parameters }
    })
    if (!steps.length) throw new Error('工艺模板至少需要 1 个步骤')
    const body: Row = {
      template_code: templateForm.template_code.trim(), template_name: templateForm.template_name.trim(),
      description: templateForm.description.trim() || null, steps,
    }
    if (!body.template_code || !body.template_name) throw new Error('请填写模板编码与名称')
    if (templateEditing.value) await api(`/step-templates/${templateEditing.value}`, { method: 'PATCH', body })
    else await api(`/chemistry-systems/${systemId(detail.value)}/step-templates`, { method: 'POST', body })
    templateOpen.value = false
    ElMessage.success('工艺模板已保存')
    await refreshDetail()
  } catch (cause) {
    formError.value = errorText(cause)
  } finally { saving.value = false }
}
async function removeTemplate(row: Row) {
  if (saving.value || !writable.value) return
  try {
    await ElMessageBox.confirm(`确定删除模板「${row.template_code}」？`, '删除确认', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
  } catch { return }
  saving.value = true
  try {
    await api(`/step-templates/${templateId(row)}`, { method: 'DELETE' })
    ElMessage.success('模板已删除')
    await refreshDetail()
  } catch (cause) { ElMessage.error(errorText(cause)) } finally { saving.value = false }
}
onMounted(() => { void load() })
</script>

<template>
  <div class="chemistry-view" data-testid="chemistry-page">
    <PageHeading title="化学体系" description="维护体系、物质与工艺模板（步骤名称、类型、循环次数与参数行）。执行表单中的化学体系下拉来自这里。">
      <template #actions>
        <el-button :loading="loading" @click="load"><RefreshCw :size="15" />刷新</el-button>
        <el-button v-if="writable" type="primary" @click="openCreate"><Plus :size="15" />新建体系</el-button>
      </template>
    </PageHeading>
    <p v-if="!writable" class="readonly-note">当前账户为只读权限，可查看化学体系；新建与编辑需要写入权限（管理员或实验员），删除体系仅管理员。</p>

    <section class="panel">
      <form class="toolbar" @submit.prevent="search">
        <el-input v-model="filters.keyword" class="search-input" placeholder="搜索体系编码 / 名称" aria-label="搜索化学体系" clearable />
        <el-select v-model="filters.status" class="filter-select" clearable placeholder="全部状态" aria-label="体系状态" @change="search">
          <el-option v-for="status in chemistryStatuses" :key="status" :label="label(status)" :value="status" />
        </el-select>
        <el-button native-type="submit" :loading="loading">查询</el-button>
        <el-button text @click="filters.keyword = ''; filters.status = ''; search()">重置</el-button>
      </form>
      <StatePanel v-if="error" title="化学体系加载失败" :description="error" tone="error"><el-button @click="load">重试</el-button></StatePanel>
      <div v-else class="table-wrap" v-loading="loading">
        <el-table :data="systems" empty-text="尚无化学体系；新建后可在这里维护物质与工艺模板。">
          <el-table-column label="体系编码" min-width="170"><template #default="{ row }"><el-button link type="primary" @click="openDetail(idOf(row))">{{ row.system_code }}</el-button><div class="table-sub">{{ row.system_name }}</div></template></el-table-column>
          <el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag :type="row.status === 'superseded' ? 'info' : 'success'">{{ label(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="说明" min-width="220"><template #default="{ row }">{{ row.description || '—' }}</template></el-table-column>
          <el-table-column label="操作" min-width="120" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(idOf(row))">查看详情</el-button></template></el-table-column>
        </el-table>
      </div>
      <div class="pagination"><span>共 {{ total }} 个体系</span><el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[10, 20, 50]" :total="total" layout="sizes, prev, pager, next" @size-change="search" @current-change="load" /></div>
    </section>

    <section v-if="selectedId" class="panel panel-body chemistry-detail">
      <el-skeleton v-if="detailLoading" :rows="6" animated />
      <StatePanel v-else-if="detailError" title="体系详情加载失败" :description="detailError" tone="error"><el-button @click="refreshDetail">重试</el-button></StatePanel>
      <template v-else-if="detail">
        <div class="detail-title">
          <h2>{{ detail.system_code }}</h2>
          <el-tag :type="detail.status === 'superseded' ? 'info' : 'success'">{{ label(detail.status) }}</el-tag>
          <el-tag>版本 {{ detail.row_version }}</el-tag>
          <el-button v-if="writable" :disabled="saving" @click="archiveSystem">归档体系</el-button>
          <el-button v-if="isAdmin" type="danger" plain :disabled="saving" @click="removeSystem">删除体系</el-button>
        </div>
        <el-alert v-if="formError" class="drawer-alert" :title="formError" type="error" :closable="false" show-icon />
        <p v-if="conflict" class="field-hint">版本冲突：请刷新详情后重新提交。</p>
        <FormSection title="体系信息" description="system_code 在系统内唯一；名称与说明可随时调整。">
          <div class="form-grid">
            <el-form-item label="体系名称"><el-input v-model="detail.system_name" maxlength="255" :disabled="saving || !writable" /></el-form-item>
            <el-form-item label="状态"><el-select v-model="detail.status" :disabled="saving || !writable"><el-option v-for="status in chemistryStatuses" :key="status" :label="label(status)" :value="status" /></el-select></el-form-item>
            <el-form-item label="说明" class="span-2"><el-input v-model="detail.description" type="textarea" :rows="2" maxlength="20000" :disabled="saving || !writable" /></el-form-item>
          </div>
          <el-button v-if="writable" type="primary" :loading="saving" @click="patchSystem({ system_name: detail.system_name, description: detail.description || null, status: detail.status })">保存体系信息</el-button>
        </FormSection>

        <FormSection title="物质列表" description="role 取 precursor / reactant / purge / carrier / other；模板参数只以文本引用物质编码。">
          <el-button v-if="writable" :disabled="saving" @click="openSpecies()">新增物质</el-button>
          <StatePanel v-if="!speciesList.length" title="尚无物质" description="添加参与该体系的物质与角色。" tone="empty" />
          <el-table v-else :data="speciesList">
            <el-table-column prop="species_code" label="物质编码" min-width="120" />
            <el-table-column prop="species_name" label="名称" min-width="130" />
            <el-table-column prop="formula" label="分子式" min-width="100" />
            <el-table-column label="角色 role" min-width="120"><template #default="{ row }">{{ label(row.role) }}</template></el-table-column>
            <el-table-column prop="default_unit" label="默认单位" min-width="110" />
            <el-table-column v-if="writable" label="操作" min-width="140" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="saving" @click="openSpecies(row)">编辑</el-button><el-button link type="danger" :disabled="saving" @click="removeSpecies(row)">删除</el-button></template></el-table-column>
          </el-table>
        </FormSection>

        <FormSection title="工艺模板" description="steps 数组顺序即步骤顺序；每步可设循环次数与参数行（key / 中文标签 / 单位）。">
          <el-button v-if="writable" :disabled="saving" @click="openTemplate()">新增工艺模板</el-button>
          <StatePanel v-if="!templates.length" title="尚无工艺模板" description="模板用于快速套用步骤与参数骨架。" tone="empty" />
          <article v-for="template in templates" :key="templateId(template)" class="chemistry-template">
            <div class="chemistry-template-title"><strong>{{ template.template_code }} · {{ template.template_name }}</strong><template v-if="writable"><el-button link type="primary" :disabled="saving" @click="openTemplate(template)">编辑</el-button><el-button link type="danger" :disabled="saving" @click="removeTemplate(template)">删除</el-button></template></div>
            <p class="field-hint">{{ template.description || '未填写说明' }}</p>
            <ol class="chemistry-steps">
              <li v-for="(step, index) in template.steps" :key="index">
                <strong>{{ Number(index) + 1 }}. {{ step.name }}</strong>
                <span class="muted"> · {{ label(step.kind) }}<template v-if="step.loop_count != null"> · 循环 {{ step.loop_count }}</template></span>
                <div v-if="step.parameters?.length" class="field-hint">参数：{{ step.parameters.map((p: Row) => `${p.key}（${p.label}${p.unit ? ` / ${p.unit}` : ''}）`).join('、') }}</div>
              </li>
            </ol>
          </article>
        </FormSection>
      </template>
    </section>

    <el-dialog v-model="createOpen" title="新建化学体系" width="min(560px, 94vw)" :before-close="closeCreate" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <el-alert v-if="formError" :title="formError" type="error" :closable="false" show-icon />
      <el-form label-position="top" data-testid="chemistry-system-form" @submit.prevent="createSystem">
        <el-form-item label="体系编码" required><el-input v-model="systemForm.system_code" maxlength="64" placeholder="例如 SIN-ALE" :disabled="saving" /></el-form-item>
        <el-form-item label="体系名称" required><el-input v-model="systemForm.system_name" maxlength="255" placeholder="例如 SiN ALE 体系" :disabled="saving" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="systemForm.status" :disabled="saving"><el-option v-for="status in chemistryStatuses" :key="status" :label="label(status)" :value="status" /></el-select></el-form-item>
        <el-form-item label="说明"><el-input v-model="systemForm.description" type="textarea" :rows="2" maxlength="20000" :disabled="saving" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="closeCreate()">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving" @click="createSystem">创建体系</el-button></template>
    </el-dialog>

    <el-dialog v-model="speciesOpen" :title="speciesEditing ? '编辑物质' : '新增物质'" width="min(560px, 94vw)" :before-close="closeSpecies" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <el-alert v-if="formError" :title="formError" type="error" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="saveSpecies">
        <div class="form-grid">
          <el-form-item label="物质编码" required><el-input v-model="speciesForm.species_code" maxlength="64" placeholder="例如 O3" :disabled="saving" /></el-form-item>
          <el-form-item label="物质名称" required><el-input v-model="speciesForm.species_name" maxlength="255" placeholder="例如 臭氧" :disabled="saving" /></el-form-item>
          <el-form-item label="分子式"><el-input v-model="speciesForm.formula" maxlength="64" placeholder="例如 O3" :disabled="saving" /></el-form-item>
          <el-form-item label="角色 role"><el-select v-model="speciesForm.role" :disabled="saving"><el-option v-for="role in speciesRoles" :key="role" :label="label(role)" :value="role" /></el-select></el-form-item>
          <el-form-item label="默认单位"><el-input v-model="speciesForm.default_unit" maxlength="24" placeholder="例如 sccm" :disabled="saving" /></el-form-item>
        </div>
        <el-form-item label="备注"><el-input v-model="speciesForm.notes" type="textarea" :rows="2" maxlength="20000" :disabled="saving" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="closeSpecies()">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving" @click="saveSpecies">保存物质</el-button></template>
    </el-dialog>

    <el-dialog v-model="templateOpen" :title="templateEditing ? '编辑工艺模板' : '新增工艺模板'" width="min(860px, 96vw)" :before-close="closeTemplate" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
      <el-alert v-if="formError" :title="formError" type="error" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="saveTemplate">
        <div class="form-grid">
          <el-form-item label="模板编码" required><el-input v-model="templateForm.template_code" maxlength="64" placeholder="例如 O3-HF-TMA" :disabled="saving" /></el-form-item>
          <el-form-item label="模板名称" required><el-input v-model="templateForm.template_name" maxlength="255" placeholder="例如 O3-HF-TMA 循环" :disabled="saving" /></el-form-item>
          <el-form-item label="说明" class="span-2"><el-input v-model="templateForm.description" type="textarea" :rows="2" maxlength="20000" :disabled="saving" /></el-form-item>
        </div>
      </el-form>
      <FormSection title="步骤（按顺序执行）" description="数组顺序即步骤顺序；kind 用于分类，名称可自定义。">
        <el-button :disabled="saving" @click="addStep">添加步骤</el-button>
        <article v-for="(step, index) in templateSteps" :key="index" class="chemistry-step-editor">
          <div class="chemistry-step-editor-title">
            <strong>步骤 {{ index + 1 }}</strong>
            <el-button link :disabled="saving || index === 0" @click="moveStep(index, -1)">上移</el-button>
            <el-button link :disabled="saving || index === templateSteps.length - 1" @click="moveStep(index, 1)">下移</el-button>
            <el-button link type="danger" :disabled="saving" @click="removeStep(index)">删除步骤</el-button>
          </div>
          <div class="form-grid">
            <el-form-item label="步骤名称" required><el-input v-model="step.name" maxlength="128" placeholder="例如 O3 暴露" :disabled="saving" /></el-form-item>
            <el-form-item label="步骤分类（自由填写）"><el-input v-model="step.kind" maxlength="128" placeholder="例如 Ar 活化、Xe 暴露、自定义处理" :disabled="saving" /></el-form-item>
            <el-form-item label="循环次数 loop_count（1–100000，可空）"><el-input v-model="step.loop_count" inputmode="numeric" :disabled="saving" /></el-form-item>
          </div>
          <div class="chemistry-parameter-editor">
            <div class="chemistry-parameter-head"><span>参数标识</span><span>中文标签</span><span>单位</span><span></span></div>
            <div v-for="(parameter, pindex) in step.parameters" :key="pindex" class="chemistry-parameter-row">
              <el-input v-model="parameter.key" maxlength="64" placeholder="例如 duration_s" :disabled="saving" />
              <el-input v-model="parameter.label" maxlength="64" placeholder="例如 时长" :disabled="saving" />
              <el-input v-model="parameter.unit" maxlength="24" placeholder="例如 s" :disabled="saving" />
              <el-button link type="danger" :disabled="saving" @click="removeParameter(step, pindex)">删除</el-button>
            </div>
            <el-button link type="primary" :disabled="saving" @click="addParameter(step)">添加参数行</el-button>
          </div>
        </article>
      </FormSection>
      <template #footer><el-button :disabled="saving" @click="closeTemplate()">取消</el-button><el-button type="primary" :loading="saving" :disabled="saving" @click="saveTemplate">保存模板</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.chemistry-detail { margin-top: 24px; }
.chemistry-template { padding: 14px 0; border-bottom: 1px solid var(--line); }
.chemistry-template:last-child { border-bottom: 0; }
.chemistry-template-title { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.chemistry-steps { margin: 8px 0 0; padding-left: 20px; font-size: 13px; }
.chemistry-steps li { margin-bottom: 6px; }
.chemistry-step-editor { border: 1px solid var(--line); border-radius: 6px; padding: 14px 16px; margin-top: 14px; }
.chemistry-step-editor-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.chemistry-parameter-editor { margin-top: 4px; }
.chemistry-parameter-head, .chemistry-parameter-row { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.1fr) minmax(0, .8fr) auto; gap: 8px; align-items: center; }
.chemistry-parameter-head { font-size: 12px; color: var(--muted); padding-bottom: 4px; }
.chemistry-parameter-row { margin-bottom: 8px; }
@media (max-width: 760px) {
  .chemistry-parameter-head { display: none; }
  .chemistry-parameter-row { grid-template-columns: minmax(0, 1fr); }
}
</style>
