"""Plans and executions. Parent locks serialize child edits with transitions."""
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select, and_, or_, true, func
from .db import table, get_db
from .common import envelope, fail, audit, page_result
from .security import current_user, writer
from .records import fetch as record, scope as record_scope, ordered, protect_delete, dependency_counts, PROTECTED_DEPENDENCIES, require_active_sample
from . import schemas as S

router=APIRouter(prefix='/api/v1',tags=['Experiments'])
KINDS={'plans':('experiment_plans','plan_id','experiment_plan'),'processes':('processes','process_id','process')}

def visible(kind,user):
    if user['role']=='admin':return true()
    b=table('batches');p=table('experiment_plans');r=table('processes')
    plans=and_(p.c.owner_user_id==user['user_id'],or_(p.c.batch_id.is_(None),p.c.batch_id.in_(select(b.c.batch_id).where(record_scope('batches',user)))))
    if kind=='plans':return plans
    links=table('process_samples');s=table('samples')
    bad=select(links.c.process_sample_id).where(links.c.process_id==r.c.process_id,~links.c.sample_id.in_(select(s.c.sample_id).where(record_scope('samples',user)))).exists()
    return and_(r.c.operator_user_id==user['user_id'],or_(r.c.batch_id.is_(None),r.c.batch_id.in_(select(b.c.batch_id).where(record_scope('batches',user)))),or_(r.c.plan_id.is_(None),r.c.plan_id.in_(select(p.c.plan_id).where(plans))),~bad)

def fetch(db,kind,id,user,lock=False,extra_plan_ids=(),allow_void=False):
    name,pk,_=KINDS[kind];t=table(name);q=select(t).where(t.c[pk]==id,visible(kind,user))
    if lock and kind=='processes':
        # Quick records have versioned anonymous results and a separate program contract.
        # Do not let legacy editors silently diverge from their canonical snapshots.
        from .db import metadata
        quick=metadata().tables.get('quick_runs')
        if quick is not None and db.scalar(select(quick.c.process_id).where(quick.c.process_id==id)):
            fail(409,'此执行由实验快录维护，请在实验快录中编辑；专业模式可查看。')
    if lock and kind=='processes':
        # Discover without holding a run lock, then acquire all plans in ID order.
        # Recheck after the locking read: a concurrent reparent must be retried.
        initial=db.execute(q).mappings().first()
        if initial is None:fail(404)
        plan_ids=set(extra_plan_ids)
        if initial['plan_id'] is not None:plan_ids.add(initial['plan_id'])
        for plan_id in sorted(plan_ids):fetch(db,'plans',plan_id,user,True,allow_void=allow_void)
        row=db.execute(q.with_for_update()).mappings().first()
        if row is None:fail(404)
        if row['plan_id']!=initial['plan_id']:fail(409,'Run plan was changed; reload and retry')
        if not allow_void and row.get('voided_at') is not None:fail(409,'执行已作废，不能修改或新增关联')
        return dict(row)
    row=db.execute(q.with_for_update() if lock else q).mappings().first()
    if row is None:fail(404)
    if lock and not allow_void and row.get('voided_at') is not None:fail(409,'记录已作废，不能修改或新增关联')
    return dict(row)

def check_version(row,expected):
    if expected is not None and row['row_version']!=expected:fail(409,'Record was changed; reload and retry')

def values_for(body):
    values=body.model_dump(exclude_unset=True)
    values.pop('expected_row_version',None)
    if 'planned_parameters' in values and body.planned_parameters is not None:
        values['planned_parameters']=body.planned_parameters.model_dump(mode='json',exclude_unset=True)
    if 'custom_parameters' in values and body.custom_parameters is not None:
        # Free-form parameters keep only supplied fields; the stored shape is
        # always {key: {"value":str|null,"unit":str|null,"note":str|null}}.
        values['custom_parameters']={key:item.model_dump(mode='json',exclude_unset=True)
                                     for key,item in body.custom_parameters.items()}
    if 'parameter_snapshot' in values and body.parameter_snapshot is not None:
        values['parameter_snapshot']=body.parameter_snapshot.model_dump(mode='json')
    return values

def bump(db,kind,row):
    name,pk,_=KINDS[kind];t=table(name)
    db.execute(t.update().where(t.c[pk]==row[pk],t.c.row_version==row['row_version']).values(row_version=row['row_version']+1))

