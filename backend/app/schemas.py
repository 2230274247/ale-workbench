from .step_templates import ParameterSnapshot
from .process_flow import ProcessFlow
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, EmailStr, create_model, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)

Name = Annotated[str, Field(min_length=3, max_length=64, pattern=r'^[A-Za-z][A-Za-z0-9_.-]{2,63}$')]
Password = Annotated[str, Field(min_length=8, max_length=128)]
Role = Literal['admin','operator','viewer']
AccountPurpose = Literal['management','research','testing']
OrdinaryAccountPurpose = Literal['research','testing']

def valid_account_purpose(role, purpose):
    return (role == 'admin' and purpose == 'management') or (
        role in ('operator','viewer') and purpose in ('research','testing'))
UserStatus = Literal['active','disabled']
BatchStatus = Literal['active','archived','quarantined']
SampleStatus = Literal['available','in_process','consumed','lost','quarantined']
SampleType = Literal['parent_wafer','full_wafer','coupon']

def decimal_type(precision, scale):
    def check(v):
        if not isinstance(v, str) or not re.fullmatch(r'-?\d+(?:\.\d+)?', v):
            raise ValueError('Decimal must be a plain decimal string')
        whole, _, fraction = v.lstrip('-').partition('.')
        if len(whole.lstrip('0')) > precision-scale or len(fraction) > scale:
            raise ValueError('Decimal exceeds precision or scale')
        return Decimal(v)
    return Annotated[Decimal, BeforeValidator(check)]
Thickness = decimal_type(12,3)
Temperature = decimal_type(8,2)

class Login(Input):
    username: Annotated[str, Field(min_length=1,max_length=64)]
    password: Annotated[str, Field(min_length=1,max_length=128)]
class Register(Input):
    username: Name
    password: Password
    display_name: Annotated[str, Field(max_length=128)] | None = None
    email: EmailStr | Literal[''] | None = None
    invite_code: Annotated[str, Field(min_length=1,max_length=64)]
class Setup(Input):
    username: Name
    password: Password
    display_name: Annotated[str, Field(max_length=128)] | None = None
    setup_code: Annotated[str, Field(min_length=1,max_length=256)]
class Refresh(Input):
    refresh_token: Annotated[str, Field(max_length=4096)] | None = None
class ChangePassword(Input):
    old_password: Annotated[str, Field(max_length=128)]
    new_password: Password
class ResetPassword(Input):
    new_password: Password
class UserCreate(Input):
    username: Name
    password: Password
    display_name: Annotated[str, Field(max_length=128)] | None = None
    email: EmailStr | Literal[''] | None = None
    role: Role = 'viewer'
    account_purpose: AccountPurpose = 'research'
    status: UserStatus = 'active'
    notes: Annotated[str, Field(max_length=20000)] | None = None

    @model_validator(mode='after')
    def role_purpose(self):
        if self.role == 'admin' and 'account_purpose' not in self.model_fields_set:
            self.account_purpose = 'management'
        if not valid_account_purpose(self.role, self.account_purpose):
            raise ValueError('Account purpose must match role')
        return self

class UserUpdate(Input):
    display_name: Annotated[str, Field(max_length=128)] | None = None
    email: EmailStr | Literal[''] | None = None
    role: Role | None = None
    account_purpose: AccountPurpose | None = None
    status: UserStatus | None = None
    notes: Annotated[str, Field(max_length=20000)] | None = None
class InvitationCreate(Input):
    role: Literal['operator','viewer'] = 'viewer'
    account_purpose: OrdinaryAccountPurpose = 'research'
    expires_in_hours: Annotated[int, Field(ge=1,le=168,strict=True)] = 72
class BatchCreate(Input):
    batch_code: Annotated[str, Field(min_length=1,max_length=64)]
    batch_name: Annotated[str, Field(min_length=1,max_length=255)]
    material: Annotated[str, Field(min_length=1,max_length=128)] = 'PECVD SiNx:H'
    wafer_size: Annotated[str, Field(max_length=32)] | None = None
    nominal_thickness_nm: Thickness | None = None
    deposit_recipe_id: Annotated[int, Field(gt=0,strict=True)] | None = None
    deposit_date: date | None = None
    deposit_set_temp_c: Temperature | None = None
    deposit_actual_temp_c: Temperature | None = None
    deposit_gas_flows: dict | None = None
    source_zip: Annotated[str, Field(max_length=255)] | None = None
    source_zip_sha256: Annotated[str, Field(pattern='^[a-f0-9]{64}$')] | None = None
    anomaly_flag: bool = False
    anomaly_note: Annotated[str, Field(max_length=20000)] | None = None
    status: BatchStatus = 'active'
    notes: Annotated[str, Field(max_length=20000)] | None = None
