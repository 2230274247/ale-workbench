"""Append-only sample history; sample locks are the cross-run occupancy mutex."""
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy import select
from .db import table,get_db
from .common import fail,envelope,audit,page_result
from .security import current_user,writer
from .records import fetch,scope,require_active_sample
from . import schemas as S
from .data_visibility import reference_visible

router=APIRouter(prefix='/api/v1',tags=['Transitions'])

def append(db,sample,values,user):
    sample=require_active_sample(db,sample['sample_id'],user)
    s=table('samples');t=table('sample_transitions')
    result=db.execute(s.update().where(s.c.sample_id==sample['sample_id'],s.c.row_version==sample['row_version']).values(status=values['to_status'],row_version=sample['row_version']+1))
    if result.rowcount!=1:fail(409,'Sample was changed; reload and retry')
    id=db.execute(t.insert().values(**values,sample_id=sample['sample_id'],from_status=sample['status'],operator_user_id=user['user_id'])).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','sample_transition',id);audit(db,user['user_id'],'update','sample',sample['sample_id'])
    return {**dict(db.execute(select(t).where(t.c.transition_id==id)).mappings().one()),'context_redacted':False}

def status_event(status):
    return {'available':'receive','quarantined':'quarantine','consumed':'dispose','lost':'dispose','in_process':'process'}[status]

def patch_status(db,sample,target,user):
    if target=='in_process' or sample['status']=='in_process':fail(409,'Use load/unload for in-process samples')
    return append(db,sample,dict(to_status=target,event_type=status_event(target),event_at=None),user)

def initial_history(db,sample,user):
    t=table('sample_transitions')
    id=db.execute(t.insert().values(sample_id=sample['sample_id'],from_status=None,to_status=sample['status'],event_type=status_event(sample['status']),event_at=None,operator_user_id=user['user_id'])).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','sample_transition',id)

def transition(db,id,body,user):
    from .experiments import fetch as execution
    values=body.model_dump(exclude={'expected_row_version'})
    # Parent before sample matches binding edits; all history writers lock sample before reading history.
    if body.process_id is not None:execution(db,'processes',body.process_id,user,True)
    sample=require_active_sample(db,id,user)
    if body.expected_row_version!=sample['row_version']:fail(409,'Sample was changed; reload and retry')
    if body.step_id is not None:
        if body.process_id is None:fail(422,'Step must belong to supplied run')
        st=table('process_steps');step=db.execute(select(st).where(st.c.step_id==body.step_id).with_for_update()).mappings().first()
        if body.process_id is None or step is None or step['process_id']!=body.process_id:fail(422,'Step must belong to supplied run')
    if body.process_id is not None:
        link=table('process_samples')
        if not db.execute(select(link.c.process_sample_id).where(link.c.process_id==body.process_id,link.c.sample_id==id).with_for_update()).first():fail(422,'Sample must be linked to run')
    if body.measurement_id is not None:
        m=table('measurements');measurement=db.execute(select(m).where(m.c.measurement_id==body.measurement_id)).mappings().first()
        if measurement is None or measurement['sample_id']!=id:fail(422,'Measurement must belong to sample')
    t=table('sample_transitions')
    # Locking read observes the latest committed event even under MySQL REPEATABLE READ.
    recent=db.execute(select(t).where(t.c.sample_id==id,t.c.event_type.in_(('load','unload'))).order_by(t.c.transition_id.desc()).limit(1).with_for_update()).mappings().first()
    active=recent if recent and recent['event_type']=='load' else None
    if body.event_type=='load':
        if body.process_id is None:fail(422,'Load requires a run')
        if sample['status']!='available' or body.to_status!='in_process' or active:fail(409,'Load requires available, unoccupied sample')
    elif body.event_type=='unload':
        if body.process_id is None:fail(422,'Unload requires a run')
        if sample['status']!='in_process' or body.to_status not in ('available','quarantined','consumed') or active is None or active['process_id']!=body.process_id:fail(409,'Unload requires an active load in this run')
        if active['step_id'] is not None and body.step_id is not None:
            st=table('process_steps');load_index=db.scalar(select(st.c.step_index).where(st.c.step_id==active['step_id']))
            if step['step_index']<load_index:fail(409,'Unload boundary precedes load boundary')
    else:
        if body.to_status=='in_process' and sample['status']!='in_process':fail(409,'Only load can enter in_process')
        if sample['status']=='in_process' and body.to_status!='in_process':fail(409,'Unload before changing in-process status')
        allowed={'receive':{'available'},'quarantine':{'quarantined'},'dispose':{'consumed','lost'}}
        if body.event_type in allowed and body.to_status not in allowed[body.event_type]:fail(422,'Event and status do not match')
        if body.event_type in ('cut','measure','process') and body.to_status!=sample['status']:fail(422,'Observation events preserve status')
        if sample['status']=='in_process' and (active is None or body.process_id!=active['process_id']):fail(409,'In-process event requires its active run')
    return append(db,sample,values,user)

def history(request,db,user,page,size,sample_id=None,event_type=None,date_from=None,date_to=None):
    t=table('sample_transitions');s=table('samples')
    q=select(t).join(s,s.c.sample_id==t.c.sample_id).where(scope('samples',user))
    if sample_id is not None:q=q.where(t.c.sample_id==sample_id)
    if event_type is not None:q=q.where(t.c.event_type==event_type)
    if date_from:q=q.where(t.c.event_at>=S.UTCInput.utc(date_from))
    if date_to:q=q.where(t.c.event_at<=S.UTCInput.utc(date_to))
    data,meta=page_result(db,q.order_by(t.c.transition_id),page,size)
    from .experiments import visible
    process_ids={row['process_id'] for row in data if row['process_id'] is not None}
    p=table('processes')
    allowed=set(db.scalars(select(p.c.process_id).where(p.c.process_id.in_(process_ids),visible('processes',user)))) if process_ids else set()
    for row in data:
        row['context_redacted']=(row['process_id'] is not None and row['process_id'] not in allowed) or not reference_visible(db,'measurement',row['measurement_id'],user)
        if row['step_id'] is not None:
            st=table('process_steps')
            parent=db.scalar(select(st.c.process_id).where(st.c.step_id==row['step_id']))
            if parent is None or not reference_visible(db,'process',parent,user):row['context_redacted']=True
        if user['role']!='admin' and row['operator_user_id']!=user['user_id']:
            row['operator_user_id']=None
        if row['context_redacted']:
            for field in ('process_id','step_id','operator_user_id','location','note','measurement_id'):row[field]=None
    return envelope(request,data,meta)

@router.get('/samples/{id}/transitions')
def sample_history(id:int,request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),user=Depends(current_user),db=Depends(get_db)):
    fetch(db,'samples',id,user);return history(request,db,user,page,size,id)
@router.post('/samples/{id}/transitions',status_code=201)
def post_transition(id:int,body:S.TransitionCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    return envelope(request,transition(db,id,body,user))
@router.get('/transitions')
def all_history(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),sample_id:int|None=Query(None,gt=0),event_type:S.EventType|None=None,date_from:S.datetime|None=None,date_to:S.datetime|None=None,user=Depends(current_user),db=Depends(get_db)):
    return history(request,db,user,page,size,sample_id,event_type,date_from,date_to)
