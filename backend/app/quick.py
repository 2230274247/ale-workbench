"""Quick records extend existing process identity; all writes use request transactions."""
import copy
import hashlib
import json
from datetime import date, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, UploadFile, File, Body, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from pydantic import Field
from .db import table, get_db, metadata, MigrationRequired
from .common import envelope, fail, audit, dbnow
from .security import current_user, writer
from .experiments import fetch, visible
from .quick_models import Model, Run, calculated

router=APIRouter(prefix='/api/v1/quick',tags=['V2.2 Quick records'])

def qt(name):
    try:return table('quick_'+name)
    except KeyError:raise MigrationRequired('V2.2 migration '+('0015' if name=='sources' else '0014')+' required')

def owned(t,user):
    return t.c.owner_user_id==user['user_id']

def lock_owner(db,user):
    u=table('users')
    db.execute(select(u.c.user_id).where(u.c.user_id==user['user_id']).with_for_update()).one()

def raw(db,id,user,lock=False):
    process=fetch(db,'processes',id,user,lock=False)
    if lock:
        p=table('processes')
        process=dict(db.execute(select(p).where(p.c.process_id==id).with_for_update()).mappings().one())
        if process['voided_at'] is not None:fail(409,'记录已作废，不能编辑')
    t=qt('runs')
    row=db.execute(select(t).where(t.c.process_id==id)).mappings().first()
    if not row:fail(404)
    # Management visibility follows existing processes; mutation still requires ownership.
    if lock and row['owner_user_id']!=user['user_id']:fail(403)
    return dict(row),process

def material(db,mid,user):
    if mid is None:return None
    t=qt('materials')
    row=db.execute(select(t).where(t.c.material_id==str(mid),owned(t,user))).mappings().first()
    if not row:fail(422,'材料不存在或无权使用，请重新选择材料')
    return dict(row)

def present(db,row,process,user):
    body=copy.deepcopy(row['payload'])
    body.update(run_id=row['process_id'],process_code=process['process_code'],version=process['row_version'],sequence_id=row['sequence_id'],previous_run_id=row['previous_process_id'],archived=process.get('archived_at') is not None)
    mats=qt('materials')
    names={r['material_id']:r['canonical_name'] for r in db.execute(select(mats)).mappings() if r['owner_user_id']==row['owner_user_id']}
    body['material_name']=names.get(body.get('material_id'))
    runs=qt('runs');procs=table('processes')
    ancestors={r['process_id']:r for r in db.execute(select(runs).join(procs,runs.c.process_id==procs.c.process_id).where(runs.c.sequence_id==row['sequence_id'],procs.c.voided_at.is_(None))).mappings()}
    chain=[];cursor=row;seen=set()
    while cursor:
        if cursor['process_id'] in seen:fail(409,'连续序列循环，请核查')
        seen.add(cursor['process_id']);chain.append(cursor)
        cursor=ancestors.get(cursor['previous_process_id'])
    body['stage_no']=len(chain)
    warnings=[]
    for r in body['results']:
        r.update(calculated(r));r['material_name']=names.get(r.get('material_id') or body.get('material_id'))
        total=0;known=True;expected=str(r['result_id'])
        # Walk explicit result links; aliases and co-chamber positions never imply identity.
        for node in chain:
            match=next((v for v in node['payload']['results'] if str(v['result_id'])==expected),None)
            if not match or match['effective_cycles'] is None:known=False;break
            total+=match['effective_cycles'];expected=match.get('carried_from_result_id')
            if node['previous_process_id'] and not expected:known=False;break
        r['cumulative_cycles']=total if known else None
        if r['before_origin']=='carried_forward':
            prev=ancestors.get(row['previous_process_id'])
            source=next((v for v in prev['payload']['results'] if v['result_id']==r['carried_from_result_id']),None) if prev else None
            r['reference_needs_review']=not source or source['thickness_after_nm']!=r['thickness_before_nm']
        program=body['program'];g=program['groups']
        if len(g)==1 and program['outer_cycles'] is not None and g[0]['repeat_count'] is not None and r['effective_cycles'] is not None and program['outer_cycles']*g[0]['repeat_count']!=r['effective_cycles']:
            warnings.append('程序循环与本段有效循环不一致，请核实周期口径')
    body['warnings']=list(dict.fromkeys(warnings))
    return body

