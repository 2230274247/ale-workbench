"""Home dashboard aggregates.

All values are read from existing records and restricted with the same
visibility helpers the list endpoints use (records.scope, experiments.visible,
measurement_scope, source_scope). Nothing is inferred or fabricated: a count is
zero when the caller cannot see a record, and unknown stays absent.
"""
from fastapi import APIRouter,Depends,Request,Query
from sqlalchemy import select,func,or_,and_,false
from .db import table,metadata,get_db
from .security import current_user
from .records import scope
from .experiments import visible as experiment_visible
from .measurement_management import measurement_scope,source_scope,source_columns,dataset_scope
from .common import envelope,now

router=APIRouter(prefix='/api/v1/dashboard',tags=['Dashboard'])

PLAN_STATUS_LABELS={'draft':'草稿','approved':'已批准','running':'进行中','completed':'已完成','abandoned':'已放弃','archived':'已归档'}
LOG_STATUS_LABELS={'ok':'完整','partial':'部分','aborted':'中止','unknown':'未知'}
QUALITY_LABELS={'ok':'正常','suspect':'疑似异常','abnormal':'异常','excluded':'已排除'}


def _count(db,query):
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def _pending_import_counts():
    """Jobs stay personal even for admins (see imports.job_row)."""
    it=table('import_items')
    return (select(it.c.job_id,func.count().label('pending_count'))
            .where(it.c.status=='pending').group_by(it.c.job_id).subquery())


@router.get('/summary')
def summary(request:Request,user=Depends(current_user),db=Depends(get_db)):
    b=table('batches');s=table('samples');m=metadata().tables
    count=lambda q:db.scalar(select(func.count()).select_from(q.subquery()))
    scoped_samples=select(s.c.sample_id).where(scope('samples',user))
    scoped_batches=select(b.c.batch_id).where(scope('batches',user))
    result={'batch_count':count(scoped_batches),'sample_count':count(scoped_samples),
            'sample_excluded_count':count(scoped_samples.where(s.c.exclude_from_analysis==1)),
            'anomaly_batch_count':count(scoped_batches.where(b.c.anomaly_flag==1)),
            'generated_at':now()}
    for name,key in [('measurements','measurement_count'),('processes','process_count'),('findings','finding_count'),('issues','open_issue_count'),('experiment_plans','plan_count'),('derived_results','derived_result_count'),('source_files','source_file_count'),('instrument_datasets','instrument_dataset_count')]:
        t=m.get(name)
        if t is None:result[key]=0;continue
        q=select(t)
        if name=='experiment_plans':q=q.where(experiment_visible('plans',user))
        elif name=='processes':q=q.where(experiment_visible('processes',user))
        elif name=='measurements':q=q.where(measurement_scope(user))
        elif name=='source_files':q=q.where(source_scope(user))
        elif name=='instrument_datasets':q=q.where(dataset_scope(user))
        elif name=='issues' and user['role']!='admin':q=q.where(false())
        elif user['role']!='admin':
            if 'sample_id' in t.c:q=q.where(t.c.sample_id.in_(scoped_samples))
            elif 'batch_id' in t.c:q=q.where(t.c.batch_id.in_(scoped_batches))
            elif name=='processes' and 'process_samples' in m:
                links=m['process_samples'];q=q.where(t.c.process_id.in_(select(links.c.process_id).where(links.c.sample_id.in_(scoped_samples))))
            else:q=q.where(false()) # No established visibility link: disclose no counts.
        if name=='issues':q=q.where(t.c.status.in_(['open','investigating','deferred']))
        if name=='measurements' and 'is_current' in t.c:q=q.where(t.c.is_current==1)
        result[key]=count(q)
        if name=='issues':result['open_issue_high_count']=count(q.where(t.c.severity.in_(['high','medium_high'])))
        if name=='findings':result['finding_hypothesis_count']=count(q.where(t.c.evidence_level=='hypothesis'))
    result.setdefault('open_issue_high_count',0)
    result.setdefault('finding_hypothesis_count',0)
    result.setdefault('instrument_dataset_count',0)
    return envelope(request,result)

