"""
ALE 实验工作台 · Pydantic 数据模型

由 tools/gen_models.py 从 openapi.bundled.yaml 自动生成，请勿手工修改。

类型约定:
  数据库 DECIMAL 字段映射为 Decimal（不是 float）——
  数据库存的是 DECIMAL(14,6) 等定点类型，转 float 会精度失真。
  数据库 DATETIME 映射为 datetime，DATE 映射为 date。
契约包含 planned 模型；模型存在不代表路由或科研写入已经实现。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Generic, TypeVar, Annotated
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, model_validator, field_validator, SecretStr

def validate_endpoint(value):
    from urllib.parse import urlsplit
    import ipaddress
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment
                or p.port not in (None, 443) or '\\' in value or '%' in p.netloc
                or not re.fullmatch(r'[A-Za-z0-9.:-]+|\[[A-Fa-f0-9:]+\]', p.netloc)
                or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/*', p.path)):
            raise ValueError()
        host = p.hostname.lower()
        if host == 'localhost' or '.' not in host and ':' not in host: raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global: raise ValueError()
        except ValueError:
            if ':' in host or re.fullmatch(r'[0-9.]+', host): raise ValueError()
        return value.rstrip('/')
    except (ValueError, TypeError):
        raise ValueError('A public HTTPS provider endpoint is required') from None


def _decimal_input(pattern):
    def check(value):
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise ValueError('Decimal must be a plain decimal string within precision and scale')
        return Decimal(value)
    return check


class ApiBaseModel(BaseModel):
    """所有模型基类。允许从 ORM 对象构造，忽略未声明字段。"""

    model_config = ConfigDict(
        from_attributes=True,
        extra='ignore',
        populate_by_name=True,
    )


class PageMeta(ApiBaseModel):
    """分页元信息。"""
    page: int
    size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool

T = TypeVar('T')
class ApiEnvelope(ApiBaseModel, Generic[T]):
    code: int
    message: str
    data: T | None = None
    request_id: str
    timestamp: datetime

class PagedData(ApiEnvelope[list[T]], Generic[T]):
    data: list[T]
    meta: PageMeta

class FieldError(ApiBaseModel):
    """字段级校验错误。"""
    field: str
    message: str
    rejected_value: Any | None = None


class ErrorDetail(ApiBaseModel):
    """错误详情（兼容 RFC 9457 Problem Details）。"""
    type: str
    title: str
    status: int
    code: int
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None



AIRequestStatus = Literal['pending', 'completed', 'failed']

AISourceKind = Literal['sample', 'batch', 'plan', 'process', 'measurement', 'source_file', 'transition']

AccountPurpose = Literal['management', 'research', 'testing']

AttachmentType = Literal['figure', 'origin_project', 'pdf', 'report', 'script', 'table', 'other']

AuditAction = Literal['insert', 'update', 'delete', 'login', 'export']

BatchStatus = Literal['active', 'archived', 'quarantined']

ChannelType = Literal['spectrum', 'survey', 'peak', 'ion_current', 'image']

ChartType = Literal['bar', 'line', 'scatter', 'mapping', 'histogram', 'box', 'radar']

EntityType = Literal['experiment_plan', 'process', 'sample', 'measurement', 'source_file', 'finding', 'batch', 'derived_result', 'instrument_dataset']

EvidenceLevel = Literal['measured', 'hypothesis', 'unverified']

FileRole = Literal['instrument_raw', 'derived_summary', 'point_derived', 'analysis_output', 'metadata', 'xps_raw']

ImportItemStatus = Literal['pending', 'imported', 'original_only', 'skipped']

ImportJobStatus = Literal['draft', 'completed']

InstrumentType = Literal['xps', 'rga', 'xrr', 'afm', 'sem', 'sims', 'other']

InvitationRole = Literal['viewer', 'operator']

IssueSeverity = Literal['high', 'medium_high', 'medium', 'medium_low', 'low']

IssueStatus = Literal['open', 'investigating', 'resolved', 'accepted_risk', 'deferred']

MeasurementQualityFlag = Literal['ok', 'suspect', 'abnormal', 'excluded']

MeasurementStage = Literal['initial', 'after_o2_plasma', 'after_o3_pre', 'after_ale', 'after_hf_only', 'after_o3_only', 'intermediate', 'final', 'other']

OpticalModelStatus = Literal['active', 'superseded', 'experimental']

OrdinaryAccountPurpose = Literal['research', 'testing']

PairingMethod = Literal['same_xy_coordinate', 'row_index', 'mean_difference']

ParseStatus = Literal['pending', 'parsed', 'failed', 'ignored']

PlanPriority = Literal['high', 'normal', 'low']

PlanStatus = Literal['draft', 'approved', 'running', 'completed', 'abandoned', 'archived']

ProcessLogStatus = Literal['ok', 'partial', 'aborted', 'unknown']

ProcessMode = Literal['full_cycle', 'pre_expose_then_react', 'hf_only', 'o3_only', 'tma_only', 'plasma', 'deposition', 'other']

RecipeKind = Literal['deposition', 'o3', 'hf', 'tma', 'plasma', 'full_cycle', 'purge']

RecipeStatus = Literal['active', 'superseded', 'obsolete']

ResultKind = Literal['apparent_removal_R', 'delta_d', 'apparent_epc', 'rate', 'paired_point_delta', 'uniformity', 'fit_quality', 'other']

SampleMappingStatus = Literal['resolved', 'unresolved', 'ambiguous']

SampleStatus = Literal['available', 'in_process', 'consumed', 'lost', 'quarantined']

SampleType = Literal['parent_wafer', 'full_wafer', 'coupon']

SortOrder = Literal['asc', 'desc']

SpeciesRole = Literal['precursor', 'reactant', 'purge', 'carrier', 'other']

SystemStatus = Literal['active', 'superseded', 'experimental']

ToolStatus = Literal['active', 'maintenance', 'retired']

ToolType = Literal['ellipsometer', 'thermal_ale', 'xps', 'rga', 'xrr', 'afm', 'sem', 'other']

TransitionEventType = Literal['cut', 'load', 'unload', 'measure', 'process', 'quarantine', 'dispose', 'receive']

UserRole = Literal['admin', 'operator', 'viewer']

UserStatus = Literal['active', 'disabled']

class AIAccountRecovery(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    at: str = Field(..., description='服务器UTC无时区ISO时间字符串（存储元数据原值）。')
    unknown_calls: int = Field(..., ge=0)

class AIChatRequest(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    message: str = Field(..., min_length=1, max_length=4000, pattern='\\S')
    context: AIContext | None = None
    @field_validator('message')
    @classmethod
    def nonempty(cls, value):
        if not value.strip(): raise ValueError('Message required')
        return value


class AICompletedResult(ApiBaseModel):
    """AICompletedResult；详见AIResult重放语义。"""
    model_config = ConfigDict(extra='forbid')
    status: Literal['completed']
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None
    answer: str | None
    sources: list[AISource] = Field(..., max_length=40)
    tool_trace: list[AIToolTrace] = Field(..., max_length=8)
    usage: AIRequestUsage
    error: AIResultError | None
    replayed: bool
    models: list[AIModelMetadata] = Field(None, max_length=200)

class AIConfig(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    provider_name: str = Field(..., min_length=1, max_length=64)
    base_url: str = Field(..., max_length=255)
    model: str = Field(..., max_length=128)
    provider_options: dict[str, Any]
    currency: str = Field(..., pattern='^[A-Z]{3}$')
    input_price_per_million: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    cached_input_price_per_million: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    output_price_per_million: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    monthly_budget: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    monthly_token_limit: Annotated[int, Field(strict=True)] = Field(..., ge=1000, le=1000000000, strict=True)
    daily_call_limit: Annotated[int, Field(strict=True)] = Field(..., ge=1, le=100000, strict=True)
    user_daily_call_limit: Annotated[int, Field(strict=True)] = Field(..., ge=1, le=10000, strict=True)
    admin_daily_call_limit: Annotated[int, Field(strict=True)] = Field(..., ge=1, le=10000, strict=True)
    max_output_tokens: Annotated[int, Field(strict=True)] = Field(..., ge=64, le=4096, strict=True)
    max_tool_rounds: Annotated[int, Field(strict=True)] = Field(..., ge=1, le=4, strict=True)
    key_configured: bool
    revision: int = Field(..., ge=0)
    configured: bool
    updated_at: datetime | None
    discovered_models: list[str]
    pricing_note: str
    user_monthly_budget: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$', description='每用户默认月预算，默认10，可为0，最大1000000，最多8位小数；响应Decimal字符串。')
    user_monthly_token_limit: Annotated[int, Field(strict=True)] = Field(..., ge=0, le=1000000000, strict=True)
    user_policies: dict[str, AIUserPolicyView] = Field(..., description='用户ID字符串到策略的映射。键必须规范正整数且≤9223372036854775807，最多10000项；仅admin可配置。')

class AIConfigWrite(ApiBaseModel):
    """完整设置替换，非PATCH；api.deepseek.com（按hostname，不依赖模型名）必须显式provider_options={thinking:{type:disabled}}，否则422；旧空配置仍可GET读取修复，但test/chat在预留和外发前409阻止。其他服务商保留原默认。revision必填严格非负整数。先以空model保存端点/密钥，GET models发现后再选择model；修改端点或密钥会清空发现列表；修改端点时未提供新api_key则清除旧密钥。启用须有端点、发现过的model和密钥。预算不得低于已记账与预留量；活动账期不能换币种。"""
    model_config = ConfigDict(extra='forbid', validate_default=True)
    enabled: bool = False
    provider_name: str = Field('OpenAI-compatible', min_length=1, max_length=64)
    base_url: str = Field('', max_length=255)
    model: str = Field('', max_length=128, pattern='^(?:[A-Za-z0-9_.:/-]{1,128})?$')
    provider_options: dict[str, Any] = {}
    currency: str = Field('USD', pattern='^[A-Z]{3}$')
    input_price_per_million: Annotated[Decimal, Field(gt=0, le=10000, decimal_places=8)] = Field('1', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    cached_input_price_per_million: Annotated[Decimal, Field(ge=0, le=10000, decimal_places=8)] = Field('1', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    output_price_per_million: Annotated[Decimal, Field(gt=0, le=10000, decimal_places=8)] = Field('1', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    monthly_budget: Annotated[Decimal, Field(gt=0, le=1000000, decimal_places=8)] = Field('10', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    monthly_token_limit: Annotated[int, Field(strict=True)] = Field(2000000, ge=1000, le=1000000000, strict=True)
    daily_call_limit: Annotated[int, Field(strict=True)] = Field(100, ge=1, le=100000, strict=True)
    user_daily_call_limit: Annotated[int, Field(strict=True)] = Field(20, ge=1, le=10000, strict=True)
    admin_daily_call_limit: Annotated[int, Field(strict=True)] = Field(50, ge=1, le=10000, strict=True)
    max_output_tokens: Annotated[int, Field(strict=True)] = Field(1024, ge=64, le=4096, strict=True)
    max_tool_rounds: Annotated[int, Field(strict=True)] = Field(4, ge=1, le=4, strict=True)
    api_key: SecretStr | None = Field(None, exclude=True, repr=False, description='仅写入，8..512个ASCII可见非空白字符；地址不变时null/省略保留旧密钥；base_url改变清除旧密钥，除非同时提供新api_key。clear_api_key清除；两者不能同时指定。响应绝不返回密钥或密文。')
    clear_api_key: bool = False
    revision: Annotated[int, Field(strict=True)] = Field(..., ge=0, strict=True)
    user_monthly_budget: Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=8)] = Field('10', description='每用户默认月预算，默认10，可为0，最大1000000，最多8位小数；响应Decimal字符串。')
    user_monthly_token_limit: Annotated[int, Field(strict=True)] = Field(2000000, ge=0, le=1000000000, strict=True)
    user_policies: dict[str, AIUserPolicy] = Field({}, description='用户ID字符串到策略的映射。键必须规范正整数且≤9223372036854775807，最多10000项；仅admin可配置。')
    @field_validator('base_url')
    @classmethod
    def endpoint(cls, value):
        return validate_endpoint(value) if value else ''

    @field_validator('model')
    @classmethod
    def model_id(cls, value):
        if value and not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}', value): raise ValueError('Invalid model')
        return value

    @field_validator('provider_options')
    @classmethod
    def options(cls, value):
        if value not in ({}, {'thinking': {'type': 'disabled'}}):
            raise ValueError('Only explicit thinking disabled is supported')
        return value

    @model_validator(mode='after')
    def valid(self):
        if self.enabled and (not self.base_url or not self.model): raise ValueError('Endpoint and discovered model required')
        if self.cached_input_price_per_million > self.input_price_per_million:
            raise ValueError('Cached input price cannot exceed regular input price')
        # This service deliberately supports nonthinking requests only. An empty
        # option object is for compatible providers whose default is nonthinking.
        return self

    @model_validator(mode='after')
    def key_shape(self):
        from urllib.parse import urlsplit
        if urlsplit(self.base_url).hostname == 'api.deepseek.com' and self.provider_options != {'thinking': {'type': 'disabled'}}:
            raise ValueError('api.deepseek.com requires provider_options thinking.type disabled for this nonthinking flow')
        if self.api_key is not None:
            value = self.api_key.get_secret_value()
            if not 8 <= len(value) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise ValueError('Invalid key')
        if self.clear_api_key and self.api_key is not None: raise ValueError('Conflicting key action')
        return self


    @field_validator('user_policies')
    @classmethod
    def policy_keys(cls, value):
        if len(value) > 10000 or any(not re.fullmatch(r'[1-9][0-9]{0,18}', k) or int(k) > 9223372036854775807 for k in value):
            raise ValueError('User policies require canonical positive user IDs')
        return value

class AIContext(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['sample', 'batch', 'plan', 'process', 'measurement', 'none']
    id: Annotated[int, Field(strict=True)] | None = Field(None, ge=1, le=9223372036854775807)
    @model_validator(mode='after')
    def valid(self):
        if (self.kind == 'none') != (self.id is None): raise ValueError('Context requires record ID')
        return self


class AIFailedResult(ApiBaseModel):
    """AIFailedResult；详见AIResult重放语义。 恢复终态额外recovery，error=request_recovered；未派发预留释放，已测量保留真实量，unknown保守估算；对账后reconciliation_required=false。"""
    model_config = ConfigDict(extra='forbid')
    status: Literal['failed']
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None
    answer: None
    sources: list[AISource] = Field(..., max_length=40)
    tool_trace: list[AIToolTrace] = Field(..., max_length=8)
    usage: AIRequestUsage
    error: AIResultError | None
    replayed: bool
    models: list[AIModelMetadata] = Field(None, max_length=200)
    recovery: AIResultRecovery = None

class AIModelCapabilities(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    anthropic_messages: dict[str, Any]

class AIModelEffort(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    supported_levels: list[Annotated[str, Field(pattern='^[a-z_-]{1,32}$')]] = Field(..., max_length=10)
    default_level: str = Field(None, pattern='^[a-z_-]{1,32}$')

class AIModelMetadata(ApiBaseModel):
    """供应商实际返回并经白名单裁剪的可选元数据；不根据模型ID推断能力。仅GET /ai/models发现结果，不注册科学分析工具。"""
    model_config = ConfigDict(extra='forbid')
    id: str = Field(..., pattern='^[A-Za-z0-9_.:/-]{1,128}$')
    name: str = Field(None, min_length=1, max_length=128, pattern='^[^\\x00-\\x1f]+$')
    owned_by: str = Field(None, min_length=1, max_length=128, pattern='^[^\\x00-\\x1f]+$')
    context_window: Annotated[int, Field(strict=True)] = Field(None, ge=1, le=1000000000, strict=True)
    max_output_tokens: Annotated[int, Field(strict=True)] = Field(None, ge=1, le=1000000000, strict=True)
    input_modalities: list[Annotated[str, Field(pattern='^[a-z_-]{1,32}$')]] = Field(None, max_length=8)
    output_modalities: list[Annotated[str, Field(pattern='^[a-z_-]{1,32}$')]] = Field(None, max_length=8)
    effort: AIModelEffort = None
    api_capabilities: AIModelCapabilities = None

class AIMyUsage(ApiBaseModel):
    """本人当前UTC月分账；无请求时记账与预留均为零，不暴露其他用户。"""
    model_config = ConfigDict(extra='forbid')
    period: str = Field(..., pattern='^\\d{4}-\\d{2}$')
    scope: Literal['current_user']
    currency: str = Field(..., pattern='^[A-Z]{3}$')
    owner_user_id: int = Field(..., ge=1)
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    charged_tokens: int = Field(..., ge=0)
    reserved_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    reserved_tokens: int = Field(..., ge=0)
    monthly_budget: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    monthly_token_limit: int = Field(..., ge=0)

class AIOriginalUsage(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    cache_hit_tokens: int = Field(..., ge=0)
    cache_miss_tokens: int = Field(..., ge=0)
    charged_tokens: int = Field(..., ge=0)
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')

class AIPendingResult(ApiBaseModel):
    """AIPendingResult；详见AIResult重放语义。"""
    model_config = ConfigDict(extra='forbid')
    status: Literal['pending']
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None
    answer: None
    sources: list[AISource] = Field(..., max_length=0)
    tool_trace: list[AIToolTrace] = Field(..., max_length=0)
    usage: None
    error: AIResultError

class AIPolicy(ApiBaseModel):
    """本人有效策略；research_ai_allowed为账户策略判断结果，不表示全局AI已启用或已配置。management默认拒绝科研AI；testing默认拒绝外发；需admin user_policies显式true允许。testing外发拒绝优先于科研AI拒绝。"""
    model_config = ConfigDict(extra='forbid')
    account_purpose: AccountPurpose
    research_ai_allowed: bool
    denial_reason: Literal[None, 'account_purpose_invalid', 'testing_external_send_denied', 'research_ai_denied'] | None
    external_send_allowed: bool
    monthly_budget: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    monthly_token_limit: int = Field(..., ge=0)

class AIReconcileRequest(ApiBaseModel):
    """仅admin；终态且usage_estimated=true的未知费用可对账一次。同reconciliation_id与完全相同submission重放幂等；同ID不同证据或第二个ID均409。reason/evidence去空白后至少10字符，不自动trim。cache hit不得超过prompt。"""
    model_config = ConfigDict(extra='forbid')
    reconciliation_id: uuid.UUID
    reason: str = Field(..., min_length=10, max_length=1000)
    evidence: str = Field(..., min_length=10, max_length=2000)
    actual_prompt_tokens: Annotated[int, Field(strict=True)] = Field(..., ge=0, le=1000000000, strict=True)
    actual_completion_tokens: Annotated[int, Field(strict=True)] = Field(..., ge=0, le=1000000000, strict=True)
    actual_cache_hit_tokens: Annotated[int, Field(strict=True)] = Field(0, ge=0, le=1000000000, strict=True)
    actual_cost: Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=8)] = Field(..., description='非负有限金额，最大1000000，最多8位小数；接受JSON数值或Decimal字符串。')
    @model_validator(mode='after')
    def meaningful(self):
        if len(self.reason.strip()) < 10 or len(self.evidence.strip()) < 10:
            raise ValueError('Reason and provider billing evidence required')
        if self.actual_cache_hit_tokens > self.actual_prompt_tokens:
            raise ValueError('Invalid cached tokens')
        return self

class AIReconciliationAudit(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    reconciliation_id: uuid.UUID
    at: str
    actor_user_id: int = Field(..., ge=1)
    submission: AIReconcileRequest
    original_usage: AIOriginalUsage
    original_result_usage: AIRequestUsage | None

class AIRecoverResult(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    recovered_request_ids: list[uuid.UUID]
    recovered_count: int = Field(..., ge=0)

AIRequestAccount = Any

class AIRequestAccountAdmin(ApiBaseModel):
    """仅admin全部请求账目；额外owner/账期/原始预留及一次对账审计。reserved_*为该请求原始预留快照，终态不代表仍有活动预留；活动预留查usage。"""
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None
    purpose: Literal['chat', 'test', 'models']
    status: AIRequestStatus
    created_at: datetime
    finished_at: datetime | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    dispatched_calls: int = Field(..., ge=0)
    charged_tokens: int = Field(..., ge=0)
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    usage_estimated: bool
    recovery: AIAccountRecovery | None
    reconciled: bool
    owner_user_id: int = Field(..., ge=1)
    period: str = Field(..., pattern='^\\d{4}-\\d{2}$')
    reserved_tokens: int = Field(..., ge=0)
    reserved_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    reconciliation_history: list[AIReconciliationAudit] = Field(..., max_length=1)

class AIRequestAccountOwner(ApiBaseModel):
    """普通登录用户本人账目。无prompt、answer、内部execution token或证据；recovery元数据不含原执行token。lease/heartbeat为UTC无时区ISO字符串或null。"""
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None
    purpose: Literal['chat', 'test', 'models']
    status: AIRequestStatus
    created_at: datetime
    finished_at: datetime | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    dispatched_calls: int = Field(..., ge=0)
    charged_tokens: int = Field(..., ge=0)
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    usage_estimated: bool
    recovery: AIAccountRecovery | None
    reconciled: bool

class AIRequestList(ApiBaseModel):
    """最近100条，created_at/request_id倒序；无分页及查询参数。普通用户本人；admin全用户。GET同时惰性恢复过期请求。"""
    model_config = ConfigDict(extra='forbid')
    requests: list[AIRequestAccount] = Field(..., max_length=100)
    limit: int

class AIRequestUsage(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    cache_hit_tokens: int = Field(..., ge=0)
    cache_miss_tokens: int = Field(..., ge=0)
    charged_tokens: int = Field(..., ge=0)
    provider_calls: int = Field(..., ge=0)
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    estimated: bool
    currency: str = Field(..., pattern='^[A-Z]{3}$')

class AIResult(ApiBaseModel):
    """pending: answer/usage=null，sources/trace空，error=request_in_progress，不含replayed。首次完成/失败含replayed=false和usage；models发现成功额外models。已结算原ID查询不外发、不重复计费；重新核验当前session、配置revision及全部证据，一致则返回原答案/来源/trace并replayed=true，否则status=failed、隐藏答案/来源/trace并给出authorization_changed、configuration_changed或evidence_unavailable。旧版本无证据请求保守隐藏。失败可有已执行工具trace，成功通常error=null。 恢复终态额外recovery，error=request_recovered；未派发预留释放，已测量保留真实量，unknown保守估算；对账后reconciliation_required=false。"""
    model_config = ConfigDict(extra='forbid')
    status: AIRequestStatus
    request_id: uuid.UUID
    conversation_id: uuid.UUID | None
    answer: str | None
    sources: list[AISource] = Field(..., max_length=40)
    tool_trace: list[AIToolTrace] = Field(..., max_length=8)
    usage: AIRequestUsage | None
    error: AIResultError | None
    replayed: bool = None
    models: list[AIModelMetadata] = Field(None, max_length=200)
    recovery: AIResultRecovery = None

class AIResultError(ApiBaseModel):
    """请求级错误，位于HTTP200 data.error；包括request_in_progress、evidence_unavailable、configuration_changed、authorization_changed、ai_unavailable及provider/工具/限制错误。 恢复/租约错误含request_recovered、execution_fenced、turn_time_limit、accounting_period_changed；错误code保持开放字符串以容纳服务商安全错误。 provider HTTP401=provider_auth_failed、402=provider_insufficient_balance、403=provider_permission_denied、400/422=provider_parameter_invalid、429=provider_rate_limited；这些明确拒绝不估算收费，不重试。5xx=provider_unavailable保守未知。finish_reason=length为provider_output_truncated，content_filter为provider_content_filtered，aborted/insufficient_system_resource为provider_generation_interrupted；隐藏截断答案，保留已测usage。均在HTTP200 data.error中，非本服务HTTP状态。"""
    model_config = ConfigDict(extra='forbid')
    code: str
    message: str

class AIResultRecovery(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    recovered: Literal[True]
    unknown_calls: int = Field(..., ge=0)
    reconciliation_required: bool

class AISettings(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', validate_default=True)
    enabled: bool = False
    provider_name: str = Field('OpenAI-compatible', min_length=1, max_length=64)
    base_url: str = Field('', max_length=255)
    model: str = Field('', max_length=128, pattern='^(?:[A-Za-z0-9_.:/-]{1,128})?$')
    provider_options: dict[str, Any] = {}
    currency: str = Field('USD', pattern='^[A-Z]{3}$')
    input_price_per_million: Annotated[Decimal, Field(gt=0, le=10000, decimal_places=8)] = Field('1', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    cached_input_price_per_million: Annotated[Decimal, Field(ge=0, le=10000, decimal_places=8)] = Field('1', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    output_price_per_million: Annotated[Decimal, Field(gt=0, le=10000, decimal_places=8)] = Field('1', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    monthly_budget: Annotated[Decimal, Field(gt=0, le=1000000, decimal_places=8)] = Field('10', description='接受JSON数值或Decimal字符串；最多8位小数，有限值。响应返回十进制字符串。')
    monthly_token_limit: Annotated[int, Field(strict=True)] = Field(2000000, ge=1000, le=1000000000, strict=True)
    daily_call_limit: Annotated[int, Field(strict=True)] = Field(100, ge=1, le=100000, strict=True)
    user_daily_call_limit: Annotated[int, Field(strict=True)] = Field(20, ge=1, le=10000, strict=True)
    admin_daily_call_limit: Annotated[int, Field(strict=True)] = Field(50, ge=1, le=10000, strict=True)
    max_output_tokens: Annotated[int, Field(strict=True)] = Field(1024, ge=64, le=4096, strict=True)
    max_tool_rounds: Annotated[int, Field(strict=True)] = Field(4, ge=1, le=4, strict=True)
    user_monthly_budget: Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=8)] = Field('10', description='每用户默认月预算，默认10，可为0，最大1000000，最多8位小数；响应Decimal字符串。')
    user_monthly_token_limit: Annotated[int, Field(strict=True)] = Field(2000000, ge=0, le=1000000000, strict=True)
    user_policies: dict[str, AIUserPolicy] = Field({}, description='用户ID字符串到策略的映射。键必须规范正整数且≤9223372036854775807，最多10000项；仅admin可配置。')
    @field_validator('base_url')
    @classmethod
    def endpoint(cls, value):
        return validate_endpoint(value) if value else ''

    @field_validator('model')
    @classmethod
    def model_id(cls, value):
        if value and not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}', value): raise ValueError('Invalid model')
        return value

    @field_validator('provider_options')
    @classmethod
    def options(cls, value):
        if value not in ({}, {'thinking': {'type': 'disabled'}}):
            raise ValueError('Only explicit thinking disabled is supported')
        return value

    @model_validator(mode='after')
    def valid(self):
        if self.enabled and (not self.base_url or not self.model): raise ValueError('Endpoint and discovered model required')
        if self.cached_input_price_per_million > self.input_price_per_million:
            raise ValueError('Cached input price cannot exceed regular input price')
        # This service deliberately supports nonthinking requests only. An empty
        # option object is for compatible providers whose default is nonthinking.
        return self


    @field_validator('user_policies')
    @classmethod
    def policy_keys(cls, value):
        if len(value) > 10000 or any(not re.fullmatch(r'[1-9][0-9]{0,18}', k) or int(k) > 9223372036854775807 for k in value):
            raise ValueError('User policies require canonical positive user IDs')
        return value

class AISource(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: AISourceKind
    id: int = Field(..., ge=1)
    href: str = Field(..., description='服务器生成内部UI链接；transition使用sample_id')

class AIStatus(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    configured: bool

class AITestRequest(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID

class AIToolTrace(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    tool: Literal['search_records', 'record_detail', 'sample_timeline', 'quality_hints', 'unsupported']
    status: Literal['completed', 'denied']
    sources: list[AISource]
    result_bytes: int = Field(..., ge=0)
    read_only: Literal[True]
    origin: Literal['current_context', 'prior_plan', 'model'] = Field(None, description='当前记录服务器预查 / 先前计划按当前权限重执行 / 本轮模型实际工具调用。旧持久化trace可能缺失。')

AITurnResult = Any

class AIUsageSummary(ApiBaseModel):
    """admin当前UTC月全用户账本；含预留与估算，非供应商账单。过期租约惰性恢复；未知已派发费用保守保留，管理员凭证据对账。"""
    model_config = ConfigDict(extra='forbid')
    request_count: int = Field(..., ge=0)
    estimated_requests: int = Field(..., ge=0)
    pending_requests: int = Field(..., ge=0)
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    cache_hit_tokens: int = Field(..., ge=0)
    cache_miss_tokens: int = Field(..., ge=0)
    provider_calls: int = Field(..., ge=0)
    charged_tokens: int = Field(..., ge=0)
    reserved_tokens: int = Field(..., ge=0)
    monthly_token_limit: int = Field(..., ge=0)
    period: str = Field(..., pattern='^\\d{4}-\\d{2}$')
    scope: Literal['all_users']
    currency: str = Field(..., pattern='^[A-Z]{3}$')
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    reserved_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    monthly_budget: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    users: list[AIUserUsage] = Field(..., description='当月有请求的用户分账，按owner_user_id升序；无请求用户不出现。')

class AIUserPolicy(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    monthly_budget: Annotated[Decimal, Field(ge=0, le=1000000, decimal_places=8)] | None = Field(None, description='null或省略继承用户默认额度。')
    monthly_token_limit: Annotated[int, Field(strict=True, ge=0, le=1000000000)] | None = Field(None, ge=0, le=1000000000, description='null或省略继承用户默认额度。')
    research_ai_allowed: bool | None = Field(None, description='null或省略按账户用途取默认值；management科研AI默认拒绝，只有admin显式true允许。')
    external_send_allowed: bool | None = Field(None, description='null或省略按账户用途取默认值；testing默认拒绝外发，只有admin显式true允许，用户同意不能覆盖。')

class AIUserPolicyView(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    monthly_budget: str | None = Field(None, pattern='^\\d+(?:\\.\\d+)?$')
    monthly_token_limit: Annotated[int, Field(strict=True, ge=0, le=1000000000)] | None = Field(None, ge=0, le=1000000000, description='null或省略继承用户默认额度。')
    research_ai_allowed: bool | None = Field(None, description='null或省略按账户用途取默认值；management科研AI默认拒绝，只有admin显式true允许。')
    external_send_allowed: bool | None = Field(None, description='null或省略按账户用途取默认值；testing默认拒绝外发，只有admin显式true允许，用户同意不能覆盖。')

class AIUserUsage(ApiBaseModel):
    """按owner_user_id的当前月分账；已记账包含恢复与对账，预留仅累计pending；预算为覆盖后有效额度。"""
    model_config = ConfigDict(extra='forbid')
    owner_user_id: int = Field(..., ge=1)
    charged_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    charged_tokens: int = Field(..., ge=0)
    reserved_cost: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    reserved_tokens: int = Field(..., ge=0)
    monthly_budget: str = Field(..., pattern='^\\d+(?:\\.\\d+)?$')
    monthly_token_limit: int = Field(..., ge=0)

class AnalysisCalculate(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    sources: list[AnalysisSource] = Field(min_length=1,max_length=20)
    selection: AnalysisSelection = Field(default_factory=lambda: AnalysisSelection())
    before_index: Annotated[int, Field(ge=0,le=19)] | None = None
    after_index: Annotated[int, Field(ge=0,le=19)] | None = None
    confirm_pair: bool = False
    @model_validator(mode='after')
    def source_identity(self):
        keys=[(s.kind,s.id,s.block_index) for s in self.sources]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate sources')
        if (self.before_index is None)!=(self.after_index is None):raise ValueError('Both pair indices required')
        if self.before_index is not None and (not self.confirm_pair or self.before_index==self.after_index or max(self.before_index,self.after_index)>=len(self.sources)):
            raise ValueError('Confirm distinct before/after sources')
        return self

class AnalysisMetric(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    count: int = Field(..., ge=0)
    excluded_nonfinite_or_missing: int = Field(..., ge=0)
    mean: str = Field(None, pattern='^-?\\d+(?:\\.\\d+)?$')
    min: str = Field(None, pattern='^-?\\d+(?:\\.\\d+)?$')
    max: str = Field(None, pattern='^-?\\d+(?:\\.\\d+)?$')
    sd_sample: str | None = Field(None, pattern='^-?\\d+(?:\\.\\d+)?$')
    sd_population: str = Field(None, pattern='^-?\\d+(?:\\.\\d+)?$')

class AnalysisPair(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    pairing_method: Literal['same_xy_coordinate']
    direction: Literal['after - before']
    model_consistent: Literal[True]
    paired_point_count: int = Field(..., ge=0)
    unmatched_before: int = Field(..., ge=0)
    unmatched_after: int = Field(..., ge=0)
    ineligible_before: int = Field(..., ge=0)
    ineligible_after: int = Field(..., ge=0)
    mean_delta_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    mean_before_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    mean_after_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    sd_delta_nm: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    observation: Literal['increase', 'decrease', 'unchanged']
    interpretation: str
    points: list[AnalysisPairPoint]

class AnalysisPairPoint(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    x_mm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    y_mm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    before_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    after_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    delta_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    thickness_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    mse: None
    gof: None
    before_key: str
    after_key: str

class AnalysisPoint(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    x_mm: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    y_mm: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    thickness_nm: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    mse: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    gof: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    point_no: int | None
    source_row: int | None
    source_file_id: int | None
    point_id: int | None
    outlier_note: str | None
    source_sheet: str | None
    source_cell: str | None
    key: str
    included: bool
    is_outlier: bool

class AnalysisReadonlyToolMetadata(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['scientific_analysis']
    readonly: Literal[True]
    external_raw_data: Literal[False]
    function: Literal['app.scientificanalysis.calculate']
    request_schema: dict[str, Any]
    response_projection: list[str]
    requires_authenticated_scope: Literal[True]
    live_ai_registered: Literal[False]

class AnalysisRecordedConditions(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    process_id: int
    row_version: int
    process_code: str
    r1_temp_c: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    r2_temp_c: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    o3_pre_duration_s: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    full_ale_cycles: int | None
    hf_tma_repeats: int | None
    o3_pre_cycles: int | None
    recorded_total_cycles: int | None

class AnalysisResult(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis_version: str
    decimal_precision: int
    rounding: Literal['ROUND_HALF_EVEN']
    request: AnalysisCalculate
    series: list[AnalysisSeries]
    pair: AnalysisPair | None
    persisted: Literal[False]
    limits: dict[str, Any]
    scientific_sources_modified: Literal[False]
    result_sha256: str = Field(..., pattern='^[a-f0-9]{64}$')

class AnalysisSave(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    calculation: AnalysisCalculate
    label: Annotated[str, Field(min_length=1,max_length=100)]

class AnalysisSaveResult(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    result_id: int
    persisted: Literal[True]
    result_sha256: str
    scientific_sources_modified: Literal[False]

class AnalysisSavedRecord(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str
    request: AnalysisCalculate
    result_sha256: str
    analysis_version: str
    sources: list[AnalysisSourceMetadata]
    statistics: list[AnalysisStatistics]
    pair: dict[str, Any] | dict[str, Any]

class AnalysisSavedResult(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    result_id: int
    is_valid: bool
    computed_at: datetime
    record: AnalysisSavedRecord
    scientific_sources_modified: Literal[False]
    invalid_reasons: list[Literal['source_or_result_changed', 'measurement_not_current_or_excluded', 'source_unavailable_or_changed', 'record_invalidated']]
    recomputed_result_sha256: str | None = Field(..., pattern='^[a-f0-9]{64}$')

class AnalysisSelection(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    include_outliers: bool = True
    excluded_points: list[Annotated[str, Field(min_length=1,max_length=80)]] = Field(default_factory=list,max_length=1000)
    reason: Annotated[str, Field(max_length=4000)] = ''
    @model_validator(mode='after')
    def reason_for_exclusion(self):
        if (not self.include_outliers or self.excluded_points) and not self.reason.strip():
            raise ValueError('Exclusion requires an auditable reason')
        if len(set(self.excluded_points)) != len(self.excluded_points):
            raise ValueError('Duplicate exclusions')
        return self

class AnalysisSeries(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    source: AnalysisSourceMetadata
    points: list[AnalysisPoint]
    statistics: AnalysisStatistics
    raw_count: int = Field(..., ge=0)
    included_count: int = Field(..., ge=0)
    excluded_count: int = Field(..., ge=0)
    mapping: dict[str, Any]
    warnings: list[str]

class AnalysisSource(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    kind: Literal['measurement','import_item']
    id: Annotated[int, Field(strict=True, gt=0)]
    block_index: Annotated[int, Field(ge=0, le=15)] = 0
    # Preview-only declarations; never persisted into measurements by analysis.
    sample_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    stage: Literal['initial', 'after_o2_plasma', 'after_o3_pre', 'after_ale', 'after_hf_only', 'after_o3_only', 'intermediate', 'final', 'other'] | None = None
    stage_seq: Annotated[int, Field(ge=0, le=4294967295)] | None = None
    optical_model_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    confirm_associations: bool = False
    expected_row_version: Annotated[int, Field(strict=True, gt=0)] | None = None
    @model_validator(mode='after')
    def formal_identity(self):
        if self.kind == 'measurement' and (self.block_index or any(v is not None for v in (self.sample_id,self.stage,self.stage_seq,self.optical_model_id)) or self.confirm_associations):
            raise ValueError('Formal associations come only from stored measurements')
        return self

class AnalysisSourceMetadata(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['measurement', 'import_item']
    id: int = Field(..., gt=0)
    block_index: int = Field(..., ge=0)
    row_version: int
    label: str
    sample_id: int | None
    stage_seq: int | None
    optical_model_id: int | None
    cumulative_cycles: int | None
    process_id: int | None = None
    source_file_id: int | None = None
    import_item_id: int | None = None
    stage: str | None
    parser: str | None
    parser_version: str | None
    sha256: str | None = None
    quality_flag: str | None = None
    is_current: bool = None
    recorded_conditions: AnalysisRecordedConditions | None = None
    associations_source: Literal['user_confirmed_preview', 'unknown'] = None
    locator: Any = None
    formal_measurements_written: Literal[False] = None
    model_parameter_columns: list[Any]
    units: dict[str, Any]
    points_sha256: str = Field(..., pattern='^[a-f0-9]{64}$')
    optical_model: dict[str, Any] | None
    sample_dependency: dict[str, Any] = Field(None, description='Only present when model applicable_batch_id requires sample batch validation.')

class AnalysisStatistics(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    point_count: int = Field(..., ge=0)
    includes_outliers: bool
    sd_convention: dict[str, Any]
    decimal_precision: int
    rounding: Literal['ROUND_HALF_EVEN']
    db_write_policy: str
    thickness_nm: AnalysisMetric
    mse: AnalysisMetric
    gof: AnalysisMetric

class Attachment(ApiBaseModel):
    """附件登记（图、Origin 工程、报告等非结构化产出）。"""
    attachment_id: int
    file_sha256: str | None = Field(None, pattern='^[a-f0-9]{64}$')
    file_name: str = Field(..., max_length=512)
    rel_path: str | None = Field(None, max_length=1024)
    attachment_type: AttachmentType
    entity_type: EntityType = None
    entity_id: int | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    description: str | None = None
    uploaded_by: int | None = None
    created_at: datetime

class AttachmentCreate(ApiBaseModel):
    file_sha256: str = Field(None, pattern='^[a-f0-9]{64}$')
    file_name: str = Field(..., max_length=512)
    rel_path: str = None
    attachment_type: AttachmentType
    entity_type: EntityType = None
    entity_id: int = None
    mime_type: str = None
    size_bytes: int = None
    description: str = None

class AuditLog(ApiBaseModel):
    """操作审计记录。用于追溯"这个数值是谁改的、什么时候改的"。"""
    audit_id: int
    user_id: int | None = None
    user: UserBrief = None
    action: AuditAction
    entity_type: str = Field(..., description='被操作实体类型')
    entity_id: int | None = None
    field_name: str | None = Field(None, description='被修改的字段名（update 时有值）')
    old_value: str | None = None
    new_value: str | None = None
    client_info: str | None = Field(None, description='客户端标识（IP / UA）')
    occurred_at: datetime

class Batch(ApiBaseModel):
    """沉积批次。**批次是数据可比性的强制隔离边界**——"""
    batch_id: int
    batch_code: str = Field(..., max_length=64, description='批次编码，全局唯一')
    batch_name: str = Field(..., max_length=255)
    material: str = Field(..., max_length=128)
    wafer_size: str | None = Field(None, max_length=32)
    nominal_thickness_nm: Decimal | None = Field(None, description='标称厚度（nm）。为 string 以避免浮点精度损失。')
    deposit_recipe_id: int | None = None
    deposit_date: date | None = None
    deposit_set_temp_c: Decimal | None = Field(None, description='PECVD 设定温度（℃）')
    deposit_actual_temp_c: Decimal | None = Field(None, description='PECVD 实测温度（℃）。**必须与设定值分开记录**——\nISS-02 要求不可据文件名断言温度异常幅度。')
    deposit_gas_flows: dict[str, Any] | None = Field(None, description='沉积气体流量，如 {"SiH4": 20, "NH3": 100, "N2": 200}')
    source_zip: str | None = Field(None, max_length=255)
    source_zip_sha256: str | None = Field(None, pattern='^[a-f0-9]{64}$', description='原始压缩包 SHA-256，用于溯源校验')
    anomaly_flag: bool = Field(..., description='是否为已知异常批次')
    anomaly_note: str | None = Field(None, description='异常描述。**禁止据文件名断言故障机理**（ISS-02）。')
    owner_user_id: int | None = None
    status: BatchStatus
    notes: str | None = None
    created_at: datetime
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本，每次更新递增。')
    archived_at: datetime | None = Field(None, description='独立归档时间；null 表示未归档，不改原有科学状态。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)

class BatchCodeStatus(ApiBaseModel):
    available: bool
    restricted: bool = None
    namespace: str = None
    message: str
    existing: dict[str, Any] = Field(None, description='仅调用者可见时提供批次身份；私有冲突不返回此字段。')
    can_rename: bool = None
    lifecycle: dict[str, Any] = None

class BatchCodeUpdate(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_code: str = Field(..., min_length=1, max_length=64)
    expected_row_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=2000)

class BatchCreate(ApiBaseModel):
    batch_code: str = Field(..., max_length=64)
    batch_name: str = Field(..., max_length=255)
    material: str = Field('PECVD SiNx:H', max_length=128)
    wafer_size: str = Field(None, max_length=32)
    nominal_thickness_nm: Decimal = None
    deposit_recipe_id: int = None
    deposit_date: date = None
    deposit_set_temp_c: Decimal = None
    deposit_actual_temp_c: Decimal = None
    deposit_gas_flows: dict[str, Any] = None
    source_zip: str = None
    source_zip_sha256: str = Field(None, pattern='^[a-f0-9]{64}$')
    anomaly_flag: bool = False
    anomaly_note: str = None
    status: BatchStatus = None
    notes: str = None

class BatchItem(ApiBaseModel):
    """批量创建样品中的单个样品；批次来自路径，不在请求体中。"""
    model_config = ConfigDict(extra='forbid')
    sample_code: str = Field(..., min_length=1, max_length=64)
    sample_type: SampleType = None
    display_label: str | None = Field(None, max_length=128)
    nominal_thickness_nm: Decimal | None = None
    size_desc: str | None = Field(None, max_length=64)
    cut_position: str | None = Field(None, max_length=128)
    surface_state: str | None = Field(None, max_length=128)
    pre_treatment: str | None = Field(None, max_length=255)
    status: SampleStatus = None
    exclude_from_analysis: bool = False
    exclude_reason: str | None = Field(None, max_length=20000)
    notes: str | None = Field(None, max_length=20000)

class BatchLinkCreate(ApiBaseModel):
    """一次绑定 1–50 个样品到同一执行；公共附加字段对每条相同。"""
    model_config = ConfigDict(extra='forbid')
    sample_ids: list[Annotated[int, Field(gt=0)]] = Field(..., min_length=1, max_length=50)
    chamber_position: str | None = Field(None, max_length=64)
    o3_pre_cycles: int | None = Field(None, ge=0, le=4294967295)
    hf_tma_repeats: int | None = Field(None, ge=0, le=4294967295)
    full_ale_cycles: int | None = Field(None, ge=0, le=4294967295)
    is_control: bool = False
    sample_role_note: str | None = Field(None, max_length=20000)

class BatchSampleCreate(ApiBaseModel):
    """在一个批次下原子创建 1–50 个样品；sample_code 必填且全局唯一，重复或校验失败整批回滚。"""
    model_config = ConfigDict(extra='forbid')
    request_key: str | None = Field(None, min_length=16, max_length=64, description='可选创建意图键；相同键与内容重试返回原样品，修改内容则冲突。')
    parent_sample_id: int | None = Field(None, gt=0, description='可选；必须属于该批次且为母片/整片。')
    items: list[BatchItem] = Field(..., min_length=1, max_length=50)

class BatchUpdate(ApiBaseModel):
    """批次更新（部分更新，仅传需修改字段）"""
    batch_name: str = None
    wafer_size: str | None = None
    nominal_thickness_nm: str | None = None
    deposit_set_temp_c: str | None = None
    deposit_actual_temp_c: str | None = None
    deposit_gas_flows: dict[str, Any] | None = None
    anomaly_flag: bool = None
    anomaly_note: str | None = None
    status: BatchStatus = None
    notes: str | None = None
    expected_row_version: int = Field(None, ge=1, description='可选；提供时必须匹配当前 row_version，否则返回 409。省略时保持原有更新行为。')

class ChangePasswordRequest(ApiBaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

class ChartTemplate(ApiBaseModel):
    """预置图表模板。前端可直接按模板渲染，无需自行拼装数据结构。"""
    template_code: str
    name: str
    description: str | None = None
    chart_type: ChartType
    data_source: str = Field(..., description='数据来源标识（对应各数据接口）')
    required_params: list[str] = Field(None, description='该模板必填的参数名')

class ChemistrySpecies(ApiBaseModel):
    """化学体系下的物种（前驱体/反应物/吹扫/载气等）。"""
    species_id: int
    system_id: int
    species_code: str = Field(..., max_length=64)
    species_name: str = Field(..., max_length=255)
    formula: str | None = Field(None, max_length=64)
    role: SpeciesRole
    default_unit: str | None = Field(None, max_length=24)
    notes: str | None = Field(None, max_length=20000)
    created_at: datetime = None

class ChemistryStepTemplate(ApiBaseModel):
    """可复用步骤模板；steps 为有序 JSON 数组，至少 1 条。"""
    template_id: int
    system_id: int
    template_code: str = Field(..., max_length=64)
    template_name: str = Field(..., max_length=255)
    description: str | None = Field(None, max_length=20000)
    steps: list[TemplateStep] = Field(..., min_length=1, max_length=200)
    created_at: datetime = None
    updated_at: datetime = None

class ChemistrySystem(ApiBaseModel):
    """通用化学体系。详情响应额外内嵌 species[]、templates[] 与 owner。"""
    system_id: int
    system_code: str = Field(..., max_length=64)
    system_name: str = Field(..., max_length=255)
    description: str | None = Field(None, max_length=20000)
    status: SystemStatus
    owner_user_id: int | None = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新体系或其子记录时递增。')
    created_at: datetime = None
    updated_at: datetime = None
    species: list[ChemistrySpecies] = None
    templates: list[ChemistryStepTemplate] = None
    owner: UserBrief | None = None

class ChemistrySystemCreate(ApiBaseModel):
    """创建化学体系；owner_user_id 由服务端确定。"""
    model_config = ConfigDict(extra='forbid')
    system_code: str = Field(..., min_length=1, max_length=64)
    system_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=20000)
    status: SystemStatus = None

class ChemistrySystemUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）。"""
    model_config = ConfigDict(extra='forbid')
    system_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=20000)
    status: SystemStatus = None
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配当前 row_version，否则 409。')

