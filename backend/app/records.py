import json
import hashlib
from fastapi import APIRouter,Depends,Request,Query,Response
from sqlalchemy import select,or_,and_,true,false,func
from sqlalchemy.exc import IntegrityError
from .db import table,metadata,get_db
from .common import fail,envelope,audit,page_result,dbnow
from .security import current_user,writer,admin
from . import schemas as S

router=APIRouter(prefix='/api/v1',tags=['Records'])

def scope(kind,user):
    b=table('batches');s=table('samples')
    if user['role']=='admin':return true()
    if kind=='batches':return b.c.owner_user_id==user['user_id']
    return and_(s.c.owner_user_id==user['user_id'],s.c.batch_id.in_(select(b.c.batch_id).where(b.c.owner_user_id==user['user_id'])))

def fetch(db,kind,id,user,lock=False,allow_void=False):
    t=table(kind);q=select(t).where(t.c[('batch' if kind == 'batches' else 'sample')+'_id']==id,scope(kind,user))
    row=db.execute(q.with_for_update() if lock else q).mappings().first()
    if not row:fail(404)
    if lock and not allow_void and row.get('voided_at') is not None:fail(409,'记录已作废，不能修改或新增关联')
    return dict(row)

def require_active_sample(db,sample_id,user):
    """Lock and return a visible, non-voided sample; call before any new association.

    Keep this lock until the association transaction commits. Acquire process/plan
    locks first and multiple sample locks in ID order, as in existing writers.
    """
    row=fetch(db,'samples',sample_id,user,True)
    if row['voided_at'] is not None:fail(409,'样品已作废，不能修改或新增科研关联')
    if row.get('archived_at') is not None:fail(409,'样品已归档，请先恢复')
    return row

def protect_sample_void(db,row):
    """Fail closed: only an available sample with its sole initial receipt is safe."""
    if row['status']!='available':fail(409,'仅可作废误建且未使用的可用样品；实际使用样品请隔离或排除分析')
    t=table('sample_transitions')
    history=list(db.execute(select(t).where(t.c.sample_id==row['sample_id'])).mappings())
    if len(history)!=1:fail(409,'样品已有流转历史或缺少可确认的初始记录，不能作废')
    initial=history[0]
    if (initial['from_status'] is not None or initial['to_status']!='available' or initial['event_type']!='receive'
        or any(initial.get(k) is not None for k in ('process_id','step_id','measurement_id','event_at','location','note'))):
        fail(409,'样品已有实际流转历史，不能作废；请隔离或排除分析')
    # A legacy receive event is not enough: require creation audit evidence.
    a=table('audit_log')
    for entity,key in [('sample',row['sample_id']),('sample_transition',initial['transition_id'])]:
        if not db.scalar(select(a.c.audit_id).where(a.c.entity_type==entity,a.c.entity_id==key,a.c.action=='insert').limit(1)):
            fail(409,'缺少可确认的初始创建审计，不能作废')
    target=table('samples');pk=target.c.sample_id
    for candidate in metadata().tables.values():
        if candidate.name in ('audit_log','sample_transitions'):continue
        predicates=[]
        for constraint in candidate.foreign_key_constraints:
            if constraint.referred_table is target:
                predicates.extend(candidate.c[link.parent.name]==row['sample_id'] for link in constraint.elements if link.column is pk)
        if 'entity_type' in candidate.c and 'entity_id' in candidate.c:
            predicates.append(and_(candidate.c.entity_type=='sample',candidate.c.entity_id==row['sample_id']))
        if predicates and db.execute(select(list(candidate.c)[0]).where(or_(*predicates)).limit(1)).first():
            # Deliberately no names/counts: this includes records outside caller scope.
            fail(409,'样品存在科研、来源文件、子样品或其他关联记录，不能作废；请隔离或排除分析')

