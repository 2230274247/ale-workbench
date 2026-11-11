"""Round 7 real MySQL rollback, real uploaded workbook, and pure Decimal tests."""
import copy
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from app.db import table
from app.scientificanalysis import Calculate,Selection,summarize_points,pair_series
from app.parsers import parse_file
from test_phase3_imports import originals,sample,choice,workbook,unique

def upload(client,actors,files):
    return client.post('/api/v1/imports/preview',headers=actors['operator']['headers'],files=[('files[]',(name,data,'application/octet-stream')) for name,data in files])
def confirm(client,actors,job,choices):
    return client.post(f"/api/v1/imports/{job['job_id']}/confirm",headers=actors['operator']['headers'],json={'expected_row_version':job['row_version'],'items':choices})

UPLOADS=Path('/sessions/intelligent-hopeful-fermat/mnt/uploads')

def actual_files():
    if not UPLOADS.exists():pytest.skip('Original upload archives not mounted')
    found={}
    for archive in sorted(UPLOADS.glob('*.zip')):
        with zipfile.ZipFile(archive) as z:
            candidates=[i for i in z.infolist() if i.filename.endswith('.xlsx') and not i.filename.rsplit('/',1)[-1].startswith('~$')]
            for i in candidates:
                if not (i.filename.endswith('/1.xlsx') or '81' in i.filename or 'Mapping' in i.filename or 'mapping' in i.filename):continue
                assert i.file_size<25*1024*1024
                content=z.read(i);parsed=parse_file(content,i.filename)
                for b in parsed.get('blocks',[]):
                    n=len(b['points'])
                    if parsed['status']=='parsed' and n in (4,81) and n not in found:
                        found[n]=(i.filename.rsplit('/',1)[-1],content,parsed)
                if len(found)==2:return found
    # Any actual 81-point file may not advertise its count in filename.
    for archive in sorted(UPLOADS.glob('*.zip')):
        with zipfile.ZipFile(archive) as z:
            for i in z.infolist():
                if not i.filename.endswith('.xlsx') or i.file_size>25*1024*1024:continue
                content=z.read(i);parsed=parse_file(content,i.filename)
                if parsed['status']=='parsed' and any(len(b['points'])==81 for b in parsed['blocks']):
                    found[81]=(i.filename.rsplit('/',1)[-1],content,parsed);return found
    return found

def post(client,actors,body,role='operator',path='calculate'):
    return client.post('/api/v1/analysis/'+path,json=body,headers=actors[role]['headers'])

def ref(item,job,**kw):return dict(kind='import_item',id=item['item_id'],expected_row_version=job['row_version'],**kw)

def test_decimal_stats_and_coordinate_pairs():
    src=dict(sample_id=1,stage='initial',stage_seq=0,optical_model_id=1,model_parameter_columns=[])
    raw=[dict(point_no=i+1,x_mm=str(i),y_mm='0',thickness_nm=str(Decimal('0.1')+i),mse='20.58',gof='1',is_outlier=i==2) for i in range(3)]
    a=summarize_points(src,raw,Selection(),0)
    assert a['statistics']['thickness_nm']['mean']=='1.1'
    assert a['statistics']['thickness_nm']['sd_sample']=='1'
    braw=[dict(p,thickness_nm=str(Decimal(p['thickness_nm'])+Decimal('.2'))) for p in reversed(raw)]
    b=summarize_points(dict(src,stage='after_ale'),braw,Selection(),1)
    p=pair_series(a,b)
    assert p['mean_delta_nm']=='0.2' and p['observation']=='increase'
    assert p['paired_point_count']==3
    assert p['mean_before_nm']=='1.1' and p['mean_after_nm']=='1.3'
    assert a['statistics']['mse']['mean']=='20.58'
    assert summarize_points(src,raw,Selection(include_outliers=False,reason='review'),0)['included_count']==2
    assert all('raw_values' not in p for p in a['points'])
    for edit in ({'sample_id':2},{'optical_model_id':None},{'optical_model_id':2},{'stage':'other'},{'model_parameter_columns':['different']},{'optical_model':{'status':'superseded'}}):
        with pytest.raises(HTTPException):pair_series(a,dict(b,source={**b['source'],**edit}))
    duplicate=copy.deepcopy(b);duplicate['points'][1].update(x_mm=duplicate['points'][0]['x_mm'],y_mm='0')
    with pytest.raises(HTTPException):pair_series(a,duplicate)