def nonnull(t,values):
    if any(v is None and not t.c[k].nullable for k,v in values.items()):fail(422)

def ref(db,name,pk,id):
    if id is not None and not db.execute(select(table(name).c[pk]).where(table(name).c[pk]==id)).first():fail(422,'Referenced resource does not exist')

def dates(row,start,end):
    if row.get(start) is not None and row.get(end) is not None and row[start]>row[end]:fail(422,'End must not precede start')

def reference_record(db,kind,id,user,label):
    from fastapi import HTTPException
    try:
        return record(db,kind,id,user,True) if kind=='batches' else fetch(db,kind,id,user,True)
    except HTTPException as exc:
        if exc.status_code==404:fail(404,f'{label}不存在或无权访问，请从列表重新选择')
        raise

def validate_plan(db,row,user):
    if row.get('batch_id') is not None:reference_record(db,'batches',row['batch_id'],user,'批次（batch_id）')
    dates(row,'planned_start','planned_end')
    if row.get('plan_id'):
        r=table('processes')
        if row.get('batch_id') is not None and db.execute(select(r.c.process_id).where(r.c.plan_id==row['plan_id'],or_(r.c.batch_id.is_(None),r.c.batch_id!=row['batch_id'])).limit(1)).first():fail(409,'Existing runs must retain the plan batch')

def validate_process(db,row,user):
    if row.get('plan_id') is not None:
        plan=reference_record(db,'plans',row['plan_id'],user,'实验计划（plan_id）')
        if plan['batch_id'] is not None and plan['batch_id']!=row.get('batch_id'):fail(422,'批次（batch_id）必须与所选实验计划的批次一致')
    if row.get('batch_id') is not None:reference_record(db,'batches',row['batch_id'],user,'批次（batch_id）')
    if row.get('tool_id') is not None and not db.execute(select(table('tools').c.tool_id).where(table('tools').c.tool_id==row['tool_id'])).first():
        fail(422,'设备（tool_id）不存在，请从设备列表选择；设备编号不能代替数据库 ID')
    dates(row,'started_at','ended_at')
    if row.get('chemistry_system_id') is not None:
        from .chemistry import fetch as chemistry
        from fastapi import HTTPException
        # Preserve the existing PATCH error-status contract; creation uses one
        # scoped lookup for missing and hidden IDs. Neither reveals row content.
        if row.get('process_id'):
            ref(db,'chemistry_systems','system_id',row['chemistry_system_id'])
        try:chemistry(db,'systems',row['chemistry_system_id'],user)
        except HTTPException as exc:
            if exc.status_code==404:fail(404,'化学体系（chemistry_system_id）不存在或无权访问，请重新选择')
            raise
    if row.get('process_id'):
        links=table('process_samples');steps=table('process_steps');ps=table('experiment_plan_steps')
        for sid in db.scalars(select(links.c.sample_id).where(links.c.process_id==row['process_id']).order_by(links.c.sample_id)):
            sample=record(db,'samples',sid,user)
            if row.get('batch_id') is not None and row['batch_id']!=sample['batch_id']:fail(409,'Linked samples conflict with batch')
        for plan_id in db.scalars(select(ps.c.plan_id).join(steps,steps.c.plan_step_id==ps.c.step_id).where(steps.c.process_id==row['process_id'])):
            if plan_id!=row.get('plan_id'):fail(409,'Mapped steps prevent changing plan')

def rows(db,name,pk,value,order):
    t=table(name)
    return [dict(r) for r in db.execute(select(t).where(t.c[pk]==value).order_by(t.c[order])).mappings()]

def links(db,id,user):
    result=rows(db,'process_samples','process_id',id,'process_sample_id')
    from .participation import process_sample_details
    for row in result:
        row['is_control']=bool(row['is_control']);row['sample']=record(db,'samples',row['sample_id'],user)
        sample=row['sample']
        row['batch']=record(db,'batches',sample['batch_id'],user)
        details=process_sample_details(db,row['sample_id'],id,user)
        cumulative=details.pop('cumulative')
        row.update(details)
        row['cumulative_recorded_cycles']=cumulative['recorded_cycles']
        row['cumulative_participations']=cumulative['participation_count']
        row['cumulative_missing_participations']=cumulative['missing_participations']
        row['cumulative_complete']=cumulative['complete']
        row['cycle_groups']=cumulative['cycle_groups']
    return result