@router.get('/materials')
def materials(request:Request,q:str='',db=Depends(get_db),user=Depends(current_user)):
    t=qt('materials');query=select(t).where(owned(t,user))
    if q:query=query.where(t.c.canonical_name.contains(q,autoescape=True))
    return envelope(request,[dict(x) for x in db.execute(query.order_by(t.c.canonical_name)).mappings()])

class Material(Model):
    canonical_name:str=Field(min_length=1,max_length=128)
    aliases:list[str]=Field(default_factory=list,max_length=30)


class Source(Model):
    canonical_name:str=Field(min_length=1,max_length=128,pattern=r'^[^\x00-\x1f\x7f]+$')


@router.get('/sources')
def sources(request:Request,db=Depends(get_db),user=Depends(current_user)):
    t=qt('sources')
    return envelope(request,[dict(row) for row in db.execute(select(t).where(owned(t,user)).order_by(t.c.canonical_name)).mappings()])


@router.post('/sources',status_code=201)
def add_source(body:Source,request:Request,db=Depends(get_db),user=Depends(writer)):
    name=body.canonical_name.strip()
    if not name:fail(422,'源名称不能为空')
    lock_owner(db,user);t=qt('sources')
    old=db.execute(select(t).where(owned(t,user),t.c.canonical_name==name)).mappings().first()
    if old:return envelope(request,dict(old))
    value=dict(source_id=str(uuid4()),owner_user_id=user['user_id'],canonical_name=name)
    db.execute(t.insert().values(**value))
    return envelope(request,value)

@router.post('/materials',status_code=201)
def add_material(body:Material,request:Request,db=Depends(get_db),user=Depends(writer)):
    name=body.canonical_name.strip()
    if not name:fail(422,'材料名不能为空')
    t=qt('materials');lock_owner(db,user)
    old=db.execute(select(t).where(owned(t,user),t.c.canonical_name==name)).mappings().first()
    if old:return envelope(request,dict(old))
    data=dict(material_id=str(uuid4()),owner_user_id=user['user_id'],canonical_name=name,aliases=body.aliases)
    db.execute(t.insert().values(**data));return envelope(request,data)

@router.get('/next-number')
def next_number(request:Request,experiment_date:date,db=Depends(get_db),user=Depends(current_user)):
    t=qt('runs');number=db.scalar(select(func.max(t.c.daily_no)).where(owned(t,user),t.c.experiment_date==experiment_date))
    return envelope(request,{'daily_no':(number or 0)+1})

def selection(db,user,filters=None):
    filters=filters or {};t=qt('runs');p=table('processes')
    query=select(t,p.c.process_code,p.c.row_version,p.c.archived_at).join(p,t.c.process_id==p.c.process_id).where(visible('processes',user),p.c.voided_at.is_(None))
    query=query.where(p.c.archived_at.is_not(None) if filters.get('archived')=='yes' else p.c.archived_at.is_(None))
    try:
        lower=date.fromisoformat(filters['date_from']) if filters.get('date_from') else None
        upper=date.fromisoformat(filters['date_to']) if filters.get('date_to') else None
    except ValueError:fail(422,'日期筛选格式应为 YYYY-MM-DD')
    if lower and upper and lower>upper:fail(422,'开始日期不能晚于结束日期')
    if lower:query=query.where(t.c.experiment_date>=lower)
    if upper:query=query.where(t.c.experiment_date<=upper)
    data=[]
    for row in db.execute(query.order_by(t.c.experiment_date.desc(),t.c.daily_no.desc())).mappings():
        body=present(db,dict(row),row,user)
        if filters.get('equipment') and body['environment']['equipment']!=filters['equipment']:continue
        results=body['results']
        for key in ('data_nature','quality_status'):
            if filters.get(key):results=[r for r in results if r[key]==filters[key]]
        if filters.get('material_id'):results=[r for r in results if (r.get('material_id') or body.get('material_id'))==filters['material_id']]
        for field,flag in [('epc_a_per_cycle','has_epc'),('uniformity_pct','has_uniformity')]:
            if filters.get(flag) in ('yes','no'):results=[r for r in results if (r[field] is not None)==(filters[flag]=='yes')]
        if filters.get('excel') in ('yes','no'):results=[r for r in results if bool(r.get('source'))==(filters['excel']=='yes')]
        active=any(filters.get(k) for k in ('data_nature','quality_status','material_id','has_epc','has_uniformity','excel'))
        if active and not results:continue
        body['results']=results;data.append(body)
    return data

@router.get('/runs')
def runs(request:Request,page:int=Query(1,ge=1),db=Depends(get_db),user=Depends(current_user)):
    data=selection(db,user,dict(request.query_params))
    size=50
    return envelope(request,{'items':data[(page-1)*size:page*size],'total':len(data),'result_count':sum(len(r['results']) for r in data),'page':page})

