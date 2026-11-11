"""Real isolated MySQL, rollback transactions, genuine parser and workbook readback."""
import copy
import json
from io import BytesIO
from uuid import uuid4
import pytest
from openpyxl import load_workbook
from sqlalchemy import select,func
from app.db import table
from app.quick_models import calculated
from app.quick_dataset import HEADERS, STEP_HEADERS
from test_phase3_imports import workbook

pytestmark=pytest.mark.skipif(not __import__('os').environ.get('ALE_DB_NAME','').endswith('_test'),reason='isolated database only')

@pytest.fixture
def world(client,actors):
    headers=actors['operator']['headers']
    mid=client.post('/api/v1/quick/materials',headers=headers,json={'canonical_name':'SiN'}).json()['data']['material_id']
    def body(n=1):
        return dict(experiment_date='2026-10-24',daily_no=n,material_id=mid,state='recorded',note='=danger\n<test>',idempotency_key=str(uuid4()),program={'outer_cycles':1,'groups':[{'code':'A','repeat_count':100,'steps':[{'source_label':'Purge','pulse_ms':'10000','purge_s':'200','wait_s':'0'}]}]},environment={'r1_temperature_c':'100','r2_temperature_c':'150','n2_flow_sccm':'0'},results=[{'alias':'样品1','effective_cycles':100,'thickness_before_nm':'46.8','thickness_after_nm':'46.2','before_origin':'measured','data_nature':'synthetic'}])
    return headers,body

def create(client,h,b):
    response=client.post('/api/v1/quick/runs',headers=h,json=b)
    assert response.status_code==201,response.text
    return response.json()['data']

def test_direct_storage_diagnostics(db,actors,world):
    from app.quick import store,raw,present
    from app.quick_models import Run
    _,body=world
    user=actors['operator']['user'];id=store(db,Run.model_validate(body()),user)
    row,process=raw(db,id,user)
    assert present(db,row,process,user)

def editable(run):
    keys=['experiment_date','daily_no','timezone','material_id','started_at','ended_at','note','state','program','environment','previous_run_id']
    r={k:copy.deepcopy(run[k]) for k in keys}
    from app.quick_models import Result
    r['results']=[{k:v for k,v in x.items() if k in Result.model_fields} for x in run['results']]
    r.update(expected_version=run['version'],idempotency_key=str(uuid4()))
    return r

@pytest.mark.parametrize('a,b,n,expected',[('46.8','46.2',100,'0.06'),('46.2','45.3',100,'0.09'),('28.8675','36.7925',100,'-0.7925'),('0','0',0,None),(None,'1',100,None)])
def test_epc(a,b,n,expected):
    assert calculated({'thickness_before_nm':a,'thickness_after_nm':b,'effective_cycles':n})['epc_a_per_cycle']==expected

def test_roundtrip_idempotency_permissions_and_version(client,actors,db,world):
    h,body=world;b=body();run=create(client,h,b);id=run['run_id']
    assert create(client,h,b)['run_id']==id
    assert run['results'][0]['epc_a_per_cycle']=='0.06'
    assert run['program']['groups'][0]['steps'][0]['wait_s']=='0'
    assert run['environment']['n2_flow_sccm']=='0'
    assert run['results'][0]['cumulative_cycles']==100
    assert client.get(f'/api/v1/quick/runs/{id}',headers=actors['other']['headers']).status_code==404
    assert client.post('/api/v1/quick/runs',headers=actors['viewer']['headers'],json=b).status_code==403
    b2=editable(run);b2['note']='updated'
    assert client.put(f'/api/v1/quick/runs/{id}',headers=h,json=b2).status_code==200
    assert client.put(f'/api/v1/quick/runs/{id}',headers=h,json=b2).status_code==409
    assert len(client.get(f'/api/v1/quick/runs/{id}/revisions',headers=h).json()['data'])==2
    assert db.scalar(select(table('processes').c.r1_temp_c).where(table('processes').c.process_id==id))==100