class BatchCodeUpdate(Input):
    batch_code: Annotated[str, Field(min_length=1,max_length=64)]
    expected_row_version: Annotated[int, Field(ge=1,strict=True)]
    reason: Annotated[str, Field(min_length=1,max_length=2000)]
class SampleCreate(Input):
    sample_code: Annotated[str, Field(min_length=1,max_length=64)]
    batch_id: Annotated[int, Field(gt=0,strict=True)]
    parent_sample_id: Annotated[int, Field(gt=0,strict=True)] | None = None
    sample_type: SampleType = 'coupon'
    display_label: Annotated[str, Field(max_length=128)] | None = None
    nominal_thickness_nm: Thickness | None = None
    size_desc: Annotated[str, Field(max_length=64)] | None = None
    cut_position: Annotated[str, Field(max_length=128)] | None = None
    surface_state: Annotated[str, Field(max_length=128)] | None = None
    pre_treatment: Annotated[str, Field(max_length=255)] | None = None
    status: SampleStatus = 'available'
    exclude_from_analysis: bool = False
    exclude_reason: Annotated[str, Field(max_length=20000)] | None = None
    notes: Annotated[str, Field(max_length=20000)] | None = None

def patch_model(name, source, fields):
    # Public Pydantic API retains field constraints and BeforeValidator metadata
    # across Python versions, including Python 3.14's typing implementation.
    definitions = {
        key: (source.model_fields[key].rebuild_annotation(), None)
        for key in fields
    }
    definitions['expected_row_version'] = (Annotated[int, Field(ge=1,strict=True)] | None, None)
    return create_model(name, __base__=Input, **definitions)
BatchUpdate = patch_model('BatchUpdate', BatchCreate, ['batch_name','wafer_size','nominal_thickness_nm','deposit_set_temp_c','deposit_actual_temp_c','deposit_gas_flows','anomaly_flag','anomaly_note','status','notes'])
SampleUpdate = patch_model('SampleUpdate', SampleCreate, ['sample_code','display_label','nominal_thickness_nm','size_desc','cut_position','surface_state','pre_treatment','status','exclude_from_analysis','exclude_reason','notes'])

# Phase 2 scientific inputs: decimals are strings; omitted observations stay NULL.
from datetime import datetime, timezone
from pydantic import field_validator
Id = Annotated[int, Field(gt=0, strict=True)]
Count = Annotated[int, Field(ge=0, le=4294967295, strict=True)]
Index = Annotated[int, Field(ge=1, le=4294967295, strict=True)]
Text = Annotated[str, Field(max_length=20000)]
Code = Annotated[str, Field(min_length=1, max_length=64)]
PlanStatus = Literal['draft','approved','running','completed','abandoned','archived']
Priority = Literal['high','normal','low']
ProcessMode = Literal['full_cycle','pre_expose_then_react','hf_only','o3_only','tma_only','plasma','deposition','other']
LogStatus = Literal['ok','partial','aborted','unknown']
StepKind = Annotated[str, Field(min_length=1, max_length=128)]
EventType = Literal['cut','load','unload','measure','process','quarantine','dispose','receive']
D103 = decimal_type(10,3)
D124 = decimal_type(12,4)
D126 = decimal_type(12,6)

class PlanCreate(Input):
    plan_code: Code
    title: Annotated[str, Field(min_length=1,max_length=255)]
    objective: Text | None = None
    hypothesis: Text | None = None
    design_note: Text | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    priority: Priority = 'normal'
    status: PlanStatus = 'draft'
    batch_id: Id | None = None
    notes: Text | None = None
PlanUpdate = patch_model('PlanUpdate',PlanCreate,[k for k in PlanCreate.model_fields if k!='plan_code'])

class StepParameters(Input):
    chemistry: Annotated[str, Field(max_length=64)] | None = None
    recipe_id: Id | None = None
    cycles: Count | None = None
    cumulative_cycles: Count | None = None
    duration_s: D103 | None = None
    pulse_s: D103 | None = None
    purge_s: D103 | None = None
    wait_s: D103 | None = None
    actual_temp_c: Temperature | None = None
    delta_p: D124 | None = None
    delta_p_unit: Literal['kPa','Pa','mTorr'] | None = None
    o3_delta_p_kpa: D124 | None = None
    hf_delta_p_pa: D124 | None = None
    tma_delta_p_pa: D124 | None = None
    o3_generator_o2_flow_set_sccm: D103 | None = None
    o3_generator_o2_flow_measured_sccm: D103 | None = None
    o3_concentration: D126 | None = None
    o2_plasma_w: D103 | None = None
    o2_plasma_sccm: D103 | None = None
    o2_plasma_pa: D124 | None = None