def test_real_preview_and_formal_same_calculation(db,client,actors,originals):
    files=actual_files();assert set(files)=={4,81}
    sid=sample(db,actors)
    counts={n:db.scalar(select(func.count()).select_from(table(n))) for n in ('measurements','measurement_points','source_files')}
    job=upload(client,actors,[(f'real-{n}.xlsx',files[n][1]) for n in (4,81)]).json()['data']
    response=post(client,actors,{'sources':[ref(i,job) for i in job['items']]})
    assert response.status_code==200,response.text
    preview=response.json()['data'];assert [s['raw_count'] for s in preview['series']]==[4,81]
    for n,v in counts.items():assert db.scalar(select(func.count()).select_from(table(n)))==v
    for s in preview['series']:
        assert s['mapping']['actual_xy_point_count']==s['raw_count']
        assert s['mapping']['interpolation_available'] is False
    saved=confirm(client,actors,job,[choice(i,sid) for i in job['items']])
    assert saved.status_code==200,saved.text
    mids=[m for i in saved.json()['data']['items'] for m in i['measurement_ids']]
    formal=post(client,actors,{'sources':[{'kind':'measurement','id':m} for m in mids]})
    assert formal.status_code==200,formal.text
    assert [s['statistics'] for s in preview['series']]==[s['statistics'] for s in formal.json()['data']['series']]
    assert [s['source']['sha256'] for s in preview['series']]==[s['source']['sha256'] for s in formal.json()['data']['series']]
    print('REAL_FILES',[(n,files[n][0],files[n][2]['source']['sha256']) for n in files])
    print('PREVIEW_NO_FORMAL_WRITES',counts,'POINTS',[s['raw_count'] for s in preview['series']],'FORMAL_STATS_IDENTICAL',True)


def test_scope_strict_selection_save_and_cas(db,client,actors,originals):
    sid=sample(db,actors);job=upload(client,actors,[('points.xlsx',workbook(('1','2','3','4','5','100')))]).json()['data']
    args={'sources':[ref(job['items'][0],job)]}
    assert post(client,actors,args,'other').status_code==404
    assert post(client,actors,args,'admin').status_code==404 # uploads remain personal
    for body in ({**args,'sql':'SELECT 1'},{'sources':[{'kind':'measurement','id':True}]},{**args,'selection':{'include_outliers':False}},
                 {**args,'selection':{'excluded_points':['99:0'],'reason':'bad id'}}):
        assert post(client,actors,body).status_code==422
    res=post(client,actors,{**args,'selection':{'include_outliers':False,'reason':'review outlier'}})
    assert res.status_code==200,res.text
    s=res.json()['data']['series'][0]
    assert s['raw_count']==6 and s['included_count']==5 and s['points'][-1]['is_outlier']
    committed=confirm(client,actors,job,[choice(job['items'][0],sid)]).json()['data']
    mid=committed['items'][0]['measurement_ids'][0]
    assert post(client,actors,args).status_code==409
    refs={'sources':[{'kind':'measurement','id':mid,'expected_row_version':1}]}
    assert post(client,actors,refs,'other').status_code==404
    assert post(client,actors,refs,'viewer').status_code==404
    bid=db.scalar(select(table('samples').c.batch_id).where(table('samples').c.sample_id==sid))
    db.execute(table('batches').update().where(table('batches').c.batch_id==bid).values(owner_user_id=actors['viewer']['user']['user_id']))
    db.execute(table('samples').update().where(table('samples').c.sample_id==sid).values(owner_user_id=actors['viewer']['user']['user_id']))
    assert post(client,actors,refs,'viewer').status_code==200
    db.execute(table('batches').update().where(table('batches').c.batch_id==bid).values(owner_user_id=actors['operator']['user']['user_id']))
    db.execute(table('samples').update().where(table('samples').c.sample_id==sid).values(owner_user_id=actors['operator']['user']['user_id']))
    assert post(client,actors,{'calculation':refs,'label':'review'},'viewer','save').status_code==403
    before=db.scalar(select(func.count()).select_from(table('derived_results')))
    response=post(client,actors,{'calculation':refs,'label':'review'},path='save')
    assert response.status_code==201,response.text
    assert db.scalar(select(func.count()).select_from(table('derived_results')))==before+1
    rid=response.json()['data']['result_id'];row=db.execute(select(table('derived_results')).where(table('derived_results').c.result_id==rid)).mappings().one()
    note=json.loads(row['computation_note']);assert note['request']==Calculate(**refs).model_dump()
    assert note['result_sha256']==response.json()['data']['result_sha256']
    read=client.get(f'/api/v1/analysis/saved/{rid}',headers=actors['operator']['headers'])
    assert read.status_code==200 and read.json()['data']['is_valid']
    assert client.get(f'/api/v1/analysis/saved/{rid}',headers=actors['other']['headers']).status_code==404
    db.execute(table('measurements').update().where(table('measurements').c.measurement_id==mid).values(row_version=2))
    assert not client.get(f'/api/v1/analysis/saved/{rid}',headers=actors['operator']['headers']).json()['data']['is_valid']
    db.execute(table('measurements').update().where(table('measurements').c.measurement_id==mid).values(row_version=1))
    refs['sources'][0]['expected_row_version']=2
    assert post(client,actors,{'calculation':refs,'label':'stale'},path='save').status_code==409
    print('SCOPE: other/admin preview 404; viewer formal read 200, save 403; stale version 409; explicit save uses existing derived_results only')