def test_sequences_three_results_and_recompute(client,world):
    h,body=world;a=create(client,h,body());b=body(2)
    b['previous_run_id']=a['run_id'];b['results'][0].update(thickness_before_nm='46.2',thickness_after_nm='45.3',before_origin='carried_forward',carried_from_result_id=a['results'][0]['result_id'])
    second=create(client,h,b);c=body(3);c['previous_run_id']=second['run_id'];c['results'][0].update(effective_cycles=50,before_origin='carried_forward',carried_from_result_id=second['results'][0]['result_id'],thickness_before_nm='45.3')
    third=create(client,h,c)
    assert third['sequence_id']==a['sequence_id'] and third['results'][0]['cumulative_cycles']==250
    change=editable(second);change['results'][0]['effective_cycles']=80
    assert client.put(f"/api/v1/quick/runs/{second['run_id']}",headers=h,json=change).status_code==200
    assert client.get(f"/api/v1/quick/runs/{third['run_id']}",headers=h).json()['data']['results'][0]['cumulative_cycles']==230
    independent=create(client,h,body(4));assert independent['sequence_id']!=a['sequence_id']
    multi=body(5);multi['results']*=3
    run=create(client,h,multi);assert len({r['result_id'] for r in run['results']})==3
    from app.quick_dataset import wide
    rows=wide([a,second,third,run])
    assigned={}
    for row in rows:
        key=row['meta_leak_group'];assigned.setdefault(key,set()).add(row['meta_suggested_group_split'])
        assert 'step_id' not in row['X_recipe_json'] and 'group_id' not in row['X_recipe_json']
    assert all(len(v)==1 for v in assigned.values())

def test_validation_rollback_and_null(client,db,world):
    h,body=world
    count=db.scalar(select(func.count()).select_from(table('processes')))
    for field,val in [('pulse_ms','汉字'),('pulse_ms','-1'),('purge_s','NaN')]:
        b=body();b['program']['groups'][0]['steps'][0][field]=val
        assert client.post('/api/v1/quick/runs',headers=h,json=b).status_code==422
    b=body();b['material_id']=None
    assert client.post('/api/v1/quick/runs',headers=h,json=b).status_code==422
    assert db.scalar(select(func.count()).select_from(table('processes')))==count
    b['state']='draft';r=create(client,h,b)
    assert r['material_id'] is None and r['environment']['chamber_pressure_pa'] is None
    assert client.get('/api/v1/quick/runs?date_from=bad',headers=h).status_code==422
    assert client.get('/api/v1/quick/runs?page=bad',headers=h).status_code==422
    b=body(2);b['environment']['r1_temperature_c']='100.123'
    assert client.post('/api/v1/quick/runs',headers=h,json=b).status_code==422

def test_export_real_xlsx_json_wide_readiness(client,world):
    h,body=world;a=create(client,h,body());b=body(2)
    b['program']['groups'][0]['steps']=[{'source_label':str(n),'pulse_ms':str(n)} for n in range(6)]
    create(client,h,b)
    result=client.get('/api/v1/quick/dataset/download?format=xlsx',headers=h)
    assert result.status_code==200,result.text
    w=load_workbook(BytesIO(result.content),data_only=False);s=w['实验记录']
    assert [c.value for c in s[2]]==HEADERS and s.max_row==4 and s.max_column==33
    by_source={s.cell(i,7).value:i for i in (3,4)}
    assert set(by_source)=={'Purge','0'}
    six_step=by_source['0']
    assert s.cell(six_step,8).value=='1' and s.cell(six_step,9).value=='2'
    assert s.cell(by_source['Purge'],9).value is None
    assert all(s.cell(i,10).value==100 for i in (3,4))
    assert all(s.cell(i,13).value is not None for i in (3,4))
    assert float(s.cell(six_step,21).value)==2
    assert all(s.cell(i,31).value=='待复核' for i in (3,4))
    assert all(s.cell(i,32).value in ('是','否') for i in (3,4))
    assert len(list(s.merged_cells.ranges))==6
    assert all(s.cell(i,33).data_type!='f' and s.cell(i,33).value.startswith("'") for i in (3,4))
    assert all(s.cell(i,12).value==0 for i in (3,4))
    assert {'记录明细','源步骤明细','结果明细'}<=set(w.sheetnames)
    assert [c.value for c in w['源步骤明细'][2]]==STEP_HEADERS
    assert 'Purge' in [c.value for c in w['源步骤明细']['E']]
    data=client.get('/api/v1/quick/dataset/download?format=json',headers=h).json()
    assert len(data['runs'][0]['program']['groups'][0]['steps'])==6
    assert len(data['revisions'])==2
    wide=load_workbook(BytesIO(client.get('/api/v1/quick/dataset/download?format=wide',headers=h).content))
    keys=[c.value for c in wide['建模宽表'][1]]
    assert 'X_before_measured_nm' in keys and 'X_thickness_after_nm' not in keys
    ready=client.get('/api/v1/quick/dataset/readiness',headers=h).json()['data']
    assert ready['eligible_count']==0 and ready['data_nature']['synthetic']==2
    assert client.get('/api/v1/quick/runs?data_nature=real_experiment',headers=h).json()['data']['total']==0

