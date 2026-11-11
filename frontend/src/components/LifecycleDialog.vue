<script setup lang="ts">
// 生命周期对话框：删除影响预览与归档/恢复/作废/删除操作。
// 所有计数都来自 GET /lifecycle/{kind}/{id}/impact 的真实查询；
// 受权限保护的依赖只显示通用提示，不显示类型名称或数量。
import { computed, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api, ApiError, errorText } from '../api'

type Row = Record<string, any>
type Kind = 'batches' | 'samples' | 'plans' | 'processes'
type Action = 'archive' | 'archive_with_dependents' | 'void' | 'delete' | 'restore'

const props = withDefaults(defineProps<{
  modelValue: boolean
  kind: Kind
  id: number | null
  rowVersion?: number | null
  code?: string
}>(), { rowVersion: null, code: '' })
const emit = defineEmits<{
  'update:modelValue': [boolean]
  applied: [action: Action, data: Row]
}>()

const impact = ref<Row | null>(null)
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const actionError = ref('')
const conflict = ref(false)
const reason = ref('')
const selectedAction = ref<Action | null>(null)
const selectedSamples = ref<number[]>([])
const showUntouched = ref(true)
const pendingBody = ref<Row | null>(null)
const uncertain = ref(false)
let request = 0

const kindNoun: Record<Kind, string> = { batches: '批次', samples: '样品', plans: '实验计划', processes: '工艺执行' }
const noun = computed(() => kindNoun[props.kind] || '记录')
const groups = computed<Row[]>(() => impact.value?.groups ?? [])
const visibleGroups = computed(() => groups.value.filter(group => !group.restricted))
const restrictedGroups = computed(() => groups.value.filter(group => group.restricted))
const restricted = computed(() => !!impact.value?.restricted)
const dependencies = computed(() => impact.value?.dependencies_total_visible ?? 0)
const archived = computed(() => !!impact.value?.archived)
const actions = computed<Action[]>(() => impact.value?.actions ?? [])
const candidates = computed<Row[]>(() => impact.value?.sample_counts?.candidates ?? [])
const sharedSamples = computed<Row[]>(() => impact.value?.shared?.shared_samples ?? [])
const sharedPlans = computed<Row[]>(() => impact.value?.shared?.shared_plans ?? [])
const needsReason = computed(() => selectedAction.value === 'void')

const actionLabel: Record<Action, string> = {
  archive: '归档',
  archive_with_dependents: '归档批次并归档所选未使用样品',
  void: '逻辑作废',
  delete: '永久删除',
  restore: '恢复',
}

// 明确列出不会被修改的对象；与后端实际行为保持一致。
const untouched = computed(() => {
  const items = [
    '其他实验的样品与来源原件不会被修改',
    '测量记录、派生结果、仪器数据集与样品流转记录一律保留',
    '审计日志会追加本次操作记录',
  ]
  if (props.kind === 'batches') items.push('未被勾选的批次内样品保持原状')
  if (props.kind === 'samples') items.push('已作废样品的作废原因与作废人保持不变')
  if (props.kind === 'processes') items.push('样品绑定、实际步骤与测量记录不会被删除')
  return items
})

function reset() {
  ++request
  impact.value = null
  pendingBody.value = null
  uncertain.value = false
  loadError.value = ''
  actionError.value = ''
  conflict.value = false
  reason.value = ''
  selectedAction.value = null
  selectedSamples.value = []
}

async function load() {
  if (!props.id) return
  const current = ++request
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  conflict.value = false
  try {
    const result = await api<Row>(`/lifecycle/${props.kind}/${props.id}/impact`)
    if (current !== request) return
    pendingBody.value = null
    uncertain.value = false
    impact.value = result.data
    selectedAction.value = result.data.actions?.[0] ?? null
    selectedSamples.value = []
  } catch (cause) {
    if (current === request) loadError.value = errorText(cause)
  } finally {
    if (current === request) loading.value = false
  }
}

function choose(action: Action) {
  if (!actions.value.includes(action)) return
  selectedAction.value = action
  actionError.value = ''
  conflict.value = false
  if (action !== 'archive_with_dependents') selectedSamples.value = []
}

function toggleSample(sampleId: number, checked: boolean) {
  selectedSamples.value = checked
    ? [...new Set([...selectedSamples.value, sampleId])]
    : selectedSamples.value.filter(id => id !== sampleId)
}

const canSubmit = computed(() => {
  if (!impact.value || loading.value || saving.value || conflict.value || uncertain.value || !selectedAction.value) return false
  if (!actions.value.includes(selectedAction.value)) return false
  if (needsReason.value && !reason.value.trim()) return false
  if (selectedAction.value === 'archive_with_dependents' && !selectedSamples.value.length) return false
  return true
})

