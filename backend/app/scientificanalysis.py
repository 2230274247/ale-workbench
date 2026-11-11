"""Bounded, scoped scientific analysis shared by manual UI and future read-only tools.

Decimal strings remain authoritative; JavaScript numeric conversion is display-only.
No source edits, arbitrary SQL, interpolation, inferred cycles or inferred associations.
"""
import hashlib
import json
import uuid
from collections import Counter
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Query, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from .common import audit, dbnow, envelope, fail, clean
from .db import get_db, table
from .security import current_user, writer
from .measurement_management import measurement, measurement_scope, lock_measurements
from .parsers.core import decimal_value, stats
from .records import fetch as sample_fetch
from .data_visibility import optical_model, project, reference_visible, require_snapshot_visibility

router = APIRouter(prefix='/api/v1/analysis', tags=['数据分析'])
VERSION = '1.1.0'
MAX_POINTS = 20000
Positive = Annotated[int, Field(strict=True, gt=0)]
Stage = Literal['initial','after_o2_plasma','after_o3_pre','after_ale','after_hf_only','after_o3_only','intermediate','final','other']

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Source(Strict):
    kind: Literal['measurement','import_item']
    id: Positive
    block_index: Annotated[int, Field(ge=0, le=15)] = 0
    # Preview-only declarations; never persisted into measurements by analysis.
    sample_id: Positive | None = None
    stage: Stage | None = None
    stage_seq: Annotated[int, Field(ge=0, le=4294967295)] | None = None
    optical_model_id: Positive | None = None
    confirm_associations: bool = False
    expected_row_version: Positive | None = None
    @model_validator(mode='after')
    def formal_identity(self):
        if self.kind == 'measurement' and (self.block_index or any(v is not None for v in (self.sample_id,self.stage,self.stage_seq,self.optical_model_id)) or self.confirm_associations):
            raise ValueError('Formal associations come only from stored measurements')
        return self

class Selection(Strict):
    include_outliers: bool = True
    excluded_points: list[Annotated[str, Field(min_length=1,max_length=80)]] = Field(default_factory=list,max_length=1000)
    reason: Annotated[str, Field(max_length=4000)] = ''
    @model_validator(mode='after')
    def reason_for_exclusion(self):
        if (not self.include_outliers or self.excluded_points) and not self.reason.strip():
            raise ValueError('Exclusion requires an auditable reason')
        if len(set(self.excluded_points)) != len(self.excluded_points):
            raise ValueError('Duplicate exclusions')
        return self

class Calculate(Strict):
    sources: list[Source] = Field(min_length=1,max_length=20)
    selection: Selection = Field(default_factory=Selection)
    before_index: Annotated[int, Field(ge=0,le=19)] | None = None
    after_index: Annotated[int, Field(ge=0,le=19)] | None = None
    confirm_pair: bool = False
    @model_validator(mode='after')
    def source_identity(self):
        keys=[(s.kind,s.id,s.block_index) for s in self.sources]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate sources')
        if (self.before_index is None)!=(self.after_index is None):raise ValueError('Both pair indices required')
        if self.before_index is not None and (not self.confirm_pair or self.before_index==self.after_index or max(self.before_index,self.after_index)>=len(self.sources)):
            raise ValueError('Confirm distinct before/after sources')
        return self

class PairRequest(Strict):
    before_measurement_id: Positive
    after_measurement_id: Positive
    pairing_method: Literal['same_xy_coordinate'] = 'same_xy_coordinate'
    include_points: bool = True
    confirm_pair: bool
    selection: Selection = Field(default_factory=Selection)

class SaveRequest(Strict):
    calculation: Calculate
    label: Annotated[str, Field(min_length=1,max_length=100)]