@router.get('/runs/{id}')
def get_run(id:int,request:Request,db=Depends(get_db),user=Depends(current_user)):
    row,p=raw(db,id,user);return envelope(request,present(db,row,p,user))

def project_fields(db,id,body):
    """Mirror the authoritative payload into explicit columns for external SQL access.
    Skipped (not failed) when migration 0016 has not been applied on this database."""
    try:
        t=qt('runs');r=qt('results');s=qt('steps')
    except MigrationRequired:
        return
    if 'external_experiment_id' not in t.c or 'result_id' not in r.c or 'step_id' not in s.c:
        return
    env=body.environment
    utc=lambda d:d.astimezone(timezone.utc).replace(tzinfo=None) if d else None
    dec=lambda v:Decimal(str(v)) if v is not None else None
    db.execute(t.update().where(t.c.process_id==id).values(
        external_experiment_id=body.external_experiment_id,external_batch_id=body.external_batch_id,
        process_type=env.process_type,rf_icp_power_w=dec(env.rf_icp_power_w),bias_power_w=dec(env.bias_power_w),
        equipment=env.equipment,chamber_pressure_pa=dec(env.chamber_pressure_pa),
        r1_temp_c=dec(env.r1_temperature_c),r2_temp_c=dec(env.r2_temperature_c),n2_flow_sccm=dec(env.n2_flow_sccm),
        started_at=utc(body.started_at),ended_at=utc(body.ended_at),note=body.note))
    db.execute(r.delete().where(r.c.run_id==id))
    for i,res in enumerate(body.results):
        db.execute(r.insert().values(run_id=id,result_id=str(res.result_id),ordinal=i,alias=res.alias,
            material_id=str(res.material_id) if res.material_id else None,
            thickness_before_nm=dec(res.thickness_before_nm),thickness_after_nm=dec(res.thickness_after_nm),
            effective_cycles=res.effective_cycles,uniformity_pct=dec(res.uniformity_pct),
            uniformity_definition=res.uniformity_definition,reported_epc=dec(res.reported_epc),
            data_nature=res.data_nature,quality_status=res.quality_status,result_label=res.result_label,
            use_for_model_override=res.use_for_model_override,before_origin=res.before_origin,after_origin=res.after_origin))
    db.execute(s.delete().where(s.c.run_id==id))
    for gi,g in enumerate(body.program.groups):
        for si,st in enumerate(g.steps):
            db.execute(s.insert().values(run_id=id,step_id=str(st.step_id),group_id=str(g.group_id),
                group_code=g.code,repeat_count=g.repeat_count,ordinal=gi*1000+si,
                source_label=st.source_label or None,pulse_ms=dec(st.pulse_ms),purge_s=dec(st.purge_s),
                wait_s=dec(st.wait_s),delta_p_pa=dec(st.delta_p_pa),
                delta_p_pa_min=dec(st.delta_p_pa_min),delta_p_pa_max=dec(st.delta_p_pa_max),enabled=bool(st.enabled)))