def test_excel_preview_conflict_revisions_and_duplicate(client,world,tmp_path,monkeypatch):
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path/'originals'))
    h,body=world;r=create(client,h,body());id=r['run_id']
    content=workbook(('45.27','45.27','45.27','45.27'))
    response=client.post(f'/api/v1/quick/runs/{id}/preview',headers=h,files={'file':('measurement.xlsx',content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==200,response.text
    pre=response.json()['data'];assert client.get(f'/api/v1/quick/runs/{id}',headers=h).json()['data']['version']==1
    b={'expected_version':1,'mappings':[{'block_index':0,'result_id':r['results'][0]['result_id'],'field':'thickness_after_nm'}]}
    assert client.post(f"/api/v1/quick/imports/{pre['token']}/confirm",headers=h,json=b).status_code==409
    b['confirm_conflicts']=True
    response=client.post(f"/api/v1/quick/imports/{pre['token']}/confirm",headers=h,json=b)
    assert response.status_code==200,response.text
    assert client.post(f"/api/v1/quick/imports/{pre['token']}/confirm",headers=h,json=b).json()['data']['duplicate']
    updated=client.get(f'/api/v1/quick/runs/{id}',headers=h).json()['data']
    assert updated['results'][0]['thickness_after_nm']=='45.27' and updated['version']==2
    original=client.get(f"/api/v1/quick/imports/{pre['token']}/original",headers=h)
    assert original.status_code==200 and original.content==content
    quality=editable(updated);quality['results'][0]['quality_status']='approved'
    response=client.put(f'/api/v1/quick/runs/{id}',headers=h,json=quality)
    assert response.status_code==200,response.text
    assert response.json()['data']['results'][0]['source']['sha256']==pre['sha256']
    exported=client.get('/api/v1/quick/dataset/download?format=json',headers=h).json()
    assert len(exported['imports'])==1 and exported['imports'][0]['preview']['blocks'][0]['points']
    assert client.post(f'/api/v1/quick/runs/{id}/preview',headers=h,files={'file':('bad.xlsx',b'bad')}).status_code==422

def test_cross_midnight_conflict_and_legacy_editor_protection(client,world):
    h,body=world;b=body();b.update(started_at='2026-10-24T23:30:00+08:00',ended_at='2026-10-25T00:30:00+08:00')
    r=create(client,h,b);id=r['run_id']
    assert r['started_at']=='2026-10-24T23:30:00+08:00' and r['ended_at']=='2026-10-25T00:30:00+08:00'
    professional=client.get(f'/api/v1/processes/{id}',headers=h).json()['data']
    assert professional['started_at']=='2026-10-24T15:30:00+00:00'
    assert professional['quick_record_url']==f'/quick?run={id}'
    assert client.patch(f'/api/v1/processes/{id}',headers=h,json={'notes':'diverging','expected_row_version':1}).status_code==409
    b2=body();conflict=client.post('/api/v1/quick/runs',headers=h,json=b2)
    assert conflict.status_code==409 and '序号' in conflict.json()['message']
    b2.update(daily_no=2,started_at='2026-10-24T23:30:00',ended_at='2026-10-24T22:30:00')
    assert client.post('/api/v1/quick/runs',headers=h,json=b2).status_code==422

def test_multi_result_excel_mapping_and_reupload_idempotency(client,actors,world,tmp_path,monkeypatch):
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path/'originals'))
    h,body=world;b=body();b['results']*=3;run=create(client,h,b);id=run['run_id']
    w=load_workbook(BytesIO(workbook(('10','10','10','10'))));w.copy_worksheet(w.active).title='Second measurement'
    buf=BytesIO();w.save(buf);content=buf.getvalue()
    def upload():
        response=client.post(f'/api/v1/quick/runs/{id}/preview',headers=h,files={'file':('two-blocks.xlsx',content)})
        assert response.status_code==200,response.text
        return response.json()['data']
    pre=upload();assert len(pre['blocks'])==2
    mappings=[{'block_index':i,'result_id':run['results'][i]['result_id'],'field':'thickness_after_nm'} for i in range(2)]
    b={'expected_version':1,'mappings':mappings,'confirm_conflicts':True}
    response=client.post(f"/api/v1/quick/imports/{pre['token']}/confirm",headers=h,json=b);assert response.status_code==200,response.text
    updated=client.get(f'/api/v1/quick/runs/{id}',headers=h).json()['data']
    assert [r['thickness_after_nm'] for r in updated['results']]==['10','10','46.2']
    pre2=upload();b['mappings'].reverse()
    assert client.post(f"/api/v1/quick/imports/{pre2['token']}/confirm",headers=h,json=b).json()['data']['duplicate']
    assert client.get(f"/api/v1/quick/imports/{pre2['token']}/original",headers=actors['other']['headers']).status_code==404
    assert client.get(f'/api/v1/quick/runs/{id}',headers=h).json()['data']['version']==2

def test_readiness_field_missing_units_groups_and_zero(client,world):
    h,body=world;run=create(client,h,body())
    report=client.get('/api/v1/quick/dataset/readiness',headers=h).json()['data']
    assert report['missing_fields']['X_n2_sccm']==0  # Explicit zero is present, not missing.
    assert report['missing_fields']['X_absolute_pressure_pa']==1
    assert report['missing_fields']['y_uniformity_pct']==1
    assert report['by_material']['SiN']['row_count']==1
    assert report['by_material']['SiN']['missing_fields']['X_absolute_pressure_pa']==1
    assert report['by_sequence'][run['sequence_id']]['eligible_count']==0
    assert report['group_split_audit']['checked_rows']==1
    assert report['group_split_audit']['shared_groups_across_splits']==[]
    from app.quick_dataset import readiness,group_audit
    # Explicit pure audit fault inputs; not a successful API response mock.
    run['results'][0]['source']={'units':'µm','sha256':'test-only-unit-audit'}
    audit=readiness([run],{})
    assert audit['unit_audit']['status']=='FAIL' and audit['unit_audit']['anomaly_count']==1
    assert 'measurement_unit_unconfirmed' in audit['row_issues'][0]['issues']
    assert group_audit([{'meta_leak_group':'same','meta_suggested_group_split':'train'},
                        {'meta_leak_group':'same','meta_suggested_group_split':'test'}])['shared_groups_across_splits']==['same']

def test_private_template_and_preview_writes_require_owner(client,actors,world,tmp_path,monkeypatch):
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path/'originals'))
    h,body=world;run=create(client,h,body());id=run['run_id']
    admin=actors['admin']['headers']
    # Management can read the process, but cannot attach private provenance or templates.
    assert client.get(f'/api/v1/quick/runs/{id}',headers=admin).status_code==200
    assert client.post('/api/v1/quick/templates',headers=admin,json={'name':'admin-copy','run_id':id}).status_code==403
    assert client.post(f'/api/v1/quick/runs/{id}/preview',headers=admin,files={'file':('measurement.xlsx',workbook(('1',)*4))}).status_code==403
    assert client.post('/api/v1/quick/templates',headers=h,json={'name':'   ','run_id':id}).status_code==422
    assert not (tmp_path/'originals').exists()

