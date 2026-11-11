"""Experiment wizard: existing records are the only draft and progress store."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import schemas as S
from .common import envelope, fail
from .db import get_db, table
from .security import current_user, writer
from . import experiments as E
from .measurement_management import measurement_scope

router = APIRouter(prefix='/api/v1/workflow', tags=['Experiment workflow'])

class StartPlan(S.PlanCreate):
    plan_code: S.Code = Field(default_factory=lambda: 'PL-' + uuid4().hex)

class StartProcess(S.ProcessCreate):
    process_code: S.Code = Field(default_factory=lambda: 'EX-' + uuid4().hex)
    log_status: S.LogStatus = 'unknown'

def start_record(kind, body, request, user, db, create):
    """Receipt and record commit together; unique codes arbitrate simultaneous starts.

    Compare the submitted request, before inheritance/default expansion. A changed
    plan or a later edit to the execution cannot change the original receipt.
    Only a digest is persisted, never raw scientific inputs or request secrets.
    """
    name, pk, entity = E.KINDS[kind]
    code_key = 'plan_code' if kind == 'plans' else 'process_code'
    owner_key = 'owner_user_id' if kind == 'plans' else 'operator_user_id'
    submitted = body.model_dump(mode='json', exclude_unset=True)
    submitted[code_key] = getattr(body, code_key)
    fingerprint = hashlib.sha256(json.dumps(submitted, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    t, a = table(name), table('audit_log')

    def replay():
        # Locking reads see a concurrent winner even after a duplicate INSERT.
        row = db.execute(select(t).where(t.c[code_key] == getattr(body, code_key))
                         .with_for_update()).mappings().first()
        if row is None:
            return None
        if row[owner_key] != user['user_id']:
            fail(409, '编号已被使用，请重新选择')
        # Recheck all current visibility rules, including linked parents/samples.
        data = E.detail(db, kind, row[pk], user)
        receipt = db.execute(select(a.c.new_value).where(a.c.entity_type == entity,
            a.c.entity_id == row[pk], a.c.user_id == user['user_id'],
            a.c.field_name == 'workflow_start').order_by(a.c.audit_id.desc()).limit(1)).scalar()
        if receipt is None or json.loads(receipt) != {'version': 1, 'fingerprint': fingerprint}:
            fail(409, '编号已用于不同请求，请核对已保存记录')
        return envelope(request, data)

    # Avoid a missing-key locking read (gap locks) before the unique INSERT.
    if db.scalar(select(t.c[pk]).where(t.c[code_key] == getattr(body, code_key))) is not None:
        return replay()
    try:
        with db.begin_nested():
            result = create()
            db.execute(a.insert().values(user_id=user['user_id'], action='insert',
                entity_type=entity, entity_id=result['data'][pk], field_name='workflow_start',
                new_value=json.dumps({'version': 1, 'fingerprint': fingerprint})))
            return result
    except IntegrityError as exc:
        # Other FK/check errors retain their existing contract. The SAVEPOINT
        # removes every partial child/audit write before recovering the winner.
        if getattr(exc.orig, 'args', (None,))[0] != 1062:
            raise
        result = replay()
        if result is None:
            raise
        return result


@router.post('/plans', status_code=201)
def start_plan(body: StartPlan, request: Request, user=Depends(writer), db=Depends(get_db)):
    return start_record('plans', body, request, user, db,
        lambda: E.create_plan(S.PlanCreate(**body.model_dump()), request, user, db))


def legacy_snapshot(step):
    """Frontend legacySnapshot mapping, retaining structure/units only."""
    p = step.get('planned_parameters') or {}
    mappings = [
        ('源', [('chemistry', '名称', None), ('recipe_id', '配方 ID', None)]),
        ('循环', [('cycles', '循环数', None), ('cumulative_cycles', '累计循环数', None)]),
        ('持续时间', [('duration_s', '时长（原始字段 s）', 's')]),
        ('脉冲', [('pulse_s', '时长（原始字段 s）', 's')]),
        ('吹扫', [('purge_s', '时长（原始字段 s）', 's')]),
        ('等待', [('wait_s', '时长（原始字段 s）', 's')]),
        ('压差', [('delta_p', '压差', p.get('delta_p_unit')), ('o3_delta_p_kpa', 'O₃ 压差', 'kPa'),
                 ('hf_delta_p_pa', 'HF 压差', 'Pa'), ('tma_delta_p_pa', 'TMA 压差', 'Pa')]),
        ('O₃ 发生器', [('o3_generator_o2_flow_set_sccm', 'O₂ 设定流量', 'sccm'),
                      ('o3_generator_o2_flow_measured_sccm', 'O₂ 测量流量', 'sccm'),
                      ('o3_concentration', 'O₃ 浓度（原记录未定义单位）', None)]),
        ('O₂ 等离子体', [('o2_plasma_w', '功率', 'W'), ('o2_plasma_sccm', '流量', 'sccm'),
                       ('o2_plasma_pa', '压力', 'Pa')]),
    ]
    groups = []
    for name, fields in mappings:
        present = [dict(name=label, value=None, unit=unit) for key, label, unit in fields
                   if p.get(key) is not None]
        if present:
            groups.append(dict(name=name, fields=present))
    custom = step.get('custom_parameters') or {}
    if custom:
        groups.append(dict(name='历史自定义参数', fields=[
            dict(name=key, value=None, unit=field.get('unit') or None) for key, field in custom.items()]))
    # Match the frontend's label fallback without importing UI or inferring values.
    labels = {'o2_plasma':'O₂ 等离子体', 'o3_purge':'O₃ / 吹扫',
              'hf_purge':'HF / 吹扫', 'tma_purge':'TMA / 吹扫',
              'purge':'吹扫', 'wait':'等待', 'other':'其他'}
    return dict(step_type=step.get('step_name') or labels.get(step['step_kind'], step['step_kind']),
                temperature=dict(value=None, unit='°C'), groups=groups)


@router.post('/processes', status_code=201)
def start_process(body: StartProcess, request: Request, user=Depends(writer), db=Depends(get_db)):
    return start_record('processes', body, request, user, db,
        lambda: create_process(body, request, user, db))


def create_process(body, request, user, db):
    values = body.model_dump()
    values['is_independent_run'] = body.plan_id is None
    if body.plan_id:
        plan = E.detail(db, 'plans', body.plan_id, user)
        if body.batch_id is None:
            values['batch_id'] = plan['batch_id']
        # Only the skeleton and units carry across. Every observed value stays NULL.
        if not body.steps:
            steps = []
            ids = {}
            for index, step in enumerate(plan['steps'], 1):
                snapshot = deepcopy(step.get('parameter_snapshot')) or legacy_snapshot(step)
                if snapshot:
                    snapshot['temperature']['value'] = None
                    for group in snapshot['groups']:
                        for field in group['fields']:
                            field['value'] = None
                steps.append(dict(step_index=index, step_kind=step['step_kind'],
                                  step_name=step['step_name'], plan_step_id=step['step_id'],
                                  parameter_snapshot=snapshot,
                                  step_note=f"计划步骤映射：#{step['step_id']}（计划值不复制，实际值请独立填写）",
                                  custom_parameters={key: dict(value=None, unit=field.get('unit'), note=None)
                                      for key, field in (step.get('custom_parameters') or {}).items()} or None))
                ids[str(step['step_id'])] = f'index:{index}'
            values['steps'] = steps
            flow = deepcopy(plan.get('process_flow'))
            if flow:
                flow['total_cycles'] = None
                def clear(nodes):
                    for node in nodes:
                        if node['kind'] == 'step':
                            node['step_id'] = ids[str(node['step_id'])]
                        else:
                            node['repeat'] = None
                            clear(node['children'])
                clear(flow['children'])
                values['process_flow'] = flow
    return E.create_process(S.ProcessCreate(**values), request, user, db)

def has_actual(run):
    if not run:
        return False
    if any(run.get(k) is not None for k in ('r1_temp_c','r2_temp_c','n2_flow_sccm','full_ale_cycles','o3_pre_cycles','o3_pre_duration_s','hf_tma_repeats')):
        return True
    flow = run.get('process_flow') or {}
    def has_repeat(nodes):
        return any(node.get('repeat') is not None or has_repeat(node.get('children', []))
                   for node in nodes if node['kind'] == 'group')
    if flow.get('total_cycles') is not None or has_repeat(flow.get('children', [])):
        return True
    for step in run['steps']:
        snap = step.get('parameter_snapshot')
        if snap:
            if snap['temperature']['value'] is not None or any(f['value'] is not None for g in snap['groups'] for f in g['fields']):
                return True
        else:
            # Units describe values; a unit by itself is not an observation.
            if any(step.get(k) is not None for k in S.StepParameters.model_fields if k != 'delta_p_unit'):
                return True
            if any(field.get('value') not in (None, '') for field in (step.get('custom_parameters') or {}).values()):
                return True
    return False

@router.get('/state')
def state(request: Request, plan_id: int | None = Query(None, gt=0),
          process_id: int | None = Query(None, gt=0), user=Depends(current_user), db=Depends(get_db)):
    run = E.detail(db, 'processes', process_id, user) if process_id else None
    requested_plan = E.detail(db, 'plans', plan_id, user) if plan_id else None
    if run and plan_id is not None and run['plan_id'] != plan_id:
        fail(422, '执行不属于所选计划，请重新选择')
    selected_plan = run['plan_id'] if run else plan_id
    plan = requested_plan or (E.detail(db, 'plans', selected_plan, user) if selected_plan else None)
    measurements = []
    if run and run['samples']:
        m = table('measurements')
        measurements = [dict(r) for r in db.execute(select(m).where(
            measurement_scope(user), m.c.process_id == process_id,
            m.c.sample_id.in_([s['sample_id'] for s in run['samples']]),
            m.c.is_current == True)).mappings()]
    goal = bool((plan and plan.get('objective')) or (not plan and run and run.get('notes')))
    facts = [goal, bool(plan or run), bool((plan or run or {}).get('steps')),
             bool(run and run['samples']), bool(run and (run['started_at'] or run['ended_at'])),
             has_actual(run), bool(measurements)]
    return envelope(request, dict(plan=plan, process=run, measurements=measurements,
        stages=[dict(key=key, status='saved' if fact else 'empty') for key, fact in zip(
            ('goal','plan','matrix','samples','execution','actual','measurement'), facts)]))
