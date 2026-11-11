"""Read-only projections that connect one sample with every visible execution.

All counts come from stored facts. A missing per-sample cycle value stays NULL
and is reported as "not recorded"; it is never replaced by the execution total.
"""
from sqlalchemy import select

from .db import table
from .common import dbnow


MEASUREMENT_FIELDS = (
    'measurement_id', 'measurement_code', 'stage', 'stage_seq', 'cumulative_cycles',
    'measured_at', 'thickness_mean_nm', 'thickness_sd_nm', 'thickness_min_nm',
    'thickness_max_nm', 'mse_mean', 'quality_flag', 'is_current', 'process_id',
)
EVENT_FIELDS = (
    'transition_id', 'event_type', 'from_status', 'to_status', 'process_id',
    'step_id', 'event_at', 'location', 'note',
)


def measurements_for(db, sample_id, process_id):
    m = table('measurements')
    q = select(*[m.c[name] for name in MEASUREMENT_FIELDS]).where(
        m.c.sample_id == sample_id, m.c.is_current == True)
    if process_id is None:
        q = q.where(m.c.process_id.is_(None))
    else:
        q = q.where(m.c.process_id == process_id)
    return [dict(row) for row in db.execute(
        q.order_by(m.c.stage_seq, m.c.measured_at, m.c.measurement_id)).mappings()]


def events_for(db, sample_id, process_id=None):
    t = table('sample_transitions')
    steps = table('process_steps')
    q = select(*[t.c[name] for name in EVENT_FIELDS], steps.c.step_index).where(
        t.c.sample_id == sample_id).outerjoin(
        steps, t.c.step_id == steps.c.step_id)
    if process_id is not None:
        q = q.where(t.c.process_id == process_id)
    rows = [dict(row) for row in db.execute(
        q.order_by(t.c.transition_id)).mappings()]
    for row in rows:
        row['step_index'] = None if row.get('step_index') is None else int(row['step_index'])
    return rows


def visible_process_ids(user):
    """Standalone IN-subquery; avoids auto-correlating the visibility EXISTS."""
    from .experiments import visible
    p = table('processes')
    return select(p.c.process_id).where(visible('processes', user)).correlate(None)


def execution_evidence(process, events):
    """A binding or a future schedule alone is not evidence of processing."""
    if process.get('voided_at'):return 'voided'
    now=dbnow()
    actual=[e for e in events if e['event_at'] is None or e['event_at']<=now]
    loads=[e for e in actual if e['event_type']=='load']
    unloads=[e for e in actual if e['event_type']=='unload']
    if loads and any(u['transition_id']>loads[0]['transition_id'] for u in unloads):return 'recorded_loading'
    if loads and process.get('started_at') and process['started_at']<=now:return 'recorded_time'
    return 'not_confirmed'

def cumulative_rows(rows):
    recorded=[r['full_ale_cycles'] for r in rows if r['cycles_confirmed']]
    groups={}
    for row in rows:
        key=(row.get('chemistry_system_id'),row['process_mode']) if row.get('chemistry_system_id') else ('unknown',row['process_id'])
        group=groups.setdefault(key,{'label':row.get('chemistry_name') or f"体系未确认 · {row['process_code']}",
            'process_mode':row['process_mode'],'recorded_cycles':0,'recorded_participations':0,'missing_participations':0})
        if row['cycles_confirmed']:
            group['recorded_cycles']+=row['full_ale_cycles'];group['recorded_participations']+=1
        else:group['missing_participations']+=1
    confirmed=[g for g in groups.values() if g['recorded_participations']]
    return {
        'recorded_cycles': sum(recorded) if len(confirmed)<=1 else None,
        'cycle_groups':list(groups.values()),
        'participation_count': len(rows),
        'recorded_participations': len(recorded),
        'missing_participations': len(rows) - len(recorded),
        'complete': len(recorded) == len(rows),
    }

def cumulative_for(db, sample_id, user):
    return sample_experiments(db,sample_id,user)[1]