def step_response(row, planned=False):
    """Keep legacy bytes readable, but identify the sole current parameter source.

    Coexisting representations may disagree (including units); never infer a
    conversion or rewrite history. Old fields are historical when a snapshot exists.
    """
    legacy = dict(row.get('planned_parameters') or {}) if planned else {
        key: row.get(key) for key in S.StepParameters.model_fields if row.get(key) is not None}
    if row.get('custom_parameters') is not None:
        legacy['custom_parameters'] = row['custom_parameters']
    current = row.get('parameter_snapshot') is not None
    return {**row, 'parameter_source': 'parameter_snapshot' if current else 'legacy_fields',
            'legacy_parameters': legacy,
            'legacy_parameters_status': 'historical_readonly' if current else 'current',
            'parameter_conflict': bool(current and legacy)}

def detail(db,kind,id,user):
    row=fetch(db,kind,id,user)
    if kind=='plans':
        row['steps']=[step_response(s,True) for s in rows(db,'experiment_plan_steps','plan_id',id,'step_index')]
        r=table('processes');row['processes']=[detail(db,'processes',pid,user) for pid in db.scalars(select(r.c.process_id).where(r.c.plan_id==id,visible('processes',user)).order_by(r.c.started_at.is_(None),r.c.started_at,r.c.process_id)).all()]
        row['process_count']=len(row['processes'])
        u=table('users');row['owner']=dict(db.execute(select(u.c.user_id,u.c.username,u.c.display_name).where(u.c.user_id==row['owner_user_id'])).mappings().one()) if row['owner_user_id'] else None
    else:
        row['is_independent_run']=bool(row['is_independent_run'])
        row['steps']=[step_response(s) for s in rows(db,'process_steps','process_id',id,'step_index')];row['samples']=links(db,id,user)
        row['step_count']=len(row['steps']);row['sample_count']=len(row['samples'])
        row['plan']=fetch(db,'plans',row['plan_id'],user) if row['plan_id'] else None
        t=table('tools');row['tool']=dict(db.execute(select(t).where(t.c.tool_id==row['tool_id'])).mappings().one()) if row['tool_id'] else None
        from .db import metadata
        quick=metadata().tables.get('quick_runs')
        if quick is not None and db.scalar(select(quick.c.process_id).where(quick.c.process_id==id)):
            row['quick_record_url']=f'/quick?run={id}'
    row['batch']=record(db,'batches',row['batch_id'],user) if row['batch_id'] else None
    return row

@router.get('/plans')
def list_plans(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),sort:str|None=None,keyword:str=Query('',max_length=128),status:S.PlanStatus|None=None,priority:S.Priority|None=None,batch_id:int|None=Query(None,gt=0),owner_user_id:int|None=Query(None,gt=0),include_voided:bool=False,user=Depends(current_user),db=Depends(get_db)):
    t=table('experiment_plans');q=select(t).where(visible('plans',user))
    if not include_voided:q=q.where(t.c.voided_at.is_(None))
    if keyword:q=q.where(or_(t.c.plan_code.contains(keyword,autoescape=True),t.c.title.contains(keyword,autoescape=True)))
    for k,v in [('status',status),('priority',priority),('batch_id',batch_id),('owner_user_id',owner_user_id)]:
        if v is not None:q=q.where(t.c[k]==v)
    q=ordered(q,t,sort,'-created_at',{'plan_id','plan_code','title','status','priority','planned_start','planned_end','created_at','updated_at'})
    data,meta=page_result(db,q,page,size);return envelope(request,data,meta)

@router.get('/processes')
def list_processes(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),sort:str|None=None,keyword:str=Query('',max_length=128),process_mode:S.ProcessMode|None=None,plan_id:int|None=Query(None,gt=0),batch_id:int|None=Query(None,gt=0),log_status:S.LogStatus|None=None,is_independent_run:bool|None=None,co_etch_group:str|None=Query(None,max_length=64),date_from:S.datetime|None=None,date_to:S.datetime|None=None,include_voided:bool=False,user=Depends(current_user),db=Depends(get_db)):
    t=table('processes');pl=table('experiment_plans');q=select(t,pl.c.title.label('plan_title')).outerjoin(pl,t.c.plan_id==pl.c.plan_id).where(visible('processes',user))
    if not include_voided:q=q.where(t.c.voided_at.is_(None))
    if keyword:q=q.where(or_(t.c.process_code.contains(keyword,autoescape=True),pl.c.title.contains(keyword,autoescape=True)))
    for k,v in [('process_mode',process_mode),('plan_id',plan_id),('batch_id',batch_id),('log_status',log_status),('is_independent_run',is_independent_run),('co_etch_group',co_etch_group)]:
        if v is not None:q=q.where(t.c[k]==v)
    if date_from:q=q.where(t.c.started_at>=S.UTCInput.utc(date_from))
    if date_to:q=q.where(t.c.started_at<=S.UTCInput.utc(date_to))
    q=ordered(q,t,sort,'-created_at',{'process_id','process_code','process_mode','started_at','ended_at','created_at','updated_at','log_status'})
    data,meta=page_result(db,q,page,size)
    for r in data:r['is_independent_run']=bool(r['is_independent_run'])
    return envelope(request,data,meta)

