"""V2.2 quick-record semantic contract; unknown is never zero."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

class Model(BaseModel):
    model_config=ConfigDict(extra='forbid', allow_inf_nan=False)

Number=Decimal | None

class Step(Model):
    step_id: UUID=Field(default_factory=uuid4)
    source_label: str=Field(default='',max_length=128)
    enabled: bool=True
    pulse_ms: Number=Field(default=None,ge=0,le=100000000)
    purge_s: Number=Field(default=None,ge=0,le=100000000)
    wait_s: Number=Field(default=None,ge=0,le=100000000)
    delta_p_pa: Number=Field(default=None,ge=-100000000,le=100000000)
    delta_p_pa_min: Number=Field(default=None,ge=-100000000,le=100000000)
    delta_p_pa_max: Number=Field(default=None,ge=-100000000,le=100000000)
    @model_validator(mode='after')
    def blank_slot(self):
        if not self.source_label.strip() and all(v is None for v in (self.pulse_ms,self.purge_s,self.wait_s,self.delta_p_pa,self.delta_p_pa_min,self.delta_p_pa_max)):
            self.enabled=False
        return self
    @model_validator(mode='after')
    def delta_range(self):
        low,high=self.delta_p_pa_min,self.delta_p_pa_max
        if (low is None)!=(high is None):raise ValueError('DeltaP range needs both bounds')
        if low is not None and high is not None and low>high:raise ValueError('DeltaP range lower bound exceeds upper bound')
        if self.delta_p_pa is not None and (low is not None or high is not None):raise ValueError('DeltaP single value and range are exclusive')
        return self

class Group(Model):
    group_id: UUID=Field(default_factory=uuid4)
    code: str=Field(min_length=1,max_length=32)
    repeat_count: int | None=Field(default=None,ge=0,le=1000000)
    steps: list[Step]=Field(default_factory=list,max_length=100)

class Program(Model):
    outer_cycles: int | None=Field(default=1,ge=0,le=1000000)
    groups: list[Group]=Field(default_factory=list,max_length=16)
    @model_validator(mode='after')
    def keys(self):
        ids=[str(s.step_id) for g in self.groups for s in g.steps]
        if len(ids)!=len(set(ids)) or len({g.group_id for g in self.groups})!=len(self.groups):
            raise ValueError('Duplicate stable keys')
        return self

class Environment(Model):
    r1_temperature_c: Number=Field(default=None,ge=-273.15,le=3000,max_digits=8,decimal_places=2)
    r2_temperature_c: Number=Field(default=None,ge=-273.15,le=3000,max_digits=8,decimal_places=2)
    n2_flow_sccm: Number=Field(default=None,ge=0,le=1000000,max_digits=10,decimal_places=3)
    chamber_pressure_pa: Number=Field(default=None,ge=0,le=100000000)
    equipment: str | None=Field(default=None,max_length=128)
    film_context: str | None=Field(default=None,max_length=1000)
    process_type: str | None=Field(default=None,max_length=64)
    rf_icp_power_w: Number=Field(default=None,ge=0,le=100000000)
    bias_power_w: Number=Field(default=None,ge=0,le=100000000)

class Result(Model):
    result_id: UUID=Field(default_factory=uuid4)
    alias: str=Field(default='样品1',max_length=128)
    material_id: UUID | None=None
    effective_cycles: int | None=Field(default=None,ge=0,le=1000000)
    thickness_before_nm: Number=Field(default=None,ge=0,le=10000000)
    thickness_after_nm: Number=Field(default=None,ge=0,le=10000000)
    before_origin: Literal['measured','carried_forward','unknown']='unknown'
    after_origin: Literal['manual','excel','unknown']='manual'
    carried_from_result_id: UUID | None=None
    uniformity_pct: Number=Field(default=None,ge=-100000000,le=1000000)
    uniformity_definition: str | None=Field(default=None,max_length=256)
    reported_epc: Number=Field(default=None,ge=-100000000,le=100000000)
    data_nature: Literal['real_experiment','synthetic','unknown_legacy']='unknown_legacy'
    quality_status: Literal['unreviewed','approved','excluded']='unreviewed'
    source: dict | None=None
    result_label: str | None=Field(default=None,max_length=32)
    use_for_model_override: bool | None=None

class Run(Model):
    experiment_date: date
    daily_no: int=Field(ge=1,le=1000000)
    timezone: Literal['Asia/Hong_Kong']='Asia/Hong_Kong'
    material_id: UUID | None=None
    started_at: datetime | None=None
    ended_at: datetime | None=None
    note: str=Field(default='',max_length=20000)
    external_experiment_id: str | None=Field(default=None,max_length=128)
    external_batch_id: str | None=Field(default=None,max_length=128)
    state: Literal['draft','recorded']='draft'
    program: Program=Field(default_factory=Program)
    environment: Environment=Field(default_factory=Environment)
    results: list[Result]=Field(default_factory=list,max_length=100)
    previous_run_id: int | None=Field(default=None,ge=1)
    expected_version: int | None=Field(default=None,ge=1)
    idempotency_key: UUID
    @field_validator('started_at','ended_at')
    @classmethod
    def zoned(cls,v):
        if v is not None and v.utcoffset() is None: raise ValueError('Timezone required')
        return v
    @model_validator(mode='after')
    def valid(self):
        if self.state=='recorded' and self.material_id is None: raise ValueError('Material required')
        if self.started_at and self.ended_at and self.ended_at<self.started_at: raise ValueError('End precedes start')
        if len({r.result_id for r in self.results})!=len(self.results): raise ValueError('Duplicate result keys')
        return self

def calculated(r):
    a,b,n=r.get('thickness_before_nm'),r.get('thickness_after_nm'),r.get('effective_cycles')
    loss=Decimal(str(a))-Decimal(str(b)) if a is not None and b is not None else None
    epc=10*loss/Decimal(str(n)) if loss is not None and n else None
    reported=r.get('reported_epc')
    return {'thickness_loss_nm':str(loss) if loss is not None else None,
            'epc_a_per_cycle':str(epc) if epc is not None else None,
            'reported_epc_difference':str(Decimal(str(reported))-epc) if reported is not None and epc is not None else None,
            'ingestion_status':'excel_confirmed' if r.get('source') else 'manual_only' if b is not None else 'awaiting_excel'}