def store(db,body,user,id=None,reason='manual'):
    lock_owner(db,user)
    existing=raw(db,id,user,lock=True) if id is not None else None
    data=body.model_dump(mode='json');data.pop('expected_version');key=data.pop('idempotency_key')
    def intent(value):
        if isinstance(value,dict):return {k:intent(v) for k,v in value.items() if k not in ('step_id','group_id','result_id')}
        if isinstance(value,list):return [intent(v) for v in value]
        return value
    fingerprint=hashlib.sha256(json.dumps(intent(data),sort_keys=True).encode()).hexdigest()
    t=qt('runs');p=table('processes')
    if id is None:
        old=db.execute(select(t).where(owned(t,user),t.c.request_key==key)).mappings().first()
        if old:
            if old['request_hash']!=fingerprint:fail(409,'同一保存请求的内容已改变，请重新读取已保存记录')
            return old['process_id']
    conflict=db.scalar(select(t.c.process_id).where(owned(t,user),t.c.experiment_date==body.experiment_date,t.c.daily_no==body.daily_no,t.c.process_id!=(id or 0)))
    if conflict:
        suggestion=(db.scalar(select(func.max(t.c.daily_no)).where(owned(t,user),t.c.experiment_date==body.experiment_date)) or 0)+1
        fail(409,f'当天序号已占用，请将“当日第几次”改为 {suggestion} 或其他未占用序号；当前输入已保留。')
    material(db,body.material_id,user)
    for result in body.results:material(db,result.material_id,user)
    previous=None
    if body.previous_run_id:
        previous,_=raw(db,body.previous_run_id,user,lock=True)
        if previous['owner_user_id']!=user['user_id']:fail(403)
        if id is not None and body.previous_run_id==id:fail(422,'连续记录不能引用自身')
        previous_results={r['result_id']:r for r in previous['payload']['results']}
        for result in body.results:
            if result.carried_from_result_id and str(result.carried_from_result_id) not in previous_results:fail(422,'前段结果关联无效')
    for result in body.results:
        if result.before_origin=='carried_forward' and (not previous or not result.carried_from_result_id):fail(422,'承接参考值必须有明确前段来源')
        if result.source is not None and reason!='excel':
            if id is None:fail(422,'文件来源只能由确认导入生成')
    utc=lambda d:d.astimezone(timezone.utc).replace(tzinfo=None) if d else None
    values=dict(r1_temp_c=body.environment.r1_temperature_c,r2_temp_c=body.environment.r2_temperature_c,n2_flow_sccm=body.environment.n2_flow_sccm,started_at=utc(body.started_at),ended_at=utc(body.ended_at),notes=body.note)
    if id is None:
        id=db.execute(p.insert().values(process_code='Q-'+uuid4().hex[:20],process_mode='other',operator_user_id=user['user_id'],log_status='partial' if body.state=='draft' else 'ok',**values)).inserted_primary_key[0]
        version=1
        db.execute(t.insert().values(process_id=id,owner_user_id=user['user_id'],experiment_date=body.experiment_date,daily_no=body.daily_no,sequence_id=previous['sequence_id'] if previous else str(uuid4()),previous_process_id=body.previous_run_id,payload=data,request_key=key,request_hash=fingerprint))
    else:
        old,process=existing
        if body.expected_version!=process['row_version']:fail(409,'VERSION_CONFLICT：记录已在其他页面修改；请先下载当前输入或重新加载记录')
        if body.previous_run_id!=old['previous_process_id']:fail(422,'已保存记录不能更改连续链')
        if reason!='excel':
            old_results={r['result_id']:r for r in old['payload']['results']}
            for r in data['results']:
                if r['source']!=old_results.get(r['result_id'],{}).get('source'):fail(422,'不得修改文件来源')
                source_field=r['source'].get('field') if r['source'] else None
                if source_field and r.get(source_field)!=old_results.get(r['result_id'],{}).get(source_field):
                    r['source']=None;r['after_origin']='manual'
        version=process['row_version']+1
        db.execute(p.update().where(p.c.process_id==id).values(row_version=version,log_status='partial' if body.state=='draft' else 'ok',**values))
        db.execute(t.update().where(t.c.process_id==id).values(experiment_date=body.experiment_date,daily_no=body.daily_no,payload=data))
    db.execute(qt('revisions').insert().values(process_id=id,actor_user_id=user['user_id'],version=version,snapshot=data,reason=reason))
    project_fields(db,id,body)
    audit(db,user['user_id'],'insert' if version==1 else 'update','process',id)
    return id

@router.post('/runs',status_code=201)
def create_run(body:Run,request:Request,db=Depends(get_db),user=Depends(writer)):
    id=store(db,body,user);row,p=raw(db,id,user);return envelope(request,present(db,row,p,user))

@router.put('/runs/{id}')
def update_run(id:int,body:Run,request:Request,db=Depends(get_db),user=Depends(writer)):
    store(db,body,user,id);row,p=raw(db,id,user);return envelope(request,present(db,row,p,user))

class Batch(Model):
    run_ids: list[int]=Field(min_length=1,max_length=200)

def set_archived(db,id,user,archived):
    """Archive (soft-delete) or restore a quick run via its backing process row.

    Archiving keeps every row, revision and original untouched; it only sets the
    process archived_at flag so the run leaves the default dataset list and its
    external experiment ID can be reused by a re-import.
    """
    row,process=raw(db,id,user,lock=True)
    if (process['archived_at'] is not None)==archived:
        return
    p=table('processes')
    changed=db.execute(p.update().where(p.c.process_id==id,p.c.row_version==process['row_version'])
                       .values(archived_at=dbnow() if archived else None,row_version=process['row_version']+1))
    if changed.rowcount!=1:fail(409,'记录已变更，请刷新后重试')
    audit(db,user['user_id'],'update','process',id)