def test_large_recipe_wide_export_does_not_silently_clip_json(client,world):
    h,body=world;b=body()
    b['program']={'outer_cycles':3,'groups':[{'code':'G'+str(g),'repeat_count':100,
        'steps':[{'source_label':'unconfirmed-'+str(i)+'x'*110,'pulse_ms':'10000','purge_s':'200'} for i in range(100)]} for g in range(6)]}
    run=create(client,h,b)
    response=client.get('/api/v1/quick/dataset/download?format=wide',headers=h);assert response.status_code==200,response.text
    w=load_workbook(BytesIO(response.content));s=w['建模宽表'];keys=[c.value for c in s[1]]
    recipe=s.cell(2,keys.index('X_recipe_json')+1).value
    if recipe is not None:assert sum(len(g['steps']) for g in json.loads(recipe)['groups'])==600
    assert 'meta_recipe_json_export_status' in keys
    assert s.cell(2,keys.index('meta_recipe_json_export_status')+1).value=='normalized_rows'
    extras=w['完整附加字段'];steps=[json.loads(row[2]) for row in extras.iter_rows(min_row=2,values_only=True) if row[1]=='step']
    assert len(steps)==600 and all(x['pulse_ms']=='10000' and x['purge_s']=='200' for x in steps)
    program=[json.loads(row[2]) for row in extras.iter_rows(min_row=2,values_only=True) if row[1]=='program'][0]
    assert program['outer_cycles']==3 and len(program['group_order'])==6
    assert any('单格' in str(row[1]) for row in w['映射说明'].iter_rows(min_row=2,values_only=True))
    full=client.get('/api/v1/quick/dataset/download?format=json',headers=h).json()
    assert sum(len(g['steps']) for g in full['runs'][0]['program']['groups'])==600