const confirmText = computed(() => {
  const action = selectedAction.value
  const label = impact.value?.code || props.code || `#${props.id}`
  if (action === 'delete') return `确认永久删除${noun.value}“${label}”？此操作不可撤销，且只删除该记录本身。`
  if (action === 'void') return `确认作废${noun.value}“${label}”？记录与历史保留，编码不可复用，业务状态不变。`
  if (action === 'restore') return `确认恢复${noun.value}“${label}”？归档标记将移除，计划恢复归档前状态。`
  if (action === 'archive_with_dependents') return `确认归档${noun.value}“${label}”及所选 ${selectedSamples.value.length} 份未使用样品？`
  return `确认归档${noun.value}“${label}”？历史记录与关联关系全部保留。`
})

async function submit() {
  if (!canSubmit.value || !impact.value || !selectedAction.value) return
  const action = selectedAction.value
  try {
    await ElMessageBox.confirm(confirmText.value, actionLabel[action], {
      type: action === 'delete' || action === 'void' ? 'warning' : 'info',
      confirmButtonText: action === 'delete' ? '确认删除' : action === 'void' ? '确认作废' : action === 'restore' ? '确认恢复' : '确认归档',
      cancelButtonText: '取消',
    })
  } catch { return }
  const body: Row = {
    action, expected_row_version: impact.value.row_version,
    preview_token: impact.value.preview_token,
    operation_id: crypto.randomUUID(),
  }
  if (reason.value.trim()) body.reason = reason.value.trim()
  if (action === 'archive_with_dependents') {
    body.include_sample_ids = [...selectedSamples.value]
    body.sample_versions = Object.fromEntries(candidates.value.filter(s => selectedSamples.value.includes(s.sample_id)).map(s => [s.sample_id, s.row_version]))
  }
  pendingBody.value = body
  await applyPending()
}

async function applyPending() {
  if (!pendingBody.value || saving.value) return
  saving.value = true
  actionError.value = ''
  conflict.value = false
  const body = pendingBody.value
  try {
    const result = await api<Row>(`/lifecycle/${props.kind}/${props.id}/apply`, { method: 'POST', body })
    emit('applied', body.action, result.data ?? {})
    pendingBody.value = null
    uncertain.value = false
    emit('update:modelValue', false)
  } catch (cause) {
    conflict.value = cause instanceof ApiError && cause.status === 409
    uncertain.value = !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500
    actionError.value = `${actionLabel[body.action as Action]}失败：${errorText(cause)}${conflict.value ? '。输入已保留，请重载影响预览。' : uncertain.value ? '。响应未确认，请使用原请求恢复结果。' : ''}`
  } finally {
    saving.value = false
  }
}

async function reload() {
  await load()
}