@router.get('/recent')
def recent(request:Request,limit:int=Query(8,ge=1,le=50),user=Depends(current_user),db=Depends(get_db)):
    a=table('audit_log');b=table('batches');s=table('samples')
    visible=or_(and_(a.c.entity_type=='batch',a.c.entity_id.in_(select(b.c.batch_id).where(scope('batches',user)))),and_(a.c.entity_type=='sample',a.c.entity_id.in_(select(s.c.sample_id).where(scope('samples',user)))))
    if user['role']=='admin':visible=or_(visible,a.c.entity_type=='user')
    rows=db.execute(select(a.c.entity_type,a.c.entity_id,a.c.action,a.c.occurred_at).where(visible).order_by(a.c.occurred_at.desc(),a.c.audit_id.desc()).limit(limit)).mappings()
    return envelope(request,[{**dict(row),'description':f"{row['entity_type']} #{row['entity_id']} · {row['action']}"} for row in rows])


@router.get('/todo')
def todo(request:Request,limit:int=Query(20,ge=1,le=20),user=Depends(current_user),db=Depends(get_db)):
    """Pending work derived only from stored states. Every count is permission scoped."""
    p=table('experiment_plans');r=table('processes');j=table('import_jobs');it=table('import_items');ms=table('measurements')
    items=[];counts={}
    # Draft/approved plans that have no execution at all.
    no_run=~select(r.c.process_id).where(r.c.plan_id==p.c.plan_id).exists()
    plan_q=select(p).where(experiment_visible('plans',user),p.c.status.in_(['draft','approved']),no_run)
    counts['plan_without_process']=_count(db,plan_q)
    for row in db.execute(plan_q.order_by(p.c.updated_at.desc(),p.c.plan_id.desc()).limit(limit)).mappings():
        items.append({'kind':'plan_without_process','entity_id':row['plan_id'],'code':row['plan_code'],
            'title':row['title'] or row['plan_code'],
            'detail':f"计划状态：{PLAN_STATUS_LABELS.get(row['status'],row['status'])}；尚无实验执行",
            'status':row['status'],'updated_at':row['updated_at'],'path':'/plans','query':{'plan_id':row['plan_id']}})
    # Executions whose log status is not a completed record.
    proc_q=select(r).where(experiment_visible('processes',user),r.c.log_status.in_(['unknown','partial']),r.c.archived_at.is_(None))
    counts['process_log']=_count(db,proc_q)
    for row in db.execute(proc_q.order_by(r.c.updated_at.desc(),r.c.process_id.desc()).limit(limit)).mappings():
        items.append({'kind':'process_log','entity_id':row['process_id'],'code':row['process_code'],
            'title':row['process_code'],
            'detail':f"日志状态：{LOG_STATUS_LABELS.get(row['log_status'],row['log_status'])}；请补齐实际记录",
            'status':row['log_status'],'updated_at':row['updated_at'],'path':'/processes','query':{'process_id':row['process_id']}})
    # Import jobs are personal, including for admins: only the owner's drafts appear.
    pending=_pending_import_counts()
    job_q=(select(j.c.job_id,j.c.status,j.c.created_at,pending.c.pending_count)
           .join(pending,pending.c.job_id==j.c.job_id)
           .where(j.c.owner_user_id==user['user_id'],j.c.status=='draft'))
    counts['import_pending']=_count(db,job_q)
    for row in db.execute(job_q.order_by(j.c.created_at.desc(),j.c.job_id.desc()).limit(limit)).mappings():
        items.append({'kind':'import_pending','entity_id':row['job_id'],'code':None,
            'title':f"导入任务 #{row['job_id']}",
            'detail':f"{int(row['pending_count'])} 个文件待确认",
            'status':'draft','updated_at':row['created_at'],'path':'/imports','query':{'job':row['job_id']}})
    # A stored parser rejection is the only persisted failure state for an item.
    parse_status=func.json_unquote(func.json_extract(it.c.parse_result,'$.status'))
    fail_q=(select(it.c.item_id,it.c.job_id,it.c.filename,it.c.created_at)
            .join(j,j.c.job_id==it.c.job_id)
            .where(j.c.owner_user_id==user['user_id'],it.c.status=='pending',parse_status=='rejected'))
    counts['import_failure']=_count(db,fail_q)
    for row in db.execute(fail_q.order_by(it.c.created_at.desc(),it.c.item_id.desc()).limit(limit)).mappings():
        items.append({'kind':'import_failure','entity_id':row['item_id'],'code':None,
            'title':row['filename'],'detail':'文件解析失败，请重新上传或仅保留原件',
            'status':'failed','updated_at':row['created_at'],'path':'/imports','query':{'job':row['job_id']}})
    # Current measurements explicitly flagged for review. 'excluded' is a decision, not a review flag.
    review_q=select(ms).where(measurement_scope(user),ms.c.is_current==1,ms.c.quality_flag.in_(['suspect','abnormal']))
    counts['measurement_review']=_count(db,review_q)
    for row in db.execute(review_q.order_by(ms.c.updated_at.desc(),ms.c.measurement_id.desc()).limit(limit)).mappings():
        items.append({'kind':'measurement_review','entity_id':row['measurement_id'],'code':row['measurement_code'],
            'title':row['measurement_code'],
            'detail':f"质量标记：{QUALITY_LABELS.get(row['quality_flag'],row['quality_flag'])}；样品 #{row['sample_id']}",
            'status':row['quality_flag'],'updated_at':row['updated_at'],'path':'/measurements','query':{'id':row['measurement_id']}})
    # Issue ledger has no established non-admin visibility link; mirror /summary and expose none.
    if user['role']=='admin':
        issue=table('issues')
        issue_q=select(issue).where(issue.c.status.in_(['open','investigating','deferred']))
        counts['issue']=_count(db,issue_q)
        for row in db.execute(issue_q.order_by(issue.c.updated_at.desc(),issue.c.issue_id.desc()).limit(limit)).mappings():
            items.append({'kind':'issue','entity_id':row['issue_id'],'code':row['issue_code'],
                'title':row['title'],'detail':f"问题状态：{row['status']}；严重度：{row['severity']}",
                'status':row['status'],'severity':row['severity'],'updated_at':row['updated_at'],'path':None,'query':None})
    else:
        counts['issue']=0
    items.sort(key=lambda item:(item['updated_at'] is not None,item['updated_at'] or 0),reverse=True)
    return envelope(request,{'generated_at':now(),'total':sum(counts.values()),'counts':counts,'items':items[:limit]})


