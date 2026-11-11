// Explicit visual-review fixtures, not a copy of production research data.
// The 11 → 10 nm / 100-cycle case follows the existing browser acceptance scenario.
const measurement = (id: number, code: string, stage: string, mean: number, values: number[]) => ({
  measurement_id: id, measurement_code: code, stage, thickness_mean_nm: mean,
  valid_point_count: values.length, point_count: values.length, quality_flag: 'ok', is_current: true,
  measured_at: stage === 'initial' ? '2026-01-01T09:00:00+08:00' : '2026-01-01T12:00:00+08:00',
  mse_mean: null, model_name: '演示模型 A', model_parameters: [], source_file_id: null,
  values,
})
export const measurements = [
  measurement(1, 'DEMO-BEFORE', 'initial', 11, [10.8, 11, 11.1, 11.1]),
  measurement(2, 'DEMO-AFTER', 'after_ale', 10, [9.8, 10, 10.1, 10.1]),
]
export const result = {
  before_code: 'DEMO-BEFORE', after_code: 'DEMO-AFTER', before_mean_nm: 11, after_mean_nm: 10,
  after_measurement_id: 2, thinning_nm: 1, effective_cycles: 100, epc_nm_per_cycle: 0.01,
  reason: null, quality_rule: '演示：同模型、明确配对、实际区间和逐片参与依据均已确认。',
  interpretation: '表观减薄不等于已确认材料刻蚀机理。', version: 'demo', analysis_version: 'demo', sources: [],
}
export const review = { measurements, results: [result] }
const sampleA = { sample_id: 1, sample_code: 'S01-1', batch_id: 1 }
const sampleB = { sample_id: 2, sample_code: 'S01-2', batch_id: 1 }
const run = {
  process_id: 1, process_code: 'DEMO-RUN-01', plan: { title: '氮化硅刻蚀研究' },
  started_at: '2026-01-01T10:00:00+08:00', ended_at: '2026-01-01T11:00:00+08:00',
  process_mode: 'full_cycle', r1_temp_c: null, r2_temp_c: null, n2_flow_sccm: null,
  samples: [
    { sample: sampleA, sample_id: 1, process_sample_id: 1, batch: { material: 'SiNₓ' }, chemistry_name: '演示体系 A', cycles_confirmed: true, full_ale_cycles: 100, execution_evidence: 'recorded_loading', participation_status: 'unloaded', unload_event: { step_index: 5 }, research_review: review },
    { sample: sampleB, sample_id: 2, process_sample_id: 2, batch: { material: 'SiNₓ' }, chemistry_name: null, cycles_confirmed: false, full_ale_cycles: null, execution_evidence: 'not_confirmed', participation_status: 'bound', unload_event: null, research_review: { measurements: [], results: [{ after_measurement_id: 3, before_code: 'DEMO-B2', after_code: 'DEMO-A2', reason: '前后光学模型不同，不可直接比较', sources: [] }] } },
  ],
}
export const runs = [run]
const firstExperiment = {
  ...run, plan_title: run.plan.title, execution_evidence: 'recorded_loading', cycles_confirmed: true,
  full_ale_cycles: 100, load_event: { step_index: 1, event_at: '2026-01-01T10:00:00+08:00' },
  unload_event: { step_index: 5, event_at: '2026-01-01T11:00:00+08:00' }, measurements: [measurements[1]], steps: [],
}
export const sample = {
  ...sampleA, participation_summary: { recorded_participations: 1, recorded_cycles: null, missing_participations: 1,
    cycle_groups: [{ label: '演示体系 A', process_mode: 'full_cycle', recorded_participations: 1, recorded_cycles: 100, missing_participations: 0 }, { label: '体系未确认 · 第二次执行', process_mode: 'full_cycle', recorded_participations: 0, recorded_cycles: null, missing_participations: 1 }] },
  experiments: [firstExperiment, { ...firstExperiment, process_id: 2, process_code: 'DEMO-RUN-02', plan_title: '第二次处理 · 待核对', started_at: null, ended_at: null, full_ale_cycles: null, cycles_confirmed: false, execution_evidence: 'not_confirmed', load_event: null, unload_event: null, measurements: [] }],
}
export const analysis = {
  series: measurements.map(m => ({
    source: { label: m.stage === 'initial' ? 'S01-1 · 处理前' : 'S01-1 · 处理后', stage: m.stage, optical_model_id: '演示模型 A', sample_id: 1, recorded_conditions: { full_ale_cycles: 100 } },
    included_count: 4, excluded_count: 0, statistics: { thickness_nm: { mean: m.thickness_mean_nm } },
    points: m.values.map((value, i) => ({ point_no: i + 1, thickness_nm: value, included: true, is_outlier: false, x_mm: null, y_mm: null, mse: null, gof: null })),
  })),
}