def sample_experiments(db, sample_id, user):
    """Every visible execution of this sample, in actual processing order."""
    ps, p, pl = table('process_samples'), table('processes'), table('experiment_plans')
    rows = db.execute(
        select(
            ps.c.process_sample_id, ps.c.chamber_position, ps.c.o3_pre_cycles,
            ps.c.hf_tma_repeats, ps.c.full_ale_cycles, ps.c.is_control,
            ps.c.sample_role_note, ps.c.created_at.label('link_created_at'),
            p.c.process_id, p.c.process_code, p.c.process_mode, p.c.log_status,
            p.c.started_at, p.c.ended_at, p.c.plan_id, p.c.batch_id,
            p.c.r1_temp_c, p.c.r2_temp_c, p.c.n2_flow_sccm, p.c.voided_at,p.c.chemistry_system_id,
            pl.c.plan_code, pl.c.title.label('plan_title'),
        ).join(p, ps.c.process_id == p.c.process_id).outerjoin(
            pl, p.c.plan_id == pl.c.plan_id).where(
            ps.c.sample_id == sample_id,
            ps.c.process_id.in_(visible_process_ids(user))).order_by(
            p.c.started_at.is_(None), p.c.started_at, p.c.created_at, p.c.process_id)
    ).mappings().all()
    result = []
    from .chemistry import visible as chemistry_visible
    systems=table('chemistry_systems')
    chemistry={r['system_id']:r['system_name'] for r in db.execute(select(systems.c.system_id,systems.c.system_name).where(chemistry_visible(user))).mappings()}
    for row in rows:
        item = dict(row)
        if item['chemistry_system_id'] not in chemistry:item['chemistry_system_id']=None
        item['chemistry_name']=chemistry.get(item['chemistry_system_id'])
        item['is_control'] = bool(item['is_control'])
        events = events_for(db, sample_id, item['process_id'])
        measurements = measurements_for(db, sample_id, item['process_id'])
        loads = [event for event in events if event['event_type'] == 'load']
        unloads = [event for event in events if event['event_type'] == 'unload']
        item['events'] = events
        item['load_event'] = loads[-1] if loads else None
        item['unload_event'] = unloads[-1] if unloads else None
        item['participation_status'] = ('unloaded' if unloads and (not loads or unloads[-1]['transition_id']>loads[-1]['transition_id']) else 'loaded' if loads else 'not_recorded')
        item['measurements'] = measurements
        item['measurement_count'] = len(measurements)
        item['cycles_recorded'] = item['full_ale_cycles'] is not None
        item['execution_evidence']=execution_evidence(item,events)
        item['cycles_confirmed']=item['cycles_recorded'] and item['execution_evidence'] in ('recorded_time','recorded_loading')
        from .experiments import step_response
        steps=table('process_steps')
        item['steps']=[step_response(dict(r)) for r in db.execute(select(steps).where(steps.c.process_id==item['process_id']).order_by(steps.c.step_index)).mappings()]
        result.append(item)
    cumulative = cumulative_rows(result)
    return result, cumulative


def process_sample_details(db, sample_id, process_id, user):
    history,cumulative=sample_experiments(db,sample_id,user)
    item=next((r for r in history if r['process_id']==process_id),{})
    events = events_for(db, sample_id, process_id)
    measurements = measurements_for(db, sample_id, process_id)
    loads = [event for event in events if event['event_type'] == 'load']
    unloads = [event for event in events if event['event_type'] == 'unload']
    from .sample_review import review
    from .records import fetch
    research=review(db,sample_id,user,history,fetch(db,'samples',sample_id,user)['exclude_from_analysis'])
    associated={m['measurement_id'] for m in research['measurements'] if m['process_id']==process_id}
    research['results']=[r for r in research['results'] if r['after_measurement_id'] in associated]
    associated.update(r['before_measurement_id'] for r in research['results'] if r['before_measurement_id'] is not None)
    research['measurements']=[m for m in research['measurements'] if m['measurement_id'] in associated]
    return {
        'research_review':research,
        'chemistry_name':item.get('chemistry_name'),
        'events': events,
        'load_event': loads[-1] if loads else None,
        'unload_event': unloads[-1] if unloads else None,
        'participation_status': item.get('participation_status','not_recorded'),
        'execution_evidence': item.get('execution_evidence','not_confirmed'),
        'cycles_confirmed': item.get('cycles_confirmed',False),
        'measurements': measurements,
        'measurement_count': len(measurements),
        'cumulative': cumulative,
    }