# Phase 4 step extension: a free-form step name plus bounded custom parameters.
# Numbers are accepted on input but always stored as their plain string form so
# the stored JSON shape stays exactly {key: {"value","unit","note"}}.
ParameterKey = Annotated[str, Field(pattern=r'^[A-Za-z0-9_]{1,64}$')]
class CustomParameter(Input):
    value: str | int | float | None = None
    unit: Annotated[str, Field(max_length=24)] | None = None
    note: Annotated[str, Field(max_length=255)] | None = None

    @field_validator('value', mode='before')
    @classmethod
    def stringify(cls, value):
        # Runs before union coercion so JSON true (an int subclass) is rejected
        # rather than silently stored as '1'; numbers keep their plain text form.
        if isinstance(value, bool):
            raise ValueError('Boolean is not a valid parameter value')
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        raise ValueError('Parameter value must be a string, a number or null')
CustomParameters = Annotated[dict[ParameterKey, CustomParameter], Field(max_length=32)]
StepName = Annotated[str, Field(max_length=128)]

class PlanStepCreate(Input):
    step_index: Index
    step_kind: StepKind
    step_name: StepName | None = None
    custom_parameters: CustomParameters | None = None
    parameter_snapshot: ParameterSnapshot | None = None
    planned_parameters: StepParameters | None = None
    step_note: Text | None = None
PlanStepUpdate = patch_model('PlanStepUpdate',PlanStepCreate,list(PlanStepCreate.model_fields))
class ProcessStepCreate(StepParameters):
    step_index: Index
    step_kind: StepKind
    step_name: StepName | None = None
    custom_parameters: CustomParameters | None = None
    parameter_snapshot: ParameterSnapshot | None = None
    plan_step_id: Id | None = None
    step_note: Text | None = None
ProcessStepUpdate = patch_model('ProcessStepUpdate',ProcessStepCreate,list(ProcessStepCreate.model_fields))
class ProcessSampleCreate(Input):
    sample_id: Id
    chamber_position: Annotated[str, Field(max_length=64)] | None = None
    o3_pre_cycles: Count | None = None
    hf_tma_repeats: Count | None = None
    full_ale_cycles: Count | None = None
    is_control: bool = False
    sample_role_note: Text | None = None
ProcessSampleUpdate = patch_model('ProcessSampleUpdate',ProcessSampleCreate,[k for k in ProcessSampleCreate.model_fields if k!='sample_id'])

class BatchItem(Input):
    """One sample of a batch create; the batch comes from the path, not the body."""
    sample_code: Annotated[str, Field(min_length=1, max_length=64)]
    sample_type: SampleType = 'coupon'
    display_label: Annotated[str, Field(max_length=128)] | None = None
    nominal_thickness_nm: Thickness | None = None
    size_desc: Annotated[str, Field(max_length=64)] | None = None
    cut_position: Annotated[str, Field(max_length=128)] | None = None
    surface_state: Annotated[str, Field(max_length=128)] | None = None
    pre_treatment: Annotated[str, Field(max_length=255)] | None = None
    status: SampleStatus = 'available'
    exclude_from_analysis: bool = False
    exclude_reason: Annotated[str, Field(max_length=20000)] | None = None
    notes: Annotated[str, Field(max_length=20000)] | None = None
class BatchSampleCreate(Input):
    request_key: Annotated[str, Field(min_length=16,max_length=64)] | None = None
    parent_sample_id: Id | None = None
    items: Annotated[list[BatchItem], Field(min_length=1, max_length=50)]
class BatchLinkCreate(Input):
    """Common per-sample fields applied identically to every selected sample."""
    sample_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    chamber_position: Annotated[str, Field(max_length=64)] | None = None
    o3_pre_cycles: Count | None = None
    hf_tma_repeats: Count | None = None
    full_ale_cycles: Count | None = None
    is_control: bool = False
    sample_role_note: Text | None = None
class PlanArchive(Input):
    expected_row_version: Annotated[int, Field(ge=1, strict=True)] | None = None
class RecordArchive(Input):
    expected_row_version: Annotated[int, Field(ge=1, strict=True)]

