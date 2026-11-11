"""Product relationships and conservative chemistry totals; rollback-only DB."""
import uuid,hashlib,os
import pytest
from sqlalchemy import select
from app.db import table
from test_phase3_imports import originals
from test_sample_experiment_links import make_batch,make_sample,make_process,link,event

pytestmark=pytest.mark.skipif(not os.getenv('ALE_DB_NAME','').endswith('_test'),reason='Independent test DB required')

def system(db,actors,name):
    return db.execute(table('chemistry_systems').insert().values(system_code='CP-'+uuid.uuid4().hex[:10],system_name=name,owner_user_id=actors['operator']['user']['user_id'])).inserted_primary_key[0]

def test_different_and_unknown_systems_never_receive_one_total(client,actors,db):
    bid=make_batch(db,actors);sid=make_sample(db,actors,bid)
    systems=[system(db,actors,'HF / TMA'),system(db,actors,'另一体系'),None,None]
    pids=[]
    for i,chem in enumerate(systems):
        pid=make_process(db,actors,bid,500);pids.append(pid);link(db,pid,sid,(i+1)*100)
        event(db,pid,sid,'load');event(db,pid,sid,'unload')
        db.execute(table('processes').update().where(table('processes').c.process_id==pid).values(chemistry_system_id=chem))
    d=client.get(f'/api/v1/samples/{sid}',headers=actors['operator']['headers']).json()['data']
    summary=d['participation_summary']
    assert summary['recorded_cycles'] is None
    assert [g['recorded_cycles'] for g in summary['cycle_groups']]==[100,200,300,400]
    # Only explicitly identical systems and process modes may accumulate.
    db.execute(table('processes').update().where(table('processes').c.process_id.in_(pids)).values(chemistry_system_id=systems[0]))
    d=client.get(f'/api/v1/samples/{sid}',headers=actors['operator']['headers']).json()['data']
    assert d['participation_summary']['recorded_cycles']==1000
    assert len(d['participation_summary']['cycle_groups'])==1
    assert client.get(f'/api/v1/samples/{sid}',headers=actors['other']['headers']).status_code==404

def test_imported_pairs_appear_in_execution_and_plan_without_second_entry(client,actors,db,originals):
    from test_codex_core_repair import import_pair
    sid,pid,before,after=import_pair(client,actors,db)
    headers=actors['operator']['headers'];m,p=table('measurements'),table('processes')
    db.execute(m.update().where(m.c.measurement_id==before).values(measured_at='2026-01-01 09:00:00'))
    db.execute(m.update().where(m.c.measurement_id==after).values(measured_at='2026-01-01 12:00:00'))
    pl=table('experiment_plans');plan=db.execute(pl.insert().values(plan_code='CP-'+uuid.uuid4().hex[:10],title='氮化硅表观变化研究',objective='核对处理前后膜厚',owner_user_id=actors['operator']['user']['user_id'])).inserted_primary_key[0]
    db.execute(p.update().where(p.c.process_id==pid).values(plan_id=plan,started_at='2026-01-01 10:00:00',ended_at='2026-01-01 11:00:00'))
    for path in (f'/processes/{pid}',f'/plans/{plan}'):
        data=client.get('/api/v1'+path,headers=headers).json()['data']
        run=data['processes'][0] if 'processes' in data else data
        review=run['samples'][0]['research_review']
        assert {r['measurement_id'] for r in review['measurements']}=={before,after}
        result=review['results'][0]
        assert result['before_mean_nm']=='11' and result['after_mean_nm']=='10'
        assert result['thinning_nm']=='1' and result['epc_nm_per_cycle']=='0.01'
        assert result['sources'] and result['effective_cycles']==100
        assert client.get('/api/v1'+path,headers=actors['other']['headers']).status_code==404
    named=client.get(f'/api/v1/measurements/{after}',headers=headers).json()['data']
    assert named['sample_code'] and named['process_code'] and named['plan_title']=='氮化硅表观变化研究'
    found=client.get('/api/v1/processes',headers=headers,params={'keyword':'氮化硅表观变化研究'}).json()['data']
    assert found[0]['process_id']==pid and found[0]['plan_title']=='氮化硅表观变化研究'
    assert client.get('/api/v1/processes',headers=actors['other']['headers'],params={'keyword':'氮化硅表观变化研究'}).json()['data']==[]

@pytest.mark.parametrize('count',[4,81])
def test_four_points_and_mapping_keep_original_means_points_and_files(client,actors,db,originals,count):
    from test_phase3_imports import preview,workbook
    bid=make_batch(db,actors);sid=make_sample(db,actors,bid);pid=make_process(db,actors,bid);link(db,pid,sid,None)
    content=workbook(tuple(str(i) for i in range(1,count+1)))
    job=preview(client,actors,[('mapping.xlsx',content)]);item=job['items'][0];headers=actors['operator']['headers']
    response=client.post(f"/api/v1/imports/{job['job_id']}/confirm",headers=headers,json={'expected_row_version':job['row_version'],'items':[{'item_id':item['item_id'],'action':'import','sample_id':sid,'process_id':pid,'stage':'initial','confirm_units':True,'confirm_associations':True}]})
    assert response.status_code==200,response.text
    detail=client.get(f'/api/v1/processes/{pid}',headers=headers).json()['data']
    measurement=detail['samples'][0]['research_review']['measurements'][0]
    assert measurement['valid_point_count']==count and measurement['point_count']==count
    original_mean=measurement['thickness_mean_nm'];mid=measurement['measurement_id']
    points=table('measurement_points');point=db.scalar(select(points.c.point_id).where(points.c.measurement_id==mid).limit(1))
    db.execute(points.update().where(points.c.point_id==point).values(is_outlier=True))
    measurement=client.get(f'/api/v1/samples/{sid}',headers=headers).json()['data']['research_review']['measurements'][0]
    assert measurement['valid_point_count']==count-1 and measurement['thickness_mean_nm']==original_mean
    source=db.execute(select(table('source_files')).where(table('source_files').c.file_id==measurement['source_file_id'])).mappings().one()
    assert source['file_sha256']==hashlib.sha256(content).hexdigest()
    downloaded=client.get(f"/api/v1/source-files/{source['file_id']}/content",headers=headers)
    assert downloaded.status_code==200 and downloaded.content==content
