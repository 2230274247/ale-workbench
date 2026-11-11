"""Core repair acceptance on an explicitly isolated *_test DB only."""
import os
import uuid

import pytest
from sqlalchemy import select

from app.db import table
from test_sample_experiment_links import make_batch, make_sample, make_process, link, measurement
from test_phase3_imports import originals, workbook, preview

pytestmark = pytest.mark.skipif(not os.getenv('ALE_DB_NAME', '').endswith('_test'), reason='Independent test DB required')


def test_execution_business_code_edit_preserves_scientific_history(client, actors, db):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    pid = make_process(db, actors, bid, 500)
    link(db, pid, sid, 100)
    mid = measurement(db, pid, sid, '10.5')
    code = 'EX-EDIT-' + uuid.uuid4().hex[:8]
    headers = actors['operator']['headers']
    response = client.patch(f'/api/v1/processes/{pid}', headers=headers,
                            json={'process_code': code, 'expected_row_version': 1})
    assert response.status_code == 200, response.text
    assert response.json()['data']['process_code'] == code
    assert db.scalar(select(table('measurements').c.process_id).where(table('measurements').c.measurement_id == mid)) == pid
    audit = table('audit_log')
    assert db.scalar(select(audit.c.audit_id).where(audit.c.entity_type == 'process', audit.c.entity_id == pid, audit.c.field_name == 'process_code'))
    assert client.patch(f'/api/v1/processes/{pid}', headers=headers, json={'full_ale_cycles': 900}).status_code == 409
    assert client.patch(f'/api/v1/processes/{pid}', headers=actors['other']['headers'], json={'process_code': 'STOLEN'}).status_code == 404
    other = make_process(db, actors, bid)
    assert client.patch(f'/api/v1/processes/{other}', headers=headers, json={'process_code': code}).status_code == 409
    assert client.patch(f'/api/v1/processes/{pid}', headers=headers, json={'process_code': 'CHANGED', 'expected_row_version': 1}).status_code == 409


def test_sample_creation_receipt_retries_keep_ids_and_reject_changed_intent(client, actors, db):
    bid=make_batch(db,actors)
    headers=actors['operator']['headers']
    key=uuid.uuid4().hex
    body={'request_key':key,'items':[{'sample_code':'RECEIPT-'+uuid.uuid4().hex[:10]}]}
    path=f'/api/v1/batches/{bid}/samples/batch'
    first=client.post(path,headers=headers,json=body)
    assert first.status_code==201,first.text
    repeated=client.post(path,headers=headers,json=body)
    assert repeated.status_code==201 and repeated.json()['data']==first.json()['data']
    sid=first.json()['data']['created'][0]['sample_id']
    renamed='AFTER-RECEIPT-'+uuid.uuid4().hex[:10]
    assert client.patch(f'/api/v1/samples/{sid}',headers=headers,json={'sample_code':renamed}).status_code==200
    again=client.post(path,headers=headers,json=body)
    assert again.status_code==201 and again.json()['data']['created'][0]['sample_id']==sid
    assert again.json()['data']['created'][0]['sample_code']==renamed
    assert client.post(path,headers=headers,json={**body,'items':[{'sample_code':'DIFFERENT'}]}).status_code==409


def import_pair(client, actors, db, *, different_model=False):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    pid = make_process(db, actors, bid, 500)
    link(db, pid, sid, 100)
    # Explicit physical participation, distinct from binding alone.
    from test_sample_experiment_links import event
    event(db,pid,sid,'load');event(db,pid,sid,'unload')
    model = table('optical_models')
    models = [db.execute(model.insert().values(model_code='CR-' + uuid.uuid4().hex[:12], model_name='Test optical model')).inserted_primary_key[0] for _ in range(2 if different_model else 1)]
    job = preview(client, actors, [('1.xlsx', workbook(('10', '11', '12'))), ('1-O3 Exposure 10-HF-TMA 50 cycles.xlsx', workbook(('9', '10', '11')))])
    before, after = job['items']
    choices = [dict(item_id=item['item_id'], action='import', sample_id=sid, process_id=pid,
                    stage=stage, optical_model_id=mid, confirm_units=True, confirm_associations=True)
               for item, stage, mid in [(before, 'initial', models[0]), (after, 'after_ale', models[-1])]]
    choices[1]['pair_item_id'] = before['item_id']
    body = {'expected_row_version': job['row_version'], 'items': list(reversed(choices))}
    headers = actors['operator']['headers']
    response = client.post(f"/api/v1/imports/{job['job_id']}/confirm", headers=headers, json=body)
    assert response.status_code == 200, response.text
    repeated = client.post(f"/api/v1/imports/{job['job_id']}/confirm", headers=headers, json=body)
    assert repeated.status_code == 200 and repeated.json()['data'] == response.json()['data']
    ids = {r['item_id']: r['measurement_ids'][0] for r in response.json()['data']['items']}
    return sid, pid, ids[before['item_id']], ids[after['item_id']]