def test_pair_contract_and_unvalidated_archive(db,client,actors,originals):
    sid=sample(db,actors)
    model=table('optical_models');modelid=db.execute(model.insert().values(model_code=unique(),model_name=unique())).inserted_primary_key[0]
    job=upload(client,actors,[('before.xlsx',workbook(('1','2','3'))),('after.xlsx',workbook(('2','3','4'))),('rga.vgd',b'not verified')]).json()['data']
    refs=[ref(i,job,sample_id=sid,stage=stage,stage_seq=0,optical_model_id=modelid,confirm_associations=True) for i,stage in zip(job['items'],['initial','after_ale'])]
    body={'sources':refs,'before_index':0,'after_index':1,'confirm_pair':True}
    pair=post(client,actors,body)
    assert pair.status_code==200,pair.text
    assert pair.json()['data']['pair']['mean_delta_nm']=='1'
    assert post(client,actors,{'sources':[ref(job['items'][2],job)]}).status_code==422
    body['sources'][1]['optical_model_id']=None
    assert post(client,actors,body).status_code==422
    saved=confirm(client,actors,job,[choice(i,sid,stage=stage,optical_model_id=modelid) for i,stage in zip(job['items'],['initial','after_ale'])])
    assert saved.status_code==200,saved.text
    ids=[i['measurement_ids'][0] for i in saved.json()['data']['items']]
    response=post(client,actors,dict(before_measurement_id=ids[0],after_measurement_id=ids[1],confirm_pair=True),path='pair')
    assert response.status_code==200,response.text
    assert response.json()['data']['mean_delta_nm']=='1'
    assert post(client,actors,dict(before_measurement_id=ids[0],after_measurement_id=ids[1],confirm_pair=False),path='pair').status_code==422


def test_actual_files_different_model_declarations_are_denied(db,client,actors,originals):
    files=actual_files();sid=sample(db,actors)
    models=[db.execute(table('optical_models').insert().values(model_code=unique(),model_name=unique())).inserted_primary_key[0] for _ in range(2)]
    job=upload(client,actors,[(f'actual-{n}.xlsx',files[n][1]) for n in (4,81)]).json()['data']
    sources=[ref(i,job,sample_id=sid,stage=stage,stage_seq=0,optical_model_id=model,confirm_associations=True) for i,stage,model in zip(job['items'],['initial','after_ale'],models)]
    assert post(client,actors,{'sources':sources}).status_code==200
    response=post(client,actors,{'sources':sources,'before_index':0,'after_index':1,'confirm_pair':True})
    assert response.status_code==422,response.text
    print('ACTUAL_4_81_POINT_DIFFERENT_MODELS: parallel display 200, delta denied 422; no forced baseline')