@router.post('/samples/{id}/void')
def void_sample(id:int,body:S.SampleVoid,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=fetch(db,'samples',id,user,True,allow_void=True)
    if row['row_version']!=body.expected_row_version:fail(409,'记录已变更，请刷新后重试')
    if row['voided_at'] is not None:
        if body.reason!=row['void_reason']:fail(409,'样品已作废，不能改写作废原因')
        return envelope(request,serialize_record(row))
    protect_sample_void(db,row)
    at=dbnow();s=table('samples')
    values=dict(voided_at=at,void_reason=body.reason,voided_by_user_id=user['user_id'],row_version=row['row_version']+1)
    result=db.execute(s.update().where(s.c.sample_id==id,s.c.row_version==row['row_version'],s.c.voided_at.is_(None)).values(**values))
    if result.rowcount!=1:fail(409,'记录已变更，请刷新后重试')
    # Only explicit lifecycle metadata is audited; scientific values stay intact.
    new={**values,'voided_at':at.isoformat()+'+00:00'}
    old={key:row[key] for key in values}
    db.execute(table('audit_log').insert().values(user_id=user['user_id'],action='update',entity_type='sample',entity_id=id,
        field_name='void_metadata',old_value=json.dumps(old,ensure_ascii=False),new_value=json.dumps(new,ensure_ascii=False),occurred_at=at))
    return envelope(request,serialize_record(fetch(db,'samples',id,user)))

def serialize_record(row):
    for key in ('anomaly_flag','exclude_from_analysis'):
        if key in row:row[key]=bool(row[key])
    return row

def ordered(q,t,sort,default,allowed):
    columns=[]
    for token in (sort or default).split(','):
        name=token.lstrip('-')
        if name not in allowed or not token or token.startswith('--'):fail(422,'Invalid sort field')
        columns.append(t.c[name].desc() if token.startswith('-') else t.c[name].asc())
    return q.order_by(*columns,t.c[list(t.primary_key.columns)[0].name])

@router.get('/batches')
def batches(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),sort:str|None=None,keyword:str=Query('',max_length=128),status:S.BatchStatus|None=None,anomaly_flag:bool|None=None,material:str|None=None,include_voided:bool=False,user=Depends(current_user),db=Depends(get_db)):
    b=table('batches');q=select(b).where(scope('batches',user))
    if not include_voided:q=q.where(b.c.voided_at.is_(None))
    if keyword:q=q.where(or_(b.c.batch_code.contains(keyword,autoescape=True),b.c.batch_name.contains(keyword,autoescape=True)))
    if status:q=q.where(b.c.status==status)
    if anomaly_flag is not None:q=q.where(b.c.anomaly_flag==anomaly_flag)
    if material is not None:q=q.where(b.c.material==material)
    q=ordered(q,b,sort,'-deposit_date',{'batch_id','batch_code','batch_name','material','status','deposit_date','created_at','updated_at','nominal_thickness_nm'})
    rows,meta=page_result(db,q,page,size)
    return envelope(request,[serialize_record(r) for r in rows],meta)

@router.get('/tools')
def tools(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),keyword:str=Query('',max_length=128),user=Depends(current_user),db=Depends(get_db)):
    t=table('tools');q=select(t)
    if keyword:q=q.where(or_(t.c.tool_code.contains(keyword,autoescape=True),t.c.tool_name.contains(keyword,autoescape=True)))
    rows,meta=page_result(db,q.order_by(t.c.tool_name,t.c.tool_id),page,size)
    return envelope(request,rows,meta)

@router.post('/batches/{id}/archive')
def archive_batch(id:int,body:S.RecordArchive,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=fetch(db,'batches',id,user,True)
    if row['row_version']!=body.expected_row_version:fail(409,'记录已变更，请刷新后重试')
    if row['archived_at'] is None:
        t=table('batches')
        changed=db.execute(t.update().where(t.c.batch_id==id,t.c.row_version==row['row_version']).values(archived_at=func.utc_timestamp(),row_version=row['row_version']+1))
        if changed.rowcount!=1:fail(409,'记录已变更，请刷新后重试')
        audit(db,user['user_id'],'update','batch',id)
    return envelope(request,serialize_record(fetch(db,'batches',id,user)))

@router.get('/samples')
def samples(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),sort:str|None=None,keyword:str=Query('',max_length=128),batch_id:int|None=Query(None,ge=1),sample_type:S.SampleType|None=None,status:S.SampleStatus|None=None,exclude_from_analysis:bool|None=None,parent_sample_id:int|None=Query(None,ge=1),include_voided:bool=False,include_archived:bool=False,user=Depends(current_user),db=Depends(get_db)):
    return list_samples(request,db,user,page,size,sort,keyword,batch_id,sample_type,status,exclude_from_analysis,parent_sample_id,include_voided,include_archived)

