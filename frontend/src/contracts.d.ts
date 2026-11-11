// =====================================================================
// ALE 实验工作台 · API 类型定义
// 由 tools/gen_models.py 从 openapi.bundled.yaml 自动生成，请勿手工修改
// ---------------------------------------------------------------------
// 类型约定:
//   数据库 DECIMAL 字段映射为 string（不是 number）——
//   数据库存的是 DECIMAL(14,6) 等定点类型，转 JS number 会精度失真。
//   数据库 DATETIME 映射为 string（ISO 8601 含时区）。
//   数据库 DATE 映射为 string（YYYY-MM-DD）。
// =====================================================================

/** 统一响应包络。JSON 接口（含错误）返回此结构；204 无 body，原件下载成功为二进制。 */
export interface ApiEnvelope<T = unknown> {
  /** 业务状态码。0 表示成功。前端以此为准，而非 HTTP 状态码 */
  code: number;
  /** 提示信息（中文）。成功时为 'ok' */
  message: string;
  /** 业务数据。错误时为 null 或 ErrorDetail */
  data: T | null;
  /** 请求追踪 ID，排障时用于定位日志 */
  request_id: string;
  /** 服务端响应时间（ISO 8601） */
  timestamp: string;
}

/** 分页元信息 */
export interface PageMeta {
  page: number;
  size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

/** 分页响应 */
export interface PagedData<T> extends ApiEnvelope<T[]> {
  data: T[];
  meta: PageMeta;
}

/** 字段级校验错误 */
export interface FieldError {
  field: string;
  message: string;
  rejected_value?: unknown;
}

/** 错误详情（兼容 RFC 9457 Problem Details） */
export interface ErrorDetail {
  type: string;
  title: string;
  status: number;
  code: number;
  detail?: string;
  instance?: string;
  errors?: FieldError[];
}

// ---------------------------------------------------------------------
// 契约模型包含 planned 结构；类型存在不表示对应接口已实现。
// 业务实体
// ---------------------------------------------------------------------

export type AIRequestStatus = "pending" | "completed" | "failed";

export type AISourceKind = "sample" | "batch" | "plan" | "process" | "measurement" | "source_file" | "transition";

/** 账户用途独立于角色。admin固定management；operator/viewer只能research或testing。 */
export type AccountPurpose = "management" | "research" | "testing";

export type AttachmentType = "figure" | "origin_project" | "pdf" | "report" | "script" | "table" | "other";

/** 操作类型。 */
export type AuditAction = "insert" | "update" | "delete" | "login" | "export";

/** 批次状态。 */
export type BatchStatus = "active" | "archived" | "quarantined";

/** 通道类型。 */
export type ChannelType = "spectrum" | "survey" | "peak" | "ion_current" | "image";

/** 图表类型。 */
export type ChartType = "bar" | "line" | "scatter" | "mapping" | "histogram" | "box" | "radar";

/** 实体类型（用于多态关联与附件挂载）。 */
export type EntityType = "experiment_plan" | "process" | "sample" | "measurement" | "source_file" | "finding" | "batch" | "derived_result" | "instrument_dataset";

/** 证据等级。本工作台的核心字段之一，强制区分： */
export type EvidenceLevel = "measured" | "hypothesis" | "unverified";

/** 文件在数据链中的角色。 */
export type FileRole = "instrument_raw" | "derived_summary" | "point_derived" | "analysis_output" | "metadata" | "xps_raw";

export type ImportItemStatus = "pending" | "imported" | "original_only" | "skipped";

export type ImportJobStatus = "draft" | "completed";

/** 仪器类型。采用通用三层模型（数据集-通道-数据点）， */
export type InstrumentType = "xps" | "rga" | "xrr" | "afm" | "sem" | "sims" | "other";

export type InvitationRole = "viewer" | "operator";

/** 问题严重度。 */
export type IssueSeverity = "high" | "medium_high" | "medium" | "medium_low" | "low";

/** 问题处理状态。 */
export type IssueStatus = "open" | "investigating" | "resolved" | "accepted_risk" | "deferred";

/** 测量质量标记。 */
export type MeasurementQualityFlag = "ok" | "suspect" | "abnormal" | "excluded";

/** 测量阶段。区分测量处于工艺链的哪个位置。 */
export type MeasurementStage = "initial" | "after_o2_plasma" | "after_o3_pre" | "after_ale" | "after_hf_only" | "after_o3_only" | "intermediate" | "final" | "other";

export type OpticalModelStatus = "active" | "superseded" | "experimental";

/** 普通账户及邀请用途；邀请不能创建management账户。 */
export type OrdinaryAccountPurpose = "research" | "testing";

/** 配对方法。 */
export type PairingMethod = "same_xy_coordinate" | "row_index" | "mean_difference";

export type ParseStatus = "pending" | "parsed" | "failed" | "ignored";

export type PlanPriority = "high" | "normal" | "low";

export type PlanStatus = "draft" | "approved" | "running" | "completed" | "abandoned" | "archived";

export type ProcessLogStatus = "ok" | "partial" | "aborted" | "unknown";

/** 工艺模式。**本字段强制隔离两类绝不可合并的实验**： */
export type ProcessMode = "full_cycle" | "pre_expose_then_react" | "hf_only" | "o3_only" | "tma_only" | "plasma" | "deposition" | "other";

export type RecipeKind = "deposition" | "o3" | "hf" | "tma" | "plasma" | "full_cycle" | "purge";

export type RecipeStatus = "active" | "superseded" | "obsolete";

/** 派生结果类型。 */
export type ResultKind = "apparent_removal_R" | "delta_d" | "apparent_epc" | "rate" | "paired_point_delta" | "uniformity" | "fit_quality" | "other";

/** 数据集与样品的映射状态。 */
export type SampleMappingStatus = "resolved" | "unresolved" | "ambiguous";

/** 样品状态。 */
export type SampleStatus = "available" | "in_process" | "consumed" | "lost" | "quarantined";

/** 样品类型。 */
export type SampleType = "parent_wafer" | "full_wafer" | "coupon";

/** 排序方向。 */
export type SortOrder = "asc" | "desc";

/** 物种在体系中的角色；与 chemistry_species.role 的 CHECK 约束一致。 */
export type SpeciesRole = "precursor" | "reactant" | "purge" | "carrier" | "other";

/** 化学体系状态；与 chemistry_systems.status 的 CHECK 约束一致。 */
export type SystemStatus = "active" | "superseded" | "experimental";

export type ToolStatus = "active" | "maintenance" | "retired";

export type ToolType = "ellipsometer" | "thermal_ale" | "xps" | "rga" | "xrr" | "afm" | "sem" | "other";

/** 流转事件类型。 */
export type TransitionEventType = "cut" | "load" | "unload" | "measure" | "process" | "quarantine" | "dispose" | "receive";

/** admin：全部数据与用户/邀请管理；operator：自己拥有的批次/样品读写；viewer：自己拥有的批次/样品只读。后续科研权限属于 planned。 */
export type UserRole = "admin" | "operator" | "viewer";

/** 用户状态。`disabled` 用户无法登录，但历史记录保留。 */
export type UserStatus = "active" | "disabled";

export interface AIAccountRecovery {
  /** 服务器UTC无时区ISO时间字符串（存储元数据原值）。 */
  at: string;
  unknown_calls: number;
}

export interface AIChatRequest {
  request_id: string;
  conversation_id?: string | null;
  message: string;
  context?: AIContext | null;
}

/** AICompletedResult；详见AIResult重放语义。 */
export interface AICompletedResult {
  status: "completed";
  request_id: string;
  conversation_id: string | null;
  answer: string | null;
  sources: AISource[];
  tool_trace: AIToolTrace[];
  usage: AIRequestUsage;
  error: AIResultError | null;
  replayed: boolean;
  models?: AIModelMetadata[];
}

export interface AIConfig {
  enabled: boolean;
  provider_name: string;
  base_url: string;
  model: string;
  provider_options: Record<string, unknown>;
  currency: string;
  input_price_per_million: string;
  cached_input_price_per_million: string;
  output_price_per_million: string;
  monthly_budget: string;
  monthly_token_limit: number;
  daily_call_limit: number;
  user_daily_call_limit: number;
  admin_daily_call_limit: number;
  max_output_tokens: number;
  max_tool_rounds: number;
  key_configured: boolean;
  revision: number;
  configured: boolean;
  updated_at: string | null;
  discovered_models: string[];
  pricing_note: string;
  /** 每用户默认月预算，默认10，可为0，最大1000000，最多8位小数；响应Decimal字符串。 */
  user_monthly_budget: string;
  user_monthly_token_limit: number;
  /** 用户ID字符串到策略的映射。键必须规范正整数且≤9223372036854775807，最多10000项；仅admin可配置。 */
  user_policies: Record<string, AIUserPolicyView>;
}

/** 完整设置替换，非PATCH；api.deepseek.com（按hostname，不依赖模型名）必须显式provider_options={thinking:{type:disabled}}，否则422；旧空配置仍可GET读取修复，但test/chat在预留和外发前409阻止。其他服务商保留原默认。revision必填严格非负整数。先以空model保存端点/密钥，GET models发现后再选择model；修改端点或密钥会清空发现列表；修改端点时未提供新api_key则清除旧密钥。启用须有端点、发现过的model和密钥。预算不得低于已记账与预留量；活动账期不能换币种。 */
export interface AIConfigWrite {
  enabled?: boolean;
  provider_name?: string;
  base_url?: string;
  model?: string;
  provider_options?: Record<string, unknown>;
  currency?: string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  input_price_per_million?: number | string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  cached_input_price_per_million?: number | string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  output_price_per_million?: number | string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  monthly_budget?: number | string;
  monthly_token_limit?: number;
  daily_call_limit?: number;
  user_daily_call_limit?: number;
  admin_daily_call_limit?: number;
  max_output_tokens?: number;
  max_tool_rounds?: number;
  /** 仅写入，8..512个ASCII可见非空白字符；地址不变时null/省略保留旧密钥；base_url改变清除旧密钥，除非同时提供新api_key。clear_api_key清除；两者不能同时指定。响应绝不返回密钥或密文。 */
  api_key?: string | null;
  clear_api_key?: boolean;
  revision: number;
  /** 每用户默认月预算，默认10，可为0，最大1000000，最多8位小数；响应Decimal字符串。 */
  user_monthly_budget?: number | string;
  user_monthly_token_limit?: number;
  /** 用户ID字符串到策略的映射。键必须规范正整数且≤9223372036854775807，最多10000项；仅admin可配置。 */
  user_policies?: Record<string, AIUserPolicy>;
}

export interface AIContext {
  kind: "sample" | "batch" | "plan" | "process" | "measurement" | "none";
  id?: number | null;
}

/** AIFailedResult；详见AIResult重放语义。 恢复终态额外recovery，error=request_recovered；未派发预留释放，已测量保留真实量，unknown保守估算；对账后reconciliation_required=false。 */
export interface AIFailedResult {
  status: "failed";
  request_id: string;
  conversation_id: string | null;
  answer: null;
  sources: AISource[];
  tool_trace: AIToolTrace[];
  usage: AIRequestUsage;
  error: AIResultError | null;
  replayed: boolean;
  models?: AIModelMetadata[];
  recovery?: AIResultRecovery;
}

export interface AIModelCapabilities {
  anthropic_messages: { system_prompt_update: "leading-only" | "in-history" };
}

export interface AIModelEffort {
  supported_levels: string[];
  default_level?: string;
}

/** 供应商实际返回并经白名单裁剪的可选元数据；不根据模型ID推断能力。仅GET /ai/models发现结果，不注册科学分析工具。 */
export interface AIModelMetadata {
  id: string;
  name?: string;
  owned_by?: string;
  context_window?: number;
  max_output_tokens?: number;
  input_modalities?: string[];
  output_modalities?: string[];
  effort?: AIModelEffort;
  api_capabilities?: AIModelCapabilities;
}

/** 本人当前UTC月分账；无请求时记账与预留均为零，不暴露其他用户。 */
export interface AIMyUsage {
  period: string;
  scope: "current_user";
  currency: string;
  owner_user_id: number;
  charged_cost: string;
  charged_tokens: number;
  reserved_cost: string;
  reserved_tokens: number;
  monthly_budget: string;
  monthly_token_limit: number;
}

export interface AIOriginalUsage {
  prompt_tokens: number;
  completion_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  charged_tokens: number;
  charged_cost: string;
}

/** AIPendingResult；详见AIResult重放语义。 */
export interface AIPendingResult {
  status: "pending";
  request_id: string;
  conversation_id: string | null;
  answer: null;
  sources: AISource[];
  tool_trace: AIToolTrace[];
  usage: null;
  error: AIResultError;
}

/** 本人有效策略；research_ai_allowed为账户策略判断结果，不表示全局AI已启用或已配置。management默认拒绝科研AI；testing默认拒绝外发；需admin user_policies显式true允许。testing外发拒绝优先于科研AI拒绝。 */
export interface AIPolicy {
  account_purpose: AccountPurpose;
  research_ai_allowed: boolean;
  denial_reason: null | "account_purpose_invalid" | "testing_external_send_denied" | "research_ai_denied" | null;
  external_send_allowed: boolean;
  monthly_budget: string;
  monthly_token_limit: number;
}

/** 仅admin；终态且usage_estimated=true的未知费用可对账一次。同reconciliation_id与完全相同submission重放幂等；同ID不同证据或第二个ID均409。reason/evidence去空白后至少10字符，不自动trim。cache hit不得超过prompt。 */
export interface AIReconcileRequest {
  reconciliation_id: string;
  reason: string;
  evidence: string;
  actual_prompt_tokens: number;
  actual_completion_tokens: number;
  actual_cache_hit_tokens?: number;
  /** 非负有限金额，最大1000000，最多8位小数；接受JSON数值或Decimal字符串。 */
  actual_cost: number | string;
}

export interface AIReconciliationAudit {
  reconciliation_id: string;
  at: string;
  actor_user_id: number;
  submission: AIReconcileRequest;
  original_usage: AIOriginalUsage;
  original_result_usage: AIRequestUsage | null;
}

export interface AIRecoverResult {
  recovered_request_ids: string[];
  recovered_count: number;
}

export type AIRequestAccount = AIRequestAccountOwner | AIRequestAccountAdmin;

/** 仅admin全部请求账目；额外owner/账期/原始预留及一次对账审计。reserved_*为该请求原始预留快照，终态不代表仍有活动预留；活动预留查usage。 */
export interface AIRequestAccountAdmin {
  request_id: string;
  conversation_id: string | null;
  purpose: "chat" | "test" | "models";
  status: AIRequestStatus;
  created_at: string;
  finished_at: string | null;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
  dispatched_calls: number;
  charged_tokens: number;
  charged_cost: string;
  usage_estimated: boolean;
  recovery: AIAccountRecovery | null;
  reconciled: boolean;
  owner_user_id: number;
  period: string;
  reserved_tokens: number;
  reserved_cost: string;
  reconciliation_history: AIReconciliationAudit[];
}

/** 普通登录用户本人账目。无prompt、answer、内部execution token或证据；recovery元数据不含原执行token。lease/heartbeat为UTC无时区ISO字符串或null。 */
export interface AIRequestAccountOwner {
  request_id: string;
  conversation_id: string | null;
  purpose: "chat" | "test" | "models";
  status: AIRequestStatus;
  created_at: string;
  finished_at: string | null;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
  dispatched_calls: number;
  charged_tokens: number;
  charged_cost: string;
  usage_estimated: boolean;
  recovery: AIAccountRecovery | null;
  reconciled: boolean;
}

/** 最近100条，created_at/request_id倒序；无分页及查询参数。普通用户本人；admin全用户。GET同时惰性恢复过期请求。 */
export interface AIRequestList {
  requests: AIRequestAccount[];
  limit: number;
}

export interface AIRequestUsage {
  prompt_tokens: number;
  completion_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  charged_tokens: number;
  provider_calls: number;
  charged_cost: string;
  estimated: boolean;
  currency: string;
}

/** pending: answer/usage=null，sources/trace空，error=request_in_progress，不含replayed。首次完成/失败含replayed=false和usage；models发现成功额外models。已结算原ID查询不外发、不重复计费；重新核验当前session、配置revision及全部证据，一致则返回原答案/来源/trace并replayed=true，否则status=failed、隐藏答案/来源/trace并给出authorization_changed、configuration_changed或evidence_unavailable。旧版本无证据请求保守隐藏。失败可有已执行工具trace，成功通常error=null。 恢复终态额外recovery，error=request_recovered；未派发预留释放，已测量保留真实量，unknown保守估算；对账后reconciliation_required=false。 */
export interface AIResult {
  status: AIRequestStatus;
  request_id: string;
  conversation_id: string | null;
  answer: string | null;
  sources: AISource[];
  tool_trace: AIToolTrace[];
  usage: AIRequestUsage | null;
  error: AIResultError | null;
  replayed?: boolean;
  models?: AIModelMetadata[];
  recovery?: AIResultRecovery;
}

/** 请求级错误，位于HTTP200 data.error；包括request_in_progress、evidence_unavailable、configuration_changed、authorization_changed、ai_unavailable及provider/工具/限制错误。 恢复/租约错误含request_recovered、execution_fenced、turn_time_limit、accounting_period_changed；错误code保持开放字符串以容纳服务商安全错误。 provider HTTP401=provider_auth_failed、402=provider_insufficient_balance、403=provider_permission_denied、400/422=provider_parameter_invalid、429=provider_rate_limited；这些明确拒绝不估算收费，不重试。5xx=provider_unavailable保守未知。finish_reason=length为provider_output_truncated，content_filter为provider_content_filtered，aborted/insufficient_system_resource为provider_generation_interrupted；隐藏截断答案，保留已测usage。均在HTTP200 data.error中，非本服务HTTP状态。 */
export interface AIResultError {
  code: string;
  message: string;
}

export interface AIResultRecovery {
  recovered: true;
  unknown_calls: number;
  reconciliation_required: boolean;
}

export interface AISettings {
  enabled?: boolean;
  provider_name?: string;
  base_url?: string;
  model?: string;
  provider_options?: Record<string, unknown>;
  currency?: string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  input_price_per_million?: number | string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  cached_input_price_per_million?: number | string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  output_price_per_million?: number | string;
  /** 接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。 */
  monthly_budget?: number | string;
  monthly_token_limit?: number;
  daily_call_limit?: number;
  user_daily_call_limit?: number;
  admin_daily_call_limit?: number;
  max_output_tokens?: number;
  max_tool_rounds?: number;
  /** 每用户默认月预算，默认10，可为0，最大1000000，最多8位小数；响应Decimal字符串。 */
  user_monthly_budget?: number | string;
  user_monthly_token_limit?: number;
  /** 用户ID字符串到策略的映射。键必须规范正整数且≤9223372036854775807，最多10000项；仅admin可配置。 */
  user_policies?: Record<string, AIUserPolicy>;
}

export interface AISource {
  kind: AISourceKind;
  id: number;
  /** 服务器生成内部UI链接；transition使用sample_id */
  href: string;
}

export interface AIStatus {
  enabled: boolean;
  configured: boolean;
}

export interface AITestRequest {
  request_id: string;
}

export interface AIToolTrace {
  tool: "search_records" | "record_detail" | "sample_timeline" | "quality_hints" | "unsupported";
  status: "completed" | "denied";
  sources: AISource[];
  result_bytes: number;
  read_only: true;
  /** 当前记录服务器预查 / 先前计划按当前权限重执行 / 本轮模型实际工具调用。旧持久化trace可能缺失。 */
  origin?: "current_context" | "prior_plan" | "model";
}

export type AITurnResult = AIPendingResult | AICompletedResult | AIFailedResult;

/** admin当前UTC月全用户账本；含预留与估算，非供应商账单。过期租约惰性恢复；未知已派发费用保守保留，管理员凭证据对账。 */
export interface AIUsageSummary {
  request_count: number;
  estimated_requests: number;
  pending_requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  provider_calls: number;
  charged_tokens: number;
  reserved_tokens: number;
  monthly_token_limit: number;
  period: string;
  scope: "all_users";
  currency: string;
  charged_cost: string;
  reserved_cost: string;
  monthly_budget: string;
  /** 当月有请求的用户分账，按owner_user_id升序；无请求用户不出现。 */
  users: AIUserUsage[];
}

export interface AIUserPolicy {
  /** null或省略继承用户默认额度。 */
  monthly_budget?: number | string | null;
  /** null或省略继承用户默认额度。 */
  monthly_token_limit?: number | null;
  /** null或省略按账户用途取默认值；management科研AI默认拒绝，只有admin显式true允许。 */
  research_ai_allowed?: boolean | null;
  /** null或省略按账户用途取默认值；testing默认拒绝外发，只有admin显式true允许，用户同意不能覆盖。 */
  external_send_allowed?: boolean | null;
}

export interface AIUserPolicyView {
  monthly_budget?: string | null;
  /** null或省略继承用户默认额度。 */
  monthly_token_limit?: number | null;
  /** null或省略按账户用途取默认值；management科研AI默认拒绝，只有admin显式true允许。 */
  research_ai_allowed?: boolean | null;
  /** null或省略按账户用途取默认值；testing默认拒绝外发，只有admin显式true允许，用户同意不能覆盖。 */
  external_send_allowed?: boolean | null;
}

/** 按owner_user_id的当前月分账；已记账包含恢复与对账，预留仅累计pending；预算为覆盖后有效额度。 */
export interface AIUserUsage {
  owner_user_id: number;
  charged_cost: string;
  charged_tokens: number;
  reserved_cost: string;
  reserved_tokens: number;
  monthly_budget: string;
  monthly_token_limit: number;
}

export interface AnalysisCalculate {
  after_index?: number | null;
  before_index?: number | null;
  confirm_pair?: boolean;
  selection?: AnalysisSelection;
  sources: AnalysisSource[];
}

export interface AnalysisMetric {
  count: number;
  excluded_nonfinite_or_missing: number;
  mean?: string;
  min?: string;
  max?: string;
  sd_sample?: string | null;
  sd_population?: string;
}

export interface AnalysisPair {
  pairing_method: "same_xy_coordinate";
  direction: "after - before";
  model_consistent: true;
  paired_point_count: number;
  unmatched_before: number;
  unmatched_after: number;
  ineligible_before: number;
  ineligible_after: number;
  mean_delta_nm: string;
  mean_before_nm: string;
  mean_after_nm: string;
  sd_delta_nm: string | null;
  observation: "increase" | "decrease" | "unchanged";
  interpretation: string;
  points: AnalysisPairPoint[];
}

export interface AnalysisPairPoint {
  x_mm: string;
  y_mm: string;
  before_nm: string;
  after_nm: string;
  delta_nm: string;
  thickness_nm: string;
  mse: null;
  gof: null;
  before_key: string;
  after_key: string;
}

export interface AnalysisPoint {
  x_mm: string | null;
  y_mm: string | null;
  thickness_nm: string | null;
  mse: string | null;
  gof: string | null;
  point_no: number | null;
  source_row: number | null;
  source_file_id: number | null;
  point_id: number | null;
  outlier_note: string | null;
  source_sheet: string | null;
  source_cell: string | null;
  key: string;
  included: boolean;
  is_outlier: boolean;
}

export interface AnalysisReadonlyToolMetadata {
  name: "scientific_analysis";
  readonly: true;
  external_raw_data: false;
  function: "app.scientificanalysis.calculate";
  request_schema: Record<string, unknown>;
  response_projection: string[];
  requires_authenticated_scope: true;
  live_ai_registered: false;
}

export interface AnalysisRecordedConditions {
  process_id: number;
  row_version: number;
  process_code: string;
  r1_temp_c: string | null;
  r2_temp_c: string | null;
  o3_pre_duration_s: string | null;
  full_ale_cycles: number | null;
  hf_tma_repeats: number | null;
  o3_pre_cycles: number | null;
  recorded_total_cycles: number | null;
}

export interface AnalysisResult {
  analysis_version: string;
  decimal_precision: number;
  rounding: "ROUND_HALF_EVEN";
  request: AnalysisCalculate;
  series: AnalysisSeries[];
  pair: AnalysisPair | null;
  persisted: false;
  limits: { max_sources: number; max_points: number };
  scientific_sources_modified: false;
  result_sha256: string;
}

export interface AnalysisSave {
  calculation: AnalysisCalculate;
  label: string;
}

export interface AnalysisSaveResult {
  result_id: number;
  persisted: true;
  result_sha256: string;
  scientific_sources_modified: false;
}

export interface AnalysisSavedRecord {
  label: string;
  request: AnalysisCalculate;
  result_sha256: string;
  analysis_version: string;
  sources: AnalysisSourceMetadata[];
  statistics: AnalysisStatistics[];
  pair: { pairing_method: "same_xy_coordinate"; direction: "after - before"; model_consistent: true; paired_point_count: number; unmatched_before: number; unmatched_after: number; ineligible_before: number; ineligible_after: number; mean_delta_nm: string; mean_before_nm: string; mean_after_nm: string; sd_delta_nm: string | null; observation: "increase" | "decrease" | "unchanged"; interpretation: string } | {  };
}

export interface AnalysisSavedResult {
  result_id: number;
  is_valid: boolean;
  computed_at: string;
  record: AnalysisSavedRecord;
  scientific_sources_modified: false;
  invalid_reasons: ("source_or_result_changed" | "measurement_not_current_or_excluded" | "source_unavailable_or_changed" | "record_invalidated")[];
  recomputed_result_sha256: string | null;
}

export interface AnalysisSelection {
  excluded_points?: string[];
  include_outliers?: boolean;
  reason?: string;
}

export interface AnalysisSeries {
  source: AnalysisSourceMetadata;
  points: AnalysisPoint[];
  statistics: AnalysisStatistics;
  raw_count: number;
  included_count: number;
  excluded_count: number;
  mapping: { available: boolean; actual_xy_point_count: number; interpolation_available: false; note: string };
  warnings: string[];
}

export interface AnalysisSource {
  block_index?: number;
  confirm_associations?: boolean;
  expected_row_version?: number | null;
  id: number;
  kind: "measurement" | "import_item";
  optical_model_id?: number | null;
  sample_id?: number | null;
  stage?: "initial" | "after_o2_plasma" | "after_o3_pre" | "after_ale" | "after_hf_only" | "after_o3_only" | "intermediate" | "final" | "other" | null;
  stage_seq?: number | null;
}

export interface AnalysisSourceMetadata {
  kind: "measurement" | "import_item";
  id: number;
  block_index: number;
  row_version: number;
  label: string;
  sample_id: number | null;
  stage_seq: number | null;
  optical_model_id: number | null;
  cumulative_cycles: number | null;
  process_id?: number | null;
  source_file_id?: number | null;
  import_item_id?: number | null;
  stage: string | null;
  parser: string | null;
  parser_version: string | null;
  sha256?: string | null;
  quality_flag?: string | null;
  is_current?: boolean;
  recorded_conditions?: AnalysisRecordedConditions | null;
  associations_source?: "user_confirmed_preview" | "unknown";
  locator?: unknown;
  formal_measurements_written?: false;
  model_parameter_columns: unknown[];
  units: { thickness_nm: string; x_mm: string; y_mm: string; mse: string; gof: string };
  points_sha256: string;
  optical_model: Record<string, unknown> | null;
  /** Only present when model applicable_batch_id requires sample batch validation. */
  sample_dependency?: { sample_id: number; batch_id: number };
}

export interface AnalysisStatistics {
  point_count: number;
  includes_outliers: boolean;
  sd_convention: { sample: string; population: string };
  decimal_precision: number;
  rounding: "ROUND_HALF_EVEN";
  db_write_policy: string;
  thickness_nm: AnalysisMetric;
  mse: AnalysisMetric;
  gof: AnalysisMetric;
}

/** 附件登记（图、Origin 工程、报告等非结构化产出）。 */
export interface Attachment {
  attachment_id: number;
  file_sha256?: string | null;
  file_name: string;
  rel_path?: string | null;
  attachment_type: AttachmentType;
  entity_type?: EntityType;
  entity_id?: number | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  description?: string | null;
  uploaded_by?: number | null;
  created_at: string;
}

export interface AttachmentCreate {
  file_sha256?: string;
  file_name: string;
  rel_path?: string;
  attachment_type: AttachmentType;
  entity_type?: EntityType;
  entity_id?: number;
  mime_type?: string;
  size_bytes?: number;
  description?: string;
}

/** 操作审计记录。用于追溯"这个数值是谁改的、什么时候改的"。 */
export interface AuditLog {
  audit_id: number;
  user_id?: number | null;
  user?: UserBrief;
  action: AuditAction;
  /** 被操作实体类型 */
  entity_type: string;
  entity_id?: number | null;
  /** 被修改的字段名（update 时有值） */
  field_name?: string | null;
  old_value?: string | null;
  new_value?: string | null;
  /** 客户端标识（IP / UA） */
  client_info?: string | null;
  occurred_at: string;
}

/** 沉积批次。**批次是数据可比性的强制隔离边界**—— */
export interface Batch {
  batch_id: number;
  /** 批次编码，全局唯一 */
  batch_code: string;
  batch_name: string;
  material: string;
  wafer_size?: string | null;
  /** 标称厚度（nm）。为 string 以避免浮点精度损失。 */
  nominal_thickness_nm?: string | null;
  deposit_recipe_id?: number | null;
  deposit_date?: string | null;
  /** PECVD 设定温度（℃） */
  deposit_set_temp_c?: string | null;
  /** PECVD 实测温度（℃）。**必须与设定值分开记录**—— */
  deposit_actual_temp_c?: string | null;
  /** 沉积气体流量，如 {"SiH4": 20, "NH3": 100, "N2": 200} */
  deposit_gas_flows?: Record<string, unknown> | null;
  source_zip?: string | null;
  /** 原始压缩包 SHA-256，用于溯源校验 */
  source_zip_sha256?: string | null;
  /** 是否为已知异常批次 */
  anomaly_flag: boolean;
  /** 异常描述。**禁止据文件名断言故障机理**（ISS-02）。 */
  anomaly_note?: string | null;
  owner_user_id?: number | null;
  status: BatchStatus;
  notes?: string | null;
  created_at: string;
  updated_at?: string;
  /** 服务端并发版本，每次更新递增。 */
  readonly row_version: number;
  /** 独立归档时间；null 表示未归档，不改原有科学状态。 */
  readonly archived_at?: string | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
}

export interface BatchCodeStatus {
  available: boolean;
  restricted?: boolean;
  namespace?: string;
  message: string;
  /** 仅调用者可见时提供批次身份；私有冲突不返回此字段。 */
  existing?: Record<string, unknown>;
  can_rename?: boolean;
  lifecycle?: Record<string, unknown>;
}

export interface BatchCodeUpdate {
  batch_code: string;
  expected_row_version: number;
  reason: string;
}

export interface BatchCreate {
  batch_code: string;
  batch_name: string;
  material?: string;
  wafer_size?: string;
  nominal_thickness_nm?: string;
  deposit_recipe_id?: number;
  deposit_date?: string;
  deposit_set_temp_c?: string;
  deposit_actual_temp_c?: string;
  deposit_gas_flows?: Record<string, unknown>;
  source_zip?: string;
  source_zip_sha256?: string;
  anomaly_flag?: boolean;
  anomaly_note?: string;
  status?: BatchStatus;
  notes?: string;
}

/** 批量创建样品中的单个样品；批次来自路径，不在请求体中。 */
export interface BatchItem {
  sample_code: string;
  sample_type?: SampleType;
  display_label?: string | null;
  nominal_thickness_nm?: string | null;
  size_desc?: string | null;
  cut_position?: string | null;
  surface_state?: string | null;
  pre_treatment?: string | null;
  status?: SampleStatus;
  exclude_from_analysis?: boolean;
  exclude_reason?: string | null;
  notes?: string | null;
}

/** 一次绑定 1–50 个样品到同一执行；公共附加字段对每条相同。 */
export interface BatchLinkCreate {
  sample_ids: number[];
  chamber_position?: string | null;
  o3_pre_cycles?: number | null;
  hf_tma_repeats?: number | null;
  full_ale_cycles?: number | null;
  is_control?: boolean;
  sample_role_note?: string | null;
}

/** 在一个批次下原子创建 1–50 个样品；sample_code 必填且全局唯一，重复或校验失败整批回滚。 */
export interface BatchSampleCreate {
  /** 可选创建意图键；相同键与内容重试返回原样品，修改内容则冲突。 */
  request_key?: string | null;
  /** 可选；必须属于该批次且为母片/整片。 */
  parent_sample_id?: number | null;
  items: BatchItem[];
}

/** 批次更新（部分更新，仅传需修改字段） */
export interface BatchUpdate {
  batch_name?: string;
  wafer_size?: string | null;
  nominal_thickness_nm?: string | null;
  deposit_set_temp_c?: string | null;
  deposit_actual_temp_c?: string | null;
  deposit_gas_flows?: Record<string, unknown> | null;
  anomaly_flag?: boolean;
  anomaly_note?: string | null;
  status?: BatchStatus;
  notes?: string | null;
  /** 可选；提供时必须匹配当前 row_version，否则返回 409。省略时保持原有更新行为。 */
  expected_row_version?: number;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

/** 预置图表模板。前端可直接按模板渲染，无需自行拼装数据结构。 */
export interface ChartTemplate {
  template_code: string;
  name: string;
  description?: string | null;
  chart_type: ChartType;
  /** 数据来源标识（对应各数据接口） */
  data_source: string;
  /** 该模板必填的参数名 */
  required_params?: string[];
}

/** 化学体系下的物种（前驱体/反应物/吹扫/载气等）。 */
export interface ChemistrySpecies {
  readonly species_id: number;
  readonly system_id: number;
  species_code: string;
  species_name: string;
  formula?: string | null;
  role: SpeciesRole;
  default_unit?: string | null;
  notes?: string | null;
  readonly created_at?: string;
}

/** 可复用步骤模板；steps 为有序 JSON 数组，至少 1 条。 */
export interface ChemistryStepTemplate {
  readonly template_id: number;
  readonly system_id: number;
  template_code: string;
  template_name: string;
  description?: string | null;
  steps: TemplateStep[];
  readonly created_at?: string;
  readonly updated_at?: string;
}

/** 通用化学体系。详情响应额外内嵌 species[]、templates[] 与 owner。 */
export interface ChemistrySystem {
  readonly system_id: number;
  system_code: string;
  system_name: string;
  description?: string | null;
  status: SystemStatus;
  readonly owner_user_id?: number | null;
  /** 服务端并发版本；更新体系或其子记录时递增。 */
  readonly row_version: number;
  readonly created_at?: string;
  readonly updated_at?: string;
  species?: ChemistrySpecies[];
  templates?: ChemistryStepTemplate[];
  owner?: UserBrief | null;
}

/** 创建化学体系；owner_user_id 由服务端确定。 */
export interface ChemistrySystemCreate {
  system_code: string;
  system_name: string;
  description?: string | null;
  status?: SystemStatus;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）。 */
export interface ChemistrySystemUpdate {
  system_name?: string | null;
  description?: string | null;
  status?: SystemStatus;
  /** 可选且可为 null；非 null 时匹配当前 row_version，否则 409。 */
  expected_row_version?: number | null;
}

export interface CreateInvitationRequest {
  role?: InvitationRole;
  expires_in_hours?: number;
  account_purpose?: OrdinaryAccountPurpose;
}

export type CreateInvitationResponse = Invitation & { invite_code: string };

/** 仅admin创建用户；role默认viewer、account_purpose默认research。创建admin且省略account_purpose时自动management；显式不匹配返回422。 */
export interface CreateUserRequest {
  /** 登录名。字母开头，可含字母数字与 `_ . -` */
  username: string;
  /** 密码至少 8 位，服务端使用 Argon2id 哈希存储。 */
  password: string;
  /** 显示名 */
  display_name?: string;
  email?: string;
  role?: UserRole;
  status?: UserStatus;
  /** 备注 */
  notes?: string | null;
  account_purpose?: AccountPurpose;
}

/** 当前用户、实际授权权限与数据范围。前端仅用于界面显示，服务端独立执行权限及所有权过滤；未实现共享。 */
export interface CurrentUser {
  user: User;
  /** 权限标识列表（见 docs/permissions.md） */
  permissions: string[];
  /** 保留all/own：all为管理员全局范围；own为本人范围；admin_global_scope是独立可选布尔约定。 */
  data_scope: "all" | "own";
  environment: Environment;
  /** 管理员全局数据范围标志；true表示全局，false表示本人。可选扩展字段，按本字段约定；不改变data_scope现有枚举。 */
  admin_global_scope?: boolean;
}

/** 单个自定义参数项；value 为数字时统一按字符串存储与回传。 */
export interface CustomParameter {
  value?: string | number | null;
  unit?: string | null;
  note?: string | null;
}

/** 自定义参数映射；最多 32 项，键为 1–64 位字母数字下划线。 */
export type CustomParameters = Record<string, CustomParameter>;

export interface DashboardRecentActivity {
  recent_samples?: SampleBrief[];
  recent_processes?: ProcessBrief[];
  recent_measurements?: MeasurementBrief[];
}

export interface DashboardRecentData {
  generated_at: string;
  items: DashboardRecentDataItem[];
}

export type DashboardRecentDataItem = DashboardRecentImportJob | DashboardRecentMeasurement | DashboardRecentSourceFile;

export type DashboardRecentExperimentItem = DashboardRecentPlan | DashboardRecentProcess;

export interface DashboardRecentExperiments {
  generated_at: string;
  items: DashboardRecentExperimentItem[];
}

export interface DashboardRecentImportJob {
  entity_id: number;
  code: string | null;
  title: string;
  status: string;
  hint: string | null;
  occurred_at: string | null;
  kind: "import_job";
  path: "/imports";
  query: { job: number };
}

export interface DashboardRecentMeasurement {
  entity_id: number;
  code: string | null;
  title: string;
  status: string;
  hint: string | null;
  occurred_at: string | null;
  kind: "measurement";
  path: "/measurements";
  query: { id: number };
  stage: MeasurementStage;
  sample_id: number;
}

export interface DashboardRecentPlan {
  entity_id: number;
  code: string;
  title: string;
  status: string;
  batch_id: number | null;
  updated_at: string | null;
  can_continue: boolean;
  continue_label: string;
  kind: "plan";
  path: "/plans";
  query: { plan_id: number };
  continue_path: "/plans" | "/processes";
  continue_query: { plan_id: number } | { create: "1"; plan_id: number; batch_id?: number };
}

export interface DashboardRecentProcess {
  entity_id: number;
  code: string;
  title: string;
  status: string;
  batch_id: number | null;
  updated_at: string | null;
  can_continue: boolean;
  continue_label: string;
  kind: "process";
  plan_id: number | null;
  archived: boolean;
  path: "/processes";
  query: { process_id: number };
  continue_path: "/processes";
  continue_query: { process_id: number };
}

export interface DashboardRecentSourceFile {
  entity_id: number;
  code: string | null;
  title: string;
  status: string;
  hint: string | null;
  occurred_at: string | null;
  kind: "source_file";
  path: "/source-files";
  query: { id: number };
  size_bytes: number | null;
}

/** 首页概况统计。 */
export interface DashboardSummary {
  generated_at: string;
  batch_count?: number;
  sample_count?: number;
  /** 被排除出分析的样品数 */
  sample_excluded_count?: number;
  process_count?: number;
  /** 当前有效测量数（不含被取代） */
  measurement_count?: number;
  derived_result_count?: number;
  source_file_count?: number;
  instrument_dataset_count?: number;
  /** 未关闭问题数 */
  open_issue_count?: number;
  /** 高优先级未关闭问题数 */
  open_issue_high_count?: number;
  finding_count?: number;
  /** 仍为机理假设（未证实）的结论数 */
  finding_hypothesis_count?: number;
}

export interface DashboardTodo {
  generated_at: string;
  total: number;
  counts: { plan_without_process: number; process_log: number; import_pending: number; import_failure: number; measurement_review: number; issue: number };
  items: DashboardTodoItem[];
}

export interface DashboardTodoImportFailure {
  kind: "import_failure";
  entity_id: number;
  code: string | null;
  title: string;
  detail: string;
  status: string;
  updated_at: string | null;
  path: "/imports";
  query: { job: number };
}

export interface DashboardTodoImportPending {
  kind: "import_pending";
  entity_id: number;
  code: string | null;
  title: string;
  detail: string;
  status: string;
  updated_at: string | null;
  path: "/imports";
  query: { job: number };
}

export interface DashboardTodoIssue {
  kind: "issue";
  entity_id: number;
  code: string | null;
  title: string;
  detail: string;
  status: string;
  updated_at: string | null;
  path: null;
  query: null;
  severity: string;
}

export type DashboardTodoItem = DashboardTodoPlanWithoutProcess | DashboardTodoProcessLog | DashboardTodoImportPending | DashboardTodoImportFailure | DashboardTodoMeasurementReview | DashboardTodoIssue;

export interface DashboardTodoMeasurementReview {
  kind: "measurement_review";
  entity_id: number;
  code: string | null;
  title: string;
  detail: string;
  status: string;
  updated_at: string | null;
  path: "/measurements";
  query: { id: number };
}

export interface DashboardTodoPlanWithoutProcess {
  kind: "plan_without_process";
  entity_id: number;
  code: string | null;
  title: string;
  detail: string;
  status: string;
  updated_at: string | null;
  path: "/plans";
  query: { plan_id: number };
}

export interface DashboardTodoProcessLog {
  kind: "process_log";
  entity_id: number;
  code: string | null;
  title: string;
  detail: string;
  status: string;
  updated_at: string | null;
  path: "/processes";
  query: { process_id: number };
}

export interface DashboardUpcomingPlan {
  plan_id?: number;
  plan_code?: string;
  title?: string;
  planned_start?: string | null;
  planned_end?: string | null;
  priority?: PlanPriority;
  status?: PlanStatus;
  owner?: UserBrief;
}

/** 数据质量提示。服务端主动识别的问题，例如： */
export interface DataQualityAlert {
  alert_type: "cross_model_comparison" | "high_mse_measurement" | "superseded_baseline" | "unresolved_instrument_mapping" | "excluded_sample_used" | "missing_intermediate_measurement" | "model_inconsistent_derived";
  severity: "high" | "medium" | "low";
  /** 面向用户的说明（中文） */
  message: string;
  entity_type?: EntityType;
  entity_id?: number | null;
  /** 实体编码，便于前端跳转 */
  entity_code?: string | null;
}

/** 派生分析结果。 */
export interface DerivedResult {
  result_id: number;
  result_code: string;
  result_kind: ResultKind;
  sample_id: number;
  sample_code?: string | null;
  before_measurement_id?: number | null;
  after_measurement_id?: number | null;
  process_id?: number | null;
  /** 数值（单位见 value_unit） */
  value_nm?: string | null;
  value_unit?: "nm" | "A_per_cycle" | "pct" | null | null;
  /** 空间 SD（**非独立重复误差**） */
  value_sd_nm?: string | null;
  /** 计算速率所用循环基数 */
  cycles_basis?: number | null;
  pairing_method?: PairingMethod;
  paired_point_count?: number | null;
  /** 前后测量是否使用同一光学模型。 */
  model_consistent?: boolean | null;
  /** 由服务端根据 model_consistent 自动生成的警告文字 */
  readonly model_warning?: string | null;
  /** 结果是否有效。 */
  is_valid: boolean;
  evidence_level: EvidenceLevel;
  /** 计算说明与限制 */
  computation_note?: string | null;
  computed_at?: string | null;
  computed_by?: string | null;
  created_at?: string;
}

export interface DerivedResultCreate {
  result_code: string;
  result_kind: ResultKind;
  sample_id: number;
  before_measurement_id?: number;
  after_measurement_id?: number;
  process_id?: number;
  value_nm?: string;
  value_unit?: "nm" | "A_per_cycle" | "pct";
  value_sd_nm?: string;
  cycles_basis?: number;
  pairing_method?: PairingMethod;
  paired_point_count?: number;
  evidence_level?: EvidenceLevel;
  computation_note?: string;
  computed_by?: string;
}

export type DerivedResultDetail = DerivedResult & { before_measurement?: MeasurementBrief; after_measurement?: MeasurementBrief; sample?: SampleBrief; process?: ProcessBrief };

/** 部署环境标识，只由ALE_ENVIRONMENT、ALE_ENVIRONMENT_LABEL、ALE_INSTANCE_ID配置提供，不能从账户用途推断。 */
export interface Environment {
  name: "production" | "testing";
  label: string;
  instance_id: string;
}

/** 实验计划。位于实验执行之前，一个计划可派生多个执行。 */
export interface ExperimentPlan {
  readonly plan_id: number;
  plan_code: string;
  title: string;
  /** 实验目的 */
  objective?: string | null;
  /** 待验证假设 */
  hypothesis?: string | null;
  /** 变量设计与对照组设置 */
  design_note?: string | null;
  planned_start?: string | null;
  planned_end?: string | null;
  priority: PlanPriority;
  status: PlanStatus;
  owner_user_id?: number | null;
  batch_id?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at?: string;
  /** 服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。 */
  readonly row_version: number;
  /** 保存后step_id为真实数据库ID；空值表示旧记录无布局。 */
  process_flow?: ProcessFlow | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
  readonly archive_previous_status: string | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ExperimentPlanCreate {
  plan_code: string;
  title: string;
  objective?: string | null;
  hypothesis?: string | null;
  design_note?: string | null;
  planned_start?: string | null;
  planned_end?: string | null;
  priority?: "high" | "normal" | "low";
  status?: "draft" | "approved" | "running" | "completed" | "abandoned";
  batch_id?: number | null;
  notes?: string | null;
}

export type ExperimentPlanDetail = ExperimentPlan & { owner: UserBrief | null; batch: Batch | null; processes: ProcessDetail[]; process_count: number; steps: PlanStep[] };

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ExperimentPlanUpdate {
  title?: string;
  objective?: string | null;
  hypothesis?: string | null;
  design_note?: string | null;
  planned_start?: string | null;
  planned_end?: string | null;
  priority?: "high" | "normal" | "low";
  status?: "draft" | "approved" | "running" | "completed" | "abandoned";
  batch_id?: number | null;
  notes?: string | null;
  /** 可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。 */
  expected_row_version?: number | null;
}

/** 研究结论台账。**强制区分实测观察与机理假设。** */
export interface Finding {
  finding_id: number;
  finding_code: string;
  statement: string;
  evidence_level: EvidenceLevel;
  /** 支撑样品数。 */
  support_sample_count?: number | null;
  is_confirmed: boolean;
  /** 适用边界与禁止外推说明 */
  scope_note?: string | null;
  created_by?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface FindingCreate {
  finding_code: string;
  statement: string;
  evidence_level: EvidenceLevel;
  support_sample_count?: number;
  is_confirmed?: boolean;
  scope_note?: string;
}

export interface FindingUpdate {
  statement?: string;
  evidence_level?: EvidenceLevel;
  support_sample_count?: number;
  is_confirmed?: boolean;
  scope_note?: string;
}

export interface FlowNode {
  children?: FlowNode[];
  id: string;
  kind: "group" | "step";
  name?: string | null;
  repeat?: number | null;
  step_id?: number | string | null;
}

export interface GridStep {
  key: string;
  parameter_snapshot: ParameterSnapshot;
  plan_step_id?: number | null;
  step_id?: number | null;
  step_kind: string;
  step_name?: string | null;
}

export interface ImportAssociationOptions {
  sample: Sample;
  processes: ImportProcessOption[];
  baseline_measurements: ImportBaselineOption[];
}

export interface ImportBaselineOption {
  measurement_id: number;
  measurement_code: string;
  stage: MeasurementStage;
  stage_seq: number;
  optical_model_id: number | null;
}

/** import 必须显式选择 sample/stage（stage_seq 留空由系统在样品锁下分配） 并确认单位与关联；process 必须绑定到 sample。重复内容必须 confirm_duplicate=true 且提供 duplicate_reason；不自动 supersede。配对基线必须同样品且 current，initial 不可指定基线；模型不一致只给 warning。original_only 可不关联样品；有关联时也必须确认。skip 不建科学记录。 */
export interface ImportChoice {
  item_id: number;
  action: "import" | "original_only" | "skip";
  sample_id?: number | null;
  process_id?: number | null;
  optical_model_id?: number | null;
  /** 用户有依据填写的实际测量时间；未知留空，不取上传时间。 */
  measured_at?: string | null;
  /** 本次提交中明确选择的同样品单块初始测量文件项；与 pair_measurement_id 互斥。 */
  pair_item_id?: number;
  pair_measurement_id?: number | null;
  stage?: "initial" | "after_o2_plasma" | "after_o3_pre" | "after_ale" | "after_hf_only" | "after_o3_only" | "intermediate" | "final" | "other" | null;
  stage_seq?: number | null;
  measurement_code?: string | null;
  confirm_units?: boolean;
  confirm_associations?: boolean;
  confirm_duplicate?: boolean;
  duplicate_reason?: string | null;
  notes?: string | null;
}

/** item_id 不得重复；按选中项原子确认；未选项 pending；相同规范化请求含版本号重放已保存结果，不同旧版本返回409。 */
export interface ImportConfirmation {
  expected_row_version: number;
  items: ImportChoice[];
}

export interface ImportConfirmationRecord {
  readonly job_id: number;
  readonly confirmation_hash: string;
  readonly result: ImportConfirmationResult;
}

export interface ImportConfirmationResult {
  job_id: number;
  row_version: number;
  status: ImportJobStatus;
  pending_count: number;
  items: ImportItemResult[];
}

export interface ImportDeleteResult {
  job_id: number;
  deleted: true;
  cleanup: string;
}

export interface ImportItem {
  readonly item_id: number;
  readonly job_id: number;
  readonly filename: string;
  readonly sha256: string;
  readonly parse_result: ImportParseResult;
  readonly confirmation: ImportChoice | null;
  readonly status: "pending" | "imported" | "original_only" | "skipped";
  readonly result: ImportItemResult | null;
  readonly created_at: string;
  suggestions: ImportSuggestions;
}

export interface ImportItemResult {
  item_id: number;
  action: "import" | "original_only" | "skip";
  measurement_ids: number[];
  warnings: string[];
  source_file_id?: number;
}

export interface ImportJob {
  readonly job_id: number;
  readonly owner_user_id: number;
  readonly status: "draft" | "completed";
  readonly row_version: number;
  readonly created_at: string;
}

export type ImportJobDetail = ImportJob & { items: ImportItem[] };

export interface ImportParseResult {
  type: "unsupported" | "eoptics" | "xps_chart_configuration";
  parser: string;
  version: string;
  status: "original_only" | "rejected" | "needs_confirmation" | "parsed";
  blocks: ParserBlock[];
  warnings: ParserIssue[];
  blocking_issues: ParserIssue[];
  filename_hints: { source: string; requires_confirmation: boolean; n: string | null; k: string | null };
  source: { filename: string; sha256: string; size_bytes: number };
  preview_metadata?: Record<string, unknown>;
}

/** multipart files[]；1–20 个文件；每个 <=20 MiB，总计 <=100 MiB；不接收其他字段。 */
export interface ImportPreviewRequest {
  "files[]": string[];
}

export interface ImportProcessOption {
  process_id: number;
  process_code: string;
}

export interface ImportSampleOption {
  sample_id: number;
  sample_code: string;
  display_label: string | null;
  batch_code: string;
}

/** 始终手动选关联；候选仅限上传者自己的样品（含 admin），任务始终个人可见。 */
export interface ImportSuggestions {
  requires_manual_selection: boolean;
  association_is_fact: boolean;
  warnings: string[];
  samples: ({ sample_id: number; sample_code: string; display_label: string | null; batch_id: number; batch_code: string; batch_hint_match: boolean; processes: { process_id: number; process_code: string }[]; baseline_measurements: ({ measurement_id: number; measurement_code: string; stage: "initial" | "after_o2_plasma" | "after_o3_pre" | "after_ale" | "after_hf_only" | "after_o3_only" | "intermediate" | "final" | "other"; stage_seq: number | null; optical_model_id: number | null })[] })[];
  optical_models: ({ model_id: number; model_code: string; model_name: string; rcp_name?: string | null; spl_name?: string | null; n_setting?: string | null; k_setting?: string | null; layer_structure?: Record<string, unknown>[] | null; aoi_deg?: string | null; valid_range_nm?: string | null; applicable_batch_id?: number | null; quality_note?: string | null; status: OpticalModelStatus; created_at?: string; updated_at?: string })[];
}

/** 仪器信号通道。 */
export interface InstrumentChannel {
  channel_id: number;
  dataset_id: number;
  channel_code: string;
  channel_label?: string | null;
  channel_type: ChannelType;
  /** 元素符号 */
  element?: string | null;
  /** 轨道 */
  transition?: string | null;
  /** RGA 的 m/z */
  mass_charge?: string | null;
  x_unit?: "binding_energy_eV" | "kinetic_energy_eV" | "mz" | "angle_deg" | "time_s" | null | null;
  y_unit?: "counts_per_s" | "ion_current_A" | "intensity" | null | null;
  /** 峰位（如 XPS 结合能 eV） */
  peak_center?: string | null;
  peak_height?: string | null;
  fwhm?: string | null;
  peak_area?: string | null;
  /** 仪器特有属性 */
  extra_json?: Record<string, unknown> | null;
  created_at?: string;
  datapoints?: InstrumentDatapoint[];
}

export interface InstrumentChannelCreate {
  channel_code: string;
  channel_label?: string;
  channel_type: ChannelType;
  element?: string;
  transition?: string;
  mass_charge?: string;
  x_unit?: string;
  y_unit?: string;
  peak_center?: string;
  peak_height?: string;
  fwhm?: string;
  peak_area?: string;
  extra_json?: Record<string, unknown>;
  /** 可随通道一并提交数据点 */
  datapoints?: InstrumentDatapointCreate[];
}

export interface InstrumentDatapoint {
  datapoint_id: number;
  channel_id: number;
  /** 点序号 */
  point_index: number;
  x_value?: string | null;
  y_value?: string | null;
}

export interface InstrumentDatapointCreate {
  point_index: number;
  x_value?: string;
  y_value?: string;
}

export interface InstrumentDataset {
  dataset_id: number;
  dataset_code: string;
  instrument_type: InstrumentType;
  tool_id?: number | null;
  sample_id?: number | null;
  process_id?: number | null;
  /** 若与某次椭偏测量对应同一阶段 */
  measurement_id?: number | null;
  batch_id?: number | null;
  title?: string | null;
  /** 仪器侧编号 */
  external_ref?: string | null;
  acquired_at?: string | null;
  operator_user_id?: number | null;
  source_file_id?: number | null;
  /** 采集参数（通能、阳极电压、束流等） */
  acquisition_params?: Record<string, unknown> | null;
  sample_mapping_status: SampleMappingStatus;
  mapping_note?: string | null;
  created_at?: string;
}

export interface InstrumentDatasetCreate {
  dataset_code: string;
  instrument_type: InstrumentType;
  tool_id?: number;
  sample_id?: number;
  process_id?: number;
  measurement_id?: number;
  batch_id?: number;
  title?: string;
  external_ref?: string;
  acquired_at?: string;
  source_file_id?: number;
  acquisition_params?: Record<string, unknown>;
  sample_mapping_status?: SampleMappingStatus;
  mapping_note?: string;
}

export type InstrumentDatasetDetail = InstrumentDataset & { channels?: InstrumentChannel[] };

export interface InstrumentDatasetUpdate {
  sample_id?: number;
  process_id?: number;
  measurement_id?: number;
  title?: string;
  external_ref?: string;
  acquired_at?: string;
  acquisition_params?: Record<string, unknown>;
  sample_mapping_status?: SampleMappingStatus;
  mapping_note?: string;
}

/** 邀请安全视图，不返回邀请码或其哈希。 用途只能research/testing，注册者继承邀请角色与用途。 */
export interface Invitation {
  invitation_id: number;
  role: InvitationRole;
  created_by: number;
  expires_at: string;
  used_by?: number | null;
  used_at?: string | null;
  revoked_at?: string | null;
  created_at: string;
  account_purpose: OrdinaryAccountPurpose;
}

/** 问题台账。对应交接文档 ISS-01 至 ISS-10。 */
export interface Issue {
  issue_id: number;
  issue_code: string;
  title: string;
  severity: IssueSeverity;
  status: IssueStatus;
  /** 现象与证据 */
  observed?: string | null;
  /** 对结论的影响 */
  effect?: string | null;
  /** 交接处理措施 */
  action?: string | null;
  /** 禁止误用条款。 */
  avoid?: string | null;
  opened_at?: string | null;
  closed_at?: string | null;
  owner_user_id?: number | null;
  /** 关联实体数量（服务端聚合） */
  readonly linked_entity_count?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface IssueCreate {
  issue_code: string;
  title: string;
  severity?: IssueSeverity;
  status?: IssueStatus;
  observed?: string;
  effect?: string;
  action?: string;
  avoid?: string;
  opened_at?: string;
  owner_user_id?: number;
}

export type IssueDetail = Issue & { links?: IssueLink[] };

export interface IssueLink {
  link_id: number;
  issue_id: number;
  entity_type: EntityType;
  entity_id: number;
  relation: "related" | "caused_by" | "blocked_by" | "evidence_for";
  note?: string | null;
  created_at?: string;
}

export interface IssueLinkCreate {
  entity_type: EntityType;
  entity_id: number;
  relation?: "related" | "caused_by" | "blocked_by" | "evidence_for";
  note?: string;
}

export interface IssueUpdate {
  title?: string;
  severity?: IssueSeverity;
  status?: IssueStatus;
  observed?: string;
  effect?: string;
  action?: string;
  avoid?: string;
  closed_at?: string;
  owner_user_id?: number;
}

/** One lifecycle action; the reason is required for void and optional otherwise. */
export interface LifecycleApply {
  preview_token: string;
  operation_id: string;
  sample_versions?: Record<string, number>;
  action: "archive" | "archive_with_dependents" | "void" | "delete" | "restore";
  expected_row_version: number;
  reason?: string | null;
  include_sample_ids?: number[] | null;
}

export type LifecycleApplyResult = LifecycleBatch | LifecycleSample | LifecycleExperimentPlan | LifecycleProcess | LifecycleDeletedBatch | LifecycleDeletedSample | LifecycleDeletedPlan | LifecycleDeletedProcess;

/** 沉积批次。**批次是数据可比性的强制隔离边界**—— */
export interface LifecycleBatch {
  batch_id: number;
  /** 批次编码，全局唯一 */
  batch_code: string;
  batch_name: string;
  material: string;
  wafer_size: string | null;
  /** 标称厚度（nm）。为 string 以避免浮点精度损失。 */
  nominal_thickness_nm: string | null;
  deposit_recipe_id: number | null;
  deposit_date: string | null;
  /** PECVD 设定温度（℃） */
  deposit_set_temp_c: string | null;
  /** PECVD 实测温度（℃）。**必须与设定值分开记录**—— */
  deposit_actual_temp_c: string | null;
  /** 沉积气体流量，如 {"SiH4": 20, "NH3": 100, "N2": 200} */
  deposit_gas_flows: Record<string, unknown> | null;
  source_zip: string | null;
  /** 原始压缩包 SHA-256，用于溯源校验 */
  source_zip_sha256: string | null;
  anomaly_flag: boolean | number;
  /** 异常描述。**禁止据文件名断言故障机理**（ISS-02）。 */
  anomaly_note: string | null;
  owner_user_id: number | null;
  status: BatchStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** 服务端并发版本，每次更新递增。 */
  readonly row_version: number;
  /** 独立归档时间；null 表示未归档，不改原有科学状态。 */
  readonly archived_at: string | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
}

export interface LifecycleDeletedBatch {
  batch_id: number;
  batch_code: string;
  deleted: true;
}

export interface LifecycleDeletedPlan {
  plan_id: number;
  plan_code: string;
  deleted: true;
}

export interface LifecycleDeletedProcess {
  process_id: number;
  process_code: string;
  deleted: true;
}

export interface LifecycleDeletedSample {
  sample_id: number;
  sample_code: string;
  deleted: true;
}

/** 实验计划。位于实验执行之前，一个计划可派生多个执行。 */
export interface LifecycleExperimentPlan {
  readonly plan_id: number;
  plan_code: string;
  title: string;
  /** 实验目的 */
  objective: string | null;
  /** 待验证假设 */
  hypothesis: string | null;
  /** 变量设计与对照组设置 */
  design_note: string | null;
  planned_start: string | null;
  planned_end: string | null;
  priority: PlanPriority;
  status: PlanStatus;
  owner_user_id: number | null;
  batch_id: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** 服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。 */
  readonly row_version: number;
  /** 保存后step_id为真实数据库ID；空值表示旧记录无布局。 */
  process_flow: ProcessFlow | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
  readonly archive_previous_status: string | null;
}

export interface LifecycleGroup {
  type: string;
  label: string;
  count: number;
  restricted: boolean;
  deletable_hint: boolean;
}

export interface LifecycleImpact {
  kind: "batches" | "samples" | "plans" | "processes";
  id: number;
  code: string | null;
  row_version: number;
  status: LifecycleStatus;
  archived: boolean;
  can_restore: boolean;
  groups: LifecycleGroup[];
  restricted: boolean;
  restricted_flag: string | null;
  shared: LifecycleShared;
  sample_counts: LifecycleSampleCounts | null;
  dependencies_total_visible: number;
  delete_blocked: boolean;
  delete_allowed: boolean;
  delete_permitted: boolean;
  void_allowed: boolean;
  actions: ("archive" | "archive_with_dependents" | "void" | "delete" | "restore")[];
  preview_token: string;
}

/** 工艺运行（一次实际执行事件）。 */
export interface LifecycleProcess {
  readonly process_id: number;
  process_code: string;
  /** 所属实验计划（可为空，表示临时加做） */
  plan_id: number | null;
  batch_id: number | null;
  process_mode: ProcessMode;
  tool_id: number | null;
  /** 关联的通用化学体系（可为空）；删除被引用的体系返回 409。 */
  chemistry_system_id: number | null;
  /** R1 实测温度（℃）。与配方标称值分开。 */
  r1_temp_c: string | null;
  r2_temp_c: string | null;
  n2_flow_sccm: string | null;
  /** O3 预暴露**次数**。 */
  o3_pre_cycles: number | null;
  /** 单次预暴露时长（秒）。与次数分开记录。 */
  o3_pre_duration_s: string | null;
  full_ale_cycles: number | null;
  hf_tma_repeats: number | null;
  started_at: string | null;
  ended_at: string | null;
  operator_user_id: number | null;
  /** 共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品 */
  co_etch_group: string | null;
  is_independent_run: boolean | number;
  log_status: ProcessLogStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** 服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。 */
  readonly row_version: number;
  /** 独立归档时间；null 表示未归档，不改原有科学状态。 */
  readonly archived_at: string | null;
  /** 保存后step_id为真实数据库ID；空值表示旧记录无布局。 */
  process_flow: ProcessFlow | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
}

/** 样品。**工作台的中心实体**。 */
export interface LifecycleSample {
  sample_id: number;
  /** 全局唯一样品编码 */
  sample_code: string;
  batch_id: number;
  /** 母片/上级样品 ID（支持母片-小样层级） */
  parent_sample_id: number | null;
  sample_type: SampleType;
  /** 原始文件中的编号，如 "1" / "9" */
  display_label: string | null;
  nominal_thickness_nm: string | null;
  size_desc: string | null;
  cut_position: string | null;
  surface_state: string | null;
  /** 前处理描述。ISS-05 要求必须记录前处理—— */
  pre_treatment: string | null;
  status: SampleStatus;
  exclude_from_analysis: boolean | number;
  /** 排除理由。`exclude_from_analysis=true` 时应填写。 */
  exclude_reason: string | null;
  owner_user_id: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** 服务端并发版本，每次更新递增。 */
  readonly row_version: number;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
  readonly archived_at: string | null;
  readonly archived_by_user_id: number | null;
}

export interface LifecycleSampleCandidate {
  sample_id: number;
  sample_code: string;
  row_version: number;
}

export interface LifecycleSampleCounts {
  total: number;
  available: number;
  unused_candidates: number;
  candidates: LifecycleSampleCandidate[];
}

export interface LifecycleShared {
  shared_samples: LifecycleSharedSample[];
  shared_plans: LifecycleSharedPlan[];
}

export interface LifecycleSharedPlan {
  plan_id: number;
  process_count: number;
}

export interface LifecycleSharedSample {
  sample_id: number;
  process_count: number;
}

export interface LifecycleStatus {
  status: string | null;
  archived_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: TokenPair;
  user: User;
}

export interface Measurement {
  sample_code?: string | null;
  process_code?: string | null;
  plan_title?: string | null;
  optical_model_name?: string | null;
  readonly measurement_id: number;
  readonly measurement_code: string;
  readonly sample_id: number;
  readonly process_id: number | null;
  readonly tool_id: number | null;
  readonly optical_model_id: number | null;
  readonly stage: MeasurementStage;
  readonly stage_seq: number | null;
  readonly cumulative_cycles: number | null;
  readonly measured_at: string | null;
  readonly operator_user_id: number | null;
  readonly point_count: number | null;
  readonly thickness_mean_nm: string | null;
  readonly thickness_sd_nm: string | null;
  readonly thickness_min_nm: string | null;
  readonly thickness_max_nm: string | null;
  readonly mse_mean: string | null;
  readonly mse_max: string | null;
  readonly gof_mean: string | null;
  readonly wafer_size: string | null;
  readonly grid_desc: string | null;
  readonly supersedes_measurement_id: number | null;
  readonly is_current: boolean;
  readonly supersede_reason: string | null;
  readonly quality_flag: MeasurementQualityFlag;
  readonly quality_note: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly source_file_id: number | null;
  readonly import_item_id: number | null;
  readonly import_locator: string | null;
  readonly row_version: number;
  readonly provenance: unknown | null;
}

export interface MeasurementBrief {
  measurement_id: number;
  measurement_code: string;
  stage: MeasurementStage;
  stage_seq?: number | null;
  thickness_mean_nm?: string | null;
  is_current: boolean;
  quality_flag?: MeasurementQualityFlag;
}

export interface MeasurementCreate {
  measurement_code: string;
  sample_id: number;
  process_id?: number;
  tool_id?: number;
  optical_model_id?: number;
  stage: MeasurementStage;
  stage_seq?: number;
  cumulative_cycles?: number;
  measured_at?: string;
  point_count?: number;
  thickness_mean_nm?: string;
  thickness_sd_nm?: string;
  thickness_min_nm?: string;
  thickness_max_nm?: string;
  mse_mean?: string;
  mse_max?: string;
  gof_mean?: string;
  wafer_size?: string;
  grid_desc?: string;
  quality_flag?: MeasurementQualityFlag;
  quality_note?: string;
  /** 可随测量一并提交点级数据 */
  points?: MeasurementPointCreate[];
}

export type MeasurementDetail = Measurement & { points: MeasurementPoint[] };

export interface MeasurementPoint {
  readonly point_id: number;
  readonly measurement_id: number;
  readonly point_no: number | null;
  readonly x_mm: string | null;
  readonly y_mm: string | null;
  readonly thickness_nm: string | null;
  readonly intensity: string | null;
  readonly height_mm: string | null;
  readonly mse: string | null;
  readonly gof: string | null;
  readonly aoi_deg: string | null;
  readonly fit_iter: number | null;
  readonly lbh: string | null;
  readonly fit_time_ms: string | null;
  readonly dispersion_params: unknown | null;
  readonly source_file_id: number | null;
  readonly source_sheet: string | null;
  readonly source_row: number | null;
  readonly source_cell: string | null;
  readonly is_outlier: boolean;
  readonly outlier_note: string | null;
  readonly created_at: string;
  readonly raw_values: unknown | null;
}

export interface MeasurementPointCreate {
  point_no?: number;
  x_mm?: string;
  y_mm?: string;
  thickness_nm?: string;
  intensity?: string;
  height_mm?: string;
  mse?: string;
  gof?: string;
  aoi_deg?: string;
  fit_iter?: number;
  lbh?: string;
  fit_time_ms?: string;
  dispersion_params?: Record<string, unknown>;
  source_file_id?: number;
  source_sheet?: string;
  source_row?: number;
  source_cell?: string;
  is_outlier?: boolean;
  outlier_note?: string;
}

export interface MeasurementPointUpdate {
  thickness_nm?: string;
  mse?: string;
  gof?: string;
  is_outlier?: boolean;
  outlier_note?: string;
}

export interface MeasurementSupersedeRequest {
  replacement_measurement_id: number;
  expected_row_version: number;
  expected_replacement_row_version: number;
  reason: string;
}

export type MeasurementSupersedeResult = Measurement & { points: MeasurementPoint[] } & { replacement: { sample_code?: string | null; process_code?: string | null; plan_title?: string | null; optical_model_name?: string | null; readonly measurement_id: number; readonly measurement_code: string; readonly sample_id: number; readonly process_id: number | null; readonly tool_id: number | null; readonly optical_model_id: number | null; readonly stage: MeasurementStage; readonly stage_seq: number | null; readonly cumulative_cycles: number | null; readonly measured_at: string | null; readonly operator_user_id: number | null; readonly point_count: number | null; readonly thickness_mean_nm: string | null; readonly thickness_sd_nm: string | null; readonly thickness_min_nm: string | null; readonly thickness_max_nm: string | null; readonly mse_mean: string | null; readonly mse_max: string | null; readonly gof_mean: string | null; readonly wafer_size: string | null; readonly grid_desc: string | null; readonly supersedes_measurement_id: number | null; readonly is_current: boolean; readonly supersede_reason: string | null; readonly quality_flag: MeasurementQualityFlag; readonly quality_note: string | null; readonly created_at: string; readonly updated_at: string; readonly source_file_id: number | null; readonly import_item_id: number | null; readonly import_locator: string | null; readonly row_version: number; readonly provenance: unknown | null } };

/** 仅质量更新；至少显式提交 quality_flag 或 quality_note。只更新实际提交字段；变化时将依赖结果 is_valid=false；版本递增。 */
export interface MeasurementUpdate {
  expected_row_version: number;
  quality_flag?: MeasurementQualityFlag;
  quality_note?: string | null;
}

/** 椭偏光学模型（n/k 设定）。 */
export interface OpticalModel {
  model_id: number;
  model_code: string;
  model_name: string;
  rcp_name?: string | null;
  spl_name?: string | null;
  /** 折射率 n */
  n_setting?: string | null;
  /** 消光系数 k */
  k_setting?: string | null;
  layer_structure?: Record<string, unknown>[] | null;
  /** 入射角（度） */
  aoi_deg?: string | null;
  valid_range_nm?: string | null;
  applicable_batch_id?: number | null;
  /** 模型质量备注。如 ISS-03 记录的 300nm 模型 MSE 偏高。 */
  quality_note?: string | null;
  status: OpticalModelStatus;
  created_at?: string;
  updated_at?: string;
}

/** 单对配对点的差值。 */
export interface PairedPointDelta {
  point_no: number;
  x_mm?: string | null;
  y_mm?: string | null;
  before_thickness_nm?: string | null;
  after_thickness_nm?: string | null;
  /** after - before */
  delta_nm?: string | null;
  /** before - after */
  r_nm?: string | null;
  delta_mse?: string | null;
  delta_gof?: string | null;
}

export interface PairingRequest {
  after_measurement_id: number;
  before_measurement_id: number;
  confirm_pair: boolean;
  include_points?: boolean;
  pairing_method?: "same_xy_coordinate";
  selection?: AnalysisSelection;
}

export interface PairingResponse {
  pairing_method: "same_xy_coordinate";
  direction: "after - before";
  model_consistent: true;
  paired_point_count: number;
  unmatched_before: number;
  unmatched_after: number;
  ineligible_before: number;
  ineligible_after: number;
  mean_delta_nm: string;
  mean_before_nm: string;
  mean_after_nm: string;
  sd_delta_nm: string | null;
  observation: "increase" | "decrease" | "unchanged";
  interpretation: string;
  points?: AnalysisPairPoint[];
  before_measurement_id: number;
  after_measurement_id: number;
  analysis_version: string;
  selection: AnalysisSelection;
  result_sha256: string;
}

export interface ParameterField {
  name: string;
  value?: string | null;
  unit?: string | null;
}

export interface ParameterGroup {
  name: string;
  fields?: ParameterField[];
}

export interface ParameterSnapshot {
  step_type: string;
  temperature?: Temperature;
  groups?: ParameterGroup[];
}

/** metadata 保留 headers/units/preamble/instrument_summary/optical_model；locator 保留 sheet/header_row/end_row。 */
export interface ParserBlock {
  metadata: Record<string, unknown>;
  points: ParserPoint[];
  statistics: ParserStatistics;
  warnings: ParserIssue[];
  blocking_issues: ParserIssue[];
  locator: Record<string, unknown>;
}

export interface ParserFieldStatistics {
  count: number;
  excluded_nonfinite_or_missing: number;
  mean?: string;
  min?: string;
  max?: string;
  sd_sample?: string | null;
  sd_population?: string;
}

export interface ParserIssue {
  code: string;
  message: string;
  locator: Record<string, unknown> | null;
  field: string | null;
}

/** 预览数值为十进制字符串或 null，保留原始词法值；不以 DB scale 舍入。 */
export interface ParserPoint {
  x_mm: string | null;
  y_mm: string | null;
  intensity: string | null;
  height_mm: string | null;
  mse: string | null;
  gof: string | null;
  thickness_nm: string | null;
  aoi_deg: string | null;
  lbh: string | null;
  fit_time_ms: string | null;
  point_no: number | null;
  fit_iter: number | null;
  dispersion_params: Record<string, string | null>;
  source_sheet: string;
  source_row: number;
  source_cell: string | null;
  is_outlier: boolean;
  outlier_note: string | null;
  raw_values: ParserRawValue[];
  locator: Record<string, unknown>;
}

export interface ParserRawValue {
  value: unknown;
  cell: string | null;
  data_type: string;
  /** 原始公式文本（含前导等号）；不执行求值。 */
  formula?: string;
  /** 原始 OOXML 公式属性。 */
  formula_attributes?: Record<string, string>;
  /** 原始公式缓存词法值；不转为数值，不作为可信观测。 */
  cached_value_lexeme?: string | null;
  /** 原始 OOXML 缓存类型；缺省为 n。 */
  cached_type?: string;
  /** 原始 v 元素是否存在；区分缺失缓存与空缓存。 */
  cache_present?: boolean;
}

export interface ParserStatistics {
  point_count: number;
  includes_outliers: boolean;
  sd_convention: { sample: string; population: string };
  decimal_precision: number;
  rounding: string;
  db_write_policy: string;
  thickness_nm: ParserFieldStatistics;
  mse: ParserFieldStatistics;
  gof: ParserFieldStatistics;
}

export interface ParticipationEvent {
  transition_id: number;
  event_type: TransitionEventType;
  from_status?: string | null;
  to_status?: string;
  process_id?: number | null;
  step_id?: number | null;
  step_index?: number | null;
  event_at?: string | null;
  location?: string | null;
  note?: string | null;
}

export interface ParticipationMeasurement {
  sample_code?: string | null;
  process_code?: string | null;
  plan_title?: string | null;
  optical_model_name?: string | null;
  measurement_id: number;
  measurement_code: string;
  stage: string;
  stage_seq?: number | null;
  cumulative_cycles?: number | null;
  measured_at?: string | null;
  thickness_mean_nm?: string | null;
  thickness_sd_nm?: string | null;
  thickness_min_nm?: string | null;
  thickness_max_nm?: string | null;
  mse_mean?: string | null;
  quality_flag?: string;
  is_current: boolean;
  process_id?: number | null;
}

export interface ParticipationSummary {
  recorded_cycles: number | null;
  cycle_groups?: Record<string, unknown>[];
  participation_count: number;
  recorded_participations: number;
  missing_participations: number;
  complete: boolean;
}

/** 计划归档请求；expected_row_version 可选，不匹配返回 409；已归档幂等返回当前详情。 */
export interface PlanArchive {
  expected_row_version?: number | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface PlanCreate {
  plan_code: string;
  title: string;
  objective?: string | null;
  hypothesis?: string | null;
  design_note?: string | null;
  planned_start?: string | null;
  planned_end?: string | null;
  priority?: "high" | "normal" | "low";
  status?: "draft" | "approved" | "running" | "completed" | "abandoned";
  batch_id?: number | null;
  notes?: string | null;
}

export type PlanGridDetail = ExperimentPlan & { steps: PlanStep[]; batch: Batch | null; processes: Process[]; process_count: number; owner: Record<string, unknown> | null };

/** 有序计划步骤；step_id 由服务端生成。被实际步骤映射后，更新或删除均返回 409。 */
export interface PlanStep {
  readonly step_id: number;
  readonly plan_id: number;
  step_index: number;
  step_kind: ProcessStepKind;
  planned_parameters?: StepParameters | null;
  step_note?: string | null;
  /** 自定义步骤名（如“O3 暴露”）；步骤类型仍由 step_kind 表达。 */
  step_name?: string | null;
  /** 自由参数映射，按 {key: {value,unit,note}} 存储；数字取值统一按字符串回传。 */
  custom_parameters?: CustomParameters | null;
  readonly created_at: string;
  /** 通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。 */
  parameter_snapshot?: ParameterSnapshot | null;
  /** 当前参数来源；非空快照优先，旧字段保持原值。 */
  readonly parameter_source: "parameter_snapshot" | "legacy_fields";
  /** 原样返回已记录旧字段及custom_parameters；不推断单位或转换数值。 */
  readonly legacy_parameters: Record<string, unknown>;
  /** 存在快照时旧值仅供历史读取，否则仍为当前参数。 */
  readonly legacy_parameters_status: "historical_readonly" | "current";
  /** 非空快照与非空旧参数同时存在；不表示已推断数值是否相等。 */
  readonly parameter_conflict: boolean;
}

/** 计划步骤创建；客户端必须提供 step_index 和 step_kind，不接受服务端 step_id/plan_id。 */
export interface PlanStepCreate {
  step_index: number;
  step_kind: ProcessStepKind;
  planned_parameters?: StepParameters | null;
  step_note?: string | null;
  /** 自定义步骤名（可空）。 */
  step_name?: string | null;
  /** 自由参数映射，最多 32 项。 */
  custom_parameters?: CustomParameters | null;
  /** 通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。 */
  parameter_snapshot?: ParameterSnapshot | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface PlanStepUpdate {
  step_index?: number;
  step_kind?: ProcessStepKind;
  planned_parameters?: StepParameters | null;
  step_note?: string | null;
  /** 自定义步骤名（可空）。 */
  step_name?: string | null;
  /** 自由参数映射，最多 32 项。 */
  custom_parameters?: CustomParameters | null;
  /** 可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。 */
  expected_row_version?: number | null;
  /** 通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。 */
  parameter_snapshot?: ParameterSnapshot | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface PlanUpdate {
  title?: string;
  objective?: string | null;
  hypothesis?: string | null;
  design_note?: string | null;
  planned_start?: string | null;
  planned_end?: string | null;
  priority?: "high" | "normal" | "low";
  status?: "draft" | "approved" | "running" | "completed" | "abandoned";
  batch_id?: number | null;
  notes?: string | null;
  /** 可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。 */
  expected_row_version?: number | null;
}

/** 工艺运行（一次实际执行事件）。 */
export interface Process {
  plan_title?: string | null;
  readonly process_id: number;
  process_code: string;
  /** 所属实验计划（可为空，表示临时加做） */
  plan_id?: number | null;
  batch_id?: number | null;
  process_mode: ProcessMode;
  tool_id?: number | null;
  /** 关联的通用化学体系（可为空）；删除被引用的体系返回 409。 */
  chemistry_system_id?: number | null;
  /** R1 实测温度（℃）。与配方标称值分开。 */
  r1_temp_c?: string | null;
  r2_temp_c?: string | null;
  n2_flow_sccm?: string | null;
  /** O3 预暴露**次数**。 */
  o3_pre_cycles?: number | null;
  /** 单次预暴露时长（秒）。与次数分开记录。 */
  o3_pre_duration_s?: string | null;
  full_ale_cycles?: number | null;
  hf_tma_repeats?: number | null;
  started_at?: string | null;
  ended_at?: string | null;
  operator_user_id?: number | null;
  /** 共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品 */
  co_etch_group?: string | null;
  /** 是否独立运行（false 表示与其他样品共腔） */
  is_independent_run: boolean;
  log_status: ProcessLogStatus;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
  /** 服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。 */
  readonly row_version: number;
  /** 独立归档时间；null 表示未归档，不改原有科学状态。 */
  readonly archived_at?: string | null;
  /** 保存后step_id为真实数据库ID；空值表示旧记录无布局。 */
  process_flow?: ProcessFlow | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
}

export interface ProcessBrief {
  process_id: number;
  process_code: string;
  process_mode: ProcessMode;
  started_at?: string | null;
  log_status?: ProcessLogStatus;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ProcessCreate {
  process_code: string;
  process_mode: "full_cycle" | "pre_expose_then_react" | "hf_only" | "o3_only" | "tma_only" | "plasma" | "deposition" | "other";
  plan_id?: number | null;
  batch_id?: number | null;
  tool_id?: number | null;
  /** 关联的通用化学体系（可空）；校验存在且可见。 */
  chemistry_system_id?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  r1_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  r2_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  n2_flow_sccm?: string | null;
  o3_pre_cycles?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_pre_duration_s?: string | null;
  full_ale_cycles?: number | null;
  hf_tma_repeats?: number | null;
  started_at?: string | null;
  ended_at?: string | null;
  co_etch_group?: string | null;
  is_independent_run?: boolean;
  log_status?: "ok" | "partial" | "aborted" | "unknown";
  notes?: string | null;
  steps?: ProcessStepCreate[];
  samples?: ProcessSampleCreate[];
  /** 创建流程只接受与提交steps的step_index一致的整数引用；保存后解析为实际step_id。 */
  process_flow?: ProcessFlow | null;
}

export type ProcessDetail = Process & { plan: ExperimentPlan | null; batch: Batch | null; tool: Tool | null; steps: ProcessStep[]; samples: ProcessSampleLink[]; sample_count: number; step_count: number };

export interface ProcessFlow {
  children?: FlowNode[];
  total_cycles?: number | null;
  version?: 1;
}

export type ProcessGridDetail = Process & { steps: ProcessStep[]; batch: Batch | null; samples: ProcessSampleLink[]; step_count: number; sample_count: number; plan: ExperimentPlan | null; tool: Tool | null };

export interface ProcessGridSave {
  expected_row_version: number;
  process_flow: ProcessFlow;
  steps: GridStep[];
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ProcessSampleCreate {
  sample_id: number;
  chamber_position?: string | null;
  o3_pre_cycles?: number | null;
  hf_tma_repeats?: number | null;
  full_ale_cycles?: number | null;
  is_control?: boolean;
  sample_role_note?: string | null;
}

/** 工艺运行与样品的关联。承载**共腔信息**与**逐片工艺参数**—— */
export interface ProcessSampleLink {
  chemistry_name?: string | null;
  /** 本次执行的正式测量、明确前测和确定性表观结果；可用点计数不改原始均值。 */
  research_review?: Record<string, unknown>;
  cycle_groups?: Record<string, unknown>[];
  cycles_confirmed?: boolean;
  execution_evidence?: "not_confirmed" | "voided" | "recorded_time" | "recorded_loading";
  process_sample_id: number;
  process_id: number;
  sample_id: number;
  /** 列表和运行详情嵌入；创建/更新关联响应不含 sample。 */
  sample?: Sample;
  /** 腔体位置/装载位 */
  chamber_position?: string | null;
  /** 本片在该次运行的 O3 预暴露次数（可逐片不同） */
  o3_pre_cycles?: number | null;
  hf_tma_repeats?: number | null;
  full_ale_cycles?: number | null;
  /** 是否为对照样（如 0 次 O3） */
  is_control: boolean;
  sample_role_note?: string | null;
  created_at?: string;
  /** 样品所属批次（响应投影）。 */
  batch?: Batch;
  /** 本次执行中该样品的流转事件，按 event_at、transition_id 排序。 */
  events?: ParticipationEvent[];
  load_event?: ParticipationEvent | null;
  unload_event?: ParticipationEvent | null;
  /** 依据已记录 load/unload 事件；没有事件时为 not_recorded，不推断。 */
  participation_status?: "unloaded" | "loaded" | "not_recorded";
  measurements?: ParticipationMeasurement[];
  measurement_count?: number;
  /** 仅累计已确认参与的逐片循环；不同体系或体系未知的多次执行分组，跨组总数返回 null，不由设备循环推算。 */
  cumulative_recorded_cycles?: number | null;
  cumulative_participations?: number;
  cumulative_missing_participations?: number;
  cumulative_complete?: boolean;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ProcessSampleUpdate {
  chamber_position?: string | null;
  o3_pre_cycles?: number | null;
  hf_tma_repeats?: number | null;
  full_ale_cycles?: number | null;
  is_control?: boolean;
  sample_role_note?: string | null;
  /** 可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。 */
  expected_row_version?: number | null;
}

/** 工艺步骤。记录**实际运行参数**。 */
export interface ProcessStep {
  readonly step_id: number;
  process_id: number;
  step_index: number;
  step_kind: ProcessStepKind;
  chemistry?: string | null;
  /** 所依据的配方（标称） */
  recipe_id?: number | null;
  cycles?: number | null;
  cumulative_cycles?: number | null;
  duration_s?: string | null;
  pulse_s?: string | null;
  purge_s?: string | null;
  wait_s?: string | null;
  actual_temp_c?: string | null;
  delta_p?: string | null;
  delta_p_unit?: "kPa" | "Pa" | "mTorr" | null | null;
  /** O3 脉冲 ΔP（历史典型约 5kPa）。经验压力增量代理量，非积分化学剂量。 */
  o3_delta_p_kpa?: string | null;
  /** HF 脉冲 ΔP（历史典型约 80Pa） */
  hf_delta_p_pa?: string | null;
  /** TMA 脉冲 ΔP（历史典型约 110Pa） */
  tma_delta_p_pa?: string | null;
  /** O3 发生器 O2 供气**设定**流量（sccm）。 */
  o3_generator_o2_flow_set_sccm?: string | null;
  /** O3 发生器 O2 **实测**流量。常为 null（未记录）。 */
  o3_generator_o2_flow_measured_sccm?: string | null;
  /** O3 浓度。常为 null。 */
  o3_concentration?: string | null;
  /** O2 plasma 功率（30W） */
  o2_plasma_w?: string | null;
  /** O2 plasma 流量（30 sccm）。**此为 plasma 支路，与 O3 发生器流量无关。** */
  o2_plasma_sccm?: string | null;
  /** O2 plasma 腔压（80Pa） */
  o2_plasma_pa?: string | null;
  step_note?: string | null;
  /** 自定义步骤名（如“O3 暴露”）；步骤类型仍由 step_kind 表达。 */
  step_name?: string | null;
  /** 自由参数映射，按 {key: {value,unit,note}} 存储；数字取值统一按字符串回传。 */
  custom_parameters?: CustomParameters | null;
  created_at?: string;
  plan_step_id?: number | null;
  /** 通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。 */
  parameter_snapshot?: ParameterSnapshot | null;
  /** 当前参数来源；非空快照优先，旧字段保持原值。 */
  readonly parameter_source: "parameter_snapshot" | "legacy_fields";
  /** 原样返回已记录旧字段及custom_parameters；不推断单位或转换数值。 */
  readonly legacy_parameters: Record<string, unknown>;
  /** 存在快照时旧值仅供历史读取，否则仍为当前参数。 */
  readonly legacy_parameters_status: "historical_readonly" | "current";
  /** 非空快照与非空旧参数同时存在；不表示已推断数值是否相等。 */
  readonly parameter_conflict: boolean;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ProcessStepCreate {
  chemistry?: string | null;
  recipe_id?: number | null;
  cycles?: number | null;
  cumulative_cycles?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  duration_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  pulse_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  purge_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  wait_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  actual_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  delta_p?: string | null;
  delta_p_unit?: "kPa" | "Pa" | "mTorr" | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_delta_p_kpa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  hf_delta_p_pa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  tma_delta_p_pa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_generator_o2_flow_set_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_generator_o2_flow_measured_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_concentration?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_w?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_pa?: string | null;
  step_index: number;
  step_kind: ProcessStepKind;
  plan_step_id?: number | null;
  step_note?: string | null;
  /** 自定义步骤名（可空）。 */
  step_name?: string | null;
  /** 自由参数映射，最多 32 项。 */
  custom_parameters?: CustomParameters | null;
  /** 通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。 */
  parameter_snapshot?: ParameterSnapshot | null;
}

/** 自由步骤分类；0010 将计划/执行 step_kind 改为 VARCHAR(128)，无枚举 CHECK。 */
export type ProcessStepKind = string;

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ProcessStepUpdate {
  chemistry?: string | null;
  recipe_id?: number | null;
  cycles?: number | null;
  cumulative_cycles?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  duration_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  pulse_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  purge_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  wait_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  actual_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  delta_p?: string | null;
  delta_p_unit?: "kPa" | "Pa" | "mTorr" | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_delta_p_kpa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  hf_delta_p_pa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  tma_delta_p_pa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_generator_o2_flow_set_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_generator_o2_flow_measured_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_concentration?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_w?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_pa?: string | null;
  step_index?: number;
  step_kind?: ProcessStepKind;
  plan_step_id?: number | null;
  step_note?: string | null;
  /** 自定义步骤名（可空）。 */
  step_name?: string | null;
  /** 自由参数映射，最多 32 项。 */
  custom_parameters?: CustomParameters | null;
  /** 可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。 */
  expected_row_version?: number | null;
  /** 通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。 */
  parameter_snapshot?: ParameterSnapshot | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface ProcessUpdate {
  /** 可修改业务编号；内部 process_id 与历史引用保持，修改留审计。 */
  process_code?: string;
  process_mode?: "full_cycle" | "pre_expose_then_react" | "hf_only" | "o3_only" | "tma_only" | "plasma" | "deposition" | "other";
  plan_id?: number | null;
  batch_id?: number | null;
  tool_id?: number | null;
  /** 关联的通用化学体系（可空）；校验存在且可见。 */
  chemistry_system_id?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  r1_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  r2_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  n2_flow_sccm?: string | null;
  o3_pre_cycles?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_pre_duration_s?: string | null;
  full_ale_cycles?: number | null;
  hf_tma_repeats?: number | null;
  started_at?: string | null;
  ended_at?: string | null;
  co_etch_group?: string | null;
  is_independent_run?: boolean;
  log_status?: "ok" | "partial" | "aborted" | "unknown";
  notes?: string | null;
  /** 可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。 */
  expected_row_version?: number;
}

/** 工艺配方（**标称定义**）。 */
export interface Recipe {
  recipe_id: number;
  recipe_code: string;
  recipe_name: string;
  recipe_kind: RecipeKind;
  material?: string | null;
  /** 标称温度（℃），非实测 */
  nominal_temp_c?: string | null;
  nominal_pressure?: string | null;
  pressure_unit?: string | null;
  nominal_gas_flows?: Record<string, unknown> | null;
  pulse_s?: string | null;
  purge_s?: string | null;
  wait_s?: string | null;
  version: string;
  status: RecipeStatus;
  source_file_id?: number | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface RecordArchive {
  expected_row_version: number;
}

/** JSON body 可省略；refresh_token 缺省时使用 HttpOnly SameSite=Strict cookie。显式 token 优先，验证失败不会回退。 */
export interface RefreshRequest {
  refresh_token?: string;
}

/** 必须使用有效一次性邀请码注册。角色及account_purpose均从邀请继承，只能research/testing；请求禁止额外字段，不能指定role或account_purpose。 */
export interface RegisterRequest {
  /** 登录名。字母开头，可含字母数字与 `_ . -` */
  username: string;
  /** 密码至少 8 位，服务端使用 Argon2id 哈希存储。 */
  password: string;
  /** 显示名 */
  display_name?: string;
  email?: string;
  /** 一次性邀请码；注册成功原子消费，并继承邀请角色与用途。 */
  invite_code: string;
}

/** 样品。**工作台的中心实体**。 */
export interface Sample {
  sample_id: number;
  /** 全局唯一样品编码 */
  sample_code: string;
  batch_id: number;
  /** 所属批次编码（联表冗余，便于前端展示） */
  batch_code?: string;
  /** 母片/上级样品 ID（支持母片-小样层级） */
  parent_sample_id?: number | null;
  sample_type: SampleType;
  /** 原始文件中的编号，如 "1" / "9" */
  display_label?: string | null;
  nominal_thickness_nm?: string | null;
  size_desc?: string | null;
  cut_position?: string | null;
  surface_state?: string | null;
  /** 前处理描述。ISS-05 要求必须记录前处理—— */
  pre_treatment?: string | null;
  status: SampleStatus;
  /** 是否排除出常规统计。 */
  exclude_from_analysis: boolean;
  /** 排除理由。`exclude_from_analysis=true` 时应填写。 */
  exclude_reason?: string | null;
  owner_user_id?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at?: string;
  /** 服务端并发版本，每次更新递增。 */
  readonly row_version: number;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
  readonly archived_at: string | null;
  readonly archived_by_user_id: number | null;
}

/** 样品简要信息（用于嵌套展示） */
export interface SampleBrief {
  sample_id: number;
  sample_code: string;
  batch_code?: string | null;
  sample_type?: SampleType;
  status?: SampleStatus;
  exclude_from_analysis?: boolean;
}

export interface SampleCreate {
  /** 全局唯一，格式建议 `批次前缀-Sxx` */
  sample_code: string;
  batch_id: number;
  parent_sample_id?: number;
  sample_type?: SampleType;
  display_label?: string;
  nominal_thickness_nm?: string;
  size_desc?: string;
  cut_position?: string;
  surface_state?: string;
  pre_treatment?: string;
  status?: SampleStatus;
  exclude_from_analysis?: boolean;
  exclude_reason?: string;
  notes?: string;
}

export type SampleDetail = Sample & { batch?: Batch; parent_sample?: SampleBrief; child_samples?: SampleBrief[]; measurement_count?: number; point_count_total?: number; first_measured_at?: string | null; last_measured_at?: string | null; experiments?: SampleExperiment[]; participation_summary?: ParticipationSummary; research_review?: Record<string, unknown> };

export interface SampleExperiment {
  process_sample_id?: number;
  process_id: number;
  process_code: string;
  r1_temp_c?: string | null;
  r2_temp_c?: string | null;
  n2_flow_sccm?: string | null;
  voided_at?: string | null;
  process_mode?: string;
  log_status?: string;
  started_at?: string | null;
  ended_at?: string | null;
  plan_id?: number | null;
  plan_code?: string | null;
  plan_title?: string | null;
  batch_id?: number | null;
  chamber_position?: string | null;
  o3_pre_cycles?: number | null;
  hf_tma_repeats?: number | null;
  full_ale_cycles: number | null;
  cycles_recorded: boolean;
  cycles_confirmed?: boolean;
  execution_evidence?: "not_confirmed" | "voided" | "recorded_time" | "recorded_loading";
  steps?: ProcessStep[];
  is_control?: boolean;
  sample_role_note?: string | null;
  participation_status: "unloaded" | "loaded" | "not_recorded";
  events?: ParticipationEvent[];
  load_event?: ParticipationEvent | null;
  unload_event?: ParticipationEvent | null;
  measurements?: ParticipationMeasurement[];
  measurement_count: number;
}

/** 只追加历史；按 transition_id 升序（追加顺序）分页，event_at 可为 null 或回填，不能用其推断占用顺序。 */
export interface SampleTransition {
  /** 必需字段。关联运行不可见时为 true，process_id、step_id、operator_user_id、location、note、measurement_id 均为 null；保留样品状态轨迹，不代表无关联执行。 */
  readonly context_redacted: boolean;
  transition_id: number;
  sample_id: number;
  sample?: SampleBrief;
  from_status?: SampleStatus | null;
  to_status: SampleStatus;
  event_type: TransitionEventType;
  process_id?: number | null;
  measurement_id?: number | null;
  event_at?: string | null;
  operator_user_id?: number | null;
  location?: string | null;
  note?: string | null;
  created_at: string;
  /** 实际步骤完成之后的边界；须属于所提供 process_id。load 表示该步骤之后装入，unload 表示该步骤之后取出。null 表示未指定步骤边界。 */
  step_id?: number | null;
}

/** 追加流转；expected_row_version 必填，匹配样品 row_version；from_status、operator_user_id 与 ID 由服务端确定。 */
export interface SampleTransitionCreate {
  to_status: "available" | "in_process" | "consumed" | "lost" | "quarantined";
  event_type: "cut" | "load" | "unload" | "measure" | "process" | "quarantine" | "dispose" | "receive";
  expected_row_version: number;
  process_id?: number | null;
  /** 实际步骤完成之后的边界；须属于所提供 process_id。load 表示该步骤之后装入，unload 表示该步骤之后取出。null 表示未指定步骤边界。 */
  step_id?: number | null;
  measurement_id?: number | null;
  event_at?: string | null;
  location?: string | null;
  note?: string | null;
}

export interface SampleUpdate {
  /** 用户可见样品编号；全局唯一。修改不改变 sample_id，历史测量、执行与流转关联保持有效。 */
  sample_code?: string;
  display_label?: string | null;
  nominal_thickness_nm?: string | null;
  size_desc?: string | null;
  cut_position?: string | null;
  surface_state?: string | null;
  pre_treatment?: string | null;
  status?: SampleStatus;
  exclude_from_analysis?: boolean;
  exclude_reason?: string | null;
  notes?: string | null;
  /** 可选；提供时必须匹配当前 row_version，否则返回 409。省略时保持原有更新行为。 */
  expected_row_version?: number;
}

export interface SampleVoid {
  expected_row_version: number;
  reason: string;
}

/** 使用部署配置的 setup_code 创建首位管理员；仅首次初始化可用，初始化完成后拒绝重复调用。 */
export interface SetupRequest {
  setup_code: string;
  /** 登录名。字母开头，可含字母数字与 `_ . -` */
  username: string;
  /** 密码至少 8 位，服务端使用 Argon2id 哈希存储。 */
  password: string;
  /** 显示名 */
  display_name?: string;
}

export interface SetupStatus {
  needs_setup: boolean;
}

/** 历史/规划完整登记模型；当前只读 GET 使用 SourceFileRead / SourceFileReadDetail。新上传原件按 SHA 不可变保存，禁止改写。 */
export interface SourceFile {
  file_id: number;
  /** SHA-256，主溯源键 */
  file_sha256: string;
  /** 文件名（可能含 n/k 编码，如 `1-n1.9198-k0.0005-ALE.xlsx`） */
  file_name: string;
  rel_path?: string | null;
  source_zip?: string | null;
  file_role: FileRole;
  file_ext?: string | null;
  size_bytes?: number | null;
  mtime_epoch?: number | null;
  batch_id?: number | null;
  sample_id?: number | null;
  /** 原始文件只读，恒为 true */
  is_readonly: boolean;
  /** 重复文件的原始版本 ID。 */
  is_duplicate_of?: number | null;
  parse_status: ParseStatus;
  parse_note?: string | null;
  created_at?: string;
}

export interface SourceFileCreate {
  file_sha256: string;
  file_name: string;
  rel_path?: string;
  source_zip?: string;
  file_role: FileRole;
  file_ext?: string;
  size_bytes?: number;
  mtime_epoch?: number;
  batch_id?: number;
  sample_id?: number;
  is_duplicate_of?: number;
  parse_note?: string;
}

export interface SourceFileOccurrence {
  readonly occurrence_id: number;
  readonly source_file_id: number;
  readonly import_item_id: number;
  readonly owner_user_id: number;
  readonly sample_id: number | null;
  readonly filename: string;
  readonly notes: string | null;
  readonly created_at: string;
}

/** 当前 GET 安全投影；file_name 按可见 occurrence 选择，不泄漏其他上传者名字/路径/备注。 */
export interface SourceFileRead {
  readonly file_id: number;
  readonly file_sha256: string;
  readonly file_name: string;
  readonly file_ext: string | null;
  readonly size_bytes: number | null;
  readonly is_readonly: boolean;
  readonly created_at: string;
}

export type SourceFileReadDetail = SourceFileRead & { readonly storage_key: string; occurrences: SourceFileOccurrence[] };

/** 在指定体系下创建物种；species_code 在体系内唯一。 */
export interface SpeciesCreate {
  species_code: string;
  species_name: string;
  formula?: string | null;
  role: SpeciesRole;
  default_unit?: string | null;
  notes?: string | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）。 */
export interface SpeciesUpdate {
  species_name?: string | null;
  formula?: string | null;
  role?: SpeciesRole;
  default_unit?: string | null;
  notes?: string | null;
  /** 可选且可为 null；非 null 时匹配体系 row_version，否则 409。 */
  expected_row_version?: number | null;
}

/** 独立通用步骤参数模板；definition 为 JSON 快照，编辑模板不会改变已保存步骤。 */
export interface StepParameterTemplate {
  readonly template_id: number;
  template_name: string;
  definition: ParameterSnapshot;
  readonly owner_user_id: number;
  readonly row_version: number;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface StepParameterTemplateCreate {
  template_name: string;
  definition: ParameterSnapshot;
}

export interface StepParameterTemplateUpdate {
  expected_row_version: number;
  template_name?: string;
  definition?: ParameterSnapshot;
}

/** 计划参数白名单，与实际步骤参数字段相同；额外键返回 422。计划值不自动写入实际观测。 */
export interface StepParameters {
  chemistry?: string | null;
  recipe_id?: number | null;
  cycles?: number | null;
  cumulative_cycles?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  duration_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  pulse_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  purge_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  wait_s?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  actual_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  delta_p?: string | null;
  delta_p_unit?: "kPa" | "Pa" | "mTorr" | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_delta_p_kpa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  hf_delta_p_pa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  tma_delta_p_pa?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_generator_o2_flow_set_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_generator_o2_flow_measured_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_concentration?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_w?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_sccm?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o2_plasma_pa?: string | null;
}

/** 将某次测量标记为被取代。 */
export interface SupersedeRequest {
  /** 被取代的测量 ID */
  superseded_measurement_id: number;
  /** 取代原因（必填，写入 supersede_reason） */
  reason: string;
}

export interface Temperature {
  value?: string | null;
  unit?: string;
}

/** 在指定体系下创建步骤模板；template_code 在体系内唯一，steps 至少 1 条。 */
export interface TemplateCreate {
  template_code: string;
  template_name: string;
  description?: string | null;
  steps: TemplateStep[];
}

/** 模板步骤的参数定义，仅声明 key/label/unit，不含取值。 */
export interface TemplateParameter {
  key: string;
  label: string;
  unit?: string | null;
}

/** 可复用模板中的一个步骤；数组顺序即步骤顺序。 */
export interface TemplateStep {
  name: string;
  kind: string;
  loop_count?: number | null;
  parameters?: TemplateParameter[];
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）。 */
export interface TemplateUpdate {
  template_name?: string | null;
  description?: string | null;
  steps?: TemplateStep[];
  /** 可选且可为 null；非 null 时匹配体系 row_version，否则 409。 */
  expected_row_version?: number | null;
}

/** access JWT 1 小时，refresh JWT 7 天；绑定可撤销数据库会话，刷新轮换 refresh。刷新 cookie 为 HttpOnly、SameSite=Strict，HTTPS 下 Secure。 */
export interface TokenPair {
  /** 访问令牌（JWT）。放在 `Authorization: Bearer <token>` 头中。 */
  access_token: string;
  /** 刷新令牌。仅用于换取新 access_token，不得用于业务请求。 */
  refresh_token: string;
  token_type: "Bearer";
  /** access_token 有效期（秒） */
  expires_in: number;
  /** refresh_token 有效期（秒） */
  refresh_expires_in?: number;
}

export interface Tool {
  tool_id: number;
  tool_code: string;
  tool_name: string;
  tool_type: ToolType;
  vendor?: string | null;
  model?: string | null;
  location?: string | null;
  status: ToolStatus;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

/** 追加流转；expected_row_version 必填，匹配样品 row_version；from_status、operator_user_id 与 ID 由服务端确定。 */
export interface TransitionCreate {
  to_status: "available" | "in_process" | "consumed" | "lost" | "quarantined";
  event_type: "cut" | "load" | "unload" | "measure" | "process" | "quarantine" | "dispose" | "receive";
  expected_row_version: number;
  process_id?: number | null;
  /** 实际步骤完成之后的边界；须属于所提供 process_id。load 表示该步骤之后装入，unload 表示该步骤之后取出。null 表示未指定步骤边界。 */
  step_id?: number | null;
  measurement_id?: number | null;
  event_at?: string | null;
  location?: string | null;
  note?: string | null;
}

/** 用户信息（安全视图，不含密码哈希）。 admin必须为management；operator/viewer必须为research/testing。 */
export interface User {
  /** 用户 ID（主键） */
  user_id: number;
  /** 登录名，全局唯一 */
  username: string;
  /** 显示名 */
  display_name?: string | null;
  email?: string | null;
  role: UserRole;
  status: UserStatus;
  /** 备注 */
  notes?: string | null;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at?: string;
  account_purpose: AccountPurpose;
}

/** 用户简要信息（用于嵌套在其他资源中展示创建者/操作者）。 */
export interface UserBrief {
  user_id: number;
  username: string;
  display_name?: string | null;
}

/** 部分更新，可修改account_purpose。服务端将请求与已有角色/用途合并校验：admin必须management，operator/viewer必须research/testing，不匹配或role/status/account_purpose显式null返回422；改角色跨用途须同时提交匹配用途。角色、状态或用途变更撤销已有会话。 */
export interface UserUpdate {
  /** 显示名 */
  display_name?: string | null;
  email?: string | null;
  role?: UserRole;
  status?: UserStatus;
  /** 备注 */
  notes?: string | null;
  account_purpose?: AccountPurpose;
}

export interface WorkflowOwner {
  user_id: number;
  username: string;
  display_name: string | null;
}

export interface WorkflowPlanDetail {
  readonly plan_id: number;
  plan_code: string;
  title: string;
  /** 实验目的 */
  objective: string | null;
  /** 待验证假设 */
  hypothesis: string | null;
  /** 变量设计与对照组设置 */
  design_note: string | null;
  planned_start: string | null;
  planned_end: string | null;
  priority: PlanPriority;
  status: PlanStatus;
  owner_user_id: number | null;
  batch_id: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** 服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。 */
  readonly row_version: number;
  /** 保存后step_id为真实数据库ID；空值表示旧记录无布局。 */
  process_flow: ProcessFlow | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
  readonly archive_previous_status: string | null;
  steps: PlanStep[];
  batch: LifecycleBatch | null;
  processes: LifecycleProcess[];
  process_count: number;
  owner: WorkflowOwner | null;
}

export interface WorkflowProcessDetail {
  readonly process_id: number;
  process_code: string;
  /** 所属实验计划（可为空，表示临时加做） */
  plan_id: number | null;
  batch_id: number | null;
  process_mode: ProcessMode;
  tool_id: number | null;
  /** 关联的通用化学体系（可为空）；删除被引用的体系返回 409。 */
  chemistry_system_id: number | null;
  /** R1 实测温度（℃）。与配方标称值分开。 */
  r1_temp_c: string | null;
  r2_temp_c: string | null;
  n2_flow_sccm: string | null;
  /** O3 预暴露**次数**。 */
  o3_pre_cycles: number | null;
  /** 单次预暴露时长（秒）。与次数分开记录。 */
  o3_pre_duration_s: string | null;
  full_ale_cycles: number | null;
  hf_tma_repeats: number | null;
  started_at: string | null;
  ended_at: string | null;
  operator_user_id: number | null;
  /** 共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品 */
  co_etch_group: string | null;
  is_independent_run: boolean | number;
  log_status: ProcessLogStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
  /** 服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。 */
  readonly row_version: number;
  /** 独立归档时间；null 表示未归档，不改原有科学状态。 */
  readonly archived_at: string | null;
  /** 保存后step_id为真实数据库ID；空值表示旧记录无布局。 */
  process_flow: ProcessFlow | null;
  readonly voided_at: string | null;
  readonly void_reason: string | null;
  readonly voided_by_user_id: number | null;
  steps: ProcessStep[];
  batch: LifecycleBatch | null;
  samples: ProcessSampleLink[];
  step_count: number;
  sample_count: number;
  plan: LifecycleExperimentPlan | null;
  tool: Tool | null;
}

export interface WorkflowStage {
  key: "goal" | "plan" | "matrix" | "samples" | "execution" | "actual" | "measurement";
  status: "saved" | "empty";
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface WorkflowStartPlan {
  plan_code?: string;
  title: string;
  objective?: string | null;
  hypothesis?: string | null;
  design_note?: string | null;
  planned_start?: string | null;
  planned_end?: string | null;
  priority?: "high" | "normal" | "low";
  status?: "draft" | "approved" | "running" | "completed" | "abandoned";
  batch_id?: number | null;
  notes?: string | null;
}

/** 独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。 */
export interface WorkflowStartProcess {
  process_code?: string;
  process_mode: "full_cycle" | "pre_expose_then_react" | "hf_only" | "o3_only" | "tma_only" | "plasma" | "deposition" | "other";
  plan_id?: number | null;
  batch_id?: number | null;
  tool_id?: number | null;
  /** 关联的通用化学体系（可空）；校验存在且可见。 */
  chemistry_system_id?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  r1_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  r2_temp_c?: string | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  n2_flow_sccm?: string | null;
  o3_pre_cycles?: number | null;
  /** 仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。 */
  o3_pre_duration_s?: string | null;
  full_ale_cycles?: number | null;
  hf_tma_repeats?: number | null;
  started_at?: string | null;
  ended_at?: string | null;
  co_etch_group?: string | null;
  is_independent_run?: boolean;
  log_status?: "ok" | "partial" | "aborted" | "unknown";
  notes?: string | null;
  steps?: ProcessStepCreate[];
  samples?: ProcessSampleCreate[];
  /** 创建流程只接受与提交steps的step_index一致的整数引用；保存后解析为实际step_id。 */
  process_flow?: ProcessFlow | null;
}

export interface WorkflowState {
  plan: WorkflowPlanDetail | null;
  process: WorkflowProcessDetail | null;
  measurements: Measurement[];
  stages: WorkflowStage[];
}