class CreateInvitationRequest(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    role: InvitationRole = Field('viewer', validate_default=True)
    expires_in_hours: Annotated[int, Field(strict=True)] = Field(72, ge=1, le=168, strict=True)
    account_purpose: OrdinaryAccountPurpose = Field('research', validate_default=True)

class CreateInvitationResponse(ApiBaseModel):
    invitation_id: int
    role: InvitationRole
    created_by: int
    expires_at: datetime
    used_by: int | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    account_purpose: OrdinaryAccountPurpose
    invite_code: str = Field(..., description='仅创建时返回一次；列表与后续查询不再返回。')

class CreateUserRequest(ApiBaseModel):
    """仅admin创建用户；role默认viewer、account_purpose默认research。创建admin且省略account_purpose时自动management；显式不匹配返回422。"""
    model_config = ConfigDict(extra='forbid')
    username: str = Field(..., min_length=3, max_length=64, pattern='^[A-Za-z][A-Za-z0-9_.-]{2,63}$', description='登录名。字母开头，可含字母数字与 `_ . -`')
    password: str = Field(..., min_length=8, max_length=128, description='密码至少 8 位，服务端使用 Argon2id 哈希存储。')
    display_name: str = Field(None, max_length=128, description='显示名')
    email: str = Field(None, max_length=255)
    role: UserRole = Field('viewer', validate_default=True)
    status: UserStatus = Field('active', validate_default=True)
    notes: str | None = Field(None, description='备注')
    account_purpose: AccountPurpose = Field('research', validate_default=True)

    @model_validator(mode='after')
    def role_purpose(self):
        if self.role == 'admin' and 'account_purpose' not in self.model_fields_set:
            self.account_purpose = 'management'
        if not ((self.role == 'admin' and self.account_purpose == 'management') or (self.role in ('operator', 'viewer') and self.account_purpose in ('research', 'testing'))):
            raise ValueError('Account purpose must match role')
        return self

class CurrentUser(ApiBaseModel):
    """当前用户、实际授权权限与数据范围。前端仅用于界面显示，服务端独立执行权限及所有权过滤；未实现共享。"""
    user: User
    permissions: list[str] = Field(..., description='权限标识列表（见 docs/permissions.md）')
    data_scope: Literal['all', 'own'] = Field(..., description='保留all/own：all为管理员全局范围；own为本人范围；admin_global_scope是独立可选布尔约定。')
    environment: Environment
    admin_global_scope: bool = Field(None, description='管理员全局数据范围标志；true表示全局，false表示本人。可选扩展字段，按本字段约定；不改变data_scope现有枚举。')

class CustomParameter(ApiBaseModel):
    """单个自定义参数项；value 为数字时统一按字符串存储与回传。"""
    model_config = ConfigDict(extra='forbid')
    value: str | float | None = None
    unit: str | None = Field(None, max_length=24)
    note: str | None = Field(None, max_length=255)

CustomParameters = Any

class DashboardRecentActivity(ApiBaseModel):
    recent_samples: list[SampleBrief] = None
    recent_processes: list[ProcessBrief] = None
    recent_measurements: list[MeasurementBrief] = None

class DashboardRecentData(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    generated_at: datetime
    items: list[DashboardRecentDataItem]

DashboardRecentDataItem = Any

DashboardRecentExperimentItem = Any

class DashboardRecentExperiments(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    generated_at: datetime
    items: list[DashboardRecentExperimentItem]

class DashboardRecentImportJob(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    status: str
    hint: str | None
    occurred_at: datetime | None
    kind: Literal['import_job']
    path: Literal['/imports']
    query: dict[str, Any]

class DashboardRecentMeasurement(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    status: str
    hint: str | None
    occurred_at: datetime | None
    kind: Literal['measurement']
    path: Literal['/measurements']
    query: dict[str, Any]
    stage: MeasurementStage
    sample_id: int = Field(..., gt=0)

class DashboardRecentPlan(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: int = Field(..., gt=0)
    code: str
    title: str
    status: str
    batch_id: int | None = Field(..., gt=0)
    updated_at: datetime | None
    can_continue: bool
    continue_label: str
    kind: Literal['plan']
    path: Literal['/plans']
    query: dict[str, Any]
    continue_path: Literal['/plans', '/processes']
    continue_query: dict[str, Any] | dict[str, Any]

class DashboardRecentProcess(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: int = Field(..., gt=0)
    code: str
    title: str
    status: str
    batch_id: int | None = Field(..., gt=0)
    updated_at: datetime | None
    can_continue: bool
    continue_label: str
    kind: Literal['process']
    plan_id: int | None = Field(..., gt=0)
    archived: bool
    path: Literal['/processes']
    query: dict[str, Any]
    continue_path: Literal['/processes']
    continue_query: dict[str, Any]

class DashboardRecentSourceFile(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    status: str
    hint: str | None
    occurred_at: datetime | None
    kind: Literal['source_file']
    path: Literal['/source-files']
    query: dict[str, Any]
    size_bytes: int | None = Field(..., ge=0)

class DashboardSummary(ApiBaseModel):
    """首页概况统计。"""
    generated_at: datetime
    batch_count: int = None
    sample_count: int = None
    sample_excluded_count: int = Field(None, description='被排除出分析的样品数')
    process_count: int = None
    measurement_count: int = Field(None, description='当前有效测量数（不含被取代）')
    derived_result_count: int = None
    source_file_count: int = None
    instrument_dataset_count: int = None
    open_issue_count: int = Field(None, description='未关闭问题数')
    open_issue_high_count: int = Field(None, description='高优先级未关闭问题数')
    finding_count: int = None
    finding_hypothesis_count: int = Field(None, description='仍为机理假设（未证实）的结论数')

class DashboardTodo(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    generated_at: datetime
    total: int = Field(..., ge=0)
    counts: dict[str, Any]
    items: list[DashboardTodoItem]

class DashboardTodoImportFailure(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['import_failure']
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    detail: str
    status: str
    updated_at: datetime | None
    path: Literal['/imports']
    query: dict[str, Any]

class DashboardTodoImportPending(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['import_pending']
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    detail: str
    status: str
    updated_at: datetime | None
    path: Literal['/imports']
    query: dict[str, Any]

class DashboardTodoIssue(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['issue']
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    detail: str
    status: str
    updated_at: datetime | None
    path: None
    query: None
    severity: str

DashboardTodoItem = Any

class DashboardTodoMeasurementReview(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['measurement_review']
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    detail: str
    status: str
    updated_at: datetime | None
    path: Literal['/measurements']
    query: dict[str, Any]

class DashboardTodoPlanWithoutProcess(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['plan_without_process']
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    detail: str
    status: str
    updated_at: datetime | None
    path: Literal['/plans']
    query: dict[str, Any]

class DashboardTodoProcessLog(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['process_log']
    entity_id: int = Field(..., gt=0)
    code: str | None
    title: str
    detail: str
    status: str
    updated_at: datetime | None
    path: Literal['/processes']
    query: dict[str, Any]

class DashboardUpcomingPlan(ApiBaseModel):
    plan_id: int = None
    plan_code: str = None
    title: str = None
    planned_start: date | None = None
    planned_end: date | None = None
    priority: PlanPriority = None
    status: PlanStatus = None
    owner: UserBrief = None

class DataQualityAlert(ApiBaseModel):
    """数据质量提示。服务端主动识别的问题，例如："""
    alert_type: Literal['cross_model_comparison', 'high_mse_measurement', 'superseded_baseline', 'unresolved_instrument_mapping', 'excluded_sample_used', 'missing_intermediate_measurement', 'model_inconsistent_derived']
    severity: Literal['high', 'medium', 'low']
    message: str = Field(..., description='面向用户的说明（中文）')
    entity_type: EntityType = None
    entity_id: int | None = None
    entity_code: str | None = Field(None, description='实体编码，便于前端跳转')

class DerivedResult(ApiBaseModel):
    """派生分析结果。"""
    result_id: int
    result_code: str = Field(..., max_length=128)
    result_kind: ResultKind
    sample_id: int
    sample_code: str | None = None
    before_measurement_id: int | None = None
    after_measurement_id: int | None = None
    process_id: int | None = None
    value_nm: Decimal | None = Field(None, description='数值（单位见 value_unit）')
    value_unit: Literal['nm', 'A_per_cycle', 'pct', None] | None = None
    value_sd_nm: Decimal | None = Field(None, description='空间 SD（**非独立重复误差**）')
    cycles_basis: int | None = Field(None, description='计算速率所用循环基数')
    pairing_method: PairingMethod = None
    paired_point_count: int | None = None
    model_consistent: bool | None = Field(None, description='前后测量是否使用同一光学模型。\n`false` 表示该结果是**跨模型相减**，需谨慎解释。\n`null` 表示无法判定（未记录模型）。')
    model_warning: str | None = Field(None, description='由服务端根据 model_consistent 自动生成的警告文字')
    is_valid: bool = Field(..., description='结果是否有效。\n当源测量被取代时置 false，提示需重算。')
    evidence_level: EvidenceLevel
    computation_note: str | None = Field(None, description='计算说明与限制')
    computed_at: datetime | None = None
    computed_by: str | None = None
    created_at: datetime = None

class DerivedResultCreate(ApiBaseModel):
    result_code: str = Field(..., max_length=128)
    result_kind: ResultKind
    sample_id: int
    before_measurement_id: int = None
    after_measurement_id: int = None
    process_id: int = None
    value_nm: str = None
    value_unit: Literal['nm', 'A_per_cycle', 'pct'] = None
    value_sd_nm: str = None
    cycles_basis: int = None
    pairing_method: PairingMethod = None
    paired_point_count: int = None
    evidence_level: EvidenceLevel = None
    computation_note: str = None
    computed_by: str = None

class DerivedResultDetail(ApiBaseModel):
    result_id: int
    result_code: str = Field(..., max_length=128)
    result_kind: ResultKind
    sample_id: int
    sample_code: str | None = None
    before_measurement_id: int | None = None
    after_measurement_id: int | None = None
    process_id: int | None = None
    value_nm: Decimal | None = Field(None, description='数值（单位见 value_unit）')
    value_unit: Literal['nm', 'A_per_cycle', 'pct', None] | None = None
    value_sd_nm: Decimal | None = Field(None, description='空间 SD（**非独立重复误差**）')
    cycles_basis: int | None = Field(None, description='计算速率所用循环基数')
    pairing_method: PairingMethod = None
    paired_point_count: int | None = None
    model_consistent: bool | None = Field(None, description='前后测量是否使用同一光学模型。\n`false` 表示该结果是**跨模型相减**，需谨慎解释。\n`null` 表示无法判定（未记录模型）。')
    model_warning: str | None = Field(None, description='由服务端根据 model_consistent 自动生成的警告文字')
    is_valid: bool = Field(..., description='结果是否有效。\n当源测量被取代时置 false，提示需重算。')
    evidence_level: EvidenceLevel
    computation_note: str | None = Field(None, description='计算说明与限制')
    computed_at: datetime | None = None
    computed_by: str | None = None
    created_at: datetime = None
    before_measurement: MeasurementBrief = None
    after_measurement: MeasurementBrief = None
    sample: SampleBrief = None
    process: ProcessBrief = None

class Environment(ApiBaseModel):
    """部署环境标识，只由ALE_ENVIRONMENT、ALE_ENVIRONMENT_LABEL、ALE_INSTANCE_ID配置提供，不能从账户用途推断。"""
    model_config = ConfigDict(extra='forbid')
    name: Literal['production', 'testing']
    label: str
    instance_id: str

class ExperimentPlan(ApiBaseModel):
    """实验计划。位于实验执行之前，一个计划可派生多个执行。"""
    plan_id: int
    plan_code: str = Field(..., max_length=64)
    title: str = Field(..., max_length=255)
    objective: str | None = Field(None, description='实验目的')
    hypothesis: str | None = Field(None, description='待验证假设')
    design_note: str | None = Field(None, description='变量设计与对照组设置')
    planned_start: date | None = None
    planned_end: date | None = None
    priority: PlanPriority
    status: PlanStatus
    owner_user_id: int | None = None
    batch_id: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    process_flow: ProcessFlow | None = Field(None, description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archive_previous_status: str | None = Field(..., max_length=24)

class ExperimentPlanCreate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    plan_code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    objective: str | None = Field(None, max_length=20000)
    hypothesis: str | None = Field(None, max_length=20000)
    design_note: str | None = Field(None, max_length=20000)
    planned_start: date | None = None
    planned_end: date | None = None
    priority: Literal['high', 'normal', 'low'] = 'normal'
    status: Literal['draft', 'approved', 'running', 'completed', 'abandoned'] = 'draft'
    batch_id: int | None = Field(None, gt=0)
    notes: str | None = Field(None, max_length=20000)

class ExperimentPlanDetail(ApiBaseModel):
    plan_id: int
    plan_code: str = Field(..., max_length=64)
    title: str = Field(..., max_length=255)
    objective: str | None = Field(None, description='实验目的')
    hypothesis: str | None = Field(None, description='待验证假设')
    design_note: str | None = Field(None, description='变量设计与对照组设置')
    planned_start: date | None = None
    planned_end: date | None = None
    priority: PlanPriority
    status: PlanStatus
    owner_user_id: int | None = None
    batch_id: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    process_flow: ProcessFlow | None = Field(None, description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archive_previous_status: str | None = Field(..., max_length=24)
    owner: UserBrief | None
    batch: Batch | None
    processes: list[ProcessDetail] = Field(..., description='该计划派生的可见执行及逐片科研结果')
    process_count: int
    steps: list[PlanStep]

class ExperimentPlanUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    title: str = Field(None, min_length=1, max_length=255)
    objective: str | None = Field(None, max_length=20000)
    hypothesis: str | None = Field(None, max_length=20000)
    design_note: str | None = Field(None, max_length=20000)
    planned_start: date | None = None
    planned_end: date | None = None
    priority: Literal['high', 'normal', 'low'] = None
    status: Literal['draft', 'approved', 'running', 'completed', 'abandoned'] = None
    batch_id: int | None = Field(None, gt=0)
    notes: str | None = Field(None, max_length=20000)
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。')

class Finding(ApiBaseModel):
    """研究结论台账。**强制区分实测观察与机理假设。**"""
    finding_id: int
    finding_code: str = Field(..., max_length=32)
    statement: str
    evidence_level: EvidenceLevel
    support_sample_count: int | None = Field(None, description='支撑样品数。\n使「这条结论只有一个样片支撑」成为可查询事实，\n而非靠人记住。')
    is_confirmed: bool
    scope_note: str | None = Field(None, description='适用边界与禁止外推说明')
    created_by: int | None = None
    created_at: datetime = None
    updated_at: datetime = None

class FindingCreate(ApiBaseModel):
    finding_code: str
    statement: str
    evidence_level: EvidenceLevel
    support_sample_count: int = None
    is_confirmed: bool = False
    scope_note: str = None

class FindingUpdate(ApiBaseModel):
    statement: str = None
    evidence_level: EvidenceLevel = None
    support_sample_count: int = None
    is_confirmed: bool = None
    scope_note: str = None

class FlowNode(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=False, str_strip_whitespace=True)
    kind: Literal['group', 'step']
    id: Annotated[str, Field(min_length=1, max_length=80)]
    name: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    repeat: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None = None
    step_id: Annotated[int, Field(strict=True, gt=0)] | Annotated[str, Field(min_length=1, max_length=80)] | None = None
    children: Annotated[list['FlowNode'], Field(max_length=500)] = Field(default_factory=list)

    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'step' and (self.step_id is None or self.children or self.name is not None or self.repeat is not None):
            raise ValueError('A step node contains only its ID and step reference')
        if self.kind == 'group' and (self.step_id is not None or not self.name):
            raise ValueError('A group needs a name and cannot contain a step reference')
        return self

class GridStep(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=False, str_strip_whitespace=False)
    key: Annotated[str, Field(min_length=1,max_length=80)]
    step_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    step_kind: Annotated[str, Field(min_length=1, max_length=128)]
    step_name: Annotated[str, Field(max_length=128)] | None = None
    parameter_snapshot: ParameterSnapshot
    plan_step_id: Annotated[int, Field(strict=True, gt=0)] | None = None

class ImportAssociationOptions(ApiBaseModel):
    sample: Sample
    processes: list[ImportProcessOption]
    baseline_measurements: list[ImportBaselineOption]

class ImportBaselineOption(ApiBaseModel):
    measurement_id: int
    measurement_code: str
    stage: MeasurementStage
    stage_seq: int
    optical_model_id: int | None

class ImportChoice(ApiBaseModel):
    """import 必须显式选择 sample/stage（stage_seq 留空由系统在样品锁下分配） 并确认单位与关联；process 必须绑定到 sample。重复内容必须 confirm_duplicate=true 且提供 duplicate_reason；不自动 supersede。配对基线必须同样品且 current，initial 不可指定基线；模型不一致只给 warning。original_only 可不关联样品；有关联时也必须确认。skip 不建科学记录。"""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    item_id: int = Field(..., gt=0)
    action: Literal['import', 'original_only', 'skip']
    sample_id: int | None = Field(None, gt=0)
    process_id: int | None = Field(None, gt=0)
    optical_model_id: int | None = Field(None, gt=0)
    measured_at: datetime | None = Field(None, description='用户有依据填写的实际测量时间；未知留空，不取上传时间。')
    pair_item_id: int = Field(None, ge=1, description='本次提交中明确选择的同样品单块初始测量文件项；与 pair_measurement_id 互斥。')
    pair_measurement_id: int | None = Field(None, gt=0)
    stage: Literal['initial', 'after_o2_plasma', 'after_o3_pre', 'after_ale', 'after_hf_only', 'after_o3_only', 'intermediate', 'final', 'other'] | None = None
    stage_seq: int | None = Field(None, ge=0, le=4294967295)
    measurement_code: str | None = Field(None, min_length=1, max_length=80)
    confirm_units: bool = False
    confirm_associations: bool = False
    confirm_duplicate: bool = False
    duplicate_reason: str | None = Field(None, min_length=1, max_length=4000)
    notes: str | None = Field(None, max_length=10000)

class ImportConfirmation(ApiBaseModel):
    """item_id 不得重复；按选中项原子确认；未选项 pending；相同规范化请求含版本号重放已保存结果，不同旧版本返回409。"""
    model_config = ConfigDict(extra='forbid')
    expected_row_version: int = Field(..., gt=0)
    items: list[ImportChoice] = Field(..., min_length=1, max_length=20)

    @model_validator(mode='after')
    def unique_items(self):
        if len({getattr(item, 'item_id') for item in self.items}) != len(self.items):
            raise ValueError('Duplicate item_id')
        return self

class ImportConfirmationRecord(ApiBaseModel):
    job_id: int
    confirmation_hash: str
    result: ImportConfirmationResult

class ImportConfirmationResult(ApiBaseModel):
    job_id: int = Field(..., gt=0)
    row_version: int = Field(..., gt=0)
    status: ImportJobStatus
    pending_count: int = Field(..., ge=0)
    items: list[ImportItemResult]

class ImportDeleteResult(ApiBaseModel):
    job_id: int
    deleted: Literal[True]
    cleanup: str

class ImportItem(ApiBaseModel):
    item_id: int
    job_id: int
    filename: str
    sha256: str
    parse_result: ImportParseResult
    confirmation: ImportChoice | None
    status: Literal['pending', 'imported', 'original_only', 'skipped']
    result: ImportItemResult | None
    created_at: datetime
    suggestions: ImportSuggestions

class ImportItemResult(ApiBaseModel):
    item_id: int = Field(..., gt=0)
    action: Literal['import', 'original_only', 'skip']
    measurement_ids: list[Annotated[int, Field(gt=0)]]
    warnings: list[str]
    source_file_id: int = Field(None, gt=0)

class ImportJob(ApiBaseModel):
    job_id: int
    owner_user_id: int
    status: Literal['draft', 'completed']
    row_version: int
    created_at: datetime

class ImportJobDetail(ApiBaseModel):
    job_id: int
    owner_user_id: int
    status: Literal['draft', 'completed']
    row_version: int
    created_at: datetime
    items: list[ImportItem]

class ImportParseResult(ApiBaseModel):
    type: Literal['unsupported', 'eoptics', 'xps_chart_configuration']
    parser: str
    version: str
    status: Literal['original_only', 'rejected', 'needs_confirmation', 'parsed']
    blocks: list[ParserBlock]
    warnings: list[ParserIssue]
    blocking_issues: list[ParserIssue]
    filename_hints: dict[str, Any]
    source: dict[str, Any]
    preview_metadata: dict[str, Any] = None

class ImportPreviewRequest(ApiBaseModel):
    """multipart files[]；1–20 个文件；每个 <=20 MiB，总计 <=100 MiB；不接收其他字段。"""
    model_config = ConfigDict(extra='forbid')
    files: list[str] = Field(..., alias='files[]', min_length=1, max_length=20)

class ImportProcessOption(ApiBaseModel):
    process_id: int
    process_code: str

class ImportSampleOption(ApiBaseModel):
    sample_id: int
    sample_code: str
    display_label: str | None
    batch_code: str

class ImportSuggestions(ApiBaseModel):
    """始终手动选关联；候选仅限上传者自己的样品（含 admin），任务始终个人可见。"""
    requires_manual_selection: bool
    association_is_fact: bool
    warnings: list[str]
    samples: list[dict[str, Any]]
    optical_models: list[dict[str, Any]]

class InstrumentChannel(ApiBaseModel):
    """仪器信号通道。"""
    channel_id: int
    dataset_id: int
    channel_code: str = Field(..., max_length=64)
    channel_label: str | None = Field(None, max_length=128)
    channel_type: ChannelType
    element: str | None = Field(None, max_length=16, description='元素符号')
    transition: str | None = Field(None, max_length=32, description='轨道')
    mass_charge: Decimal | None = Field(None, description='RGA 的 m/z')
    x_unit: Literal['binding_energy_eV', 'kinetic_energy_eV', 'mz', 'angle_deg', 'time_s', None] | None = None
    y_unit: Literal['counts_per_s', 'ion_current_A', 'intensity', None] | None = None
    peak_center: Decimal | None = Field(None, description='峰位（如 XPS 结合能 eV）')
    peak_height: Decimal | None = None
    fwhm: Decimal | None = None
    peak_area: Decimal | None = None
    extra_json: dict[str, Any] | None = Field(None, description='仪器特有属性')
    created_at: datetime = None
    datapoints: list[InstrumentDatapoint] = None

class InstrumentChannelCreate(ApiBaseModel):
    channel_code: str
    channel_label: str = None
    channel_type: ChannelType
    element: str = None
    transition: str = None
    mass_charge: str = None
    x_unit: str = None
    y_unit: str = None
    peak_center: str = None
    peak_height: str = None
    fwhm: str = None
    peak_area: str = None
    extra_json: dict[str, Any] = None
    datapoints: list[InstrumentDatapointCreate] = Field(None, description='可随通道一并提交数据点')

class InstrumentDatapoint(ApiBaseModel):
    datapoint_id: int
    channel_id: int
    point_index: int = Field(..., description='点序号')
    x_value: Decimal | None = None
    y_value: Decimal | None = None

class InstrumentDatapointCreate(ApiBaseModel):
    point_index: int
    x_value: str = None
    y_value: str = None

class InstrumentDataset(ApiBaseModel):
    dataset_id: int
    dataset_code: str = Field(..., max_length=96)
    instrument_type: InstrumentType
    tool_id: int | None = None
    sample_id: int | None = None
    process_id: int | None = None
    measurement_id: int | None = Field(None, description='若与某次椭偏测量对应同一阶段')
    batch_id: int | None = None
    title: str | None = Field(None, max_length=255)
    external_ref: str | None = Field(None, max_length=128, description='仪器侧编号')
    acquired_at: datetime | None = None
    operator_user_id: int | None = None
    source_file_id: int | None = None
    acquisition_params: dict[str, Any] | None = Field(None, description='采集参数（通能、阳极电压、束流等）')
    sample_mapping_status: SampleMappingStatus
    mapping_note: str | None = None
    created_at: datetime = None

class InstrumentDatasetCreate(ApiBaseModel):
    dataset_code: str = Field(..., max_length=96)
    instrument_type: InstrumentType
    tool_id: int = None
    sample_id: int = None
    process_id: int = None
    measurement_id: int = None
    batch_id: int = None
    title: str = None
    external_ref: str = None
    acquired_at: datetime = None
    source_file_id: int = None
    acquisition_params: dict[str, Any] = None
    sample_mapping_status: SampleMappingStatus = None
    mapping_note: str = None

class InstrumentDatasetDetail(ApiBaseModel):
    dataset_id: int
    dataset_code: str = Field(..., max_length=96)
    instrument_type: InstrumentType
    tool_id: int | None = None
    sample_id: int | None = None
    process_id: int | None = None
    measurement_id: int | None = Field(None, description='若与某次椭偏测量对应同一阶段')
    batch_id: int | None = None
    title: str | None = Field(None, max_length=255)
    external_ref: str | None = Field(None, max_length=128, description='仪器侧编号')
    acquired_at: datetime | None = None
    operator_user_id: int | None = None
    source_file_id: int | None = None
    acquisition_params: dict[str, Any] | None = Field(None, description='采集参数（通能、阳极电压、束流等）')
    sample_mapping_status: SampleMappingStatus
    mapping_note: str | None = None
    created_at: datetime = None
    channels: list[InstrumentChannel] = None

class InstrumentDatasetUpdate(ApiBaseModel):
    sample_id: int = None
    process_id: int = None
    measurement_id: int = None
    title: str = None
    external_ref: str = None
    acquired_at: datetime = None
    acquisition_params: dict[str, Any] = None
    sample_mapping_status: SampleMappingStatus = None
    mapping_note: str = None

class Invitation(ApiBaseModel):
    """邀请安全视图，不返回邀请码或其哈希。 用途只能research/testing，注册者继承邀请角色与用途。"""
    invitation_id: int
    role: InvitationRole
    created_by: int
    expires_at: datetime
    used_by: int | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    account_purpose: OrdinaryAccountPurpose

class Issue(ApiBaseModel):
    """问题台账。对应交接文档 ISS-01 至 ISS-10。"""
    issue_id: int
    issue_code: str = Field(..., max_length=32)
    title: str = Field(..., max_length=255)
    severity: IssueSeverity
    status: IssueStatus
    observed: str | None = Field(None, description='现象与证据')
    effect: str | None = Field(None, description='对结论的影响')
    action: str | None = Field(None, description='交接处理措施')
    avoid: str | None = Field(None, description='禁止误用条款。\n例：「严禁纳入常规 HF-only 速率均值」\n    「不可将 O2 plasma 的 30sccm 误记为 O3 发生器供气流量」')
    opened_at: date | None = None
    closed_at: date | None = None
    owner_user_id: int | None = None
    linked_entity_count: int | None = Field(None, description='关联实体数量（服务端聚合）')
    created_at: datetime = None
    updated_at: datetime = None

class IssueCreate(ApiBaseModel):
    issue_code: str = Field(..., max_length=32)
    title: str = Field(..., max_length=255)
    severity: IssueSeverity = None
    status: IssueStatus = None
    observed: str = None
    effect: str = None
    action: str = None
    avoid: str = None
    opened_at: date = None
    owner_user_id: int = None

class IssueDetail(ApiBaseModel):
    issue_id: int
    issue_code: str = Field(..., max_length=32)
    title: str = Field(..., max_length=255)
    severity: IssueSeverity
    status: IssueStatus
    observed: str | None = Field(None, description='现象与证据')
    effect: str | None = Field(None, description='对结论的影响')
    action: str | None = Field(None, description='交接处理措施')
    avoid: str | None = Field(None, description='禁止误用条款。\n例：「严禁纳入常规 HF-only 速率均值」\n    「不可将 O2 plasma 的 30sccm 误记为 O3 发生器供气流量」')
    opened_at: date | None = None
    closed_at: date | None = None
    owner_user_id: int | None = None
    linked_entity_count: int | None = Field(None, description='关联实体数量（服务端聚合）')
    created_at: datetime = None
    updated_at: datetime = None
    links: list[IssueLink] = None

class IssueLink(ApiBaseModel):
    link_id: int
    issue_id: int
    entity_type: EntityType
    entity_id: int
    relation: Literal['related', 'caused_by', 'blocked_by', 'evidence_for']
    note: str | None = None
    created_at: datetime = None

class IssueLinkCreate(ApiBaseModel):
    entity_type: EntityType
    entity_id: int
    relation: Literal['related', 'caused_by', 'blocked_by', 'evidence_for'] = 'related'
    note: str = None

class IssueUpdate(ApiBaseModel):
    title: str = None
    severity: IssueSeverity = None
    status: IssueStatus = None
    observed: str = None
    effect: str = None
    action: str = None
    avoid: str = None
    closed_at: date = None
    owner_user_id: int = None

class LifecycleApply(ApiBaseModel):
    """One lifecycle action; the reason is required for void and optional otherwise."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    preview_token: Annotated[str, Field(min_length=64, max_length=64)]
    operation_id: Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{16,64}$')]
    sample_versions: dict[int, Annotated[int, Field(ge=1, strict=True)]] = {}
    action: Literal['archive', 'archive_with_dependents', 'void', 'delete', 'restore']
    expected_row_version: Annotated[int, Field(ge=1, strict=True)]
    reason: Annotated[str, Field(max_length=2000)] | None = None
    include_sample_ids: Annotated[list[Annotated[int, Field(gt=0, strict=True)]], Field(max_length=50)] | None = None

    @field_validator('reason', mode='before')
    @classmethod
    def strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


LifecycleApplyResult = Any

class LifecycleBatch(ApiBaseModel):
    """沉积批次。**批次是数据可比性的强制隔离边界**——"""
    model_config = ConfigDict(extra='forbid')
    batch_id: int
    batch_code: str = Field(..., max_length=64, description='批次编码，全局唯一')
    batch_name: str = Field(..., max_length=255)
    material: str = Field(..., max_length=128)
    wafer_size: str | None = Field(..., max_length=32)
    nominal_thickness_nm: Decimal | None = Field(..., description='标称厚度（nm）。为 string 以避免浮点精度损失。')
    deposit_recipe_id: int | None
    deposit_date: date | None
    deposit_set_temp_c: Decimal | None = Field(..., description='PECVD 设定温度（℃）')
    deposit_actual_temp_c: Decimal | None = Field(..., description='PECVD 实测温度（℃）。**必须与设定值分开记录**——\nISS-02 要求不可据文件名断言温度异常幅度。')
    deposit_gas_flows: dict[str, Any] | None = Field(..., description='沉积气体流量，如 {"SiH4": 20, "NH3": 100, "N2": 200}')
    source_zip: str | None = Field(..., max_length=255)
    source_zip_sha256: str | None = Field(..., pattern='^[a-f0-9]{64}$', description='原始压缩包 SHA-256，用于溯源校验')
    anomaly_flag: bool | int
    anomaly_note: str | None = Field(..., description='异常描述。**禁止据文件名断言故障机理**（ISS-02）。')
    owner_user_id: int | None
    status: BatchStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(..., ge=1, description='服务端并发版本，每次更新递增。')
    archived_at: datetime | None = Field(..., description='独立归档时间；null 表示未归档，不改原有科学状态。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)

class LifecycleDeletedBatch(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_id: int = Field(..., gt=0)
    batch_code: str
    deleted: Literal[True]

class LifecycleDeletedPlan(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: int = Field(..., gt=0)
    plan_code: str
    deleted: Literal[True]

class LifecycleDeletedProcess(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    process_id: int = Field(..., gt=0)
    process_code: str
    deleted: Literal[True]

class LifecycleDeletedSample(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    sample_id: int = Field(..., gt=0)
    sample_code: str
    deleted: Literal[True]

class LifecycleExperimentPlan(ApiBaseModel):
    """实验计划。位于实验执行之前，一个计划可派生多个执行。"""
    model_config = ConfigDict(extra='forbid')
    plan_id: int
    plan_code: str = Field(..., max_length=64)
    title: str = Field(..., max_length=255)
    objective: str | None = Field(..., description='实验目的')
    hypothesis: str | None = Field(..., description='待验证假设')
    design_note: str | None = Field(..., description='变量设计与对照组设置')
    planned_start: date | None
    planned_end: date | None
    priority: PlanPriority
    status: PlanStatus
    owner_user_id: int | None
    batch_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    process_flow: ProcessFlow | None = Field(..., description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archive_previous_status: str | None = Field(..., max_length=24)

class LifecycleGroup(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    type: str
    label: str
    count: int = Field(..., ge=0)
    restricted: bool
    deletable_hint: bool

class LifecycleImpact(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['batches', 'samples', 'plans', 'processes']
    id: int = Field(..., gt=0)
    code: str | None
    row_version: int = Field(..., gt=0)
    status: LifecycleStatus
    archived: bool
    can_restore: bool
    groups: list[LifecycleGroup]
    restricted: bool
    restricted_flag: str | None
    shared: LifecycleShared
    sample_counts: LifecycleSampleCounts | None
    dependencies_total_visible: int = Field(..., ge=0)
    delete_blocked: bool
    delete_allowed: bool
    delete_permitted: bool
    void_allowed: bool
    actions: list[Literal['archive', 'archive_with_dependents', 'void', 'delete', 'restore']]
    preview_token: str = Field(..., pattern='^[a-f0-9]{64}$')

class LifecycleProcess(ApiBaseModel):
    """工艺运行（一次实际执行事件）。"""
    model_config = ConfigDict(extra='forbid')
    process_id: int
    process_code: str = Field(..., max_length=64)
    plan_id: int | None = Field(..., description='所属实验计划（可为空，表示临时加做）')
    batch_id: int | None
    process_mode: ProcessMode
    tool_id: int | None
    chemistry_system_id: int | None = Field(..., description='关联的通用化学体系（可为空）；删除被引用的体系返回 409。')
    r1_temp_c: Decimal | None = Field(..., description='R1 实测温度（℃）。与配方标称值分开。')
    r2_temp_c: Decimal | None
    n2_flow_sccm: Decimal | None
    o3_pre_cycles: int | None = Field(..., description='O3 预暴露**次数**。\nISS-07: 次数不等于已标定的分子剂量，且不可与秒数混淆\n（源文件名中的 "10s" 实为 10 次）。')
    o3_pre_duration_s: Decimal | None = Field(..., description='单次预暴露时长（秒）。与次数分开记录。')
    full_ale_cycles: int | None
    hf_tma_repeats: int | None
    started_at: datetime | None
    ended_at: datetime | None
    operator_user_id: int | None
    co_etch_group: str | None = Field(..., max_length=64, description='共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品\n不构成工艺独立重复，不可平均成单个工艺点。')
    is_independent_run: bool | int
    log_status: ProcessLogStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    archived_at: datetime | None = Field(..., description='独立归档时间；null 表示未归档，不改原有科学状态。')
    process_flow: ProcessFlow | None = Field(..., description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)

class LifecycleSample(ApiBaseModel):
    """样品。**工作台的中心实体**。"""
    model_config = ConfigDict(extra='forbid')
    sample_id: int
    sample_code: str = Field(..., max_length=64, description='全局唯一样品编码')
    batch_id: int
    parent_sample_id: int | None = Field(..., description='母片/上级样品 ID（支持母片-小样层级）')
    sample_type: SampleType
    display_label: str | None = Field(..., max_length=128, description='原始文件中的编号，如 "1" / "9"')
    nominal_thickness_nm: Decimal | None
    size_desc: str | None = Field(..., max_length=64)
    cut_position: str | None = Field(..., max_length=128)
    surface_state: str | None = Field(..., max_length=128)
    pre_treatment: str | None = Field(..., max_length=255, description='前处理描述。ISS-05 要求必须记录前处理——\nW01-S09 因酒精湿巾擦拭导致结果异常。')
    status: SampleStatus
    exclude_from_analysis: bool | int
    exclude_reason: str | None = Field(..., description='排除理由。`exclude_from_analysis=true` 时应填写。')
    owner_user_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(..., ge=1, description='服务端并发版本，每次更新递增。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archived_at: datetime | None
    archived_by_user_id: int | None = Field(..., gt=0)

class LifecycleSampleCandidate(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    sample_id: int = Field(..., gt=0)
    sample_code: str
    row_version: int = Field(..., gt=0)

class LifecycleSampleCounts(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    total: int = Field(..., ge=0)
    available: int = Field(..., ge=0)
    unused_candidates: int = Field(..., ge=0)
    candidates: list[LifecycleSampleCandidate]

class LifecycleShared(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    shared_samples: list[LifecycleSharedSample]
    shared_plans: list[LifecycleSharedPlan]

class LifecycleSharedPlan(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: int = Field(..., gt=0)
    process_count: int = Field(..., ge=0)

class LifecycleSharedSample(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    sample_id: int = Field(..., gt=0)
    process_count: int = Field(..., ge=0)

class LifecycleStatus(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    status: str | None
    archived_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None

class LoginRequest(ApiBaseModel):
    username: str
    password: str

class LoginResponse(ApiBaseModel):
    token: TokenPair
    user: User

class Measurement(ApiBaseModel):
    sample_code: str | None = None
    process_code: str | None = None
    plan_title: str | None = None
    optical_model_name: str | None = None
    measurement_id: int
    measurement_code: str
    sample_id: int
    process_id: int | None
    tool_id: int | None
    optical_model_id: int | None
    stage: MeasurementStage
    stage_seq: int | None
    cumulative_cycles: int | None
    measured_at: datetime | None
    operator_user_id: int | None
    point_count: int | None
    thickness_mean_nm: Decimal | None
    thickness_sd_nm: Decimal | None
    thickness_min_nm: Decimal | None
    thickness_max_nm: Decimal | None
    mse_mean: Decimal | None
    mse_max: Decimal | None
    gof_mean: Decimal | None
    wafer_size: str | None
    grid_desc: str | None
    supersedes_measurement_id: int | None
    is_current: bool
    supersede_reason: str | None
    quality_flag: MeasurementQualityFlag
    quality_note: str | None
    created_at: datetime
    updated_at: datetime
    source_file_id: int | None
    import_item_id: int | None
    import_locator: str | None
    row_version: int
    provenance: Any | None

class MeasurementBrief(ApiBaseModel):
    measurement_id: int
    measurement_code: str
    stage: MeasurementStage
    stage_seq: int | None = None
    thickness_mean_nm: str | None = None
    is_current: bool
    quality_flag: MeasurementQualityFlag = None

class MeasurementCreate(ApiBaseModel):
    measurement_code: str = Field(..., max_length=96)
    sample_id: int
    process_id: int = None
    tool_id: int = None
    optical_model_id: int = None
    stage: MeasurementStage
    stage_seq: int = None
    cumulative_cycles: int = None
    measured_at: datetime = None
    point_count: int = None
    thickness_mean_nm: str = None
    thickness_sd_nm: str = None
    thickness_min_nm: str = None
    thickness_max_nm: str = None
    mse_mean: str = None
    mse_max: str = None
    gof_mean: str = None
    wafer_size: str = None
    grid_desc: str = None
    quality_flag: MeasurementQualityFlag = None
    quality_note: str = None
    points: list[MeasurementPointCreate] = Field(None, description='可随测量一并提交点级数据')

class MeasurementDetail(ApiBaseModel):
    sample_code: str | None = None
    process_code: str | None = None
    plan_title: str | None = None
    optical_model_name: str | None = None
    measurement_id: int
    measurement_code: str
    sample_id: int
    process_id: int | None
    tool_id: int | None
    optical_model_id: int | None
    stage: MeasurementStage
    stage_seq: int | None
    cumulative_cycles: int | None
    measured_at: datetime | None
    operator_user_id: int | None
    point_count: int | None
    thickness_mean_nm: Decimal | None
    thickness_sd_nm: Decimal | None
    thickness_min_nm: Decimal | None
    thickness_max_nm: Decimal | None
    mse_mean: Decimal | None
    mse_max: Decimal | None
    gof_mean: Decimal | None
    wafer_size: str | None
    grid_desc: str | None
    supersedes_measurement_id: int | None
    is_current: bool
    supersede_reason: str | None
    quality_flag: MeasurementQualityFlag
    quality_note: str | None
    created_at: datetime
    updated_at: datetime
    source_file_id: int | None
    import_item_id: int | None
    import_locator: str | None
    row_version: int
    provenance: Any | None
    points: list[MeasurementPoint]

class MeasurementPoint(ApiBaseModel):
    point_id: int
    measurement_id: int
    point_no: int | None
    x_mm: Decimal | None
    y_mm: Decimal | None
    thickness_nm: Decimal | None
    intensity: Decimal | None
    height_mm: Decimal | None
    mse: Decimal | None
    gof: Decimal | None
    aoi_deg: Decimal | None
    fit_iter: int | None
    lbh: Decimal | None
    fit_time_ms: Decimal | None
    dispersion_params: Any | None
    source_file_id: int | None
    source_sheet: str | None
    source_row: int | None
    source_cell: str | None
    is_outlier: bool
    outlier_note: str | None
    created_at: datetime
    raw_values: Any | None

class MeasurementPointCreate(ApiBaseModel):
    point_no: int = None
    x_mm: Decimal = None
    y_mm: Decimal = None
    thickness_nm: Decimal = None
    intensity: str = None
    height_mm: str = None
    mse: str = None
    gof: str = None
    aoi_deg: str = None
    fit_iter: int = None
    lbh: str = None
    fit_time_ms: str = None
    dispersion_params: dict[str, Any] = None
    source_file_id: int = None
    source_sheet: str = None
    source_row: int = None
    source_cell: str = None
    is_outlier: bool = None
    outlier_note: str = None

class MeasurementPointUpdate(ApiBaseModel):
    thickness_nm: str = None
    mse: str = None
    gof: str = None
    is_outlier: bool = None
    outlier_note: str = None

class MeasurementSupersedeRequest(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    replacement_measurement_id: int = Field(..., gt=0)
    expected_row_version: int = Field(..., gt=0)
    expected_replacement_row_version: int = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=20000)

    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip():
            raise ValueError('Nonblank value required')
        return value.strip()

class MeasurementSupersedeResult(ApiBaseModel):
    sample_code: str | None = None
    process_code: str | None = None
    plan_title: str | None = None
    optical_model_name: str | None = None
    measurement_id: int
    measurement_code: str
    sample_id: int
    process_id: int | None
    tool_id: int | None
    optical_model_id: int | None
    stage: MeasurementStage
    stage_seq: int | None
    cumulative_cycles: int | None
    measured_at: datetime | None
    operator_user_id: int | None
    point_count: int | None
    thickness_mean_nm: Decimal | None
    thickness_sd_nm: Decimal | None
    thickness_min_nm: Decimal | None
    thickness_max_nm: Decimal | None
    mse_mean: Decimal | None
    mse_max: Decimal | None
    gof_mean: Decimal | None
    wafer_size: str | None
    grid_desc: str | None
    supersedes_measurement_id: int | None
    is_current: bool
    supersede_reason: str | None
    quality_flag: MeasurementQualityFlag
    quality_note: str | None
    created_at: datetime
    updated_at: datetime
    source_file_id: int | None
    import_item_id: int | None
    import_locator: str | None
    row_version: int
    provenance: Any | None
    points: list[MeasurementPoint]
    replacement: dict[str, Any]

class MeasurementUpdate(ApiBaseModel):
    """仅质量更新；至少显式提交 quality_flag 或 quality_note。只更新实际提交字段；变化时将依赖结果 is_valid=false；版本递增。"""
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_row_version: int = Field(..., gt=0)
    quality_flag: MeasurementQualityFlag = Field('ok', validate_default=True)
    quality_note: str | None = Field(None, max_length=20000)

    @model_validator(mode='after')
    def has_change(self):
        if not self.model_fields_set.intersection({'quality_note', 'quality_flag'}):
            raise ValueError('Supply at least one update field')
        return self

class OpticalModel(ApiBaseModel):
    """椭偏光学模型（n/k 设定）。"""
    model_id: int
    model_code: str = Field(..., max_length=64)
    model_name: str = Field(..., max_length=255)
    rcp_name: str | None = None
    spl_name: str | None = None
    n_setting: Decimal | None = Field(None, description='折射率 n')
    k_setting: Decimal | None = Field(None, description='消光系数 k')
    layer_structure: list[dict[str, Any]] | None = None
    aoi_deg: Decimal | None = Field(None, description='入射角（度）')
    valid_range_nm: str | None = None
    applicable_batch_id: int | None = None
    quality_note: str | None = Field(None, description='模型质量备注。如 ISS-03 记录的 300nm 模型 MSE 偏高。')
    status: OpticalModelStatus
    created_at: datetime = None
    updated_at: datetime = None

class PairedPointDelta(ApiBaseModel):
    """单对配对点的差值。"""
    point_no: int
    x_mm: str | None = None
    y_mm: str | None = None
    before_thickness_nm: str | None = None
    after_thickness_nm: str | None = None
    delta_nm: str | None = Field(None, description='after - before')
    r_nm: str | None = Field(None, description='before - after')
    delta_mse: str | None = None
    delta_gof: str | None = None

class PairingRequest(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    before_measurement_id: Annotated[int, Field(strict=True, gt=0)]
    after_measurement_id: Annotated[int, Field(strict=True, gt=0)]
    pairing_method: Literal['same_xy_coordinate'] = 'same_xy_coordinate'
    include_points: bool = True
    confirm_pair: bool
    selection: AnalysisSelection = Field(default_factory=lambda: AnalysisSelection())

class PairingResponse(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    pairing_method: Literal['same_xy_coordinate']
    direction: Literal['after - before']
    model_consistent: Literal[True]
    paired_point_count: int = Field(..., ge=0)
    unmatched_before: int = Field(..., ge=0)
    unmatched_after: int = Field(..., ge=0)
    ineligible_before: int = Field(..., ge=0)
    ineligible_after: int = Field(..., ge=0)
    mean_delta_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    mean_before_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    mean_after_nm: str = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    sd_delta_nm: str | None = Field(..., pattern='^-?\\d+(?:\\.\\d+)?$')
    observation: Literal['increase', 'decrease', 'unchanged']
    interpretation: str
    points: list[AnalysisPairPoint] = None
    before_measurement_id: int
    after_measurement_id: int
    analysis_version: str
    selection: AnalysisSelection
    result_sha256: str = Field(..., pattern='^[a-f0-9]{64}$')

class ParameterField(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: Annotated[str, Field(min_length=1, max_length=128)]
    value: Annotated[str, Field(max_length=2000)] | None = None
    unit: Annotated[str, Field(max_length=32)] | None = None

class ParameterGroup(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: Annotated[str, Field(min_length=1, max_length=128)]
    fields: Annotated[list[ParameterField], Field(max_length=64)] = Field(default_factory=list)

    @field_validator('fields')
    @classmethod
    def unique_fields(cls, fields):
        if len({f.name for f in fields}) != len(fields):
            raise ValueError('Field names must be unique within a group')
        return fields

class ParameterSnapshot(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    step_type: Annotated[str, Field(min_length=1, max_length=128)]
    temperature: Temperature = Field(default_factory=lambda: Temperature())
    groups: Annotated[list[ParameterGroup], Field(max_length=32)] = Field(default_factory=list)

    @model_validator(mode='after')
    def bounded_payload(self):
        if sum(len(g.fields) for g in self.groups) > 256:
            raise ValueError('A snapshot supports at most 256 parameter cells')
        if len(self.model_dump_json().encode('utf-8')) > 65536:
            raise ValueError('A snapshot supports at most 64 KiB')
        return self

    @field_validator('groups')
    @classmethod
    def unique_groups(cls, groups):
        if len({g.name for g in groups}) != len(groups):
            raise ValueError('Group names must be unique')
        return groups

class ParserBlock(ApiBaseModel):
    """metadata 保留 headers/units/preamble/instrument_summary/optical_model；locator 保留 sheet/header_row/end_row。"""
    metadata: dict[str, Any]
    points: list[ParserPoint]
    statistics: ParserStatistics
    warnings: list[ParserIssue]
    blocking_issues: list[ParserIssue]
    locator: dict[str, Any]

class ParserFieldStatistics(ApiBaseModel):
    count: int
    excluded_nonfinite_or_missing: int
    mean: str = None
    min: str = None
    max: str = None
    sd_sample: str | None = None
    sd_population: str = None

class ParserIssue(ApiBaseModel):
    code: str
    message: str
    locator: dict[str, Any] | None
    field: str | None

class ParserPoint(ApiBaseModel):
    """预览数值为十进制字符串或 null，保留原始词法值；不以 DB scale 舍入。"""
    x_mm: str | None
    y_mm: str | None
    intensity: str | None
    height_mm: str | None
    mse: str | None
    gof: str | None
    thickness_nm: str | None
    aoi_deg: str | None
    lbh: str | None
    fit_time_ms: str | None
    point_no: int | None
    fit_iter: int | None
    dispersion_params: dict[str, str | None]
    source_sheet: str
    source_row: int
    source_cell: str | None
    is_outlier: bool
    outlier_note: str | None
    raw_values: list[ParserRawValue]
    locator: dict[str, Any]

class ParserRawValue(ApiBaseModel):
    value: Any
    cell: str | None
    data_type: str
    formula: str = Field(None, description='原始公式文本（含前导等号）；不执行求值。')
    formula_attributes: dict[str, str] = Field(None, description='原始 OOXML 公式属性。')
    cached_value_lexeme: str | None = Field(None, description='原始公式缓存词法值；不转为数值，不作为可信观测。')
    cached_type: str = Field(None, description='原始 OOXML 缓存类型；缺省为 n。')
    cache_present: bool = Field(None, description='原始 v 元素是否存在；区分缺失缓存与空缓存。')

class ParserStatistics(ApiBaseModel):
    point_count: int
    includes_outliers: bool
    sd_convention: dict[str, Any]
    decimal_precision: int
    rounding: str
    db_write_policy: str
    thickness_nm: ParserFieldStatistics
    mse: ParserFieldStatistics
    gof: ParserFieldStatistics

class ParticipationEvent(ApiBaseModel):
    transition_id: int
    event_type: TransitionEventType
    from_status: str | None = None
    to_status: str = None
    process_id: int | None = None
    step_id: int | None = None
    step_index: int | None = None
    event_at: datetime | None = None
    location: str | None = None
    note: str | None = None

class ParticipationMeasurement(ApiBaseModel):
    sample_code: str | None = None
    process_code: str | None = None
    plan_title: str | None = None
    optical_model_name: str | None = None
    measurement_id: int
    measurement_code: str
    stage: str
    stage_seq: int | None = None
    cumulative_cycles: int | None = None
    measured_at: datetime | None = None
    thickness_mean_nm: str | None = None
    thickness_sd_nm: str | None = None
    thickness_min_nm: str | None = None
    thickness_max_nm: str | None = None
    mse_mean: str | None = None
    quality_flag: str = None
    is_current: bool
    process_id: int | None = None

class ParticipationSummary(ApiBaseModel):
    recorded_cycles: int | None
    cycle_groups: list[dict[str, Any]] = None
    participation_count: int
    recorded_participations: int
    missing_participations: int
    complete: bool

class PlanArchive(ApiBaseModel):
    """计划归档请求；expected_row_version 可选，不匹配返回 409；已归档幂等返回当前详情。"""
    model_config = ConfigDict(extra='forbid')
    expected_row_version: int | None = Field(None, ge=1)

class PlanCreate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    plan_code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    objective: str | None = Field(None, max_length=20000)
    hypothesis: str | None = Field(None, max_length=20000)
    design_note: str | None = Field(None, max_length=20000)
    planned_start: date | None = None
    planned_end: date | None = None
    priority: Literal['high', 'normal', 'low'] = 'normal'
    status: Literal['draft', 'approved', 'running', 'completed', 'abandoned'] = 'draft'
    batch_id: int | None = Field(None, gt=0)
    notes: str | None = Field(None, max_length=20000)

class PlanGridDetail(ApiBaseModel):
    plan_id: int
    plan_code: str = Field(..., max_length=64)
    title: str = Field(..., max_length=255)
    objective: str | None = Field(None, description='实验目的')
    hypothesis: str | None = Field(None, description='待验证假设')
    design_note: str | None = Field(None, description='变量设计与对照组设置')
    planned_start: date | None = None
    planned_end: date | None = None
    priority: PlanPriority
    status: PlanStatus
    owner_user_id: int | None = None
    batch_id: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    process_flow: ProcessFlow | None = Field(None, description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archive_previous_status: str | None = Field(..., max_length=24)
    steps: list[PlanStep]
    batch: Batch | None
    processes: list[Process]
    process_count: int = Field(..., ge=0)
    owner: dict[str, Any] | None

class PlanStep(ApiBaseModel):
    """有序计划步骤；step_id 由服务端生成。被实际步骤映射后，更新或删除均返回 409。"""
    step_id: int
    plan_id: int
    step_index: int = Field(..., ge=1, le=4294967295)
    step_kind: Annotated[str, Field(min_length=1, max_length=128)]
    planned_parameters: StepParameters | None = None
    step_note: str | None = Field(None, max_length=20000)
    step_name: str | None = Field(None, max_length=128, description='自定义步骤名（如“O3 暴露”）；步骤类型仍由 step_kind 表达。')
    custom_parameters: CustomParameters | None = Field(None, description='自由参数映射，按 {key: {value,unit,note}} 存储；数字取值统一按字符串回传。')
    created_at: datetime
    parameter_snapshot: ParameterSnapshot | None = Field(None, description='通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。')
    parameter_source: Literal['parameter_snapshot', 'legacy_fields'] = Field(..., description='当前参数来源；非空快照优先，旧字段保持原值。')
    legacy_parameters: dict[str, Any] = Field(..., description='原样返回已记录旧字段及custom_parameters；不推断单位或转换数值。')
    legacy_parameters_status: Literal['historical_readonly', 'current'] = Field(..., description='存在快照时旧值仅供历史读取，否则仍为当前参数。')
    parameter_conflict: bool = Field(..., description='非空快照与非空旧参数同时存在；不表示已推断数值是否相等。')

class PlanStepCreate(ApiBaseModel):
    """计划步骤创建；客户端必须提供 step_index 和 step_kind，不接受服务端 step_id/plan_id。"""
    model_config = ConfigDict(extra='forbid')
    step_index: int = Field(..., ge=1, le=4294967295)
    step_kind: Annotated[str, Field(min_length=1, max_length=128)]
    planned_parameters: StepParameters | None = None
    step_note: str | None = Field(None, max_length=20000)
    step_name: str | None = Field(None, max_length=128, description='自定义步骤名（可空）。')
    custom_parameters: CustomParameters | None = Field(None, description='自由参数映射，最多 32 项。')
    parameter_snapshot: ParameterSnapshot | None = Field(None, description='通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。')

class PlanStepUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    step_index: int = Field(None, ge=1, le=4294967295)
    step_kind: Annotated[str, Field(min_length=1, max_length=128)] = None
    planned_parameters: StepParameters | None = None
    step_note: str | None = Field(None, max_length=20000)
    step_name: str | None = Field(None, max_length=128, description='自定义步骤名（可空）。')
    custom_parameters: CustomParameters | None = Field(None, description='自由参数映射，最多 32 项。')
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。')
    parameter_snapshot: ParameterSnapshot | None = Field(None, description='通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。')

class PlanUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    title: str = Field(None, min_length=1, max_length=255)
    objective: str | None = Field(None, max_length=20000)
    hypothesis: str | None = Field(None, max_length=20000)
    design_note: str | None = Field(None, max_length=20000)
    planned_start: date | None = None
    planned_end: date | None = None
    priority: Literal['high', 'normal', 'low'] = None
    status: Literal['draft', 'approved', 'running', 'completed', 'abandoned'] = None
    batch_id: int | None = Field(None, gt=0)
    notes: str | None = Field(None, max_length=20000)
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。')

class Process(ApiBaseModel):
    """工艺运行（一次实际执行事件）。"""
    plan_title: str | None = None
    process_id: int
    process_code: str = Field(..., max_length=64)
    plan_id: int | None = Field(None, description='所属实验计划（可为空，表示临时加做）')
    batch_id: int | None = None
    process_mode: ProcessMode
    tool_id: int | None = None
    chemistry_system_id: int | None = Field(None, description='关联的通用化学体系（可为空）；删除被引用的体系返回 409。')
    r1_temp_c: Decimal | None = Field(None, description='R1 实测温度（℃）。与配方标称值分开。')
    r2_temp_c: Decimal | None = None
    n2_flow_sccm: Decimal | None = None
    o3_pre_cycles: int | None = Field(None, description='O3 预暴露**次数**。\nISS-07: 次数不等于已标定的分子剂量，且不可与秒数混淆\n（源文件名中的 "10s" 实为 10 次）。')
    o3_pre_duration_s: Decimal | None = Field(None, description='单次预暴露时长（秒）。与次数分开记录。')
    full_ale_cycles: int | None = None
    hf_tma_repeats: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    operator_user_id: int | None = None
    co_etch_group: str | None = Field(None, max_length=64, description='共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品\n不构成工艺独立重复，不可平均成单个工艺点。')
    is_independent_run: bool = Field(..., description='是否独立运行（false 表示与其他样品共腔）')
    log_status: ProcessLogStatus
    notes: str | None = None
    created_at: datetime = None
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    archived_at: datetime | None = Field(None, description='独立归档时间；null 表示未归档，不改原有科学状态。')
    process_flow: ProcessFlow | None = Field(None, description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)

class ProcessBrief(ApiBaseModel):
    process_id: int
    process_code: str
    process_mode: ProcessMode
    started_at: datetime | None = None
    log_status: ProcessLogStatus = None

class ProcessCreate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    process_code: str = Field(..., min_length=1, max_length=64)
    process_mode: Literal['full_cycle', 'pre_expose_then_react', 'hf_only', 'o3_only', 'tma_only', 'plasma', 'deposition', 'other']
    plan_id: int | None = Field(None, gt=0)
    batch_id: int | None = Field(None, gt=0)
    tool_id: int | None = Field(None, gt=0)
    chemistry_system_id: int | None = Field(None, gt=0, description='关联的通用化学体系（可空）；校验存在且可见。')
    r1_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    r2_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    n2_flow_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_pre_cycles: int | None = Field(None, ge=0, le=4294967295)
    o3_pre_duration_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    full_ale_cycles: int | None = Field(None, ge=0, le=4294967295)
    hf_tma_repeats: int | None = Field(None, ge=0, le=4294967295)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    co_etch_group: str | None = Field(None, max_length=64)
    is_independent_run: bool = True
    log_status: Literal['ok', 'partial', 'aborted', 'unknown'] = 'ok'
    notes: str | None = Field(None, max_length=20000)
    steps: list[ProcessStepCreate] = Field(None, max_length=500)
    samples: list[ProcessSampleCreate] = Field(None, max_length=500)
    process_flow: ProcessFlow | None = Field(None, description='创建流程只接受与提交steps的step_index一致的整数引用；保存后解析为实际step_id。')

class ProcessDetail(ApiBaseModel):
    plan_title: str | None = None
    process_id: int
    process_code: str = Field(..., max_length=64)
    plan_id: int | None = Field(None, description='所属实验计划（可为空，表示临时加做）')
    batch_id: int | None = None
    process_mode: ProcessMode
    tool_id: int | None = None
    chemistry_system_id: int | None = Field(None, description='关联的通用化学体系（可为空）；删除被引用的体系返回 409。')
    r1_temp_c: Decimal | None = Field(None, description='R1 实测温度（℃）。与配方标称值分开。')
    r2_temp_c: Decimal | None = None
    n2_flow_sccm: Decimal | None = None
    o3_pre_cycles: int | None = Field(None, description='O3 预暴露**次数**。\nISS-07: 次数不等于已标定的分子剂量，且不可与秒数混淆\n（源文件名中的 "10s" 实为 10 次）。')
    o3_pre_duration_s: Decimal | None = Field(None, description='单次预暴露时长（秒）。与次数分开记录。')
    full_ale_cycles: int | None = None
    hf_tma_repeats: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    operator_user_id: int | None = None
    co_etch_group: str | None = Field(None, max_length=64, description='共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品\n不构成工艺独立重复，不可平均成单个工艺点。')
    is_independent_run: bool = Field(..., description='是否独立运行（false 表示与其他样品共腔）')
    log_status: ProcessLogStatus
    notes: str | None = None
    created_at: datetime = None
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    archived_at: datetime | None = Field(None, description='独立归档时间；null 表示未归档，不改原有科学状态。')
    process_flow: ProcessFlow | None = Field(None, description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    plan: ExperimentPlan | None
    batch: Batch | None
    tool: Tool | None
    steps: list[ProcessStep]
    samples: list[ProcessSampleLink] = Field(..., description='参与该次运行的样品（含逐片参数与共腔位置）')
    sample_count: int
    step_count: int

class ProcessFlow(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=False, str_strip_whitespace=True)
    version: Literal[1] = 1
    total_cycles: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None = None
    children: Annotated[list[FlowNode], Field(max_length=500)] = Field(default_factory=list)

    @model_validator(mode='after')
    def bounded_tree(self):
        ids, refs = set(), set()
        count = groups = 0
        def visit(nodes, depth):
            nonlocal count, groups
            if depth > 5: raise ValueError('At most four nested groups are supported')
            for node in nodes:
                count += 1
                if count > 500: raise ValueError('At most 500 flow nodes are supported')
                if node.id in ids: raise ValueError('Flow node IDs must be unique')
                ids.add(node.id)
                if node.kind == 'step':
                    if node.step_id in refs: raise ValueError('Each step may appear only once; use an explicit group repeat')
                    refs.add(node.step_id)
                else:
                    groups += 1
                    if groups > 32: raise ValueError('At most 32 groups are supported')
                    visit(node.children, depth + 1)
        visit(self.children, 1)
        return self

class ProcessGridDetail(ApiBaseModel):
    plan_title: str | None = None
    process_id: int
    process_code: str = Field(..., max_length=64)
    plan_id: int | None = Field(None, description='所属实验计划（可为空，表示临时加做）')
    batch_id: int | None = None
    process_mode: ProcessMode
    tool_id: int | None = None
    chemistry_system_id: int | None = Field(None, description='关联的通用化学体系（可为空）；删除被引用的体系返回 409。')
    r1_temp_c: Decimal | None = Field(None, description='R1 实测温度（℃）。与配方标称值分开。')
    r2_temp_c: Decimal | None = None
    n2_flow_sccm: Decimal | None = None
    o3_pre_cycles: int | None = Field(None, description='O3 预暴露**次数**。\nISS-07: 次数不等于已标定的分子剂量，且不可与秒数混淆\n（源文件名中的 "10s" 实为 10 次）。')
    o3_pre_duration_s: Decimal | None = Field(None, description='单次预暴露时长（秒）。与次数分开记录。')
    full_ale_cycles: int | None = None
    hf_tma_repeats: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    operator_user_id: int | None = None
    co_etch_group: str | None = Field(None, max_length=64, description='共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品\n不构成工艺独立重复，不可平均成单个工艺点。')
    is_independent_run: bool = Field(..., description='是否独立运行（false 表示与其他样品共腔）')
    log_status: ProcessLogStatus
    notes: str | None = None
    created_at: datetime = None
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    archived_at: datetime | None = Field(None, description='独立归档时间；null 表示未归档，不改原有科学状态。')
    process_flow: ProcessFlow | None = Field(None, description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    steps: list[ProcessStep]
    batch: Batch | None
    samples: list[ProcessSampleLink]
    step_count: int = Field(..., ge=0)
    sample_count: int = Field(..., ge=0)
    plan: ExperimentPlan | None
    tool: Tool | None

class ProcessGridSave(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', strict=False, str_strip_whitespace=False)
    expected_row_version: Annotated[int, Field(strict=True, gt=0)]
    steps: Annotated[list[GridStep], Field(max_length=500)]
    process_flow: ProcessFlow

    @model_validator(mode='after')
    def bounded_grid_payload(self):
        if len(self.model_dump_json().encode('utf-8')) > 1048576:
            raise ValueError('A process grid supports at most 1 MiB')
        return self

class ProcessSampleCreate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    sample_id: int = Field(..., gt=0)
    chamber_position: str | None = Field(None, max_length=64)
    o3_pre_cycles: int | None = Field(None, ge=0, le=4294967295)
    hf_tma_repeats: int | None = Field(None, ge=0, le=4294967295)
    full_ale_cycles: int | None = Field(None, ge=0, le=4294967295)
    is_control: bool = False
    sample_role_note: str | None = Field(None, max_length=20000)

class ProcessSampleLink(ApiBaseModel):
    """工艺运行与样品的关联。承载**共腔信息**与**逐片工艺参数**——"""
    chemistry_name: str | None = None
    research_review: dict[str, Any] = Field(None, description='本次执行的正式测量、明确前测和确定性表观结果；可用点计数不改原始均值。')
    cycle_groups: list[dict[str, Any]] = None
    cycles_confirmed: bool = None
    execution_evidence: Literal['not_confirmed', 'voided', 'recorded_time', 'recorded_loading'] = None
    process_sample_id: int
    process_id: int
    sample_id: int
    sample: Sample = Field(None, description='列表和运行详情嵌入；创建/更新关联响应不含 sample。')
    chamber_position: str | None = Field(None, max_length=64, description='腔体位置/装载位')
    o3_pre_cycles: int | None = Field(None, description='本片在该次运行的 O3 预暴露次数（可逐片不同）')
    hf_tma_repeats: int | None = None
    full_ale_cycles: int | None = None
    is_control: bool = Field(..., description='是否为对照样（如 0 次 O3）')
    sample_role_note: str | None = None
    created_at: datetime = None
    batch: Batch = Field(None, description='样品所属批次（响应投影）。')
    events: list[ParticipationEvent] = Field(None, description='本次执行中该样品的流转事件，按 event_at、transition_id 排序。')
    load_event: ParticipationEvent | None = None
    unload_event: ParticipationEvent | None = None
    participation_status: Literal['unloaded', 'loaded', 'not_recorded'] = Field(None, description='依据已记录 load/unload 事件；没有事件时为 not_recorded，不推断。')
    measurements: list[ParticipationMeasurement] = None
    measurement_count: int = None
    cumulative_recorded_cycles: int | None = Field(None, description='仅累计已确认参与的逐片循环；不同体系或体系未知的多次执行分组，跨组总数返回 null，不由设备循环推算。')
    cumulative_participations: int = None
    cumulative_missing_participations: int = None
    cumulative_complete: bool = None

class ProcessSampleUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    chamber_position: str | None = Field(None, max_length=64)
    o3_pre_cycles: int | None = Field(None, ge=0, le=4294967295)
    hf_tma_repeats: int | None = Field(None, ge=0, le=4294967295)
    full_ale_cycles: int | None = Field(None, ge=0, le=4294967295)
    is_control: bool = None
    sample_role_note: str | None = Field(None, max_length=20000)
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。')

class ProcessStep(ApiBaseModel):
    """工艺步骤。记录**实际运行参数**。"""
    step_id: int
    process_id: int
    step_index: int = Field(..., ge=1, le=4294967295)
    step_kind: Annotated[str, Field(min_length=1, max_length=128)]
    chemistry: str | None = None
    recipe_id: int | None = Field(None, description='所依据的配方（标称）')
    cycles: int | None = None
    cumulative_cycles: int | None = None
    duration_s: Decimal | None = None
    pulse_s: Decimal | None = None
    purge_s: Decimal | None = None
    wait_s: Decimal | None = None
    actual_temp_c: Decimal | None = None
    delta_p: Decimal | None = None
    delta_p_unit: Literal['kPa', 'Pa', 'mTorr', None] | None = None
    o3_delta_p_kpa: Decimal | None = Field(None, description='O3 脉冲 ΔP（历史典型约 5kPa）。经验压力增量代理量，非积分化学剂量。')
    hf_delta_p_pa: Decimal | None = Field(None, description='HF 脉冲 ΔP（历史典型约 80Pa）')
    tma_delta_p_pa: Decimal | None = Field(None, description='TMA 脉冲 ΔP（历史典型约 110Pa）')
    o3_generator_o2_flow_set_sccm: Decimal | None = Field(None, description='O3 发生器 O2 供气**设定**流量（sccm）。\n**ISS-01: 严禁与 O2 plasma 的 30 sccm 混淆。**')
    o3_generator_o2_flow_measured_sccm: Decimal | None = Field(None, description='O3 发生器 O2 **实测**流量。常为 null（未记录）。')
    o3_concentration: Decimal | None = Field(None, description='O3 浓度。常为 null。')
    o2_plasma_w: Decimal | None = Field(None, description='O2 plasma 功率（30W）')
    o2_plasma_sccm: Decimal | None = Field(None, description='O2 plasma 流量（30 sccm）。**此为 plasma 支路，与 O3 发生器流量无关。**')
    o2_plasma_pa: Decimal | None = Field(None, description='O2 plasma 腔压（80Pa）')
    step_note: str | None = None
    step_name: str | None = Field(None, max_length=128, description='自定义步骤名（如“O3 暴露”）；步骤类型仍由 step_kind 表达。')
    custom_parameters: CustomParameters | None = Field(None, description='自由参数映射，按 {key: {value,unit,note}} 存储；数字取值统一按字符串回传。')
    created_at: datetime = None
    plan_step_id: int | None = Field(None, gt=0)
    parameter_snapshot: ParameterSnapshot | None = Field(None, description='通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。')
    parameter_source: Literal['parameter_snapshot', 'legacy_fields'] = Field(..., description='当前参数来源；非空快照优先，旧字段保持原值。')
    legacy_parameters: dict[str, Any] = Field(..., description='原样返回已记录旧字段及custom_parameters；不推断单位或转换数值。')
    legacy_parameters_status: Literal['historical_readonly', 'current'] = Field(..., description='存在快照时旧值仅供历史读取，否则仍为当前参数。')
    parameter_conflict: bool = Field(..., description='非空快照与非空旧参数同时存在；不表示已推断数值是否相等。')

class ProcessStepCreate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    chemistry: str | None = Field(None, max_length=64)
    recipe_id: int | None = Field(None, gt=0)
    cycles: int | None = Field(None, ge=0, le=4294967295)
    cumulative_cycles: int | None = Field(None, ge=0, le=4294967295)
    duration_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    pulse_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    purge_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    wait_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    actual_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    delta_p: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    delta_p_unit: Literal['kPa', 'Pa', 'mTorr'] | None = None
    o3_delta_p_kpa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    hf_delta_p_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    tma_delta_p_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_generator_o2_flow_set_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_generator_o2_flow_measured_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_concentration: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,6})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_w: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    step_index: int = Field(..., ge=1, le=4294967295)
    step_kind: Annotated[str, Field(min_length=1, max_length=128)]
    plan_step_id: int | None = Field(None, gt=0)
    step_note: str | None = Field(None, max_length=20000)
    step_name: str | None = Field(None, max_length=128, description='自定义步骤名（可空）。')
    custom_parameters: CustomParameters | None = Field(None, description='自由参数映射，最多 32 项。')
    parameter_snapshot: ParameterSnapshot | None = Field(None, description='通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。')

ProcessStepKind = str

class ProcessStepUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    chemistry: str | None = Field(None, max_length=64)
    recipe_id: int | None = Field(None, gt=0)
    cycles: int | None = Field(None, ge=0, le=4294967295)
    cumulative_cycles: int | None = Field(None, ge=0, le=4294967295)
    duration_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    pulse_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    purge_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    wait_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    actual_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    delta_p: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    delta_p_unit: Literal['kPa', 'Pa', 'mTorr'] | None = None
    o3_delta_p_kpa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    hf_delta_p_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    tma_delta_p_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_generator_o2_flow_set_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_generator_o2_flow_measured_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_concentration: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,6})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_w: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    step_index: int = Field(None, ge=1, le=4294967295)
    step_kind: Annotated[str, Field(min_length=1, max_length=128)] = None
    plan_step_id: int | None = Field(None, gt=0)
    step_note: str | None = Field(None, max_length=20000)
    step_name: str | None = Field(None, max_length=128, description='自定义步骤名（可空）。')
    custom_parameters: CustomParameters | None = Field(None, description='自由参数映射，最多 32 项。')
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。')
    parameter_snapshot: ParameterSnapshot | None = Field(None, description='通用步骤参数 JSON 快照，保存值的副本；修改模板不回写历史记录。')

class ProcessUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）或使用默认值（创建）。"""
    model_config = ConfigDict(extra='forbid')
    process_code: str = Field(None, min_length=1, max_length=64, description='可修改业务编号；内部 process_id 与历史引用保持，修改留审计。')
    process_mode: Literal['full_cycle', 'pre_expose_then_react', 'hf_only', 'o3_only', 'tma_only', 'plasma', 'deposition', 'other'] = None
    plan_id: int | None = Field(None, gt=0)
    batch_id: int | None = Field(None, gt=0)
    tool_id: int | None = Field(None, gt=0)
    chemistry_system_id: int | None = Field(None, gt=0, description='关联的通用化学体系（可空）；校验存在且可见。')
    r1_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    r2_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    n2_flow_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_pre_cycles: int | None = Field(None, ge=0, le=4294967295)
    o3_pre_duration_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    full_ale_cycles: int | None = Field(None, ge=0, le=4294967295)
    hf_tma_repeats: int | None = Field(None, ge=0, le=4294967295)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    co_etch_group: str | None = Field(None, max_length=64)
    is_independent_run: bool = None
    log_status: Literal['ok', 'partial', 'aborted', 'unknown'] = None
    notes: str | None = Field(None, max_length=20000)
    expected_row_version: int = Field(None, gt=0, description='可选且可为 null；非 null 时匹配父计划/运行 row_version，否则 409。修改子记录也递增父 row_version。')

class Recipe(ApiBaseModel):
    """工艺配方（**标称定义**）。"""
    recipe_id: int
    recipe_code: str = Field(..., max_length=64)
    recipe_name: str = Field(..., max_length=255)
    recipe_kind: RecipeKind
    material: str | None = None
    nominal_temp_c: Decimal | None = Field(None, description='标称温度（℃），非实测')
    nominal_pressure: Decimal | None = None
    pressure_unit: str | None = None
    nominal_gas_flows: dict[str, Any] | None = None
    pulse_s: Decimal | None = None
    purge_s: Decimal | None = None
    wait_s: Decimal | None = None
    version: str = Field(..., max_length=32)
    status: RecipeStatus
    source_file_id: int | None = None
    notes: str | None = None
    created_at: datetime = None
    updated_at: datetime = None

class RecordArchive(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_row_version: Annotated[int, Field(strict=True)] = Field(..., ge=1, strict=True)

class RefreshRequest(ApiBaseModel):
    """JSON body 可省略；refresh_token 缺省时使用 HttpOnly SameSite=Strict cookie。显式 token 优先，验证失败不会回退。"""
    refresh_token: str = None

class RegisterRequest(ApiBaseModel):
    """必须使用有效一次性邀请码注册。角色及account_purpose均从邀请继承，只能research/testing；请求禁止额外字段，不能指定role或account_purpose。"""
    model_config = ConfigDict(extra='forbid')
    username: str = Field(..., min_length=3, max_length=64, pattern='^[A-Za-z][A-Za-z0-9_.-]{2,63}$', description='登录名。字母开头，可含字母数字与 `_ . -`')
    password: str = Field(..., min_length=8, max_length=128, description='密码至少 8 位，服务端使用 Argon2id 哈希存储。')
    display_name: str = Field(None, max_length=128, description='显示名')
    email: str = Field(None, max_length=255)
    invite_code: str = Field(..., min_length=1, max_length=64, description='一次性邀请码；注册成功原子消费，并继承邀请角色与用途。')

class Sample(ApiBaseModel):
    """样品。**工作台的中心实体**。"""
    sample_id: int
    sample_code: str = Field(..., max_length=64, description='全局唯一样品编码')
    batch_id: int
    batch_code: str = Field(None, description='所属批次编码（联表冗余，便于前端展示）')
    parent_sample_id: int | None = Field(None, description='母片/上级样品 ID（支持母片-小样层级）')
    sample_type: SampleType
    display_label: str | None = Field(None, max_length=128, description='原始文件中的编号，如 "1" / "9"')
    nominal_thickness_nm: Decimal | None = None
    size_desc: str | None = Field(None, max_length=64)
    cut_position: str | None = Field(None, max_length=128)
    surface_state: str | None = Field(None, max_length=128)
    pre_treatment: str | None = Field(None, max_length=255, description='前处理描述。ISS-05 要求必须记录前处理——\nW01-S09 因酒精湿巾擦拭导致结果异常。')
    status: SampleStatus
    exclude_from_analysis: bool = Field(..., description='是否排除出常规统计。\n**本字段在数据库层面固化异常样品隔离**——\nW01-S09 表观减薄约 9.84nm（正常约 1.127nm），\n严禁纳入常规 HF-only 速率均值（ISS-05）。')
    exclude_reason: str | None = Field(None, description='排除理由。`exclude_from_analysis=true` 时应填写。')
    owner_user_id: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本，每次更新递增。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archived_at: datetime | None
    archived_by_user_id: int | None = Field(..., gt=0)

class SampleBrief(ApiBaseModel):
    """样品简要信息（用于嵌套展示）"""
    sample_id: int
    sample_code: str
    batch_code: str | None = None
    sample_type: SampleType = None
    status: SampleStatus = None
    exclude_from_analysis: bool = None

class SampleCreate(ApiBaseModel):
    sample_code: str = Field(..., max_length=64, description='全局唯一，格式建议 `批次前缀-Sxx`')
    batch_id: int
    parent_sample_id: int = None
    sample_type: SampleType = None
    display_label: str = None
    nominal_thickness_nm: Decimal = None
    size_desc: str = None
    cut_position: str = None
    surface_state: str = None
    pre_treatment: str = None
    status: SampleStatus = None
    exclude_from_analysis: bool = False
    exclude_reason: str = None
    notes: str = None

class SampleDetail(ApiBaseModel):
    sample_id: int
    sample_code: str = Field(..., max_length=64, description='全局唯一样品编码')
    batch_id: int
    batch_code: str = Field(None, description='所属批次编码（联表冗余，便于前端展示）')
    parent_sample_id: int | None = Field(None, description='母片/上级样品 ID（支持母片-小样层级）')
    sample_type: SampleType
    display_label: str | None = Field(None, max_length=128, description='原始文件中的编号，如 "1" / "9"')
    nominal_thickness_nm: Decimal | None = None
    size_desc: str | None = Field(None, max_length=64)
    cut_position: str | None = Field(None, max_length=128)
    surface_state: str | None = Field(None, max_length=128)
    pre_treatment: str | None = Field(None, max_length=255, description='前处理描述。ISS-05 要求必须记录前处理——\nW01-S09 因酒精湿巾擦拭导致结果异常。')
    status: SampleStatus
    exclude_from_analysis: bool = Field(..., description='是否排除出常规统计。\n**本字段在数据库层面固化异常样品隔离**——\nW01-S09 表观减薄约 9.84nm（正常约 1.127nm），\n严禁纳入常规 HF-only 速率均值（ISS-05）。')
    exclude_reason: str | None = Field(None, description='排除理由。`exclude_from_analysis=true` 时应填写。')
    owner_user_id: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime = None
    row_version: int = Field(..., ge=1, description='服务端并发版本，每次更新递增。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archived_at: datetime | None
    archived_by_user_id: int | None = Field(..., gt=0)
    batch: Batch = None
    parent_sample: SampleBrief = None
    child_samples: list[SampleBrief] = None
    measurement_count: int = Field(None, description='当前有效测量数')
    point_count_total: int = Field(None, description='点级数据总数')
    first_measured_at: datetime | None = None
    last_measured_at: datetime | None = None
    experiments: list[SampleExperiment] = Field(None, description='该样品参加过的可见执行，按实际执行时间排序。')
    participation_summary: ParticipationSummary = None
    research_review: dict[str, Any] = Field(None, description='只读测量历史与明确配对的椭偏表观结果，未知原因显式返回；不推断循环数。')

class SampleExperiment(ApiBaseModel):
    process_sample_id: int = None
    process_id: int
    process_code: str
    r1_temp_c: str | None = None
    r2_temp_c: str | None = None
    n2_flow_sccm: str | None = None
    voided_at: datetime | None = None
    process_mode: str = None
    log_status: str = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    plan_id: int | None = None
    plan_code: str | None = None
    plan_title: str | None = None
    batch_id: int | None = None
    chamber_position: str | None = None
    o3_pre_cycles: int | None = None
    hf_tma_repeats: int | None = None
    full_ale_cycles: int | None
    cycles_recorded: bool
    cycles_confirmed: bool = None
    execution_evidence: Literal['not_confirmed', 'voided', 'recorded_time', 'recorded_loading'] = None
    steps: list[ProcessStep] = None
    is_control: bool = None
    sample_role_note: str | None = None
    participation_status: Literal['unloaded', 'loaded', 'not_recorded']
    events: list[ParticipationEvent] = None
    load_event: ParticipationEvent | None = None
    unload_event: ParticipationEvent | None = None
    measurements: list[ParticipationMeasurement] = None
    measurement_count: int

class SampleTransition(ApiBaseModel):
    """只追加历史；按 transition_id 升序（追加顺序）分页，event_at 可为 null 或回填，不能用其推断占用顺序。"""
    context_redacted: bool = Field(..., description='必需字段。关联运行不可见时为 true，process_id、step_id、operator_user_id、location、note、measurement_id 均为 null；保留样品状态轨迹，不代表无关联执行。')
    transition_id: int
    sample_id: int
    sample: SampleBrief = None
    from_status: SampleStatus | None = None
    to_status: SampleStatus
    event_type: TransitionEventType
    process_id: int | None = None
    measurement_id: int | None = None
    event_at: datetime | None = None
    operator_user_id: int | None = None
    location: str | None = Field(None, max_length=128)
    note: str | None = None
    created_at: datetime
    step_id: int | None = Field(None, description='实际步骤完成之后的边界；须属于所提供 process_id。load 表示该步骤之后装入，unload 表示该步骤之后取出。null 表示未指定步骤边界。')

class SampleTransitionCreate(ApiBaseModel):
    """追加流转；expected_row_version 必填，匹配样品 row_version；from_status、operator_user_id 与 ID 由服务端确定。"""
    model_config = ConfigDict(extra='forbid')
    to_status: Literal['available', 'in_process', 'consumed', 'lost', 'quarantined']
    event_type: Literal['cut', 'load', 'unload', 'measure', 'process', 'quarantine', 'dispose', 'receive']
    expected_row_version: int = Field(..., gt=0)
    process_id: int | None = Field(None, gt=0)
    step_id: int | None = Field(None, gt=0, description='实际步骤完成之后的边界；须属于所提供 process_id。load 表示该步骤之后装入，unload 表示该步骤之后取出。null 表示未指定步骤边界。')
    measurement_id: int | None = Field(None, gt=0)
    event_at: datetime | None = None
    location: str | None = Field(None, max_length=128)
    note: str | None = Field(None, max_length=20000)

class SampleUpdate(ApiBaseModel):
    sample_code: str = Field(None, min_length=1, max_length=64, description='用户可见样品编号；全局唯一。修改不改变 sample_id，历史测量、执行与流转关联保持有效。')
    display_label: str | None = None
    nominal_thickness_nm: str | None = None
    size_desc: str | None = None
    cut_position: str | None = None
    surface_state: str | None = None
    pre_treatment: str | None = None
    status: SampleStatus = None
    exclude_from_analysis: bool = None
    exclude_reason: str | None = None
    notes: str | None = None
    expected_row_version: int = Field(None, ge=1, description='可选；提供时必须匹配当前 row_version，否则返回 409。省略时保持原有更新行为。')

class SampleVoid(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_row_version: Annotated[int, Field(strict=True)] = Field(..., ge=1, strict=True)
    reason: str = Field(..., min_length=1, max_length=2000)

    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip():
            raise ValueError('Nonblank value required')
        return value.strip()

class SetupRequest(ApiBaseModel):
    """使用部署配置的 setup_code 创建首位管理员；仅首次初始化可用，初始化完成后拒绝重复调用。"""
    setup_code: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3, max_length=64, pattern='^[A-Za-z][A-Za-z0-9_.-]{2,63}$', description='登录名。字母开头，可含字母数字与 `_ . -`')
    password: str = Field(..., min_length=8, max_length=128, description='密码至少 8 位，服务端使用 Argon2id 哈希存储。')
    display_name: str = Field(None, max_length=128, description='显示名')

class SetupStatus(ApiBaseModel):
    needs_setup: bool

class SourceFile(ApiBaseModel):
    """历史/规划完整登记模型；当前只读 GET 使用 SourceFileRead / SourceFileReadDetail。新上传原件按 SHA 不可变保存，禁止改写。"""
    file_id: int
    file_sha256: str = Field(..., pattern='^[a-f0-9]{64}$', description='SHA-256，主溯源键')
    file_name: str = Field(..., max_length=512, description='文件名（可能含 n/k 编码，如 `1-n1.9198-k0.0005-ALE.xlsx`）')
    rel_path: str | None = Field(None, max_length=1024)
    source_zip: str | None = Field(None, max_length=255)
    file_role: FileRole
    file_ext: str | None = None
    size_bytes: int | None = None
    mtime_epoch: int | None = None
    batch_id: int | None = None
    sample_id: int | None = None
    is_readonly: bool = Field(..., description='原始文件只读，恒为 true')
    is_duplicate_of: int | None = Field(None, description='重复文件的原始版本 ID。\nSRC-D 内嵌了 SRC-A / SRC-C 的副本，需标记避免重复计数。')
    parse_status: ParseStatus
    parse_note: str | None = None
    created_at: datetime = None

class SourceFileCreate(ApiBaseModel):
    file_sha256: str = Field(..., pattern='^[a-f0-9]{64}$')
    file_name: str = Field(..., max_length=512)
    rel_path: str = None
    source_zip: str = None
    file_role: FileRole
    file_ext: str = None
    size_bytes: int = None
    mtime_epoch: int = None
    batch_id: int = None
    sample_id: int = None
    is_duplicate_of: int = None
    parse_note: str = None

class SourceFileOccurrence(ApiBaseModel):
    occurrence_id: int
    source_file_id: int
    import_item_id: int
    owner_user_id: int
    sample_id: int | None
    filename: str
    notes: str | None
    created_at: datetime

class SourceFileRead(ApiBaseModel):
    """当前 GET 安全投影；file_name 按可见 occurrence 选择，不泄漏其他上传者名字/路径/备注。"""
    file_id: int
    file_sha256: str
    file_name: str
    file_ext: str | None
    size_bytes: int | None
    is_readonly: bool
    created_at: datetime

class SourceFileReadDetail(ApiBaseModel):
    file_id: int
    file_sha256: str
    file_name: str
    file_ext: str | None
    size_bytes: int | None
    is_readonly: bool
    created_at: datetime
    storage_key: str = Field(..., description='由 SHA 构造的相对不可变存储键，不是服务器绝对路径')
    occurrences: list[SourceFileOccurrence]

class SpeciesCreate(ApiBaseModel):
    """在指定体系下创建物种；species_code 在体系内唯一。"""
    model_config = ConfigDict(extra='forbid')
    species_code: str = Field(..., min_length=1, max_length=64)
    species_name: str = Field(..., min_length=1, max_length=255)
    formula: str | None = Field(None, max_length=64)
    role: SpeciesRole
    default_unit: str | None = Field(None, max_length=24)
    notes: str | None = Field(None, max_length=20000)

class SpeciesUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）。"""
    model_config = ConfigDict(extra='forbid')
    species_name: str | None = Field(None, min_length=1, max_length=255)
    formula: str | None = Field(None, max_length=64)
    role: SpeciesRole = None
    default_unit: str | None = Field(None, max_length=24)
    notes: str | None = Field(None, max_length=20000)
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配体系 row_version，否则 409。')

class StepParameterTemplate(ApiBaseModel):
    """独立通用步骤参数模板；definition 为 JSON 快照，编辑模板不会改变已保存步骤。"""
    template_id: int
    template_name: str = Field(..., min_length=1, max_length=128)
    definition: ParameterSnapshot
    owner_user_id: int
    row_version: int = Field(..., ge=1)
    created_at: datetime
    updated_at: datetime

class StepParameterTemplateCreate(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    template_name: str = Field(..., min_length=1, max_length=128)
    definition: ParameterSnapshot

class StepParameterTemplateUpdate(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_row_version: Annotated[int, Field(strict=True)] = Field(..., ge=1, strict=True)
    template_name: str = Field(None, min_length=1, max_length=128)
    definition: ParameterSnapshot = None

class StepParameters(ApiBaseModel):
    """计划参数白名单，与实际步骤参数字段相同；额外键返回 422。计划值不自动写入实际观测。"""
    model_config = ConfigDict(extra='forbid')
    chemistry: str | None = Field(None, max_length=64)
    recipe_id: int | None = Field(None, gt=0)
    cycles: int | None = Field(None, ge=0, le=4294967295)
    cumulative_cycles: int | None = Field(None, ge=0, le=4294967295)
    duration_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    pulse_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    purge_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    wait_s: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    actual_temp_c: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,2})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    delta_p: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    delta_p_unit: Literal['kPa', 'Pa', 'mTorr'] | None = None
    o3_delta_p_kpa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    hf_delta_p_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    tma_delta_p_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_generator_o2_flow_set_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_generator_o2_flow_measured_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o3_concentration: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,6}(?:\\.\\d{1,6})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_w: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_sccm: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,7}(?:\\.\\d{1,3})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')
    o2_plasma_pa: Annotated[Decimal, BeforeValidator(_decimal_input('^-?0*\\d{1,8}(?:\\.\\d{1,4})?$'))] | None = Field(None, description='仅接受普通十进制字符串；禁止数字、科学计数法或超出精度/小数位。未知观测保持 null。')

class SupersedeRequest(ApiBaseModel):
    """将某次测量标记为被取代。"""
    superseded_measurement_id: int = Field(..., description='被取代的测量 ID')
    reason: str = Field(..., min_length=4, description='取代原因（必填，写入 supersede_reason）')

class Temperature(ApiBaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    value: Annotated[str, Field(max_length=2000)] | None = None
    unit: Annotated[str, Field(min_length=1, max_length=32)] = '°C'

class TemplateCreate(ApiBaseModel):
    """在指定体系下创建步骤模板；template_code 在体系内唯一，steps 至少 1 条。"""
    model_config = ConfigDict(extra='forbid')
    template_code: str = Field(..., min_length=1, max_length=64)
    template_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=20000)
    steps: list[TemplateStep] = Field(..., min_length=1, max_length=200)

class TemplateParameter(ApiBaseModel):
    """模板步骤的参数定义，仅声明 key/label/unit，不含取值。"""
    model_config = ConfigDict(extra='forbid')
    key: str = Field(..., min_length=1, max_length=64, pattern='^[A-Za-z0-9_]+$')
    label: str = Field(..., min_length=1, max_length=64)
    unit: str | None = Field(None, max_length=24)

class TemplateStep(ApiBaseModel):
    """可复用模板中的一个步骤；数组顺序即步骤顺序。"""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(..., min_length=1, max_length=128)
    kind: str = Field(..., min_length=1, max_length=32)
    loop_count: int | None = Field(None, ge=1, le=100000)
    parameters: list[TemplateParameter] = Field(None, max_length=32)

class TemplateUpdate(ApiBaseModel):
    """独立请求模型；未声明字段返回 422。省略字段保持原值（PATCH）。"""
    model_config = ConfigDict(extra='forbid')
    template_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=20000)
    steps: list[TemplateStep] = Field(None, min_length=1, max_length=200)
    expected_row_version: int | None = Field(None, ge=1, description='可选且可为 null；非 null 时匹配体系 row_version，否则 409。')

class TokenPair(ApiBaseModel):
    """access JWT 1 小时，refresh JWT 7 天；绑定可撤销数据库会话，刷新轮换 refresh。刷新 cookie 为 HttpOnly、SameSite=Strict，HTTPS 下 Secure。"""
    access_token: str = Field(..., description='访问令牌（JWT）。放在 `Authorization: Bearer <token>` 头中。')
    refresh_token: str = Field(..., description='刷新令牌。仅用于换取新 access_token，不得用于业务请求。')
    token_type: Literal['Bearer']
    expires_in: int = Field(..., description='access_token 有效期（秒）')
    refresh_expires_in: int = Field(None, description='refresh_token 有效期（秒）')

class Tool(ApiBaseModel):
    tool_id: int
    tool_code: str = Field(..., max_length=64)
    tool_name: str = Field(..., max_length=255)
    tool_type: ToolType
    vendor: str | None = None
    model: str | None = None
    location: str | None = None
    status: ToolStatus
    notes: str | None = None
    created_at: datetime = None
    updated_at: datetime = None

class TransitionCreate(ApiBaseModel):
    """追加流转；expected_row_version 必填，匹配样品 row_version；from_status、operator_user_id 与 ID 由服务端确定。"""
    model_config = ConfigDict(extra='forbid')
    to_status: Literal['available', 'in_process', 'consumed', 'lost', 'quarantined']
    event_type: Literal['cut', 'load', 'unload', 'measure', 'process', 'quarantine', 'dispose', 'receive']
    expected_row_version: int = Field(..., gt=0)
    process_id: int | None = Field(None, gt=0)
    step_id: int | None = Field(None, gt=0, description='实际步骤完成之后的边界；须属于所提供 process_id。load 表示该步骤之后装入，unload 表示该步骤之后取出。null 表示未指定步骤边界。')
    measurement_id: int | None = Field(None, gt=0)
    event_at: datetime | None = None
    location: str | None = Field(None, max_length=128)
    note: str | None = Field(None, max_length=20000)

class User(ApiBaseModel):
    """用户信息（安全视图，不含密码哈希）。 admin必须为management；operator/viewer必须为research/testing。"""
    user_id: int = Field(..., description='用户 ID（主键）')
    username: str = Field(..., max_length=64, description='登录名，全局唯一')
    display_name: str | None = Field(None, max_length=128, description='显示名')
    email: str | None = Field(None, max_length=255)
    role: UserRole
    status: UserStatus
    notes: str | None = Field(None, description='备注')
    created_at: datetime = Field(..., description='创建时间')
    updated_at: datetime = Field(None, description='更新时间')
    account_purpose: AccountPurpose

class UserBrief(ApiBaseModel):
    """用户简要信息（用于嵌套在其他资源中展示创建者/操作者）。"""
    user_id: int
    username: str
    display_name: str | None = None

class UserUpdate(ApiBaseModel):
    """部分更新，可修改account_purpose。服务端将请求与已有角色/用途合并校验：admin必须management，operator/viewer必须research/testing，不匹配或role/status/account_purpose显式null返回422；改角色跨用途须同时提交匹配用途。角色、状态或用途变更撤销已有会话。"""
    model_config = ConfigDict(extra='forbid')
    display_name: str | None = Field(None, max_length=128, description='显示名')
    email: str | None = Field(None, max_length=255)
    role: UserRole = None
    status: UserStatus = Field('active', validate_default=True)
    notes: str | None = Field(None, description='备注')
    account_purpose: AccountPurpose = None

    @model_validator(mode='after')
    def supplied_role_purpose(self):
        if {'role', 'account_purpose'} <= self.model_fields_set:
            if not ((self.role == 'admin' and self.account_purpose == 'management') or (self.role in ('operator', 'viewer') and self.account_purpose in ('research', 'testing'))):
                raise ValueError('Account purpose must match role')
        return self

class WorkflowOwner(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: int = Field(..., gt=0)
    username: str
    display_name: str | None

class WorkflowPlanDetail(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: int
    plan_code: str = Field(..., max_length=64)
    title: str = Field(..., max_length=255)
    objective: str | None = Field(..., description='实验目的')
    hypothesis: str | None = Field(..., description='待验证假设')
    design_note: str | None = Field(..., description='变量设计与对照组设置')
    planned_start: date | None
    planned_end: date | None
    priority: PlanPriority
    status: PlanStatus
    owner_user_id: int | None
    batch_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    process_flow: ProcessFlow | None = Field(..., description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    archive_previous_status: str | None = Field(..., max_length=24)
    steps: list[PlanStep]
    batch: LifecycleBatch | None
    processes: list[LifecycleProcess]
    process_count: int = Field(..., ge=0)
    owner: WorkflowOwner | None

class WorkflowProcessDetail(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    process_id: int
    process_code: str = Field(..., max_length=64)
    plan_id: int | None = Field(..., description='所属实验计划（可为空，表示临时加做）')
    batch_id: int | None
    process_mode: ProcessMode
    tool_id: int | None
    chemistry_system_id: int | None = Field(..., description='关联的通用化学体系（可为空）；删除被引用的体系返回 409。')
    r1_temp_c: Decimal | None = Field(..., description='R1 实测温度（℃）。与配方标称值分开。')
    r2_temp_c: Decimal | None
    n2_flow_sccm: Decimal | None
    o3_pre_cycles: int | None = Field(..., description='O3 预暴露**次数**。\nISS-07: 次数不等于已标定的分子剂量，且不可与秒数混淆\n（源文件名中的 "10s" 实为 10 次）。')
    o3_pre_duration_s: Decimal | None = Field(..., description='单次预暴露时长（秒）。与次数分开记录。')
    full_ale_cycles: int | None
    hf_tma_repeats: int | None
    started_at: datetime | None
    ended_at: datetime | None
    operator_user_id: int | None
    co_etch_group: str | None = Field(..., max_length=64, description='共腔分组标识。ISS-06: 共腔处理的样品与独立运行样品\n不构成工艺独立重复，不可平均成单个工艺点。')
    is_independent_run: bool | int
    log_status: ProcessLogStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(..., ge=1, description='服务端并发版本；更新父记录或其子记录时递增。子记录自身没有 row_version。')
    archived_at: datetime | None = Field(..., description='独立归档时间；null 表示未归档，不改原有科学状态。')
    process_flow: ProcessFlow | None = Field(..., description='保存后step_id为真实数据库ID；空值表示旧记录无布局。')
    voided_at: datetime | None
    void_reason: str | None = Field(..., max_length=2000)
    voided_by_user_id: int | None = Field(..., gt=0)
    steps: list[ProcessStep]
    batch: LifecycleBatch | None
    samples: list[ProcessSampleLink]
    step_count: int = Field(..., ge=0)
    sample_count: int = Field(..., ge=0)
    plan: LifecycleExperimentPlan | None
    tool: Tool | None

class WorkflowStage(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    key: Literal['goal', 'plan', 'matrix', 'samples', 'execution', 'actual', 'measurement']
    status: Literal['saved', 'empty']

class WorkflowStartPlan(PlanCreate):
    plan_code: Annotated[str, Field(min_length=1, max_length=64)] = Field(default_factory=lambda: 'PL-' + uuid.uuid4().hex)

class WorkflowStartProcess(ProcessCreate):
    process_code: Annotated[str, Field(min_length=1, max_length=64)] = Field(default_factory=lambda: 'EX-' + uuid.uuid4().hex)
    log_status: Literal['ok','partial','aborted','unknown'] = 'unknown'
    steps: list[ProcessStepCreate] = Field(default_factory=list)
    samples: list[ProcessSampleCreate] = Field(default_factory=list)

class WorkflowState(ApiBaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: WorkflowPlanDetail | None
    process: WorkflowProcessDetail | None
    measurements: list[Measurement]
    stages: list[WorkflowStage] = Field(..., min_length=7, max_length=7)

MeasurementUpdate = Any | Any
AITurnResult = AIPendingResult | AICompletedResult | AIFailedResult
AIRequestAccount = AIRequestAccountOwner | AIRequestAccountAdmin
LifecycleApplyResult = LifecycleBatch | LifecycleSample | LifecycleExperimentPlan | LifecycleProcess | LifecycleDeletedBatch | LifecycleDeletedSample | LifecycleDeletedPlan | LifecycleDeletedProcess
DashboardTodoItem = DashboardTodoPlanWithoutProcess | DashboardTodoProcessLog | DashboardTodoImportPending | DashboardTodoImportFailure | DashboardTodoMeasurementReview | DashboardTodoIssue
DashboardRecentExperimentItem = DashboardRecentPlan | DashboardRecentProcess
DashboardRecentDataItem = DashboardRecentImportJob | DashboardRecentMeasurement | DashboardRecentSourceFile
# Resolve forward annotations only after every model has been defined.
for _model in list(globals().values()):
    if isinstance(_model, type) and _model is not BaseModel and issubclass(_model, BaseModel):
        _model.model_rebuild(_types_namespace=globals())
