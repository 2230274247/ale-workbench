<script setup lang="ts">
// 样品选择器：远程搜索真实样品（GET /samples?keyword&batch_id&size=200），
// 显示「样品编码 · 批次 · 状态」，支持排除已绑定样品。手填数据库 ID 容易 404，
// 因此所有绑定/创建入口统一改为从这里选择真实样品。
import { computed, onMounted, ref, watch } from 'vue'
import { api, errorText } from '../api'
import { label } from '../experiments/model'

type Row = Record<string, any>
const props = withDefaults(defineProps<{
  // 单选（multiple=false）时 v-model 是 number | null，多选时是 number[]；
  // 两种形态都接受，内部统一按数组处理，避免调用方自己做形态转换。
  modelValue: number[] | number | null
  batchId?: number | string | null
  excludeIds?: number[]
  multiple?: boolean
  disabled?: boolean
  placeholder?: string
  sampleType?: string
  testid?: string
}>(), { batchId: null, excludeIds: () => [], multiple: true, disabled: false, placeholder: '搜索并选择样品', sampleType: '', testid: 'sample-picker' })

const emit = defineEmits<{ 'update:modelValue': [number[] | number | null] }>()
const keyword = ref('')
const choices = ref<Row[]>([])
const loading = ref(false)
const error = ref('')
let sequence = 0
let timer: ReturnType<typeof setTimeout> | null = null

const excluded = computed(() => new Set(props.excludeIds.map(Number)))
const picked = computed<number[]>(() => {
  const value = props.modelValue
  if (Array.isArray(value)) return value.map(Number)
  if (value === null || value === undefined || (value as any) === '') return []
  return [Number(value)]
})
const selected = computed<number[] | number | null>({
  get: () => props.multiple ? picked.value : (picked.value[0] ?? null),
  set: value => emit('update:modelValue', props.multiple ? ((value as number[]) ?? []) : ((value as number) ?? null)),
})
const optionLabel = (sample: Row) => `${sample.sample_code} · 批次 ${sample.batch_code || `#${sample.batch_id}`} · ${label(sample.status)}`
const optionDisabled = (sample: Row) => !!sample.voided_at || (!picked.value.includes(sample.sample_id) && excluded.value.has(sample.sample_id))

async function load() {
  const request = ++sequence
  loading.value = true
  error.value = ''
  try {
    const result = await api<Row[]>('/samples', { query: { keyword: keyword.value, batch_id: props.batchId ?? undefined, sample_type: props.sampleType || undefined, include_voided: false, size: 200 } })
    if (request !== sequence) return
    const kept = choices.value.filter(sample => !sample.voided_at && picked.value.includes(sample.sample_id))
    choices.value = [...kept, ...result.data.filter(sample => !sample.voided_at && !kept.some(item => item.sample_id === sample.sample_id))]
  } catch (cause) {
    if (request === sequence) error.value = errorText(cause)
  } finally {
    if (request === sequence) loading.value = false
  }
}
function onSearch(value: string) {
  keyword.value = value
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { void load() }, 300)
}
watch(() => [props.batchId, props.sampleType], () => { void load() })
watch(() => props.modelValue, () => {
  if (picked.value.some(id => !choices.value.some(sample => sample.sample_id === id))) void load()
})
onMounted(load)
defineExpose({ reload: load })
</script>

<template>
  <div class="sample-picker">
    <el-select
      v-model="selected"
      :multiple="multiple"
      filterable
      remote
      reserve-keyword
      :remote-method="onSearch"
      :loading="loading"
      :disabled="disabled"
      :placeholder="placeholder"
      :data-testid="testid"
      style="width:100%"
      @visible-change="(visible:boolean)=>visible&&load()"
    >
      <el-option
        v-for="sample in choices"
        :key="sample.sample_id"
        :value="sample.sample_id"
        :label="optionLabel(sample)"
        :disabled="optionDisabled(sample)"
      >
        <span>{{ sample.sample_code }}</span>
        <span class="sample-picker-meta">批次 {{ sample.batch_code || `#${sample.batch_id}` }} · {{ label(sample.status) }}<template v-if="excluded.has(sample.sample_id)"> · 已绑定</template></span>
      </el-option>
      <template #empty>
        <p class="sample-picker-empty">{{ loading ? '正在搜索样品…' : keyword ? '没有匹配的样品，可更换关键词' : '输入样品编码或显示编号开始搜索' }}</p>
      </template>
    </el-select>
    <p v-if="error" class="field-hint danger-text" role="alert">样品搜索失败：{{ error }} <el-button link type="primary" @click="load">重试</el-button></p>
    <p v-else-if="!choices.length&&!loading" class="field-hint">未加载到样品；可先按批次筛选，或到样品管理创建小样。</p>
  </div>
</template>

<style scoped>
.sample-picker { width: 100%; }
.sample-picker-meta { float: right; margin-left: 18px; color: var(--muted); font-size: 12px; }
.sample-picker-empty { padding: 10px 16px; color: var(--muted); font-size: 12px; margin: 0; }
</style>
