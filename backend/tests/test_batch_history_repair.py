"""Batch identity and evidence-based sample history; isolated test DB only."""
import os
import uuid
import pytest
from sqlalchemy import select
from app.db import table
from test_sample_experiment_links import make_batch, make_sample, make_process, link, event
from test_phase3_imports import originals

pytestmark=pytest.mark.skipif(not os.getenv('ALE_DB_NAME','').endswith('_test'),reason='Independent test DB required')


def test_archived_code_conflict_is_explained_and_unused_rename_is_audited(client,actors,db):
    bid=make_batch(db,actors)
    b=table('batches');code=db.scalar(select(b.c.batch_code).where(b.c.batch_id==bid))
    h=actors['operator']['headers']
    assert client.post(f'/api/v1/batches/{bid}/archive',headers=h,json={'expected_row_version':1}).status_code==200
    conflict=client.post('/api/v1/batches',headers=h,json={'batch_code':code,'batch_name':'new'})
    assert conflict.status_code==409 and '归档' in conflict.json()['message']
    status=client.get('/api/v1/batches/code-status',headers=h,params={'code':code})
    assert status.status_code==200,status.text
    data=status.json()['data'];assert data['existing']['batch_id']==bid and data['can_rename']
    assert 'restore' in data['lifecycle']['actions']
    renamed=code+'-OLD'
    r=client.patch(f'/api/v1/batches/{bid}/code',headers=h,json={'batch_code':renamed,'expected_row_version':2,'reason':'纠正未使用误建编号'})
    assert r.status_code==200,r.text
    assert r.json()['data']['batch_id']==bid and r.json()['data']['archived_at']
    assert client.post('/api/v1/batches',headers=h,json={'batch_code':code,'batch_name':'new'}).status_code==201
    a=table('audit_log')
    assert db.scalar(select(a.c.audit_id).where(a.c.entity_type=='batch',a.c.entity_id==bid,a.c.field_name=='batch_code'))


@pytest.mark.parametrize('caller_purpose,owner_purpose',[('testing','research'),('research','testing')])
def test_cross_account_code_is_reserved_without_private_metadata(client,actors,db,caller_purpose,owner_purpose):
    bid=make_batch(db,actors,'other');b=table('batches')
    code=db.scalar(select(b.c.batch_code).where(b.c.batch_id==bid));h=actors['operator']['headers']
    db.execute(table('users').update().where(table('users').c.user_id==actors['operator']['user']['user_id']).values(account_purpose=caller_purpose))
    db.execute(table('users').update().where(table('users').c.user_id==actors['other']['user']['user_id']).values(account_purpose=owner_purpose))
    r=client.get('/api/v1/batches/code-status',headers=h,params={'code':code})
    assert r.status_code==200,r.text
    d=r.json()['data'];assert not d['available'] and d['restricted']
    assert 'existing' not in d and 'lifecycle' not in d and str(bid) not in str(d)
    assert client.patch(f'/api/v1/batches/{bid}/code',headers=h,json={'batch_code':'PRIVATE','expected_row_version':1,'reason':'test'}).status_code==404
    r=client.post('/api/v1/batches',headers=h,json={'batch_code':code,'batch_name':'new'})
    assert r.status_code==409 and 'SLB' not in r.json()['message']


def test_used_batch_code_cannot_change_and_empty_cleanup_uses_lifecycle(client,actors,db):
    bid=make_batch(db,actors);make_sample(db,actors,bid)
    h=actors['operator']['headers']
    r=client.patch(f'/api/v1/batches/{bid}/code',headers=h,json={'batch_code':'NEW-'+uuid.uuid4().hex[:8],'expected_row_version':1,'reason':'test'})
    assert r.status_code==409,r.text
    empty=make_batch(db,actors)
    impact=client.get(f'/api/v1/lifecycle/batches/{empty}/impact',headers=actors['admin']['headers']).json()['data']
    assert impact['delete_permitted'] and 'delete' in impact['actions']
    assert client.delete(f'/api/v1/batches/{empty}',headers=actors['admin']['headers']).status_code==204