def test_saved_mutable_dependency_fingerprint(db,client,actors,originals):
    sid=sample(db,actors)
    model=table('optical_models');modelid=db.execute(model.insert().values(model_code=unique(),model_name=unique())).inserted_primary_key[0]
    p=table('processes');pid=db.execute(p.insert().values(process_code=unique(),process_mode='other',operator_user_id=actors['operator']['user']['user_id'],r1_temp_c=200,full_ale_cycles=7,process_flow={'version':1,'total_cycles':30,'children':[]})).inserted_primary_key[0]
    job=upload(client,actors,[('dependency.xlsx',workbook(('1','2','3')))]).json()['data']
    committed=confirm(client,actors,job,[choice(job['items'][0],sid,optical_model_id=modelid)]).json()['data']
    mid=committed['items'][0]['measurement_ids'][0];m=table('measurements')
    db.execute(m.update().where(m.c.measurement_id==mid).values(process_id=pid,cumulative_cycles=99))
    recipe={'sources':[{'kind':'measurement','id':mid,'expected_row_version':1}]}
    first=post(client,actors,recipe).json()['data'];second=post(client,actors,recipe).json()['data']
    assert first['result_sha256']==second['result_sha256']
    import yaml
    from jsonschema import Draft202012Validator
    from app.config import ROOT
    contract=yaml.safe_load((ROOT/'api/openapi/openapi.bundled.yaml').read_text())
    def schema_valid(name,value):Draft202012Validator({**contract['components']['schemas'][name],'components':contract['components']}).validate(value)
    schema_valid('AnalysisResult',first)
    conditions=first['series'][0]['source']['recorded_conditions']
    assert conditions['recorded_total_cycles']==30 and conditions['full_ale_cycles']==7
    assert first['series'][0]['source']['cumulative_cycles']==99
    rid=post(client,actors,{'calculation':recipe,'label':'dependencies'},path='save').json()['data']['result_id']
    def valid():
        r=client.get(f'/api/v1/analysis/saved/{rid}',headers=actors['operator']['headers']);assert r.status_code==200,r.text
        schema_valid('AnalysisSavedResult',r.json()['data'])
        return r.json()['data']['is_valid']
    assert valid()
    point=table('measurement_points');pr=db.execute(select(point).where(point.c.measurement_id==mid)).mappings().first()
    changes=[(p,p.c.process_id==pid,{'r1_temp_c':201}),
             (p,p.c.process_id==pid,{'row_version':2}),
             (p,p.c.process_id==pid,{'process_flow':{'version':1,'total_cycles':31,'children':[]}}),
             (model,model.c.model_id==modelid,{'n_setting':'1.55'}),
             (point,point.c.point_id==pr['point_id'],{'thickness_nm':'8'}),
             (table('source_files'),table('source_files').c.file_id==first['series'][0]['source']['source_file_id'],{'file_sha256':'a'*64})]
    for t,where,values in changes:
        old=dict(db.execute(select(t).where(where)).mappings().one())
        db.execute(t.update().where(where).values(**values));assert not valid(),(t.name,values)
        db.execute(t.update().where(where).values(**{k:old[k] for k in values}));assert valid()
    bid=db.scalar(select(table('samples').c.batch_id).where(table('samples').c.sample_id==sid))
    db.execute(model.update().where(model.c.model_id==modelid).values(applicable_batch_id=bid))
    rid=post(client,actors,{'calculation':recipe,'label':'scoped model'},path='save').json()['data']['result_id'];assert valid()
    assert post(client,actors,recipe).json()['data']['series'][0]['source']['sample_dependency']=={'sample_id':sid,'batch_id':bid}
    other_sid=sample(db,actors);other_bid=db.scalar(select(table('samples').c.batch_id).where(table('samples').c.sample_id==other_sid))
    db.execute(table('samples').update().where(table('samples').c.sample_id==sid).values(batch_id=other_bid));assert not valid()
    db.execute(table('samples').update().where(table('samples').c.sample_id==sid).values(batch_id=bid));assert valid()
    print('FINGERPRINT: deterministic; process condition/version/total_cycles, model, points, source hash mutations invalidate; restores valid')


def test_model_batch_scope_preview_and_formal(db,client,actors,originals):
    sid=sample(db,actors);foreign=sample(db,actors,'other')
    bid=db.scalar(select(table('samples').c.batch_id).where(table('samples').c.sample_id==foreign))
    modelid=db.execute(table('optical_models').insert().values(model_code=unique(),model_name=unique(),applicable_batch_id=bid)).inserted_primary_key[0]
    job=upload(client,actors,[('model.xlsx',workbook())]).json()['data']
    source=ref(job['items'][0],job,sample_id=sid,stage='initial',optical_model_id=modelid,confirm_associations=True)
    assert post(client,actors,{'sources':[source]}).status_code==422