@router.get('/plans/{id}')
def get_plan(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):return envelope(request,detail(db,'plans',id,user))
@router.get('/processes/{id}')
def get_process(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):return envelope(request,detail(db,'processes',id,user))

@router.post('/plans',status_code=201)
def create_plan(body:S.PlanCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    values=body.model_dump();validate_plan(db,values,user);values['owner_user_id']=user['user_id']
    id=db.execute(table('experiment_plans').insert().values(**values)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','experiment_plan',id);return envelope(request,detail(db,'plans',id,user))

@router.post('/processes',status_code=201)
def create_process(body:S.ProcessCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    values=body.model_dump(exclude={'steps','samples','process_flow'});validate_process(db,values,user);values['operator_user_id']=user['user_id']
    id=db.execute(table('processes').insert().values(**values)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','process',id)
    step_ids={}
    for index,step in enumerate(body.steps,1):
        step_ids[f'index:{index}']=add_child(db,'step',id,step,user)['step_id']
    if body.process_flow is not None:
        from .process_flow import references,resolve
        flow=body.process_flow.model_dump(mode='json')
        if set(references(flow))!=set(step_ids):fail(422,'Initial flow must reference each step using index:1, index:2, …')
        db.execute(table('processes').update().where(table('processes').c.process_id==id).values(process_flow=resolve(flow,step_ids)))
    for link in sorted(body.samples,key=lambda x:x.sample_id):add_child(db,'link',id,link,user)
    return envelope(request,detail(db,'processes',id,user))

def patch_parent(db,kind,id,body,user):
    values=values_for(body)
    extra=(values['plan_id'],) if kind=='processes' and values.get('plan_id') is not None else ()
    row=fetch(db,kind,id,user,True,extra);check_version(row,body.expected_row_version)
    if kind=='processes' and set(values)-{'process_code'}:immutable_history(db,id)
    t=table(KINDS[kind][0]);nonnull(t,values)
    if kind=='processes' and 'process_code' in values:
        values['process_code']=(values['process_code'] or '').strip()
        if not values['process_code']:fail(422,'执行编号不能为空')
        if db.scalar(select(t.c.process_id).where(t.c.process_code==values['process_code'],t.c.process_id!=id).limit(1)):
            fail(409,'执行编号已存在，请换一个')
    (validate_plan if kind=='plans' else validate_process)(db,{**row,**values},user)
    db.execute(t.update().where(t.c[KINDS[kind][1]]==id,t.c.row_version==row['row_version']).values(**values,row_version=row['row_version']+1))
    audit(db,user['user_id'],'update',KINDS[kind][2],id)
    if kind=='processes' and 'process_code' in values and row['process_code']!=values['process_code']:
        import json
        db.execute(table('audit_log').insert().values(user_id=user['user_id'],action='update',entity_type='process',entity_id=id,
            field_name='process_code',old_value=json.dumps({'process_code':row['process_code']}),
            new_value=json.dumps({'process_code':values['process_code']})))
    return detail(db,kind,id,user)
@router.patch('/plans/{id}')
def patch_plan(id:int,body:S.PlanUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):return envelope(request,patch_parent(db,'plans',id,body,user))
@router.patch('/processes/{id}')
def patch_process(id:int,body:S.ProcessUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):return envelope(request,patch_parent(db,'processes',id,body,user))

def delete_parent(db,kind,id,user,expected):
    row=fetch(db,kind,id,user,True);check_version(row,expected)
    if kind=='processes':immutable_history(db,id)
    from .lifecycle import delete_allowed_base
    if not delete_allowed_base(db,kind,id,row,user):
        protect_delete(db,KINDS[kind][0],id,user)
        fail(409,'仅无依赖的未使用草稿可删除；请归档或作废')
    protect_delete(db,KINDS[kind][0],id,user)
    t=table(KINDS[kind][0]);db.execute(t.delete().where(t.c[KINDS[kind][1]]==id));audit(db,user['user_id'],'delete',KINDS[kind][2],id)
    return Response(status_code=204)
@router.delete('/plans/{id}',status_code=204)
def delete_plan(id:int,expected_row_version:int|None=Query(None,ge=1),user=Depends(writer),db=Depends(get_db)):return delete_parent(db,'plans',id,user,expected_row_version)

@router.post('/plans/{id}/archive')
def archive_plan(id:int,body:S.PlanArchive,request:Request,user=Depends(writer),db=Depends(get_db)):
    """Archive a plan instead of deleting it; already archived plans are idempotent."""
    row=fetch(db,'plans',id,user,True)
    check_version(row,body.expected_row_version)
    if row['status']!='archived':
        t=table('experiment_plans')
        db.execute(t.update().where(t.c.plan_id==id,t.c.row_version==row['row_version']).values(status='archived',archive_previous_status=row['status'],row_version=row['row_version']+1))
        audit(db,user['user_id'],'update','experiment_plan',id)
    return envelope(request,detail(db,'plans',id,user))
@router.post('/processes/{id}/archive')
def archive_process(id:int,body:S.RecordArchive,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=fetch(db,'processes',id,user,True)
    check_version(row,body.expected_row_version)
    if row['archived_at'] is None:
        t=table('processes')
        changed=db.execute(t.update().where(t.c.process_id==id,t.c.row_version==row['row_version']).values(archived_at=func.utc_timestamp(),row_version=row['row_version']+1))
        if changed.rowcount!=1:fail(409,'记录已变更，请刷新后重试')
        audit(db,user['user_id'],'update','process',id)
    return envelope(request,detail(db,'processes',id,user))

@router.delete('/processes/{id}',status_code=204)
def delete_process(id:int,expected_row_version:int|None=Query(None,ge=1),user=Depends(writer),db=Depends(get_db)):return delete_parent(db,'processes',id,user,expected_row_version)

CHILD={'plan_step':('experiment_plan_steps','step_id','plans','plan_id'),'step':('process_steps','step_id','processes','process_id'),'link':('process_samples','process_sample_id','processes','process_id')}
def child_parent(db,kind,id,user):
    name,pk,parent,fk=CHILD[kind];t=table(name)
    initial=db.execute(select(t).where(t.c[pk]==id)).mappings().first()
    if initial is None:fail(404)
    row=fetch(db,parent,initial[fk],user,True)
    child=db.execute(select(t).where(t.c[pk]==id).with_for_update()).mappings().first()
    if child is None:fail(404)
    return dict(child),row

def validate_child(db,kind,parent,values,user):
    if kind=='plan_step':
        params=values.get('planned_parameters') or {};ref(db,'recipes','recipe_id',params.get('recipe_id'))
    elif kind=='step':
        ref(db,'recipes','recipe_id',values.get('recipe_id'))
        if values.get('plan_step_id') is not None:
            t=table('experiment_plan_steps');ps=db.execute(select(t).where(t.c.step_id==values['plan_step_id'])).mappings().first()
            if ps is None or ps['plan_id']!=parent['plan_id']:fail(422,'Plan step must belong to run plan')
    else:
        sample=require_active_sample(db,values['sample_id'],user)
        if parent['batch_id'] is not None and sample['batch_id']!=parent['batch_id']:fail(422,'Sample must belong to run batch')

def add_child(db,kind,id,body,user):
    name,pk,parent,fk=CHILD[kind];row=fetch(db,parent,id,user,True)
    if parent=='processes':immutable_history(db,id)
    values=values_for(body);validate_child(db,kind,row,values,user)
    cid=db.execute(table(name).insert().values(**values,**{fk:id})).inserted_primary_key[0]
    if kind in ('step','plan_step') and row.get('process_flow') is not None:
        flow=row['process_flow'];flow['children'].append({'kind':'step','id':f'step-{cid}','step_id':cid,'name':None,'repeat':None,'children':[]})
        from .process_flow import ProcessFlow
        try: ProcessFlow.model_validate(flow)
        except ValueError: fail(422,'Flow limit reached; edit the process grid')
        pt=table(KINDS[parent][0]);db.execute(pt.update().where(pt.c[KINDS[parent][1]]==id).values(process_flow=flow))
    bump(db,parent,row);audit(db,user['user_id'],'insert',{'plan_step':'experiment_plan_step','step':'process_step','link':'process_sample'}[kind],cid)
    return dict(db.execute(select(table(name)).where(table(name).c[pk]==cid)).mappings().one())

def used_child(db,kind,child,user=None):
    if kind=='plan_step':
        t=table('process_steps');q=select(t.c.step_id).where(t.c.plan_step_id==child['step_id'])
    else:
        t=table('sample_transitions');q=select(t.c.transition_id).where(t.c.step_id==child['step_id']) if kind=='step' else select(t.c.transition_id).where(t.c.process_id==child['process_id'],t.c.sample_id==child['sample_id'])
    # Parent plan/process locks serialize writers. Do not lock a dependent actual
    # step after its plan step (the reverse path validates actual -> planned step).
    count,hidden=dependency_counts(db,t.name,q,user)
    dependencies=[]
    if count:dependencies.append(f'关联的{"实际步骤" if kind=="plan_step" else "样品流转记录"}共 {count} 条')
    if hidden:dependencies.append(PROTECTED_DEPENDENCIES)
    if dependencies:fail(409,'、'.join(dependencies)+'，不能修改或删除历史关联，请保留记录')

def immutable_history(db,process_id):
    # Called after the scoped parent lock, before ANY process/child mutation.
    # Empty process structure is editable; scientific references freeze the run.
    # Scan both FK and polymorphic references, including references to any step.
    # Counts are deliberately not disclosed: some dependents may be inaccessible.
    process=table('processes');steps=table('process_steps')
    step_ids=select(steps.c.step_id).where(steps.c.process_id==process_id)
    for candidate in process.metadata.tables.values():
        if candidate.name in ('audit_log','process_steps','process_samples'):continue
        predicates=[]
        for constraint in candidate.foreign_key_constraints:
            for link in constraint.elements:
                if link.column is process.c.process_id:
                    predicates.append(candidate.c[link.parent.name]==process_id)
                elif link.column is steps.c.step_id:
                    predicates.append(candidate.c[link.parent.name].in_(step_ids))
        if 'entity_type' in candidate.c and 'entity_id' in candidate.c:
            predicates.extend([
                and_(candidate.c.entity_type=='process',candidate.c.entity_id==process_id),
                and_(candidate.c.entity_type=='process_step',candidate.c.entity_id.in_(step_ids))])
        if predicates and db.execute(select(candidate).where(or_(*predicates)).limit(1)).first():
            fail(409,'已有科研或样品流转历史关联，不能覆盖历史工艺，请保留记录（Run has recorded history; historical data cannot be overwritten）')

def change_child(db,kind,id,body,user,expected=None):
    child,parent=child_parent(db,kind,id,user);check_version(parent,body.expected_row_version if body else expected)
    name,pk,p_kind,_=CHILD[kind];t=table(name)
    if kind in ('step','link'):immutable_history(db,parent['process_id'])
    # A referenced plan step is immutable; all run PATCHes freeze after history.
    if kind=='plan_step' or body is None:used_child(db,kind,child,user)
    if body:
        values=values_for(body);nonnull(t,values)
        if kind in ('step','plan_step') and parent.get('process_flow') and values.get('step_index',child['step_index'])!=child['step_index']:
            fail(409,'Use the process grid to reorder grouped steps')
        if kind=='step' and any(k in values and values[k]!=child[k] for k in ('step_index','step_kind','plan_step_id')):used_child(db,kind,child,user)
        validate_child(db,kind,parent,{**child,**values},user)
        db.execute(t.update().where(t.c[pk]==id).values(**values))
    else:
        protect_delete(db,name,id,user)
        if kind in ('step','plan_step') and parent.get('process_flow') is not None:
            flow=parent['process_flow']
            def remove_ref(nodes):
                return [{**n,'children':remove_ref(n['children'])} if n['kind']=='group' else n for n in nodes if n['kind']!='step' or n['step_id']!=id]
            flow['children']=remove_ref(flow['children'])
            pt=table(KINDS[p_kind][0]);db.execute(pt.update().where(pt.c[KINDS[p_kind][1]]==parent[KINDS[p_kind][1]]).values(process_flow=flow))
        db.execute(t.delete().where(t.c[pk]==id))
    bump(db,p_kind,parent);audit(db,user['user_id'],'update' if body else 'delete',{'plan_step':'experiment_plan_step','step':'process_step','link':'process_sample'}[kind],id)
    return dict(db.execute(select(t).where(t.c[pk]==id)).mappings().one()) if body else Response(status_code=204)

@router.get('/plans/{id}/steps')
def plan_steps(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    fetch(db,'plans',id,user);return envelope(request,[step_response(s,True) for s in rows(db,'experiment_plan_steps','plan_id',id,'step_index')])
@router.post('/plans/{id}/steps',status_code=201)
def post_plan_step(id:int,body:S.PlanStepCreate,request:Request,user=Depends(writer),db=Depends(get_db)):return envelope(request,step_response(add_child(db,'plan_step',id,body,user),True))
@router.patch('/plan-steps/{id}')
def patch_plan_step(id:int,body:S.PlanStepUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):return envelope(request,step_response(change_child(db,'plan_step',id,body,user),True))
@router.delete('/plan-steps/{id}',status_code=204)
def delete_plan_step(id:int,expected_row_version:int|None=Query(None,ge=1),user=Depends(writer),db=Depends(get_db)):return change_child(db,'plan_step',id,None,user,expected_row_version)
@router.get('/processes/{id}/steps')
def process_steps(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    fetch(db,'processes',id,user);return envelope(request,[step_response(s) for s in rows(db,'process_steps','process_id',id,'step_index')])
@router.post('/processes/{id}/steps',status_code=201)
def post_step(id:int,body:S.ProcessStepCreate,request:Request,user=Depends(writer),db=Depends(get_db)):return envelope(request,step_response(add_child(db,'step',id,body,user),False))
@router.patch('/process-steps/{id}')
def patch_step(id:int,body:S.ProcessStepUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):return envelope(request,step_response(change_child(db,'step',id,body,user),False))
@router.delete('/process-steps/{id}',status_code=204)
def delete_step(id:int,expected_row_version:int|None=Query(None,ge=1),user=Depends(writer),db=Depends(get_db)):return change_child(db,'step',id,None,user,expected_row_version)
@router.get('/processes/{id}/samples')
def process_samples(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    fetch(db,'processes',id,user);return envelope(request,links(db,id,user))
@router.post('/processes/{id}/samples',status_code=201)
def post_link(id:int,body:S.ProcessSampleCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=add_child(db,'link',id,body,user);row['is_control']=bool(row['is_control']);return envelope(request,row)

@router.post('/processes/{id}/samples/batch',status_code=201)
def post_links(id:int,body:S.BatchLinkCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    """Bind 1-50 samples to one run in a single transaction; the parent bumps once."""
    row=fetch(db,'processes',id,user,True)
    immutable_history(db,id)
    links=table('process_samples');common=body.model_dump(exclude={'sample_ids'})
    existing=set(db.scalars(select(links.c.sample_id).where(links.c.process_id==id)))
    created=[]
    # Sorted sample locks keep concurrent batch writers deadlock-free.
    for sample_id in sorted(set(body.sample_ids)):
        if sample_id in existing:fail(409,f'Sample {sample_id} is already bound to this run')
        values={**common,'sample_id':sample_id}
        validate_child(db,'link',row,values,user)
        created.append(db.execute(links.insert().values(**values,process_id=id)).inserted_primary_key[0])
    bump(db,'processes',row)
    result=[]
    for cid in created:
        audit(db,user['user_id'],'insert','process_sample',cid)
        link=dict(db.execute(select(links).where(links.c.process_sample_id==cid)).mappings().one())
        link['is_control']=bool(link['is_control']);link['sample']=record(db,'samples',link['sample_id'],user)
        result.append(link)
    return envelope(request,{'created':result,'count':len(result)})
@router.patch('/process-samples/{id}')
def patch_link(id:int,body:S.ProcessSampleUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=change_child(db,'link',id,body,user);row['is_control']=bool(row['is_control']);return envelope(request,row)
@router.delete('/process-samples/{id}',status_code=204)
def delete_link(id:int,expected_row_version:int|None=Query(None,ge=1),user=Depends(writer),db=Depends(get_db)):return change_child(db,'link',id,None,user,expected_row_version)

@router.put('/{kind}/{id}/process-grid')
def save_process_grid(kind:str,id:int,body:S.ProcessGridSave,request:Request,user=Depends(writer),db=Depends(get_db)):
    """One transaction for layout and existing step snapshots, with parent CAS.

    Existing IDs are updated in place. Mapped/history rows use the same guards as
    the individual endpoints. No planned values or legacy fields are inferred.
    """
    from .process_flow import references, resolve
    if kind not in KINDS: fail(404)
    parent=fetch(db,kind,id,user,True)
    check_version(parent,body.expected_row_version)
    if kind=='processes': immutable_history(db,id)
    child_kind='plan_step' if kind=='plans' else 'step'
    name,pk,_,fk=CHILD[child_kind];t=table(name)
    existing={r['step_id']:r for r in rows(db,name,fk,id,'step_index')}
    keys=[s.key for s in body.steps]
    ids=[s.step_id for s in body.steps if s.step_id is not None]
    if len(set(keys))!=len(keys) or len(set(ids))!=len(ids): fail(422,'Grid step keys and IDs must be unique')
    if any(sid not in existing for sid in ids): fail(422,'Every existing step must belong to this record')
    flow=body.process_flow.model_dump(mode='json')
    refs=references(flow)
    if any(not isinstance(ref,str) for ref in refs) or set(refs)!=set(keys):
        fail(422,'Flow must reference each submitted step key exactly once')
    ordered_steps={s.key:s for s in body.steps}
    ordered=[ordered_steps[key] for key in refs]
    removed=[row for sid,row in existing.items() if sid not in ids]
    for row in removed:
        used_child(db,child_kind,row,user)
        protect_delete(db,name,row[pk],user)
    # Mapped plan rows may remain byte-for-byte unchanged, but cannot be edited.
    updates=[]
    for index,step in enumerate(ordered,1):
        values={'step_index':index,'step_kind':step.step_kind,'step_name':step.step_name,
                'parameter_snapshot':step.parameter_snapshot.model_dump(mode='json')}
        if kind=='processes': values['plan_step_id']=step.plan_step_id
        elif step.plan_step_id is not None: fail(422,'Plan steps cannot map to plan steps')
        validate_child(db,child_kind,parent,values,user)
        previous=existing.get(step.step_id)
        if previous and any(previous[k]!=v for k,v in values.items()):
            if child_kind=='plan_step' or any(previous[k]!=values[k] for k in ('step_index','step_kind','plan_step_id') if k in values):
                used_child(db,child_kind,previous,user)
        updates.append((step,values))
    # Unique (parent,index) is maintained during permutations using a vacant
    # positive temporary range. IDs, source mappings and all other fields survive.
    max_index=max([r['step_index'] for r in existing.values()]+[0])
    temporary=max_index+len(existing)+len(ordered)+1
    if temporary+len(existing)>4294967295: fail(422,'Step index range exhausted')
    for offset,row in enumerate(existing.values()):
        db.execute(t.update().where(t.c[pk]==row[pk]).values(step_index=temporary+offset))
    for row in removed:
        db.execute(t.delete().where(t.c[pk]==row[pk]));audit(db,user['user_id'],'delete', 'experiment_plan_step' if kind=='plans' else 'process_step',row[pk])
    mapping={}
    for step,values in updates:
        sid=step.step_id
        if sid is None:
            sid=db.execute(t.insert().values(**values,**{fk:id})).inserted_primary_key[0]
        else: db.execute(t.update().where(t.c[pk]==sid).values(**values))
        mapping[step.key]=sid
        audit(db,user['user_id'],'update' if step.step_id else 'insert','experiment_plan_step' if kind=='plans' else 'process_step',sid)
    resolved_flow=resolve(flow,mapping)
    if kind=='plans' and parent.get('process_flow')!=resolved_flow:
        mapped=table('process_steps')
        if existing and db.execute(select(mapped.c.step_id).where(mapped.c.plan_step_id.in_(list(existing))).limit(1)).first():
            fail(409,'Mapped plan flow is historical; preserve its grouping and repeats')
    parent_t=table(KINDS[kind][0]);parent_pk=KINDS[kind][1]
    changed=db.execute(parent_t.update().where(parent_t.c[parent_pk]==id,parent_t.c.row_version==body.expected_row_version).values(process_flow=resolved_flow,row_version=body.expected_row_version+1))
    if changed.rowcount!=1: fail(409,'Record was changed; reload and retry')
    audit(db,user['user_id'],'update',KINDS[kind][2],id)
    return envelope(request,detail(db,kind,id,user))