watch(() => [props.modelValue, props.kind, props.id], ([open]) => {
  if (open) { reset(); void load() }
  else reset()
}, { immediate: true })
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`${noun}生命周期与删除影响`"
    width="min(760px, 96vw)"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    data-testid="lifecycle-dialog"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
  >
    <div v-if="loading" class="lifecycle-skeleton" aria-label="正在加载影响预览"><el-skeleton :rows="6" animated /></div>
    <div v-else-if="loadError" role="alert" class="lifecycle-error">
      <p>影响预览加载失败：{{ loadError }}</p>
      <el-button @click="reload">重试加载</el-button>
    </div>
    <template v-else-if="impact">
      <p class="lifecycle-target">
        <strong>{{ impact.code }}</strong>
        <span class="lifecycle-meta">{{ noun }} #{{ impact.id }} · 版本 {{ impact.row_version }}</span>
        <el-tag v-if="archived" type="info" data-testid="lifecycle-archived-badge">已归档</el-tag>
        <el-tag v-if="impact.status?.voided_at" type="danger" data-testid="lifecycle-voided-badge">已作废</el-tag>
      </p>

      <section class="lifecycle-section" data-testid="lifecycle-dependencies">
        <h4>直接关联（真实计数）</h4>
        <p v-if="!visibleGroups.length && !restricted" class="field-hint">没有直接关联记录；可执行操作以当前状态和权限校验为准。</p>
        <ul v-if="visibleGroups.length" class="lifecycle-groups">
          <li v-for="group in visibleGroups" :key="group.type" :data-testid="`lifecycle-group-${group.type}`">
            <span>{{ group.label }}</span>
            <strong>{{ group.count }} 条</strong>
          </li>
        </ul>
        <el-alert
          v-if="restricted"
          data-testid="lifecycle-restricted"
          type="warning"
          :closable="false"
          show-icon
          :title="impact.restricted_flag || '另有受权限保护的关联记录'"
          description="部分关联记录不在你的可见范围内。为避免泄露，这里不显示它们的类型和数量；这些记录同样会阻止删除。"
        />
        <p v-if="impact.sample_counts" class="field-hint" data-testid="lifecycle-sample-counts">
          当前可见批次样品 {{ impact.sample_counts.total }} 份（可用 {{ impact.sample_counts.available }} 份），
          其中 {{ impact.sample_counts.unused_candidates }} 份可随批次归档。
        </p>
        <p v-if="sharedSamples.length" class="field-hint" data-testid="lifecycle-shared-samples">
          共享样品：{{ sharedSamples.map(item => `#${item.sample_id}（${item.process_count} 次执行）`).join('、') }}。归档不会解除这些关联。
        </p>
        <p v-if="sharedPlans.length" class="field-hint" data-testid="lifecycle-shared-plans">
          共享计划：{{ sharedPlans.map(item => `#${item.plan_id}（${item.process_count} 次执行）`).join('、') }}。
        </p>
      </section>

      <section class="lifecycle-section" data-testid="lifecycle-actions">
        <h4>可执行操作</h4>
        <el-radio-group v-model="selectedAction" :disabled="saving || uncertain" class="lifecycle-actions">
          <el-radio v-for="action in actions" :key="action" :value="action" :data-testid="`lifecycle-action-${action}`" @change="choose(action)">
            {{ actionLabel[action] }}
          </el-radio>
        </el-radio-group>
        <p v-if="!actions.length" class="field-hint">当前记录没有可执行的生命周期操作。</p>
        <p v-if="!actions.includes('delete') && !archived" class="field-hint">
          删除仅在没有任何依赖时可用；已有依赖时请归档保留历史。
        </p>

        <div v-if="selectedAction === 'archive_with_dependents'" class="lifecycle-candidates" data-testid="lifecycle-candidates">
          <p class="field-hint">只列出本批次内、可用且没有任何科研关联的样品；未勾选的样品不会被修改。</p>
          <el-checkbox
            v-for="sample in candidates"
            :key="sample.sample_id"
            :model-value="selectedSamples.includes(sample.sample_id)"
            :data-testid="`lifecycle-candidate-${sample.sample_id}`"
            @update:model-value="(value: boolean | string | number) => toggleSample(sample.sample_id, !!value)"
          >
            {{ sample.sample_code }}
          </el-checkbox>
          <p v-if="!candidates.length" class="field-hint">没有可随批次归档的未使用样品。</p>
        </div>

        <el-form label-position="top" class="lifecycle-reason">
          <el-form-item :label="needsReason ? '原因（必填）' : '原因（选填）'" :required="needsReason">
            <el-input
              v-model="reason"
              type="textarea"
              :rows="2"
              maxlength="2000"
              show-word-limit
              :disabled="saving || uncertain"
              :placeholder="needsReason ? '请填写作废原因，例如：误建重复样品' : '可填写本次操作的说明'"
              aria-label="生命周期操作原因"
              data-testid="lifecycle-reason"
            />
          </el-form-item>
        </el-form>
      </section>

      <section class="lifecycle-section" data-testid="lifecycle-untouched">
        <el-checkbox v-model="showUntouched">显示不会被修改的内容</el-checkbox>
        <ul v-if="showUntouched" class="lifecycle-untouched">
          <li v-for="item in untouched" :key="item">{{ item }}</li>
        </ul>
      </section>

      <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon data-testid="lifecycle-error" />
      <el-button v-if="uncertain" :disabled="saving" data-testid="lifecycle-recover" @click="applyPending">使用原请求恢复结果</el-button>
      <el-button v-if="conflict" :disabled="saving" data-testid="lifecycle-reload" @click="reload">重载影响预览</el-button>
    </template>
    <template #footer>
      <el-button :disabled="saving" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        :type="selectedAction === 'delete' || selectedAction === 'void' ? 'danger' : 'primary'"
        :loading="saving"
        :disabled="!canSubmit"
        data-testid="lifecycle-submit"
        @click="submit"
      >
        执行{{ selectedAction ? actionLabel[selectedAction] : '操作' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.lifecycle-skeleton { padding: 8px 0 20px; }
.lifecycle-error { display: grid; gap: 12px; justify-items: start; padding: 8px 0 16px; color: var(--el-color-danger); }
.lifecycle-target { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0 0 16px; overflow-wrap: anywhere; }
.lifecycle-meta { color: var(--el-text-color-secondary); font-size: 13px; }
.lifecycle-section { padding: 14px 0; border-top: 1px solid var(--el-border-color-lighter); }
.lifecycle-section h4 { margin: 0 0 10px; font-size: 14px; }
.lifecycle-groups { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.lifecycle-groups li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 10px; border-radius: 8px; background: var(--el-fill-color-lighter); font-size: 13px; }
.lifecycle-actions { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.lifecycle-candidates { display: grid; gap: 4px; margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: var(--el-fill-color-lighter); }
.lifecycle-reason { margin-top: 12px; }
.lifecycle-untouched { margin: 8px 0 0; padding-left: 20px; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
@media (max-width: 600px) {
  .lifecycle-actions { flex-direction: column; align-items: flex-start; }
}
</style>