def test_batch_import_auto_sequence_explicit_pair_replay_and_sample_summary(client, actors, db, originals):
    sid, pid, before, after = import_pair(client, actors, db)
    headers = actors['operator']['headers']
    detail = client.get(f'/api/v1/samples/{sid}', headers=headers)
    assert detail.status_code == 200, detail.text
    review = detail.json()['data']['research_review']
    assert len(review['measurements']) == 2
    result = review['results'][0]
    assert result['before_measurement_id'] == before
    assert result['thinning_nm'] == '1'
    assert result['epc_nm_per_cycle'] is None and '时间' in result['epc_reason']
    assert client.get(f'/api/v1/samples/{sid}', headers=actors['other']['headers']).status_code == 404
    # Dates and per-sample cycles are synthetic, written only in the rolled-back test DB.
    m, p = table('measurements'), table('processes')
    db.execute(m.update().where(m.c.measurement_id == before).values(measured_at='2026-01-01 09:00:00'))
    db.execute(m.update().where(m.c.measurement_id == after).values(measured_at='2026-01-01 12:00:00'))
    db.execute(p.update().where(p.c.process_id == pid).values(started_at='2026-01-01 10:00:00', ended_at='2026-01-01 11:00:00'))
    result = client.get(f'/api/v1/samples/{sid}', headers=headers).json()['data']['research_review']['results'][0]
    assert result['epc_nm_per_cycle'] == '0.01' and result['effective_cycles'] == 100  # not equipment 500
    ps = table('process_samples')
    db.execute(ps.update().where(ps.c.sample_id == sid).values(full_ale_cycles=None))
    result = client.get(f'/api/v1/samples/{sid}', headers=headers).json()['data']['research_review']['results'][0]
    assert result['epc_nm_per_cycle'] is None and '循环' in result['epc_reason']


def test_different_models_keep_raw_plots_but_no_apparent_delta(client, actors, db, originals):
    sid, pid, before, after = import_pair(client, actors, db, different_model=True)
    headers = actors['operator']['headers']
    sources = [{'kind': 'measurement', 'id': mid} for mid in (before, after)]
    response = client.post('/api/v1/analysis/calculate', headers=headers, json={'sources': sources})
    assert response.status_code == 200 and len(response.json()['data']['series']) == 2
    assert client.post('/api/v1/analysis/calculate', headers=headers, json={'sources': sources, 'before_index': 0, 'after_index': 1, 'confirm_pair': True}).status_code == 422
    review = client.get(f'/api/v1/samples/{sid}', headers=headers).json()['data']['research_review']
    assert len(review['measurements']) == 2
    assert review['results'][0]['thinning_nm'] is None and '模型' in review['results'][0]['reason']


def test_stage_sequence_allocation_and_numeric_hint_use_coupon_suffix(client, actors, db, originals):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    s = table('samples')
    db.execute(s.update().where(s.c.sample_id == sid).values(sample_code='S01-2'))
    job = preview(client, actors, [('2.xlsx', workbook()), ('1.xlsx', workbook())])
    assert sid in [s['sample_id'] for s in job['items'][0]['suggestions']['samples']]
    assert sid not in [s['sample_id'] for s in job['items'][1]['suggestions']['samples']]
    choices = [dict(item_id=i['item_id'], action='import', sample_id=sid, stage='initial', confirm_units=True, confirm_associations=True) for i in job['items']]
    response = client.post(f"/api/v1/imports/{job['job_id']}/confirm", headers=actors['operator']['headers'], json={'expected_row_version': job['row_version'], 'items': choices})
    assert response.status_code == 200, response.text
    assert list(db.execute(select(table('measurements').c.stage_seq).where(table('measurements').c.sample_id == sid).order_by(table('measurements').c.measurement_id)).scalars()) == [0, 1]


def test_actual_measurement_time_is_optional_and_normalized_without_upload_time(client, actors, db, originals):
    from datetime import datetime
    from app.imports import Choice, choice_dump
    sid=make_sample(db,actors,make_batch(db,actors))
    job=preview(client,actors)
    selected=dict(item_id=job['items'][0]['item_id'],action='import',sample_id=sid,stage='initial',confirm_units=True,confirm_associations=True,measured_at='2026-01-01T17:00:00+08:00')
    response=client.post(f"/api/v1/imports/{job['job_id']}/confirm",headers=actors['operator']['headers'],json={'expected_row_version':job['row_version'],'items':[selected]})
    assert response.status_code==200,response.text
    mid=response.json()['data']['items'][0]['measurement_ids'][0]
    m=table('measurements')
    assert db.scalar(select(m.c.measured_at).where(m.c.measurement_id==mid))==datetime(2026,1,1,9)
    # New optional fields must not alter the old idempotency digest when omitted.
    old=Choice(item_id=1,action='original_only')
    dumped=choice_dump(old)
    assert 'measured_at' not in dumped and 'pair_item_id' not in dumped


@pytest.mark.parametrize('fault', ['outlier', 'superseded', 'extra_run', 'negative_change'])
def test_summary_quality_interval_and_sign(client, actors, db, originals, fault):
    sid, pid, before, after = import_pair(client, actors, db)
    m, p, points = table('measurements'), table('processes'), table('measurement_points')
    db.execute(m.update().where(m.c.measurement_id == before).values(measured_at='2026-01-01 09:00:00'))
    db.execute(m.update().where(m.c.measurement_id == after).values(measured_at='2026-01-01 12:00:00'))
    db.execute(p.update().where(p.c.process_id == pid).values(started_at='2026-01-01 10:00:00', ended_at='2026-01-01 11:00:00'))
    if fault == 'outlier':
        db.execute(points.update().where(points.c.measurement_id == before).values(is_outlier=True))
    elif fault == 'superseded':
        db.execute(m.update().where(m.c.measurement_id == before).values(is_current=False))
    elif fault == 'extra_run':
        other = make_process(db, actors, make_batch(db, actors))
        link(db, other, sid, 100)
    else:
        db.execute(points.update().where(points.c.measurement_id == after).values(thickness_nm='15'))
    response = client.get(f'/api/v1/samples/{sid}', headers=actors['operator']['headers'])
    assert response.status_code == 200, response.text
    result = response.json()['data']['research_review']['results'][0]
    if fault == 'negative_change':
        assert result['thinning_nm'] == '-4' and result['epc_nm_per_cycle'] == '-0.04'
    elif fault == 'extra_run':
        assert result['epc_nm_per_cycle'] is None and '其他' in result['epc_reason']
    else:
        assert result['thinning_nm'] is None and result['reason']