def test_draft_bindings_are_not_confirmed_processing_or_cumulative_cycles(client,actors,db):
    bid=make_batch(db,actors);sid=make_sample(db,actors,bid);pid=make_process(db,actors,bid,500);link(db,pid,sid,100)
    h=actors['operator']['headers'];s=client.get(f'/api/v1/samples/{sid}',headers=h).json()['data']
    assert s['experiments'][0]['execution_evidence']=='not_confirmed'
    assert not s['experiments'][0]['cycles_confirmed']
    assert s['participation_summary']['recorded_participations']==0
    # A future timestamp is not proof that the execution already happened.
    p=table('processes');db.execute(p.update().where(p.c.process_id==pid).values(started_at='2099-01-01 00:00:00'))
    s=client.get(f'/api/v1/samples/{sid}',headers=h).json()['data']
    assert s['participation_summary']['recorded_cycles']==0
    db.execute(p.update().where(p.c.process_id==pid).values(started_at='2026-01-01 00:00:00'))
    s=client.get(f'/api/v1/samples/{sid}',headers=h).json()['data']
    assert s['participation_summary']['recorded_cycles']==0  # execution alone does not prove sample loading
    event(db,pid,sid,'load');event(db,pid,sid,'unload')
    s=client.get(f'/api/v1/samples/{sid}',headers=h).json()['data']
    assert s['experiments'][0]['cycles_confirmed'] and s['participation_summary']['recorded_cycles']==100


def test_void_unknown_cycles_and_latest_append_order_are_preserved(client,actors,db):
    bid=make_batch(db,actors);sid=make_sample(db,actors,bid)
    first=make_process(db,actors,bid,500);second=make_process(db,actors,bid,500)
    link(db,first,sid,100);link(db,second,sid,None)
    for pid in (first,second):
        event(db,pid,sid,'load');event(db,pid,sid,'unload')
    event(db,first,sid,'load')
    p=table('processes');db.execute(p.update().where(p.c.process_id==first).values(voided_at='2026-01-01 00:00:00',void_reason='隔离测试作废',voided_by_user_id=actors['operator']['user']['user_id']))
    h=actors['operator']['headers'];s=client.get(f'/api/v1/samples/{sid}',headers=h).json()['data']
    assert s['experiments'][0]['participation_status']=='loaded'
    assert s['experiments'][0]['execution_evidence']=='voided'
    assert s['experiments'][1]['full_ale_cycles'] is None
    assert s['participation_summary']['recorded_cycles']==0
    assert s['participation_summary']['missing_participations']==2
    assert client.get(f'/api/v1/samples/{sid}',headers=actors['other']['headers']).status_code==404
    assert client.patch(f'/api/v1/batches/{bid}/code',headers=actors['viewer']['headers'],json={'batch_code':'FORBIDDEN','expected_row_version':1,'reason':'test'}).status_code==403


def test_future_sample_events_do_not_confirm_cycles_or_apparent_epc(client,actors,db,originals):
    from test_codex_core_repair import import_pair
    sid,pid,before,after=import_pair(client,actors,db)
    m,p,t=table('measurements'),table('processes'),table('sample_transitions')
    db.execute(m.update().where(m.c.measurement_id==before).values(measured_at='2026-01-01 09:00:00'))
    db.execute(m.update().where(m.c.measurement_id==after).values(measured_at='2026-01-01 12:00:00'))
    db.execute(p.update().where(p.c.process_id==pid).values(started_at='2026-01-01 10:00:00',ended_at='2026-01-01 11:00:00'))
    db.execute(t.update().where(t.c.sample_id==sid).values(event_at='2099-01-01 00:00:00'))
    data=client.get(f'/api/v1/samples/{sid}',headers=actors['operator']['headers']).json()['data']
    assert data['participation_summary']['recorded_cycles']==0
    result=data['research_review']['results'][0]
    assert result['thinning_nm']=='1' and result['epc_nm_per_cycle'] is None
    assert '参与依据' in result['epc_reason']