@router.get('/recent-experiments')
def recent_experiments(request:Request,limit:int=Query(10,ge=1,le=20),user=Depends(current_user),db=Depends(get_db)):
    """Recent plans and executions by updated_at, each with a next action."""
    p=table('experiment_plans');r=table('processes')
    can_write=user['role'] in ('admin','operator')
    rows=[]
    for row in db.execute(select(p).where(experiment_visible('plans',user)).order_by(p.c.updated_at.desc(),p.c.plan_id.desc()).limit(limit)).mappings():
        start=row['status'] in ('draft','approved')
        item={'kind':'plan','entity_id':row['plan_id'],'code':row['plan_code'],'title':row['title'] or row['plan_code'],
              'status':row['status'],'batch_id':row['batch_id'],'updated_at':row['updated_at'],
              'path':'/plans','query':{'plan_id':row['plan_id']}}
        if start:
            item.update(continue_path='/processes',continue_query={'create':'1','plan_id':row['plan_id'],**({'batch_id':row['batch_id']} if row['batch_id'] else {})},
                        continue_label='发起执行',can_continue=can_write)
        else:
            item.update(continue_path='/plans',continue_query={'plan_id':row['plan_id']},continue_label='查看计划',can_continue=True)
        rows.append(item)
    for row in db.execute(select(r).where(experiment_visible('processes',user)).order_by(r.c.updated_at.desc(),r.c.process_id.desc()).limit(limit)).mappings():
        rows.append({'kind':'process','entity_id':row['process_id'],'code':row['process_code'],'title':row['process_code'],
            'status':row['log_status'],'batch_id':row['batch_id'],'plan_id':row['plan_id'],'updated_at':row['updated_at'],
            'archived':row['archived_at'] is not None,'path':'/processes','query':{'process_id':row['process_id']},
            'continue_path':'/processes','continue_query':{'process_id':row['process_id']},
            'continue_label':'查看执行' if row['archived_at'] is not None or row['log_status'] in ('ok','aborted') or not can_write else '继续执行','can_continue':True})
    rows.sort(key=lambda item:(item['updated_at'] is not None,item['updated_at'] or 0),reverse=True)
    return envelope(request,{'generated_at':now(),'items':rows[:limit]})


