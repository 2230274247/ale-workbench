"""Actual source catalogs and recipe labels, isolated MySQL with transaction rollback."""
from sqlalchemy import select,func
from app.db import table
from test_quick_v22 import world,create,editable


def test_source_catalog_validation_ownership_and_deduplication(client,actors,db):
    path='/api/v1/quick/sources';h=actors['operator']['headers']
    assert client.get(path).status_code==401
    assert client.post(path,json={'canonical_name':'HF'}).status_code==401
    assert client.post(path,headers=actors['viewer']['headers'],json={'canonical_name':'HF'}).status_code==403
    for name in ['   ','x\ny','x'*129]:
        assert client.post(path,headers=h,json={'canonical_name':name}).status_code==422
    first=client.post(path,headers=h,json={'canonical_name':' HF '});assert first.status_code==201
    same=client.post(path,headers=h,json={'canonical_name':'HF'}).json()['data']
    assert same['source_id']==first.json()['data']['source_id'] and same['canonical_name']=='HF'
    assert client.post(path,headers=h,json={'canonical_name':'TMA'}).status_code==201
    mine=client.get(path,headers=h).json()['data'];assert [r['canonical_name'] for r in mine]==['HF','TMA']
    assert client.get(path,headers=actors['other']['headers']).json()['data']==[]
    assert client.get(path,headers=actors['admin']['headers']).json()['data']==[]
    assert db.scalar(select(func.count()).select_from(table('quick_sources')).where(table('quick_sources').c.owner_user_id==actors['operator']['user']['user_id']))==2


def test_real_source_labels_survive_save_and_legacy_channels_are_not_rewritten(client,world):
    h,body=world;b=body();b['program']['groups'][0]['steps']=[{'source_label':'HF','pulse_ms':'15'},{'source_label':'TMA','pulse_ms':'23','wait_s':'0'},{'source_label':'PL1','purge_s':'200'}]
    run=create(client,h,b);read=client.get(f'/api/v1/quick/runs/{run["run_id"]}',headers=h).json()['data']
    assert [s['source_label'] for s in read['program']['groups'][0]['steps']]==['HF','TMA','PL1']
    changed=editable(read);changed['note']='Retain exact user-labelled sources'
    saved=client.put(f'/api/v1/quick/runs/{run["run_id"]}',headers=h,json=changed);assert saved.status_code==200
    assert saved.json()['data']['program']==read['program']