class SampleVoid(Input):
    expected_row_version: Annotated[int, Field(ge=1, strict=True)]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]

    @field_validator('reason', mode='before')
    @classmethod
    def strip_reason(cls,value):
        return value.strip() if isinstance(value,str) else value

class LifecycleApply(Input):
    """One lifecycle action; the reason is required for void and optional otherwise."""
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

class UTCInput(Input):
    @field_validator('started_at','ended_at','event_at', check_fields=False)
    @classmethod
    def utc(cls,value):
        if value is None:return value
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
class ProcessCreate(UTCInput):
    process_code: Code
    process_mode: ProcessMode
    plan_id: Id | None = None
    batch_id: Id | None = None
    tool_id: Id | None = None
    chemistry_system_id: Id | None = None
    r1_temp_c: Temperature | None = None
    r2_temp_c: Temperature | None = None
    n2_flow_sccm: D103 | None = None
    o3_pre_cycles: Count | None = None
    o3_pre_duration_s: D103 | None = None
    full_ale_cycles: Count | None = None
    hf_tma_repeats: Count | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    co_etch_group: Annotated[str, Field(max_length=64)] | None = None
    is_independent_run: bool = True
    log_status: LogStatus = 'ok'
    notes: Text | None = None
    process_flow: ProcessFlow | None = None
    steps: Annotated[list[ProcessStepCreate], Field(max_length=500)] = Field(default_factory=list)
    samples: Annotated[list[ProcessSampleCreate], Field(max_length=500)] = Field(default_factory=list)
# Preserve UTC conversion in PATCH models as well.
ProcessUpdate = create_model('ProcessUpdate',__base__=UTCInput,**{
    **{k:(f.rebuild_annotation(),None) for k,f in ProcessCreate.model_fields.items() if k not in ('steps','samples','process_flow')},
    'expected_row_version':(Id,None)})
class TransitionCreate(UTCInput):
    to_status: SampleStatus
    event_type: EventType
    expected_row_version: Id
    process_id: Id | None = None
    step_id: Id | None = None
    measurement_id: Id | None = None
    event_at: datetime | None = None
    location: Annotated[str, Field(max_length=128)] | None = None
    note: Text | None = None

# Phase 4 general chemistry systems, species and reusable step templates.
SystemStatus = Literal['active','superseded','experimental']
SpeciesRole = Literal['precursor','reactant','purge','carrier','other']

class TemplateParameter(Input):
    key: Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_]+$')]
    label: Annotated[str, Field(min_length=1, max_length=64)]
    unit: Annotated[str, Field(max_length=24)] | None = None
class TemplateStep(Input):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    kind: StepKind
    loop_count: Annotated[int, Field(ge=1, le=100000, strict=True)] | None = None
    parameters: Annotated[list[TemplateParameter], Field(max_length=32)] = Field(default_factory=list)
class ChemistrySystemCreate(Input):
    system_code: Code
    system_name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Text | None = None
    status: SystemStatus = 'active'
ChemistrySystemUpdate = patch_model('ChemistrySystemUpdate',ChemistrySystemCreate,['system_name','description','status'])
class SpeciesCreate(Input):
    species_code: Code
    species_name: Annotated[str, Field(min_length=1, max_length=255)]
    formula: Annotated[str, Field(max_length=64)] | None = None
    role: SpeciesRole
    default_unit: Annotated[str, Field(max_length=24)] | None = None
    notes: Text | None = None
SpeciesUpdate = patch_model('SpeciesUpdate',SpeciesCreate,['species_name','formula','role','default_unit','notes'])
class TemplateCreate(Input):
    template_code: Code
    template_name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Text | None = None
    steps: Annotated[list[TemplateStep], Field(min_length=1, max_length=200)]
TemplateUpdate = patch_model('TemplateUpdate',TemplateCreate,['template_name','description','steps'])

# Atomic grid edits retain the existing step row and its legacy parameter fields.
from .process_flow import ProcessFlow
class GridStep(Input):
    key: Annotated[str, Field(min_length=1,max_length=80)]
    step_id: Id | None = None
    step_kind: StepKind
    step_name: StepName | None = None
    parameter_snapshot: ParameterSnapshot
    plan_step_id: Id | None = None

class ProcessGridSave(Input):
    expected_row_version: Id
    steps: Annotated[list[GridStep], Field(max_length=500)]
    process_flow: ProcessFlow

    @model_validator(mode='after')
    def bounded_grid_payload(self):
        if len(self.model_dump_json().encode('utf-8')) > 1048576:
            raise ValueError('A process grid supports at most 1 MiB')
        return self