def test_empty_file_provenance_cannot_be_forged(client,world,db):
    h,body=world;b=body();b['results'][0]['source']={}
    before=db.scalar(select(func.count()).select_from(table('processes')))
    response=client.post('/api/v1/quick/runs',headers=h,json=b)
    assert response.status_code==422,response.text
    assert db.scalar(select(func.count()).select_from(table('processes')))==before


def test_every_quick_write_authorization_and_invalid_rollback(client,actors,world,db,tmp_path,monkeypatch):
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path/'originals'))
    h,body=world;run=create(client,h,body());id=run['run_id'];content=workbook(('45.27',)*4)
    pre=client.post(f'/api/v1/quick/runs/{id}/preview',headers=h,files={'file':('measurement.xlsx',content)}).json()['data']
    confirm={'expected_version':1,'mappings':[{'block_index':0,'result_id':run['results'][0]['result_id'],'field':'thickness_after_nm'}],'confirm_conflicts':True}
    writes=[('POST','/materials',{'canonical_name':'Forbidden'}),('POST','/runs',body(2)),('PUT',f'/runs/{id}',editable(run)),('POST','/templates',{'run_id':id,'name':'Forbidden'}),('POST',f'/imports/{pre["token"]}/confirm',confirm)]
    for method,path,payload in writes:
        assert client.request(method,'/api/v1/quick'+path,json=payload).status_code==401
        assert client.request(method,'/api/v1/quick'+path,headers=actors['viewer']['headers'],json=payload).status_code==403
    for headers,status in [({},401),(actors['viewer']['headers'],403),(actors['other']['headers'],404)]:
        assert client.post(f'/api/v1/quick/runs/{id}/preview',headers=headers,files={'file':('measurement.xlsx',content)}).status_code==status
    for method,path,payload in writes[2:]:
        assert client.request(method,'/api/v1/quick'+path,headers=actors['other']['headers'],json=payload).status_code==404
    names=['processes','quick_runs','quick_revisions','quick_materials','quick_templates','quick_imports']
    counts=lambda:{name:db.scalar(select(func.count()).select_from(table(name))) for name in names}
    before=counts()
    assert client.post('/api/v1/quick/materials',headers=h,json={'canonical_name':'   '}).status_code==422
    assert client.post('/api/v1/quick/templates',headers=h,json={'run_id':id,'name':'   '}).status_code==422
    invalid=editable(run);invalid['results'][0]['effective_cycles']=-1
    assert client.put(f'/api/v1/quick/runs/{id}',headers=h,json=invalid).status_code==422
    assert client.post(f'/api/v1/quick/runs/{id}/preview',headers=h,files={'file':('broken.xlsx',b'broken')}).status_code==422
    invalid=copy.deepcopy(confirm);invalid['mappings'][0]['block_index']=999
    assert client.post(f'/api/v1/quick/imports/{pre["token"]}/confirm',headers=h,json=invalid).status_code==422
    assert counts()==before
    assert client.get(f'/api/v1/quick/runs/{id}',headers=h).json()['data']['version']==1