def list_samples(request,db,user,page,size,sort=None,keyword='',batch_id=None,sample_type=None,status=None,exclude_from_analysis=None,parent_sample_id=None,include_voided=False,include_archived=False):
    s=table('samples');b=table('batches');q=select(s,b.c.batch_code).join(b,s.c.batch_id==b.c.batch_id).where(scope('samples',user))
    if not include_voided:q=q.where(s.c.voided_at.is_(None))
    if not include_archived:q=q.where(s.c.archived_at.is_(None))
    if keyword:q=q.where(or_(s.c.sample_code.contains(keyword,autoescape=True),s.c.display_label.contains(keyword,autoescape=True)))
    for key,value in [('batch_id',batch_id),('sample_type',sample_type),('status',status),('exclude_from_analysis',exclude_from_analysis),('parent_sample_id',parent_sample_id)]:
        if value is not None:q=q.where(s.c[key]==value)
    q=ordered(q,s,sort,'batch_id,sample_code',{'sample_id','sample_code','batch_id','status','sample_type','created_at','updated_at','nominal_thickness_nm'})
    rows,meta=page_result(db,q,page,size)
    return envelope(request,[serialize_record(r) for r in rows],meta)

@router.get('/batches/{id}/samples')
def batch_samples(id:int,request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),include_voided:bool=False,include_archived:bool=False,user=Depends(current_user),db=Depends(get_db)):
    fetch(db,'batches',id,user)
    return list_samples(request,db,user,page,size,batch_id=id,include_voided=include_voided,include_archived=include_archived)

def batch_unused(db,id):
    from .lifecycle import predicates_for
    target=table('batches')
    for candidate in metadata().tables.values():
        if candidate.name=='audit_log':continue
        predicates=predicates_for(candidate,target,'batches','batch_id',id)
        if predicates and db.execute(select(list(candidate.c)[0]).where(or_(*predicates)).limit(1)).first():return False
    return True

def batch_code_status(db,code,user):
    b=table('batches')
    row=db.execute(select(b).where(b.c.batch_code==code)).mappings().first()
    if not row:return {'available':True,'namespace':'global','message':'编号可用；正式与测试账户共用全局唯一编号，测试建议使用 TEST- 前缀。'}
    if user['role']!='admin' and row['owner_user_id']!=user['user_id']:
        return {'available':False,'restricted':True,'message':'编号不可用，请换用个人或 TEST- 测试前缀。'}
    from .lifecycle import impact
    state='已作废' if row['voided_at'] else '已归档' if row['archived_at'] or row['status']=='archived' else '仍存在'
    return {'available':False,'restricted':False,'message':f'该编号的批次{state}，历史编号仍被保留。请打开已有批次；归档记录可恢复，完全未使用的误建记录可更正编号。',
        'existing':{key:row[key] for key in ('batch_id','batch_code','batch_name','row_version','archived_at','voided_at','status')},
        'can_rename':batch_unused(db,row['batch_id']),'lifecycle':impact(db,'batches',row['batch_id'],user)}

@router.get('/batches/code-status')
def code_status(request:Request,code:str=Query(min_length=1,max_length=64),user=Depends(current_user),db=Depends(get_db)):
    if not code.strip():fail(422,'编号不能为空')
    return envelope(request,batch_code_status(db,code.strip(),user))