def decimal_text(value):
    text=format(Decimal(value),'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def canonical(v):
    return json.dumps(clean(v),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def bounded_points(db, mid):
    p=table('measurement_points')
    rows=[dict(r) for r in db.execute(select(p).where(p.c.measurement_id==mid).order_by(p.c.point_no,p.c.point_id).limit(MAX_POINTS+1)).mappings()]
    if len(rows)>MAX_POINTS:fail(422,'测点超过分析上限，请缩小选择范围。')
    return rows


def load_source(db, ref, user):
    if ref.kind=='measurement':
        m=measurement(db,ref.id,user)
        if ref.expected_row_version is not None and ref.expected_row_version!=m['row_version']:
            fail(409,'测量已变化，请重新加载。')
        provenance=m.get('provenance') or {}
        if isinstance(provenance,str):provenance=json.loads(provenance)
        points=bounded_points(db,ref.id)
        metadata=provenance.get('metadata',{})
        source={'kind':ref.kind,'id':ref.id,'block_index':0,'row_version':m['row_version'],
                'label':m['measurement_code'],'sample_id':m['sample_id'],'stage':m['stage'],
                'stage_seq':m['stage_seq'],'optical_model_id':m['optical_model_id'],
                'process_id':m['process_id'],'cumulative_cycles':m['cumulative_cycles'],
                'is_current':bool(m['is_current']),'quality_flag':m['quality_flag'],
                'source_file_id':m['source_file_id'],'import_item_id':m['import_item_id'],
                'parser':provenance.get('parser'),'parser_version':provenance.get('parser_version')}
        projected=project(db,m,user,'measurement')
        for key in ('process_id','import_item_id'):
            source[key]=projected[key]
        if source['process_id'] is None and m['process_id'] is not None:
            source['cumulative_cycles']=None
        if m['source_file_id']:
            from .measurement_management import source as scoped_source
            source['sha256']=scoped_source(db,m['source_file_id'],user)['file_sha256']
        # Conditions come from actual process fields only and obey process visibility.
        if m['process_id']:
            from .experiments import visible
            p=table('processes')
            columns=['process_id','process_code','row_version','r1_temp_c','r2_temp_c','full_ale_cycles','hf_tma_repeats','o3_pre_cycles','o3_pre_duration_s','process_flow']
            actual=db.execute(select(*(p.c[c] for c in columns)).where(p.c.process_id==m['process_id'],visible('processes',user))).mappings().first()
            source['recorded_conditions']=dict(actual) if actual else None
            if actual:
                flow=actual['process_flow']
                if isinstance(flow,str):flow=json.loads(flow)
                source['recorded_conditions']['recorded_total_cycles']=(flow or {}).get('total_cycles')
                source['recorded_conditions'].pop('process_flow')
    else:
        i,j=table('import_items'),table('import_jobs')
        row=db.execute(select(i,j.c.row_version).join(j,j.c.job_id==i.c.job_id).where(i.c.item_id==ref.id,j.c.owner_user_id==user['user_id'])).mappings().first()
        if row is None:fail(404)
        if ref.expected_row_version is not None and ref.expected_row_version!=row['row_version']:fail(409,'导入任务已变化，请重新加载。')
        parsed=row['parse_result']
        if isinstance(parsed,str):parsed=json.loads(parsed)
        if parsed.get('status')!='parsed' or parsed.get('blocking_issues') or parsed.get('parser')!='eoptics_workbook':
            fail(422,'原件已暂存或归档；格式未经可信验证，不能生成科学图表。')
        blocks=parsed.get('blocks',[])
        if ref.block_index>=len(blocks):fail(422,'测量块不存在。')
        block=blocks[ref.block_index]
        if block.get('blocking_issues'):fail(422,'测量块存在阻断问题，不能绘图。')
        points=block['points'];metadata=block['metadata']
        if ref.sample_id is not None:sample_fetch(db,'samples',ref.sample_id,user)
        source={'kind':ref.kind,'id':ref.id,'block_index':ref.block_index,'row_version':row['row_version'],
                'label':row['filename']+f' · 块 {ref.block_index+1}','sha256':row['sha256'],
                'sample_id':ref.sample_id if ref.confirm_associations else None,
                'stage':ref.stage if ref.confirm_associations else None,
                'stage_seq':ref.stage_seq if ref.confirm_associations else None,
                'optical_model_id':ref.optical_model_id if ref.confirm_associations else None,
                'associations_source':'user_confirmed_preview' if ref.confirm_associations else 'unknown',
                'cumulative_cycles':None,'parser':parsed['parser'],'parser_version':parsed['version'],
                'locator':block.get('locator'),'formal_measurements_written':False}
    # Models are global unless explicitly restricted to a visible batch.
    mid=source.get('optical_model_id')
    source['optical_model']=None
    if mid is not None:
        model=optical_model(db,mid,user)
        source['optical_model']={k:v for k,v in model.items() if k not in ('created_at','updated_at')}
        if model['applicable_batch_id'] is not None and source.get('sample_id') is not None:
            sample=sample_fetch(db,'samples',source['sample_id'],user)
            source['sample_dependency']={'sample_id':sample['sample_id'],'batch_id':sample['batch_id']}
            if sample['batch_id']!=model['applicable_batch_id']:fail(422,'模型适用批次与样品不一致。')
    source['points_sha256']=hashlib.sha256(canonical([{k:v for k,v in p.items() if k not in ('created_at','updated_at')} for p in points]).encode()).hexdigest()
    source['model_parameter_columns']=metadata.get('optical_model',{}).get('parameter_columns',[])
    source['units']={'thickness_nm':'nm','x_mm':'mm','y_mm':'mm','mse':'dimensionless','gof':'dimensionless'}
    return source,points


def summarize_points(source, raw, selection, source_index):
    """Pure deterministic selection, retaining every raw point and original flag."""
    points=[];included=[]
    for n,p in enumerate(raw):
        key=f'{source_index}:{n}'
        excluded=key in selection.excluded_points or (not selection.include_outliers and bool(p.get('is_outlier')))
        q={k:p.get(k) for k in ('point_no','x_mm','y_mm','thickness_nm','mse','gof','is_outlier','outlier_note','source_sheet','source_row','source_cell','source_file_id','point_id')}
        q.update(key=key,included=not excluded,is_outlier=bool(p.get('is_outlier')))
        points.append(q)
        if not excluded:included.append(q)
    summary=stats(included)
    # Canonical decimal formatting makes preview and DB-scaled values identical.
    for field in ('thickness_nm','mse','gof'):
        for key,value in summary[field].items():
            if isinstance(value,str):
                text=format(Decimal(value),'f')
                summary[field][key]=text.rstrip('0').rstrip('.') if '.' in text else text
    summary['includes_outliers']=selection.include_outliers
    mapped=[p for p in included if all(decimal_value(p.get(k)) is not None for k in ('x_mm','y_mm','thickness_nm'))]
    return {'source':source,'points':points,'statistics':summary,
            'raw_count':len(points),'included_count':len(included),'excluded_count':len(points)-len(included),
            'mapping':{'available':bool(mapped),'actual_xy_point_count':len(mapped),'interpolation_available':False,
                       'note':'仅显示实际 X/Y 测点；不插值、不补坐标。'},
            'warnings':['MSE 是拟合质量指标，不是膜厚不确定度。','空间标准差不是独立重复测量误差。']}


def pair_series(before,after):
    a,b=before['source'],after['source']
    if a.get('sample_id') is None or a.get('sample_id')!=b.get('sample_id'):fail(422,'前后比较必须人工确认属于同一样品。')
    if not a.get('stage') or not b.get('stage') or 'other' in (a['stage'],b['stage']):fail(422,'阶段未知或为其他，不能前后配对。')
    if a['stage']==b['stage'] and (a.get('stage_seq') is None or b.get('stage_seq') is None or a['stage_seq']==b['stage_seq']):fail(422,'同阶段比较需要不同的已记录阶段序号。')
    if a.get('optical_model_id') is None or a.get('optical_model_id')!=b.get('optical_model_id'):fail(422,'模型未知或模型不同，不能计算前后差值。')
    if any((s.get('optical_model') or {}).get('status')=='superseded' for s in (a,b)):fail(422,'已被取代的模型不能用于前后差值。')
    if a.get('model_parameter_columns')!=b.get('model_parameter_columns'):fail(422,'文件中的模型参数定义不一致，不能计算前后差值。')
    if any(s.get('is_current') is False or s.get('quality_flag')=='excluded' for s in (a,b)):fail(422,'已被取代或排除的测量不能用于前后配对。')
    def coordinates(series):
        eligible=[p for p in series['points'] if p['included'] and all(decimal_value(p.get(k)) is not None for k in ('x_mm','y_mm','thickness_nm'))]
        coords=[(decimal_value(p['x_mm']),decimal_value(p['y_mm'])) for p in eligible]
        if any(n>1 for n in Counter(coords).values()):fail(422,'存在重复 X/Y 坐标，无法一一配对；请明确排除重复点后重算。')
        return dict(zip(coords,eligible))
    aa,bb=coordinates(before),coordinates(after)
    matched=sorted(aa.keys() & bb.keys())
    if not matched:fail(422,'没有可按真实 X/Y 坐标精确配对的点。')
    values=[]
    with localcontext() as ctx:
        ctx.prec=50;ctx.rounding=ROUND_HALF_EVEN
        for xy in matched:
            p,q=aa[xy],bb[xy];d=decimal_value(q['thickness_nm'])-decimal_value(p['thickness_nm'])
            values.append({'x_mm':str(xy[0]),'y_mm':str(xy[1]),'before_nm':str(p['thickness_nm']),'after_nm':str(q['thickness_nm']),
                           'delta_nm':decimal_text(d),'thickness_nm':decimal_text(d),'mse':None,'gof':None,'before_key':p['key'],'after_key':q['key']})
        summary=stats(values)['thickness_nm'];mean=Decimal(summary['mean'])
        return {'pairing_method':'same_xy_coordinate','direction':'after - before','model_consistent':True,
                'paired_point_count':len(values),'unmatched_before':len(aa)-len(values),'unmatched_after':len(bb)-len(values),
                'ineligible_before':before['included_count']-len(aa),'ineligible_after':after['included_count']-len(bb),
                'mean_delta_nm':decimal_text(mean),'sd_delta_nm':decimal_text(summary['sd_sample']) if summary['sd_sample'] is not None else None,
                'mean_before_nm':str(sum(Decimal(v['before_nm']) for v in values)/len(values)),
                'mean_after_nm':str(sum(Decimal(v['after_nm']) for v in values)/len(values)),
                'observation':'increase' if mean>0 else 'decrease' if mean<0 else 'unchanged',
                'interpretation':'仅为所选前后测量的厚度变化，不推断反应机理或刻蚀速率。','points':values}


def calculate(db, body, user):
    series=[];count=0
    for idx,ref in enumerate(body.sources):
        source,raw=load_source(db,ref,user);count+=len(raw)
        if count>MAX_POINTS:fail(422,'单次最多分析 20000 个真实测点，请缩小选择。')
        if not raw:fail(422,'所选测量没有测点。')
        series.append(summarize_points(source,raw,body.selection,idx))
    known={p['key'] for s in series for p in s['points']}
    if set(body.selection.excluded_points)-known:fail(422,'排除点不属于本次分析来源。')
    result={'analysis_version':VERSION,'decimal_precision':50,'rounding':'ROUND_HALF_EVEN',
            'request':body.model_dump(),'series':series,'pair':None,'persisted':False,
            'limits':{'max_sources':20,'max_points':MAX_POINTS},'scientific_sources_modified':False}
    if body.before_index is not None:result['pair']=pair_series(series[body.before_index],series[body.after_index])
    result['result_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result

@router.post('/calculate')
def calculate_route(body:Calculate,request:Request,user=Depends(current_user),db=Depends(get_db)):
    return envelope(request,calculate(db,body,user))

@router.post('/pair')
def pair_route(body:PairRequest,request:Request,user=Depends(current_user),db=Depends(get_db)):
    if not body.confirm_pair or body.before_measurement_id==body.after_measurement_id:fail(422,'请明确确认不同的前后测量。')
    args=Calculate(sources=[Source(kind='measurement',id=body.before_measurement_id),Source(kind='measurement',id=body.after_measurement_id)],
                   selection=body.selection,before_index=0,after_index=1,confirm_pair=body.confirm_pair)
    result=calculate(db,args,user);pair=result['pair']
    pair.update(before_measurement_id=body.before_measurement_id,after_measurement_id=body.after_measurement_id,
                analysis_version=VERSION,selection=body.selection.model_dump(),result_sha256=result['result_sha256'])
    if not body.include_points:pair.pop('points')
    return envelope(request,pair)

@router.post('/save',status_code=201)
def save_route(body:SaveRequest,request:Request,user=Depends(writer),db=Depends(get_db)):
    """Explicit derived snapshot only. Never edits measurements, points or originals."""
    refs=body.calculation.sources
    if len(refs)>2 or (len(refs)==2 and body.calculation.before_index is None):
        fail(422,'保存支持单组统计或明确前后配对；多组并列分析请导出完整计算记录。')
    if any(s.kind!='measurement' or s.expected_row_version is None for s in refs):fail(422,'保存仅支持带版本号的正式测量；暂存预览请导出计算记录。')
    lock_measurements(db,[s.id for s in refs],user)
    result=calculate(db,body.calculation,user)
    samples={s['source']['sample_id'] for s in result['series']}
    if len(samples)!=1:fail(422,'保存记录必须属于同一样品。')
    # Existing derived_results stores an auditable bounded selection recipe + digest,
    # not a second copy of raw data. No migration or rounding required.
    note=canonical({'label':body.label,'request':body.calculation.model_dump(),'result_sha256':result['result_sha256'],
                    'analysis_version':VERSION,'sources':[s['source'] for s in result['series']],
                    'statistics':[s['statistics'] for s in result['series']],
                    'pair':{k:v for k,v in (result['pair'] or {}).items() if k!='points'}})
    if len(note.encode())>60000:fail(422,'保存记录过大，请缩小选择范围。')
    pair=body.calculation.before_index is not None
    t=table('derived_results')
    rid=db.execute(t.insert().values(result_code='AN-'+uuid.uuid4().hex,result_kind='other',sample_id=next(iter(samples)),
        before_measurement_id=refs[body.calculation.before_index].id if pair else refs[0].id,
        after_measurement_id=refs[body.calculation.after_index].id if pair else None,
        pairing_method='same_xy_coordinate' if pair else None,paired_point_count=result['pair']['paired_point_count'] if pair else None,
        model_consistent=True if pair else None,evidence_level='measured',computation_note=note,
        computed_at=dbnow(),computed_by=f'user:{user["user_id"]};analysis:{VERSION}')).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','derived_result',rid)
    return envelope(request,{'result_id':rid,'persisted':True,'result_sha256':result['result_sha256'],'scientific_sources_modified':False})

# Preparation only: no provider registration or outbound calls. A future tool runner
# must invoke calculate under its authenticated user's scope, then project metadata.
READONLY_TOOL_METADATA={'name':'scientific_analysis','readonly':True,'external_raw_data':False,
    'function':'app.scientificanalysis.calculate','request_schema':Calculate.model_json_schema(),
    'response_projection':['analysis_version','result_sha256','statistics','source identifiers'],
    'requires_authenticated_scope':True,'live_ai_registered':False}


@router.get('/saved/{result_id}')
def saved_route(result_id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    t=table('derived_results');m=table('measurements')
    row=db.execute(select(t).where(t.c.result_id==result_id,t.c.result_code.like('AN-%'),
        t.c.sample_id.in_(select(m.c.sample_id).where(measurement_scope(user))))).mappings().first()
    if row is None:fail(404)
    try:note=json.loads(row['computation_note']);recipe=Calculate.model_validate(note['request'])
    except (ValueError,KeyError,TypeError):fail(409,'旧分析记录格式无法读取。')
    require_snapshot_visibility(db,note,user)
    # Recheck current dependency permissions independently of version checks. A
    # stale version must not mask revoked access to a historical dependency.
    for ref in recipe.sources:
        if ref.kind=='measurement':
            current_source=measurement(db,ref.id,user)
            for key,kind in (('process_id','process'),('optical_model_id','model')):
                if not reference_visible(db,kind,current_source[key],user):fail(404)
        else:
            if not reference_visible(db,'item',ref.id,user):fail(404)
    current=False;recomputed=None;reasons=[]
    try:
        recomputed=calculate(db,recipe,user)
        current=recomputed['result_sha256']==note['result_sha256']
        if not current:reasons.append('source_or_result_changed')
        if any(s['source'].get('is_current') is False or s['source'].get('quality_flag')=='excluded' for s in recomputed['series']):
            current=False;reasons.append('measurement_not_current_or_excluded')
    except HTTPException as exc:
        if exc.status_code==404:raise
        if exc.status_code not in (409,422):raise
        reasons.append('source_unavailable_or_changed')
    if not row['is_valid']:reasons.append('record_invalidated')
    return envelope(request,{'result_id':result_id,'is_valid':bool(row['is_valid']) and current,
        'computed_at':row['computed_at'],'record':note,'invalid_reasons':reasons,'recomputed_result_sha256':recomputed['result_sha256'] if recomputed else None,'scientific_sources_modified':False})


@router.get('/measurements')
def analysis_measurements(request:Request,sample_id:int|None=Query(None,gt=0),
        batch_id:int|None=Query(None,gt=0),process_id:int|None=Query(None,gt=0),
        stage:Stage|None=None,user=Depends(current_user),db=Depends(get_db)):
    m,s=table('measurements'),table('samples')
    q=select(m).where(measurement_scope(user),m.c.is_current==True)
    if batch_id is not None:
        sample_fetch(db,'batches',batch_id,user)
        q=q.where(m.c.sample_id.in_(select(s.c.sample_id).where(s.c.batch_id==batch_id)))
    for field,value in [('sample_id',sample_id),('process_id',process_id),('stage',stage)]:
        if value is not None:q=q.where(m.c[field]==value)
    rows=[dict(r) for r in db.execute(q.order_by(m.c.created_at.desc(),m.c.measurement_id).limit(201)).mappings()]
    return envelope(request,[project(db,r,user,'measurement') for r in rows[:200]],meta={'limit':200,'has_more':len(rows)>200})