def test_stage3_batch_import_template_preview_confirm(client,actors,world,db):
    """Real 33-column workbook (含反应物C) -> preview -> confirmed single-transaction batch."""
    from openpyxl import Workbook
    from app.quick_dataset import HEADERS
    h,body=world
    template=client.get('/api/v1/quick/batch/template',headers=h)
    assert template.status_code==200,template.text
    assert [c.value for c in load_workbook(BytesIO(template.content))['实验记录'][2]]==HEADERS
    w=Workbook();s=w.active;s.title='实验记录'
    s.append(['']*33);s.append(HEADERS)
    values={'日期':'2026-11-11','实验ID':'BATCH-001','批次ID':'B-1','样品ID':'S-1','材料':'SiN',
            '设备/腔体':'负一楼','反应物A':'HF','反应物B':'TMA','反应物C':'O3','温度/°C':'300','压力/Pa':'24','载气/sccm':'20',
            'A_Pulse/ms':'1000','A_ΔP/Pa':'70–100','A_Purge/s':'40','A_Wait/s':'0',
            'B_Pulse/ms':'400','B_ΔP/Pa':'24','B_Purge/s':'40','B_Wait/s':'0',
            'C_Pulse/ms':'800','C_ΔP/Pa':'120','C_Purge/s':'45','C_Wait/s':'3','Cycle':'50',
            '膜厚前/nm':'105.9975','膜厚后/nm':'104.8175','均匀性/%':'38.5','结果标签':'刻蚀',
            '数据质量':'有效','用于建模':'是','备注':'batch test'}
    s.append([values.get(k) for k in HEADERS])
    buf=BytesIO();w.save(buf)
    response=client.post('/api/v1/quick/batch/preview',headers=h,
                         files={'file':('batch.xlsx',buf.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==200,response.text
    preview=response.json()['data']
    assert preview['row_count']==1 and preview['errors']==[]
    payload=preview['rows'][0]
    assert payload['external_experiment_id']=='BATCH-001' and payload['environment']['r1_temperature_c']=='300'
    assert payload['program']['groups'][0]['steps'][0]['delta_p_pa_min']=='70'
    assert [x['source_label'] for x in payload['program']['groups'][0]['steps']]==['HF','TMA','O3']
    confirmed=client.post('/api/v1/quick/batch/confirm',headers=h,
                          json={'rows':preview['rows'],'expected_sha256':preview['expected_sha256'],'confirm':True})
    assert confirmed.status_code==201,confirmed.text
    run_id=confirmed.json()['data']['run_ids'][0]
    run=client.get(f'/api/v1/quick/runs/{run_id}',headers=h).json()['data']
    assert run['external_experiment_id']=='BATCH-001' and run['external_batch_id']=='B-1'
    assert run['program']['groups'][0]['steps'][0]['source_label']=='HF'
    assert run['results'][0]['quality_status']=='approved' and run['results'][0]['use_for_model_override'] is True
    row=db.execute(select(table('quick_runs')).where(table('quick_runs').c.process_id==run_id)).mappings().one()
    assert row['external_experiment_id']=='BATCH-001' and float(row['r1_temp_c'])==300
    steps=db.execute(select(table('quick_steps')).where(table('quick_steps').c.run_id==run_id)).mappings().all()
    assert len(steps)==3 and {x['source_label'] for x in steps}=={'HF','TMA','O3'}
    # 导出主表必须把第三个源写进 C 组五列
    exported=client.get('/api/v1/quick/dataset/download?format=xlsx',headers=h)
    sheet=load_workbook(BytesIO(exported.content),data_only=True)['实验记录']
    assert [c.value for c in sheet[2]]==HEADERS
    table_rows={sheet.cell(i,2).value:{HEADERS[j-1]:sheet.cell(i,j).value for j in range(1,34)} for i in range(3,sheet.max_row+1)}
    exported_row=table_rows[run['process_code']]
    assert exported_row['反应物A']=='HF' and exported_row['反应物B']=='TMA' and exported_row['反应物C']=='O3'
    assert exported_row['C_Pulse/ms']==800 and exported_row['C_ΔP/Pa']==120 and exported_row['C_Purge/s']==45 and exported_row['C_Wait/s']==3
    duplicate=client.post('/api/v1/quick/batch/confirm',headers=h,
                          json={'rows':preview['rows'],'expected_sha256':preview['expected_sha256'],'confirm':True})
    assert duplicate.status_code==409

def test_stage3_batch_import_accepts_legacy_28col(client,world):
    """Old 28-column workbooks keep importing; missing C group stays empty, never inferred."""
    from openpyxl import Workbook
    from app.quick_dataset import HEADERS_28
    h,_=world
    w=Workbook();s=w.active;s.title='实验记录'
    s.append(['']*28);s.append(HEADERS_28)
    values={'日期':'2026-11-10','实验ID':'LEGACY-001','样品ID':'S-9','材料':'SiN','反应物A':'HF','反应物B':'TMA',
            '温度/°C':'250','A_Pulse/ms':'1000','A_Purge/s':'40','A_Wait/s':'0','B_Pulse/ms':'400',
            'B_Purge/s':'40','B_Wait/s':'0','Cycle':'20','膜厚前/nm':'50','膜厚后/nm':'48'}
    s.append([values.get(k) for k in HEADERS_28])
    buf=BytesIO();w.save(buf)
    response=client.post('/api/v1/quick/batch/preview',headers=h,
                         files={'file':('legacy28.xlsx',buf.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==200,response.text
    preview=response.json()['data']
    assert preview['row_count']==1 and preview['errors']==[]
    steps=preview['rows'][0]['program']['groups'][0]['steps']
    assert [x['source_label'] for x in steps]==['HF','TMA']
    confirmed=client.post('/api/v1/quick/batch/confirm',headers=h,
                          json={'rows':preview['rows'],'expected_sha256':preview['expected_sha256'],'confirm':True})
    assert confirmed.status_code==201,confirmed.text

def test_stage3_batch_import_own_workbook_any_layout(client,world):
    """用户自己那份记录表直接上传：表头不在第 2 行、列顺序打乱、全角/空格差异、含汇总行都要能识别。"""
    from openpyxl import Workbook
    from app.quick_dataset import HEADERS
    h,_=world
    # 打乱列顺序，并混入一个无关列「笔记」；表头用全角 ℃ 与多余空格模拟手工编辑
    order=list(reversed(HEADERS))+['笔记']
    messy={'温度/°C':'温度/℃','A_Pulse/ms':'A_Pulse / ms','B_Pulse/ms':'B_Pulse  /  ms'}
    header=[messy.get(k,k) for k in order]
    values={'日期':'2026-11-09','实验ID':'OWN-001','样品ID':'S-3','材料':'SiN','设备/腔体':'负一楼',
            '反应物A':'HF','反应物B':'TMA','反应物C':'O3','温度/°C':'280','压力/Pa':'22','载气/sccm':'20',
            'A_Pulse/ms':'110','A_ΔP/Pa':'70–100','A_Purge/s':'35','A_Wait/s':'1',
            'B_Pulse/ms':'800','B_ΔP/Pa':'150','B_Purge/s':'40','B_Wait/s':'2',
            'C_Pulse/ms':'1500','C_ΔP/Pa':'200','C_Purge/s':'35','C_Wait/s':'3','Cycle':'100',
            '膜厚前/nm':'60','膜厚后/nm':'57','均匀性/%':'5.2','数据质量':'有效','用于建模':'否','备注':'原表直传'}
    w=Workbook();s=w.active;s.title='我的记录'   # 工作表名也不是「实验记录」
    s.append(['类别行']+['']*(len(order)-1))
    s.append(['说明行：以下为实验记录']+['']*(len(order)-1))
    s.append(header)
    s.append([values.get(k) for k in order])
    s.append(['合计','','','','','','','','','','','','','','','','','','','','','','','','','','','','','','','',''])
    buf=BytesIO();w.save(buf)
    response=client.post('/api/v1/quick/batch/preview',headers=h,
                         files={'file':('own-record.xlsx',buf.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==200,response.text
    preview=response.json()['data']
    assert preview['sheet']=='我的记录' and preview['header_row']==3
    assert preview['row_count']==1 and preview['errors']==[] and len(preview['skipped'])==1
    row=preview['rows'][0]
    assert row['environment']['r1_temperature_c']=='280' and row['environment']['chamber_pressure_pa']=='22'
    steps=row['program']['groups'][0]['steps']
    assert [x['source_label'] for x in steps]==['HF','TMA','O3']
    assert steps[0]['delta_p_pa_min']=='70' and steps[0]['delta_p_pa_max']=='100' and steps[2]['pulse_ms']=='1500'
    confirmed=client.post('/api/v1/quick/batch/confirm',headers=h,
                          json={'rows':preview['rows'],'expected_sha256':preview['expected_sha256'],'confirm':True})
    assert confirmed.status_code==201,confirmed.text
    assert confirmed.json()['data']['count']==1

def test_stage2_field_coverage_roundtrip(client,actors,world,db):
    """Excel-facing fields survive a real store/present roundtrip; DeltaP range is validated."""
    h,body=world
    b=body()
    b.update(external_experiment_id='AL-SINGLE-5号片-0050',external_batch_id='AL-SINGLE')
    b['environment'].update(process_type='Thermal ALE',rf_icp_power_w='0',bias_power_w='0',r2_temperature_c='175')
    b['program']['groups'][0]['steps'][0].update(delta_p_pa_min='70',delta_p_pa_max='100')
    b['results'][0].update(result_label='刻蚀',use_for_model_override=True)
    run=create(client,h,b)
    assert run['external_experiment_id']=='AL-SINGLE-5号片-0050'
    assert run['external_batch_id']=='AL-SINGLE'
    assert run['environment']['process_type']=='Thermal ALE'
    assert run['environment']['rf_icp_power_w']=='0'
    assert run['environment']['bias_power_w']=='0'
    assert run['environment']['r2_temperature_c']=='175'
    step=run['program']['groups'][0]['steps'][0]
    assert step['delta_p_pa'] is None and step['delta_p_pa_min']=='70' and step['delta_p_pa_max']=='100'
    assert run['results'][0]['result_label']=='刻蚀'
    assert run['results'][0]['use_for_model_override'] is True
    row=db.execute(select(table('quick_runs')).where(table('quick_runs').c.process_id==run['run_id'])).mappings().one()
    assert row['payload']['external_experiment_id']=='AL-SINGLE-5号片-0050'
    assert row['payload']['program']['groups'][0]['steps'][0]['delta_p_pa_min']=='70'
    assert row['external_experiment_id']=='AL-SINGLE-5号片-0050' and row['external_batch_id']=='AL-SINGLE'
    assert row['process_type']=='Thermal ALE' and float(row['r1_temp_c'])==100
    steps=db.execute(select(table('quick_steps')).where(table('quick_steps').c.run_id==run['run_id'])).mappings().all()
    assert len(steps)==1 and float(steps[0]['delta_p_pa_min'])==70 and float(steps[0]['delta_p_pa_max'])==100
    results=db.execute(select(table('quick_results')).where(table('quick_results').c.run_id==run['run_id'])).mappings().all()
    assert len(results)==1 and results[0]['result_label']=='刻蚀' and bool(results[0]['use_for_model_override'])
    b2=body(2);b2['program']['groups'][0]['steps'][0]['delta_p_pa']='24'
    run2=create(client,h,b2)
    assert run2['program']['groups'][0]['steps'][0]['delta_p_pa']=='24'
    count=db.scalar(select(func.count()).select_from(table('processes')))
    for bad in [dict(delta_p_pa='24',delta_p_pa_min='70',delta_p_pa_max='100'),dict(delta_p_pa_min='100'),dict(delta_p_pa_min='100',delta_p_pa_max='70')]:
        b3=body(3);b3['program']['groups'][0]['steps'][0].update(bad)
        assert client.post('/api/v1/quick/runs',headers=h,json=b3).status_code==422
    assert db.scalar(select(func.count()).select_from(table('processes')))==count