@router.patch('/batches/{id}/code')
def rename_batch_code(id:int,body:S.BatchCodeUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=fetch(db,'batches',id,user,True,allow_void=True)
    code=body.batch_code.strip();reason=body.reason.strip()
    if not code or not reason:fail(422,'编号和更正原因不能为空')
    if row['row_version']!=body.expected_row_version:fail(409,'记录已变更，请刷新后重试')
    if not batch_unused(db,id):fail(409,'批次已有样品或科研关联，必须保留历史编号；请更改新批次编号或使用已有批次')
    if code==row['batch_code']:return envelope(request,serialize_record(row))
    status=batch_code_status(db,code,user)
    if not status['available']:fail(409,status['message'])
    try:
        with db.begin_nested():
            db.execute(table('batches').update().where(table('batches').c.batch_id==id).values(batch_code=code,row_version=row['row_version']+1))
    except IntegrityError as exc:
        if exc.orig.args[0]!=1062:raise
        fail(409,'编号不可用，请刷新核查或更换编号')
    db.execute(table('audit_log').insert().values(user_id=user['user_id'],action='update',entity_type='batch',entity_id=id,field_name='batch_code',
        old_value=json.dumps({'batch_code':row['batch_code']},ensure_ascii=False),new_value=json.dumps({'batch_code':code,'reason':reason},ensure_ascii=False),occurred_at=dbnow()))
    return envelope(request,serialize_record(fetch(db,'batches',id,user)))

@router.get('/batches/{id}')
def batch(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    return envelope(request,serialize_record(fetch(db,'batches',id,user)))

@router.get('/samples/{id}')
def sample(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    row=fetch(db,'samples',id,user);b=fetch(db,'batches',row['batch_id'],user)
    row['batch_code']=b['batch_code'];row['batch']=serialize_record(b)
    s=table('samples');row['children']=[serialize_record(dict(x)) for x in db.execute(select(s).where(s.c.parent_sample_id==id,scope('samples',user)).order_by(s.c.sample_id)).mappings()]
    from .participation import sample_experiments
    row['experiments'],row['participation_summary']=sample_experiments(db,id,user)
    from .sample_review import review
    row['research_review']=review(db,id,user,row['experiments'],row['exclude_from_analysis'])
    return envelope(request,serialize_record(row))

def validate_exclusion(row):
    if row.get('exclude_from_analysis') and not (row.get('exclude_reason') or '').strip():fail(422,'Exclusion requires a reason')

def insert_record(db,kind,values,user):
    t=table(kind)
    id=db.execute(t.insert().values(**values)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert',('batch' if kind == 'batches' else 'sample'),id)
    return serialize_record(fetch(db,kind,id,user))

@router.post('/batches',status_code=201)
def create_batch(body:S.BatchCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    values=body.model_dump();values['owner_user_id']=user['user_id']
    values['batch_code']=values['batch_code'].strip()
    if not values['batch_code']:fail(422,'编号不能为空')
    status=batch_code_status(db,values['batch_code'],user)
    if not status['available']:fail(409,status['message'])
    try:
        with db.begin_nested():row=insert_record(db,'batches',values,user)
    except IntegrityError as exc:
        if exc.orig.args[0]!=1062:raise
        fail(409,'编号不可用，请刷新核查或更换编号')
    return envelope(request,row)

@router.post('/samples',status_code=201)
def create_sample(body:S.SampleCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    values=body.model_dump();b=fetch(db,'batches',body.batch_id,user,True)
    values['owner_user_id']=b['owner_user_id'];validate_exclusion(values)
    if body.parent_sample_id is not None:
        parent=require_active_sample(db,body.parent_sample_id,user)
        if parent['batch_id']!=body.batch_id or parent['owner_user_id']!=b['owner_user_id'] or parent['sample_type'] not in ('parent_wafer','full_wafer'):fail(422,'Parent must be a wafer in the same batch and ownership scope')
        # Parent cannot be reparented via PATCH; a new generated ID cannot be an ancestor.
    if body.status=='in_process':fail(409,'Use load to enter in_process')
    row=insert_record(db,'samples',values,user)
    from .transitions import initial_history
    initial_history(db,row,user)
    return envelope(request,row)

@router.post('/batches/{id}/samples/batch',status_code=201)
def create_batch_samples(id:int,body:S.BatchSampleCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    """Create 1-50 samples for one visible batch in a single all-or-nothing transaction."""
    b=fetch(db,'batches',id,user,True)
    receipt=None
    if body.request_key:
        fingerprint=hashlib.sha256(json.dumps(body.model_dump(mode='json'),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        a=table('audit_log')
        for saved in db.execute(select(a.c.new_value).where(a.c.entity_type=='batch',a.c.entity_id==id,a.c.user_id==user['user_id'],a.c.field_name=='bulk_sample_create')).scalars():
            value=json.loads(saved)
            if value['request_key']==body.request_key:
                if value['fingerprint']!=fingerprint:fail(409,'同一次样品创建请求内容已变化，请先核对原创建结果')
                created=[serialize_record(fetch(db,'samples',sid,user)) for sid in value['sample_ids']]
                return envelope(request,{'created':created,'count':len(created)})
        receipt={'request_key':body.request_key,'fingerprint':fingerprint}
    parent=None
    if body.parent_sample_id is not None:
        parent=require_active_sample(db,body.parent_sample_id,user)
        if parent['batch_id']!=id or parent['owner_user_id']!=b['owner_user_id'] or parent['sample_type'] not in ('parent_wafer','full_wafer'):
            fail(422,'Parent must be a wafer in the same batch and ownership scope')
    seen=set();rows=[]
    for item in body.items:
        if item.sample_code in seen:fail(409,f'Duplicate sample code in request: {item.sample_code}')
        seen.add(item.sample_code)
        values=item.model_dump();values['batch_id']=id
        values['parent_sample_id']=body.parent_sample_id;values['owner_user_id']=b['owner_user_id']
        validate_exclusion(values)
        if values['status']=='in_process':fail(409,'Use load to enter in_process')
        rows.append(values)
    s=table('samples')
    clash=db.execute(select(s.c.sample_code).where(s.c.sample_code.in_(sorted(seen))).limit(1)).scalar()
    if clash:fail(409,f'Sample code already exists: {clash}')
    created=[insert_record(db,'samples',values,user) for values in rows]
    from .transitions import initial_history
    for row in created:initial_history(db,row,user)
    if receipt is not None:
        db.execute(a.insert().values(user_id=user['user_id'],action='insert',entity_type='batch',entity_id=id,field_name='bulk_sample_create',
            new_value=json.dumps({**receipt,'sample_ids':[r['sample_id'] for r in created]}),occurred_at=dbnow()))
    return envelope(request,{'created':created,'count':len(created)})

def patch_record(db,kind,id,body,user):
    row=fetch(db,kind,id,user,True);values=body.model_dump(exclude_unset=True);expected=values.pop('expected_row_version',None)
    if expected is not None and expected!=row['row_version']:fail(409,'Record was changed; reload and retry')
    if kind=='samples':
        require_active_sample(db,id,user)
        validate_exclusion({**row,**values})
    old_code=None
    if kind=='samples' and 'sample_code' in values:
        code=(values['sample_code'] or '').strip()
        if not code:fail(422,'样品编号不能为空')
        # Relational history uses sample_id; the visible code is a mutable label.
        clash=db.execute(select(table('samples').c.sample_code).where(
            table('samples').c.sample_code==code,table('samples').c.sample_id!=id).limit(1)).scalar()
        if clash:fail(409,'样品编号已存在，请换一个')
        old_code=row['sample_code'];values['sample_code']=code
    t=table(kind)
    if any(value is None and not t.c[key].nullable for key,value in values.items()):fail(422)
    update_version=row['row_version']
    if kind=='samples' and 'status' in values and values['status']!=row['status']:
        from .transitions import patch_status
        patch_status(db,row,values.pop('status'),user)
        # append already advances the version within this request transaction.
        update_version+=1
    values['row_version']=row['row_version']+1
    changed=db.execute(t.update().where(t.c[('batch' if kind == 'batches' else 'sample')+'_id']==id,t.c.row_version==update_version).values(**values))
    if changed.rowcount!=1:fail(409,'Record was changed; reload and retry')
    audit(db,user['user_id'],'update',('batch' if kind == 'batches' else 'sample'),id)
    if old_code is not None and old_code!=values['sample_code']:
        db.execute(table('audit_log').insert().values(user_id=user['user_id'],action='update',
            entity_type='sample',entity_id=id,field_name='sample_code',
            old_value=json.dumps({'sample_code':old_code},ensure_ascii=False),
            new_value=json.dumps({'sample_code':values['sample_code']},ensure_ascii=False),occurred_at=dbnow()))
    return serialize_record(fetch(db,kind,id,user))

@router.patch('/batches/{id}')
def patch_batch(id:int,body:S.BatchUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    return envelope(request,patch_record(db,'batches',id,body,user))

@router.patch('/samples/{id}')
def patch_sample(id:int,body:S.SampleUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    return envelope(request,patch_record(db,'samples',id,body,user))

PROTECTED_DEPENDENCIES='另有受权限保护的关联记录'

def dependency_scope(name,user):
    """Only disclose counts with a known API visibility rule; default to hidden."""
    if user is None or user['role']=='admin':return true()
    if name in ('batches','samples'):return scope(name,user)
    if name in ('experiment_plans','processes','experiment_plan_steps','process_steps','process_samples'):
        from .experiments import visible
        if name=='experiment_plans':return visible('plans',user)
        if name=='processes':return visible('processes',user)
        parent,pk,kind=('experiment_plans','plan_id','plans') if name=='experiment_plan_steps' else ('processes','process_id','processes')
        return table(name).c[pk].in_(select(table(parent).c[pk]).where(visible(kind,user)))
    if name=='sample_transitions':
        return table(name).c.sample_id.in_(select(table('samples').c.sample_id).where(scope('samples',user)))
    if name in ('measurements','measurement_points','instrument_datasets','source_files','source_file_occurrences'):
        from .measurement_management import measurement_scope,dataset_scope,source_scope,occurrence_scope
        if name=='measurement_points':
            m=table('measurements')
            return table(name).c.measurement_id.in_(select(m.c.measurement_id).where(measurement_scope(user)))
        return {'measurements':measurement_scope,'instrument_datasets':dataset_scope,
                'source_files':source_scope,'source_file_occurrences':occurrence_scope}[name](user)
    return false()

def dependency_counts(db,name,q,user=None):
    # Global checks enforce integrity even when the caller cannot see a dependent.
    total=db.scalar(select(func.count()).select_from(q.subquery()))
    if not total or user is None or user['role']=='admin':return total,False
    visible=db.scalar(select(func.count()).select_from(q.where(dependency_scope(name,user)).subquery()))
    return visible,visible<total

def protect_delete(db,kind,id,user=None):
    # Parent locks serialize application writers; FK constraints close races with
    # unrelated parents. Dependency checks must not acquire child locks in reverse.
    target=table(kind);pk=list(target.primary_key.columns)[0]
    dependencies=[];hidden=False
    labels={'samples':'样品','experiment_plans':'实验计划','experiment_plan_steps':'计划步骤',
            'processes':'工艺执行','process_steps':'实际步骤','process_samples':'工艺样品关联',
            'sample_transitions':'样品流转记录','measurements':'测量记录','measurement_points':'测量点',
            'derived_results':'派生结果','instrument_datasets':'仪器数据集','findings':'研究发现',
            'issues':'问题记录','issue_links':'问题关联','issues_links':'问题关联','attachments':'附件','source_files':'原始文件',
            'source_file_occurrences':'原始文件引用','recipes':'配方'}
    for candidate in metadata().tables.values():
        if candidate.name=='audit_log':continue
        predicates=[]
        for constraint in candidate.foreign_key_constraints:
            if constraint.referred_table is not target:continue
            predicates.extend(candidate.c[link.parent.name]==id for link in constraint.elements if link.column is pk)
        if 'entity_type' in candidate.c and 'entity_id' in candidate.c:
            predicates.append(and_(candidate.c.entity_type=={'batches':'batch','samples':'sample','experiment_plans':'experiment_plan','processes':'process','process_steps':'process_step'}.get(kind,kind),candidate.c.entity_id==id))
        if predicates:
            count,restricted=dependency_counts(db,candidate.name,select(candidate).where(or_(*predicates)),user)
            hidden=hidden or restricted
            if count:dependencies.append(f'{labels.get(candidate.name,candidate.name)} {count} 条')
    if hidden:dependencies.append(PROTECTED_DEPENDENCIES)
    if dependencies:fail(409,'不能删除：存在'+ '、'.join(dependencies)+'。请保留历史记录，可归档批次、计划或工艺；可先查看影响预览（GET /api/v1/lifecycle/{kind}/{id}/impact）。')

def delete_record(db,kind,id,user):
    row=fetch(db,kind,id,user,True)
    if kind=='samples' and row['voided_at'] is not None:fail(409,'作废样品必须保留，不能删除')
    from .lifecycle import delete_allowed_base
    if not delete_allowed_base(db,kind,id,row,user):
        protect_delete(db,kind,id,user)
        fail(409,'仅无依赖的未使用草稿可删除；请归档或作废')
    protect_delete(db,kind,id,user);t=table(kind)
    db.execute(t.delete().where(t.c[('batch' if kind == 'batches' else 'sample')+'_id']==id));audit(db,user['user_id'],'delete',('batch' if kind == 'batches' else 'sample'),id)
    return Response(status_code=204)

@router.delete('/batches/{id}')
def delete_batch(id:int,user=Depends(admin),db=Depends(get_db)):
    return delete_record(db,'batches',id,user)

@router.delete('/samples/{id}')
def delete_sample(id:int,user=Depends(admin),db=Depends(get_db)):
    return delete_record(db,'samples',id,user)
