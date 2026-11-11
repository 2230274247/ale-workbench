"""Shared instrument upload preview and explicit atomic confirmation.

Unselected items remain pending. A request replay includes expected_row_version;
identical normalized bodies return the saved result even after a version increment.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from sqlalchemy import select, and_, or_, func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from .db import table, get_db
from .common import envelope, fail, page_result, audit
from .security import current_user, writer
from .records import scope, fetch as sample_fetch, require_active_sample
from . import experiments as E
from .import_worker import parse_preview
from .measurement_management import measurement_scope
from .data_visibility import model_scope, optical_model, project, project_import_item
from .original_storage import store_original, read_verified, lock_original, originals_root

router = APIRouter(prefix='/api/v1/imports', tags=['Imports'])
STAGES = Literal['initial','after_o2_plasma','after_o3_pre','after_ale','after_hf_only','after_o3_only','intermediate','final','other']

class Choice(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    item_id: int = Field(gt=0)
    action: Literal['import','original_only','skip']
    sample_id: int | None = Field(None, gt=0)
    process_id: int | None = Field(None, gt=0)
    stage: STAGES | None = None
    stage_seq: int | None = Field(None, ge=0, le=4294967295)
    measurement_code: str | None = Field(None, min_length=1, max_length=80)
    optical_model_id: int | None = Field(None, gt=0)
    confirm_units: bool = False
    confirm_associations: bool = False
    confirm_duplicate: bool = False
    duplicate_reason: str | None = Field(None, min_length=1, max_length=4000)
    pair_measurement_id: int | None = Field(None, gt=0)
    pair_item_id: int | None = Field(None, gt=0)
    measured_at: datetime | None = None
    notes: str | None = Field(None, max_length=10000)

    @field_validator('measured_at')
    @classmethod
    def measurement_time(cls,value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value

class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_row_version: int = Field(gt=0)
    items: list[Choice] = Field(min_length=1, max_length=20)
    @model_validator(mode='after')
    def unique_items(self):
        if len({i.item_id for i in self.items}) != len(self.items):
            raise ValueError('Duplicate item_id')
        return self

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def choice_dump(choice):
    value=choice.model_dump(mode='json')
    # Preserve pre-upgrade confirmation fingerprints for the existing API.
    if value.get('pair_item_id') is None:value.pop('pair_item_id',None)
    if value.get('measured_at') is None:value.pop('measured_at',None)
    return value

def job_row(db, job_id, user, lock=False):
    t=table('import_jobs')
    # Jobs remain personal even for admins; scientific records use sample scope.
    q=select(t).where(t.c.job_id==job_id,t.c.owner_user_id==user['user_id'])
    row=db.execute(q.with_for_update() if lock else q).mappings().first()
    if row is None: fail(404)
    return dict(row)

def suggestions(db, filename, user):
    s=table('samples'); b=table('batches'); p=table('processes'); links=table('process_samples')
    # Upload hints remain personal, including for admins; model visibility is independent.
    rows=db.execute(select(s.c.sample_id,s.c.sample_code,s.c.display_label,s.c.batch_id,b.c.batch_code)
        .join(b,b.c.batch_id==s.c.batch_id).where(
            s.c.owner_user_id==user['user_id'],b.c.owner_user_id==user['user_id'])).mappings()
    first=re.search(r'\d+',filename)
    candidates=[]
    for r in rows:
        def token(value):
            return bool(value and re.search(r'(?<![\w])'+re.escape(value)+r'(?![\w\d])',filename,re.I))
        exact=token(r['sample_code']) or token(r['display_label'])
        # A numbered file may describe a coupon suffix, never the batch's first number.
        suffix=re.search(r'(?:^|[-_])(\d+)$',r['sample_code'])
        numeric=bool(first and suffix and int(suffix[1])==int(first[0]))
        if exact or numeric:
            candidate=dict(r);candidate['batch_hint_match']=r['batch_code'].lower() in filename.lower()
            candidate['evidence']='exact_code_or_label' if exact else 'filename_number_matches_coupon_suffix'
            candidate['processes']=[dict(x) for x in db.execute(select(p.c.process_id,p.c.process_code).where(p.c.process_id.in_(select(links.c.process_id).where(links.c.sample_id==r['sample_id'])),E.visible('processes',user))).mappings()]
            m=table('measurements')
            candidate['baseline_measurements']=[project(db,x,user,'measurement') for x in db.execute(select(m.c.measurement_id,m.c.measurement_code,m.c.stage,m.c.stage_seq,m.c.optical_model_id).where(m.c.sample_id==r['sample_id'],m.c.is_current==True).order_by(m.c.measurement_id)).mappings()]
            candidates.append(candidate)
    return {'requires_manual_selection':True,'samples':candidates,'association_is_fact':False,
            'warnings':['Candidates are suggestions only; explicitly select sample, process and stage.'],
            'optical_models':[dict(r) for r in db.execute(select(table('optical_models')).where(model_scope(user))).mappings()]}

def details(db,job_id,user,include_suggestions=True):
    row=job_row(db,job_id,user);t=table('import_items')
    row['items']=[]
    for item in db.execute(select(t).where(t.c.job_id==job_id).order_by(t.c.item_id)).mappings():
        item=project_import_item(db,item,user);item.pop('storage_key',None)
        if include_suggestions:item['suggestions']=suggestions(db,item['filename'],user)
        row['items'].append(item)
    return row

def safe_filename(name):
    if not name or len(name)>255 or name in ('.','..') or '/' in name or '\\' in name or ':' in name or any(ord(c)<32 for c in name) or PureWindowsPath(name).is_absolute():
        fail(422,'Upload filename must be a plain filename')
    return name

@router.post('/preview',status_code=201,openapi_extra={'requestBody':{'required':True,'content':{'multipart/form-data':{'schema':{'type':'object','required':['files[]'],'additionalProperties':False,'properties':{'files[]':{'type':'array','minItems':1,'maxItems':20,'items':{'type':'string','format':'binary'}}}}}}}})
async def preview(request:Request,user=Depends(writer),db=Depends(get_db)):
    """Multipart files[]: 1–20 files, <=20 MiB each, <=100 MiB total. No scientific records are written."""
    staged=[];total=0
    # Enforce the total request bound while multipart is being parsed/spooled.
    # Allow bounded MIME headers in addition to the 100 MiB payload allowance.
    original_receive=request._receive
    received=0
    async def bounded_receive():
        nonlocal received
        message=await original_receive()
        received+=len(message.get('body',b''))
        if received>100*1024*1024+256*1024:fail(413,'Upload size limit exceeded')
        return message
    request._receive=bounded_receive
    # A bounded form parser prevents unbounded field/file spooling. Read limits
    # are enforced independently of user-provided Content-Length.
    async with request.form(max_files=20,max_fields=0,max_part_size=20*1024*1024) as form:
        entries=list(form.multi_items())
        if not 1<=len(entries)<=20:fail(422,'Upload requires 1–20 files[]')
        for field,upload in entries:
            if field!='files[]' or not hasattr(upload,'read'):fail(422,'Expected multipart files[]')
            name=safe_filename(upload.filename)
            chunks=[];length=0
            while chunk:=await upload.read(1024*1024):
                length+=len(chunk);total+=len(chunk)
                if length>20*1024*1024 or total>100*1024*1024:fail(413,'Upload size limit exceeded')
                chunks.append(chunk)
            content=b''.join(chunks)
            # Reject lock files before a worker can fail/timeout and mask rejection.
            if name.startswith('~$'):fail(422,'Temporary lock files cannot be uploaded')
            parsed=await parse_preview(content,name)
            if parsed['status']=='rejected':fail(422,'Temporary lock files cannot be uploaded')
            staged.append((name,content,parsed))
    # Storage creation and deletion share transaction-lifetime SHA locks.
    for sha in sorted({hashlib.sha256(content).hexdigest() for _,content,_ in staged}):
        if not lock_original(db,sha):fail(409,'原件正在被其他任务处理，请稍后重试上传。')
    job_id=db.execute(table('import_jobs').insert().values(owner_user_id=user['user_id'])).inserted_primary_key[0]
    for name,content,parsed in staged:
        sha,key=store_original(content)
        # No global duplicate metadata is returned. Same-name warnings are personal.
        i=table('import_items');j=table('import_jobs')
        if db.execute(select(i.c.item_id).join(j,j.c.job_id==i.c.job_id).where(j.c.owner_user_id==user['user_id'],i.c.filename==name,i.c.sha256!=sha).limit(1)).first():
            parsed['warnings'].append({'code':'same_name_different_sha','message':'Your prior upload has this filename with different content'})
        db.execute(i.insert().values(job_id=job_id,filename=name,sha256=sha,storage_key=key,parse_result=parsed))
    return envelope(request,details(db,job_id,user))

@router.get('')
def jobs(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),user=Depends(current_user),db=Depends(get_db)):
    t=table('import_jobs');rows,meta=page_result(db,select(t).where(t.c.owner_user_id==user['user_id']).order_by(t.c.job_id.desc()),page,size)
    return envelope(request,rows,meta)

@router.get('/options/samples')
def sample_options(request:Request,keyword:str=Query('',max_length=128),page:int=Query(1,ge=1),size:int=Query(50,ge=1,le=200),user=Depends(current_user),db=Depends(get_db)):
    s,b=table('samples'),table('batches')
    q=select(s.c.sample_id,s.c.sample_code,s.c.display_label,b.c.batch_code).join(b,b.c.batch_id==s.c.batch_id).where(scope('samples',user),s.c.voided_at.is_(None))
    if keyword:q=q.where(or_(s.c.sample_code.contains(keyword,autoescape=True),s.c.display_label.contains(keyword,autoescape=True),b.c.batch_code.contains(keyword,autoescape=True)))
    rows,meta=page_result(db,q.order_by(b.c.batch_code,s.c.sample_code,s.c.sample_id),page,size)
    return envelope(request,rows,meta)

@router.get('/options/samples/{sample_id}')
def association_options(sample_id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    sample=require_active_sample(db,sample_id,user)
    p,l,m=table('processes'),table('process_samples'),table('measurements')
    processes=[dict(r) for r in db.execute(select(p.c.process_id,p.c.process_code).where(E.visible('processes',user),p.c.process_id.in_(select(l.c.process_id).where(l.c.sample_id==sample_id))).order_by(p.c.process_code,p.c.process_id)).mappings()]
    measurements=[project(db,r,user,'measurement') for r in db.execute(select(m.c.measurement_id,m.c.measurement_code,m.c.stage,m.c.stage_seq,m.c.optical_model_id).where(m.c.sample_id==sample_id,m.c.is_current==True,measurement_scope(user)).order_by(m.c.measurement_code,m.c.measurement_id)).mappings()]
    return envelope(request,{'sample':sample,'processes':processes,'baseline_measurements':measurements})

@router.delete('/{job_id}')
def delete_job(job_id:int,request:Request,expected_row_version:int|None=Query(None,gt=0),user=Depends(writer),db=Depends(get_db)):
    job=job_row(db,job_id,user,True)
    if expected_row_version is not None and job['row_version']!=expected_row_version:
        fail(409,'任务已变化，请重新读取后再删除。')
    i,m,o=table('import_items'),table('measurements'),table('source_file_occurrences')
    items=[dict(r) for r in db.execute(select(i).where(i.c.job_id==job_id).with_for_update()).mappings()]
    ids=[r['item_id'] for r in items]
    # Archived occurrences preserve ownership, names and original-file access.
    # Their RESTRICT FK deliberately prevents removal of the task provenance.
    if any(r['status'] in ('imported','original_only') for r in items) or db.execute(select(m.c.measurement_id).where(m.c.import_item_id.in_(ids)).limit(1)).first() or db.execute(select(o.c.occurrence_id).where(o.c.import_item_id.in_(ids)).limit(1)).first():
        fail(409,'任务已生成正式测量或归档原件，不能删除；请保留此任务作为来源记录。')
    shas=sorted({r['sha256'] for r in items})
    for sha in shas:
        if not lock_original(db,sha):fail(409,'原件正在被其他任务使用，请稍后重试删除。')
    try:
        with db.begin_nested():
            ledger=table('import_confirmations')
            db.execute(ledger.delete().where(ledger.c.job_id==job_id))
            db.execute(i.delete().where(i.c.job_id==job_id))
            db.execute(table('import_jobs').delete().where(table('import_jobs').c.job_id==job_id))
    except IntegrityError:
        fail(409,'任务仍被其他记录引用，不能删除；请重新读取任务检查来源关联。')
    # Pool reset runs after commit (or rollback), rechecks ALL owners' items and
    # source_files, then removes only unreferenced bytes while holding SHA locks.
    db.info.setdefault('ale_original_cleanup',{}).update({sha:originals_root() for sha in shas})
    return envelope(request,{'job_id':job_id,'deleted':True,'cleanup':'仅在事务完成后清理无引用暂存原件；已引用原件保留。'})

@router.get('/{job_id}')
def get_job(job_id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    return envelope(request,details(db,job_id,user))

def lock_associations(db,choices,user):
    # Acquire ALL plans, then ALL processes, then ALL samples, each ascending.
    p=table('processes');discovered={}
    for pid in sorted({c.process_id for c in choices if c.process_id is not None}):
        discovered[pid]=E.fetch(db,'processes',pid,user)
    for pid in sorted({r['plan_id'] for r in discovered.values() if r['plan_id'] is not None}):
        E.fetch(db,'plans',pid,user,True)
    for pid,r in discovered.items():
        locked=db.execute(select(p).where(p.c.process_id==pid,E.visible('processes',user)).with_for_update()).mappings().first()
        if not locked:fail(404)
        if locked['plan_id']!=r['plan_id']:fail(409,'Process plan changed; reload')
    for sid in sorted({c.sample_id for c in choices if c.sample_id is not None}):require_active_sample(db,sid,user)
    for c in choices:
        if c.process_id is not None:
            if c.sample_id is None:fail(422,'Process requires sample')
            l=table('process_samples')
            if not db.execute(select(l.c.process_sample_id).where(l.c.process_id==c.process_id,l.c.sample_id==c.sample_id)).first():fail(422,'Process is not bound to the selected sample')

def exact_summary(block):
    """Only persist exactly representable summaries. Full parser precision stays in provenance."""
    from decimal import Decimal, localcontext
    fields={'thickness_mean_nm':('thickness_nm','mean',14,6),'thickness_sd_nm':('thickness_nm','sd_sample',14,6),'thickness_min_nm':('thickness_nm','min',14,6),'thickness_max_nm':('thickness_nm','max',14,6),'mse_mean':('mse','mean',14,6),'mse_max':('mse','max',14,6),'gof_mean':('gof','mean',14,8)}
    values={};omitted=[]
    with localcontext() as ctx:
        ctx.prec=210
        for column,(field,stat,precision,scale) in fields.items():
            value=block['statistics'].get(field,{}).get(stat)
            if value is None:continue
            d=Decimal(value)
            if abs(d)<Decimal(10)**(precision-scale) and d==d.quantize(Decimal(1).scaleb(-scale)):values[column]=d
            else:omitted.append(column)
    return values,omitted

def confirm_job(db,job_id,body,user):
    job=job_row(db,job_id,user,True);ledger=table('import_confirmations');it=table('import_items')
    digest=hashlib.sha256(canonical({'expected_row_version':body.expected_row_version,'items':[choice_dump(c) for c in body.items]}).encode()).hexdigest()
    replay=db.execute(select(ledger.c.result).where(ledger.c.job_id==job_id,ledger.c.confirmation_hash==digest)).scalar_one_or_none()
    if replay is not None:return replay
    if job['row_version']!=body.expected_row_version:fail(409,'Job version changed; reload')
    items={r['item_id']:dict(r) for r in db.execute(select(it).where(it.c.job_id==job_id).with_for_update()).mappings()}
    for c in body.items:
        if c.item_id not in items:fail(404)
        item=items[c.item_id]
        if item['status']!='pending' and item['confirmation']!=choice_dump(c):fail(409,'Confirmed item cannot be changed')
    pending=[c for c in body.items if items[c.item_id]['status']=='pending']
    choices_by_id={c.item_id:c for c in body.items}
    for c in pending:
        if c.pair_item_id is not None:
            baseline=choices_by_id.get(c.pair_item_id)
            if (c.pair_measurement_id is not None or not baseline or baseline.item_id==c.item_id
                or baseline.action!='import' or c.action!='import' or baseline.stage!='initial'
                or baseline.pair_item_id is not None or baseline.sample_id!=c.sample_id
                or len(items[baseline.item_id]['parse_result'].get('blocks',[]))!=1):
                fail(422,f"{items[c.item_id]['filename']}：本次上传前测必须为同一样品、已选导入的单块初始测量，请核对。")
    for c in pending:
        parsed=items[c.item_id]['parse_result']
        if c.action=='original_only' and (parsed.get('status')=='original_only' or not parsed.get('blocks')) and any(v is not None for v in (c.sample_id,c.process_id,c.stage,c.stage_seq,c.optical_model_id,c.pair_measurement_id)):
            fail(422,f"{items[c.item_id]['filename']}：未验证格式只能独立归档。请清除样品、执行、阶段、模型和配对关联后保存原件；解析后再建立科学关联。")
    lock_associations(db,pending,user)
    for c in pending:
        if c.action!='skip' and c.optical_model_id is not None:
            optical_model(db,c.optical_model_id,user, sample_fetch(db,'samples',c.sample_id,user) if c.sample_id is not None else None)
    results=[]
    # Global SHA locking in deterministic order serializes cross-job duplicates.
    sources={};sf=table('source_files')
    for sha in sorted({items[c.item_id]['sha256'] for c in pending if c.action!='skip'}):
        content=read_verified(sha)
        parsed_science=any(c.action=='import' and items[c.item_id]['sha256']==sha for c in pending)
        stmt=mysql_insert(sf).values(file_sha256=sha,file_name=sha,rel_path=None,file_role='instrument_raw',size_bytes=len(content),parse_status='parsed' if parsed_science else 'pending',is_readonly=True)
        db.execute(stmt.on_duplicate_key_update(file_sha256=stmt.inserted.file_sha256))
        sources[sha]=db.execute(select(sf.c.file_id).where(sf.c.file_sha256==sha).with_for_update()).scalar_one()
    for c in sorted(body.items,key=lambda c:c.pair_item_id is not None):
        item=items[c.item_id];choice=choice_dump(c)
        if item['status']!='pending':results.append(item['result']);continue
        result={'item_id':c.item_id,'action':c.action,'measurement_ids':[],'warnings':[]}
        if c.action!='skip':
            if c.sample_id is not None and not c.confirm_associations:fail(422,'Explicit association confirmation required')
            source_id=sources[item['sha256']]
            db.execute(table('source_file_occurrences').insert().values(source_file_id=source_id,import_item_id=c.item_id,owner_user_id=user['user_id'],sample_id=c.sample_id,filename=item['filename'],notes=c.notes))
            result['source_file_id']=source_id
        if c.action=='import':
            parsed=item['parse_result']
            if c.pair_item_id is not None:
                baseline=db.scalar(select(it.c.result).where(it.c.item_id==c.pair_item_id))
                mids=(baseline or {}).get('measurement_ids',[])
                if len(mids)!=1:fail(422,'本次前测尚未成功创建，整个确认已回滚')
                choice={**choice,'pair_measurement_id':mids[0]}
            if c.sample_id is None or c.stage is None or not c.confirm_units or not c.confirm_associations:fail(422,f"{item['filename']}：请选择样品与测量阶段，并在提交前确认单位与关联。")
            # Stage sequence is a technical allocation, not a treatment interval.
            # The sample lock serializes concurrent jobs; the replay ledger keeps
            # the allocated value stable after a lost confirmation response.
            sample_fetch(db,'samples',c.sample_id,user,True)
            m=table('measurements')
            sequence=c.stage_seq
            if sequence is None:
                previous=db.scalar(select(func.max(m.c.stage_seq)).where(m.c.sample_id==c.sample_id,m.c.stage==c.stage))
                sequence=0 if previous is None else previous+1
                if sequence>4294967295:fail(422,'阶段技术序号已达到上限')
            choice={**choice,'stage_seq':sequence}
            if not parsed['blocks'] or parsed['blocking_issues'] or any(b['blocking_issues'] for b in parsed['blocks']):fail(422,'Parser blocking issues permit original_only only')
            m=table('measurements')
            pts_existing=table('measurement_points')
            existing_source=or_(m.c.source_file_id==source_id,select(pts_existing.c.point_id).where(pts_existing.c.measurement_id==m.c.measurement_id,pts_existing.c.source_file_id==source_id).exists())
            # Global source deduplication is storage only. Scientific duplicate
            # decisions must not reveal measurements outside the caller's scope.
            if db.execute(select(m.c.measurement_id).where(existing_source,measurement_scope(user)).limit(1)).first():
                if not c.confirm_duplicate or not c.duplicate_reason:fail(409,'Content already measured; explicit duplicate confirmation and reason required')
                result['warnings'].append('Explicit duplicate imported as independent measurement; no supersession')
            if choice.get('pair_measurement_id') is not None:
                pair=db.execute(select(m).where(m.c.measurement_id==choice['pair_measurement_id'],m.c.sample_id==c.sample_id)).mappings().first()
                if not pair:fail(422,'Pair baseline must belong to the same sample')
                if not pair['is_current']:fail(422,'Pair baseline must be current')
                if pair['optical_model_id']!=c.optical_model_id:result['warnings'].append('Optical model mismatch with selected baseline')
                if c.stage=='initial':fail(422,'Initial measurement cannot select a before baseline')
            for index,block in enumerate(parsed['blocks']):
                summary,omitted=exact_summary(block)
                provenance={'parser':parsed['parser'],'parser_version':parsed['version'],'metadata':block['metadata'],'statistics':block['statistics'],'locator':block['locator'],'confirmation':choice,'summary_not_exactly_representable':omitted,'warnings':block['warnings'],'filename_hints':parsed['filename_hints']}
                code=c.measurement_code or f'IMP-{job_id}-{c.item_id}'
                if len(parsed['blocks'])>1:code+=f'-{index+1}'
                if len(code)>80:fail(422,f"{item['filename']}：测量编码加分块后缀超过 80 字符，请缩短编码后重试。")
                if db.execute(select(m.c.measurement_id).where(m.c.measurement_code==code).limit(1)).first():
                    fail(409,f"{item['filename']}：测量编码已使用，请填写其他编码；多块文件会自动追加序号。")
                mid=db.execute(m.insert().values(measurement_code=code,sample_id=c.sample_id,process_id=c.process_id,stage=c.stage,stage_seq=sequence,measured_at=c.measured_at,optical_model_id=c.optical_model_id,operator_user_id=user['user_id'],point_count=len(block['points']),source_file_id=source_id,import_item_id=c.item_id,import_locator=canonical(block['locator']),provenance=provenance,quality_flag='suspect' if any(p['is_outlier'] for p in block['points']) else 'ok',**summary)).inserted_primary_key[0]
                pts=table('measurement_points')
                for point in block['points']:
                    values={k:v for k,v in point.items() if k in pts.c and k not in ('point_id','measurement_id','source_file_id')}
                    db.execute(pts.insert().values(measurement_id=mid,source_file_id=source_id,**values))
                audit(db,user['user_id'],'insert','measurement',mid)
                result['measurement_ids'].append(mid)
        status={'import':'imported','original_only':'original_only','skip':'skipped'}[c.action]
        db.execute(it.update().where(it.c.item_id==c.item_id).values(status=status,confirmation=choice,result=result))
        results.append(result)
    remaining=db.scalar(select(func.count()).select_from(it).where(it.c.job_id==job_id,it.c.status=='pending'))
    version=job['row_version']+1;status='draft' if remaining else 'completed'
    db.execute(table('import_jobs').update().where(table('import_jobs').c.job_id==job_id).values(row_version=version,status=status))
    result={'job_id':job_id,'row_version':version,'status':status,'pending_count':remaining,'items':results}
    db.execute(ledger.insert().values(job_id=job_id,confirmation_hash=digest,result=result))
    return result

@router.post('/{job_id}/confirm')
def confirm(job_id:int,body:Confirmation,request:Request,user=Depends(writer),db=Depends(get_db)):
    """Atomic selected-item confirmation. Unselected items stay pending; identical bodies replay saved results; stale/different requests return 409."""
    return envelope(request,confirm_job(db,job_id,body,user))