def delete_run(db,id,user):
    """Hard-delete a quick run and its backing process row, never cascading history.

    A run that begins a continuous sequence (another run points at it as
    previous_process_id) cannot be removed without first removing the later runs;
    archive is the reversible alternative. The whole request rolls back on any
    conflict, so a batch delete is atomic.
    """
    row,process=raw(db,id,user,lock=True)
    t=qt('runs')
    if db.scalar(select(t.c.process_id).where(t.c.previous_process_id==id).limit(1)):
        fail(409,'此记录是连续工艺的起始段，已有后续记录承接，不能删除；请先删除后续记录，或改用归档。')
    m=metadata().tables
    for name in ('quick_results','quick_steps'):
        child=m.get(name)
        if child is not None and 'run_id' in child.c:
            db.execute(child.delete().where(child.c.run_id==id))
    for name in ('quick_revisions','quick_imports'):
        child=m.get(name)
        if child is not None and 'process_id' in child.c:
            db.execute(child.delete().where(child.c.process_id==id))
    db.execute(t.delete().where(t.c.process_id==id))
    try:
        db.execute(table('processes').delete().where(table('processes').c.process_id==id))
    except IntegrityError:
        fail(409,'此记录仍被其他专业记录引用，不能删除；请改用归档保留历史。')
    audit(db,user['user_id'],'delete','process',id)
    return id

@router.post('/runs/{id}/archive')
def archive_run(id:int,request:Request,db=Depends(get_db),user=Depends(writer)):
    set_archived(db,id,user,True)
    return envelope(request,{'run_id':id,'archived':True})

@router.post('/runs/{id}/restore')
def restore_run(id:int,request:Request,db=Depends(get_db),user=Depends(writer)):
    set_archived(db,id,user,False)
    return envelope(request,{'run_id':id,'archived':False})

@router.delete('/runs/{id}')
def delete_run_endpoint(id:int,request:Request,db=Depends(get_db),user=Depends(writer)):
    delete_run(db,id,user)
    return envelope(request,{'run_id':id,'deleted':True})

@router.post('/runs/batch-archive')
def batch_archive(body:Batch,request:Request,db=Depends(get_db),user=Depends(writer)):
    for i in body.run_ids:set_archived(db,i,user,True)
    return envelope(request,{'run_ids':body.run_ids,'count':len(body.run_ids)})

@router.post('/runs/batch-delete')
def batch_delete(body:Batch,request:Request,db=Depends(get_db),user=Depends(writer)):
    ids=[delete_run(db,i,user) for i in body.run_ids]
    return envelope(request,{'run_ids':ids,'count':len(ids)})

@router.get('/runs/{id}/revisions')
def revisions(id:int,request:Request,db=Depends(get_db),user=Depends(current_user)):
    raw(db,id,user);t=qt('revisions')
    return envelope(request,[dict(r) for r in db.execute(select(t).where(t.c.process_id==id).order_by(t.c.version.desc())).mappings()])

class Template(Model):
    name:str=Field(min_length=1,max_length=128)
    run_id:int

@router.get('/templates')
def templates(request:Request,db=Depends(get_db),user=Depends(current_user)):
    t=qt('templates');return envelope(request,[dict(r) for r in db.execute(select(t).where(owned(t,user)).order_by(t.c.created_at.desc())).mappings()])

@router.post('/templates',status_code=201)
def add_template(body:Template,request:Request,db=Depends(get_db),user=Depends(writer)):
    if not body.name.strip():fail(422,'模板名称不能为空')
    row,_=raw(db,body.run_id,user,lock=True);snap=row['payload']
    data={'program':snap['program'],'environment':snap['environment'],'material_id':snap['material_id']}
    tid=str(uuid4());db.execute(qt('templates').insert().values(template_id=tid,owner_user_id=user['user_id'],name=body.name.strip(),snapshot=data))
    return envelope(request,{'template_id':tid})