@router.get('/recent-data')
def recent_data(request:Request,limit:int=Query(10,ge=1,le=20),user=Depends(current_user),db=Depends(get_db)):
    """Recent import jobs, measurements and source files with the real quality hint each one stores."""
    j=table('import_jobs');ms=table('measurements');f=table('source_files')
    rows=[]
    pending=_pending_import_counts()
    job_q=(select(j.c.job_id,j.c.status,j.c.created_at,pending.c.pending_count)
           .outerjoin(pending,pending.c.job_id==j.c.job_id)
           .where(j.c.owner_user_id==user['user_id']))
    for row in db.execute(job_q.order_by(j.c.created_at.desc(),j.c.job_id.desc()).limit(limit)).mappings():
        count=int(row['pending_count'] or 0)
        rows.append({'kind':'import_job','entity_id':row['job_id'],'code':None,'title':f"导入任务 #{row['job_id']}",
            'status':row['status'],'hint':f'{count} 个文件待确认' if count else None,
            'occurred_at':row['created_at'],'path':'/imports','query':{'job':row['job_id']}})
    measurement_q=select(ms.c.measurement_id,ms.c.measurement_code,ms.c.sample_id,ms.c.stage,ms.c.quality_flag,ms.c.is_current,ms.c.updated_at).where(measurement_scope(user))
    for row in db.execute(measurement_q.order_by(ms.c.updated_at.desc(),ms.c.measurement_id.desc()).limit(limit)).mappings():
        hint=None
        if row['quality_flag']!='ok':hint=f"质量标记：{QUALITY_LABELS.get(row['quality_flag'],row['quality_flag'])}"
        elif not row['is_current']:hint='已被取代，仅保留历史'
        rows.append({'kind':'measurement','entity_id':row['measurement_id'],'code':row['measurement_code'],
            'title':row['measurement_code'],'status':row['quality_flag'],'stage':row['stage'],
            'sample_id':row['sample_id'],'hint':hint,'occurred_at':row['updated_at'],
            'path':'/measurements','query':{'id':row['measurement_id']}})
    # source_columns() never exposes another uploader's name; parse_status is
    # selected separately because it is a property of the shared original.
    source_q=select(*source_columns(user),f.c.parse_status).where(source_scope(user))
    for row in db.execute(source_q.order_by(f.c.created_at.desc(),f.c.file_id.desc()).limit(limit)).mappings():
        hint={'failed':'解析失败，原件已保留','pending':'解析待处理'}.get(row['parse_status'])
        rows.append({'kind':'source_file','entity_id':row['file_id'],'code':row['file_name'],
            'title':row['file_name'],'status':row['parse_status'],'size_bytes':row['size_bytes'],
            'hint':hint,'occurred_at':row['created_at'],'path':'/source-files','query':{'id':row['file_id']}})
    rows.sort(key=lambda item:(item['occurred_at'] is not None,item['occurred_at'] or 0),reverse=True)
    return envelope(request,{'generated_at':now(),'items':rows[:limit]})
