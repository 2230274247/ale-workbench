import type { Measurement, MeasurementPoint } from '../contracts'
export type MeasurementRow = Measurement & {
  row_version: number
  source_file_id?: number | null
  import_item_id?: number | null
  import_locator?: string | null
  provenance?: unknown
  points?: PointRow[]
  replacement?: MeasurementRow
}
export type PointRow = MeasurementPoint & { raw_values?: unknown }
export interface Occurrence {
  occurrence_id: number; source_file_id: number; import_item_id: number
  owner_user_id: number; sample_id: number | null; filename: string
  notes: string | null; created_at: string
}
// The runtime source endpoints deliberately expose fewer fields than SourceFile.
export interface SourceRow {
  file_id: number; file_sha256: string; file_name: string; file_ext: string | null
  size_bytes: number | null; is_readonly: boolean; created_at: string
  storage_key?: string; occurrences?: Occurrence[]
}
export const stages: Record<string,string> = { initial:'初始', after_o2_plasma:'O₂ 等离子体后', after_o3_pre:'O₃ 预处理后', after_ale:'ALE 后', after_hf_only:'仅 HF 后', after_o3_only:'仅 O₃ 后', intermediate:'中间态', final:'最终态', other:'其他' }
export const qualities: Record<string,string> = { ok:'正常', suspect:'可疑', abnormal:'异常', excluded:'排除' }
export const text = (v:unknown) => v === null || v === undefined || v === '' ? '未记录' : String(v)
export const json = (v:unknown) => JSON.stringify(v ?? null, null, 2)
export function positiveId(v:unknown, label:string): number | undefined {
  if (v === '' || v === undefined || v === null) return undefined
  if (!/^\d+$/.test(String(v)) || !Number.isSafeInteger(Number(v)) || Number(v) < 1) throw new Error(`${label}须为有效正整数`)
  return Number(v)
}
export function time(v:unknown) {
  if (!v) return '未记录'
  const value=String(v), d=new Date(/Z$|[+-]\d\d:\d\d$/.test(value)?value:`${value}Z`)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN',{hour12:false})
}