@router.post('/runs/{id}/preview')
async def preview(id:int,request:Request,file:UploadFile=File(...),db=Depends(get_db),user=Depends(writer)):
    raw(db,id,user,lock=True)
    from .parsers.core import parse_file,MAX_BYTES
    content=await file.read(MAX_BYTES+1)
    if len(content)>MAX_BYTES:fail(422,'文件超过 25 MiB 上限')
    parsed=parse_file(content,file.filename or 'unknown')
    if parsed.get('status')!='parsed' or not parsed.get('blocks'):
        fail(422,'IMPORT_UNSUPPORTED_FORMAT：尚未支持此文件格式或文件有阻断问题。请上传有效 Eoptics 量测工作簿；竞赛参数表不是量测原件')
    token=str(uuid4());sha=hashlib.sha256(content).hexdigest()
    from .original_storage import originals_root
    root=originals_root()/ 'quick' / str(user['user_id']);root.mkdir(parents=True,exist_ok=True)
    path=root/(sha+'.xlsx')
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:fail(409,'原件校验不一致')
    else:
        with path.open('xb') as target:target.write(content)
    data={'parser':parsed['parser'],'parser_version':parsed['parser_version'] if 'parser_version' in parsed else parsed.get('version'),'blocks':parsed['blocks'],'warnings':parsed['warnings'],'units':'nm','sha256':sha}
    db.execute(qt('imports').insert().values(token=token,owner_user_id=user['user_id'],process_id=id,sha256=sha,filename=Path(file.filename or 'unknown').name[:255],preview=data))
    return envelope(request,{'token':token,'filename':file.filename,**data})

class Mapping(Model):
    block_index:int=Field(ge=0)
    result_id:str
    field: str=Field(pattern='^thickness_(before|after)_nm$')

class Confirmation(Model):
    expected_version:int
    mappings:list[Mapping]=Field(min_length=1,max_length=100)
    confirm_conflicts:bool=False

@router.post('/imports/{token}/confirm')
def confirm(token:str,body:Confirmation,request:Request,db=Depends(get_db),user=Depends(writer)):
    lock_owner(db,user);t=qt('imports')
    item=db.execute(select(t).where(t.c.token==token,owned(t,user)).with_for_update()).mappings().first()
    if not item:fail(404)
    mapping=sorted((m.model_dump() for m in body.mappings),key=lambda m:(m['result_id'],m['field'],m['block_index']))
    signature={'sha256':item['sha256'],'mappings':mapping}
    other=db.execute(select(t).where(t.c.process_id==item['process_id'],owned(t,user),t.c.sha256==item['sha256'],t.c.confirmation.is_not(None))).mappings().all()
    if any(r['confirmation']==signature for r in other):return envelope(request,{'run_id':item['process_id'],'duplicate':True})
    row,p=raw(db,item['process_id'],user,lock=True);data=copy.deepcopy(row['payload'])
    results={r['result_id']:r for r in data['results']};seen=set()
    for m in body.mappings:
        if (m.result_id,m.field) in seen:fail(422,'同一结果字段不能重复映射')
        seen.add((m.result_id,m.field))
        if m.block_index>=len(item['preview']['blocks']) or m.result_id not in results:fail(422,'映射目标无效')
        block=item['preview']['blocks'][m.block_index]
        mean=block['statistics'].get('thickness_nm',{}).get('mean')
        if mean is None or block.get('blocking_issues'):fail(422,'量测块没有可信膜厚均值')
        r=results[m.result_id];old=r[m.field]
        if old is not None and Decimal(str(old))!=Decimal(str(mean)) and not body.confirm_conflicts:fail(409,'IMPORT_CONFLICT：手记与 Excel 不同，请核对并确认覆盖，旧值将保留在修订历史')
        r[m.field]=str(mean);r['before_origin' if m.field=='thickness_before_nm' else 'after_origin']='measured' if m.field=='thickness_before_nm' else 'excel'
        r['source']={'sha256':item['sha256'],'filename':item['filename'],'token':token,'parser':item['preview']['parser'],'block_index':m.block_index,'field':m.field,'measurement_metadata':block.get('metadata'),'units':'nm'}
    data.update(idempotency_key=str(uuid4()),expected_version=body.expected_version)
    store(db,Run.model_validate(data),user,item['process_id'],reason='excel')
    db.execute(t.update().where(t.c.token==token).values(confirmation=signature))
    return envelope(request,{'run_id':item['process_id'],'duplicate':False})

@router.get('/imports/{token}/original')
def original(token:str,db=Depends(get_db),user=Depends(current_user)):
    t=qt('imports');row=db.execute(select(t).where(t.c.token==token,owned(t,user))).mappings().first()
    if not row:fail(404)
    raw(db,row['process_id'],user)
    from .original_storage import originals_root
    path=originals_root()/'quick'/str(user['user_id'])/(row['sha256']+'.xlsx')
    if not path.is_file():fail(404,'原件不可用，请联系管理员核查存储')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:fail(409,'原件校验失败，已禁止下载')
    return FileResponse(path,filename=row['filename'],media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
