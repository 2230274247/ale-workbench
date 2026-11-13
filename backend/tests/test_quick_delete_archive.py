"""Hard delete, archive/restore and batch operations for V2.2 quick runs.

Archive is the reversible default: it keeps every row, revision and original and
only clears the active namespace. Delete removes the run and its backing process
row atomically and is blocked when the run begins a continuous sequence.
"""
import hashlib
import json
import uuid
import pytest
from sqlalchemy import select, func
from app.db import table

pytestmark = pytest.mark.skipif(
    not __import__('os').environ.get('ALE_DB_NAME', '').endswith('_test'),
    reason='isolated database only')


@pytest.fixture
def world(client, actors):
    headers = actors['operator']['headers']
    mid = client.post('/api/v1/quick/materials', headers=headers,
                      json={'canonical_name': 'SiO2'}).json()['data']['material_id']

    def body(n=1):
        return dict(experiment_date='2026-11-13', daily_no=n, material_id=mid, state='recorded',
                    external_experiment_id='EXP-%d' % n,
                    idempotency_key=str(uuid.uuid4()),
                    program={'outer_cycles': 1, 'groups': [{'code': 'A', 'repeat_count': 175,
                             'steps': [{'source_label': 'HF', 'pulse_ms': '1000', 'purge_s': '200', 'wait_s': '0'}]}]},
                    environment={'r1_temperature_c': '175', 'n2_flow_sccm': '0'},
                    results=[{'alias': '样品1', 'effective_cycles': 175,
                              'thickness_before_nm': '107.06', 'thickness_after_nm': '106.53',
                              'before_origin': 'measured', 'data_nature': 'real_experiment',
                              'quality_status': 'approved'}])
    return headers, body


def create(client, h, b):
    r = client.post('/api/v1/quick/runs', headers=h, json=b)
    assert r.status_code == 201, r.text
    return r.json()['data']


def test_archive_hides_default_list_and_restores(client, world):
    h, body = world
    run = create(client, h, body())
    id = run['run_id']
    assert run['archived'] is False
    assert client.get('/api/v1/quick/runs', headers=h).json()['data']['total'] == 1
    assert client.post('/api/v1/quick/runs/%d/archive' % id, headers=h).status_code == 200
    assert client.get('/api/v1/quick/runs/%d' % id, headers=h).json()['data']['archived'] is True
    assert client.get('/api/v1/quick/runs', headers=h).json()['data']['total'] == 0
    assert client.get('/api/v1/quick/runs', headers=h, params={'archived': 'yes'}).json()['data']['total'] == 1
    # idempotent
    assert client.post('/api/v1/quick/runs/%d/archive' % id, headers=h).status_code == 200
    # restore brings it back
    assert client.post('/api/v1/quick/runs/%d/restore' % id, headers=h).status_code == 200
    assert client.get('/api/v1/quick/runs', headers=h).json()['data']['total'] == 1
    assert client.get('/api/v1/quick/runs/%d' % id, headers=h).json()['data']['archived'] is False


def test_delete_removes_all_rows_and_process(client, db, world):
    h, body = world
    run = create(client, h, body())
    id = run['run_id']
    before = db.scalar(select(func.count()).select_from(table('processes')))
    assert client.delete('/api/v1/quick/runs/%d' % id, headers=h).status_code == 200
    assert client.get('/api/v1/quick/runs/%d' % id, headers=h).status_code == 404
    assert db.scalar(select(func.count()).select_from(table('quick_runs')).where(table('quick_runs').c.process_id == id)) == 0
    assert db.scalar(select(func.count()).select_from(table('quick_revisions')).where(table('quick_revisions').c.process_id == id)) == 0
    assert db.scalar(select(func.count()).select_from(table('processes'))) == before - 1
    # deleting twice is a clean 404
    assert client.delete('/api/v1/quick/runs/%d' % id, headers=h).status_code == 404


def test_delete_blocks_sequence_head_allows_tail(client, world):
    h, body = world
    a = create(client, h, body(1))
    b = body(2)
    b['previous_run_id'] = a['run_id']
    b['external_experiment_id'] = 'EXP-2'
    b['results'][0].update(thickness_before_nm='106.53', thickness_after_nm='106.0',
                           before_origin='carried_forward', carried_from_result_id=a['results'][0]['result_id'])
    second = create(client, h, b)
    assert client.delete('/api/v1/quick/runs/%d' % a['run_id'], headers=h).status_code == 409
    assert client.delete('/api/v1/quick/runs/%d' % second['run_id'], headers=h).status_code == 200
    assert client.delete('/api/v1/quick/runs/%d' % a['run_id'], headers=h).status_code == 200


def test_batch_archive_and_delete(client, world):
    h, body = world
    ids = [create(client, h, body(n))['run_id'] for n in (1, 2, 3)]
    r = client.post('/api/v1/quick/runs/batch-archive', headers=h, json={'run_ids': ids})
    assert r.status_code == 200 and r.json()['data']['count'] == 3
    assert client.get('/api/v1/quick/runs', headers=h).json()['data']['total'] == 0
    assert client.get('/api/v1/quick/runs', headers=h, params={'archived': 'yes'}).json()['data']['total'] == 3
    r = client.post('/api/v1/quick/runs/batch-delete', headers=h, json={'run_ids': ids})
    assert r.status_code == 200 and r.json()['data']['count'] == 3
    assert client.get('/api/v1/quick/runs', headers=h, params={'archived': 'yes'}).json()['data']['total'] == 0
    for i in ids:
        assert client.get('/api/v1/quick/runs/%d' % i, headers=h).status_code == 404


def test_batch_delete_atomic_on_sequence_head(client, world):
    h, body = world
    a = create(client, h, body(1))
    b = body(2)
    b['previous_run_id'] = a['run_id']
    b['external_experiment_id'] = 'EXP-2'
    second = create(client, h, b)
    r = client.post('/api/v1/quick/runs/batch-delete', headers=h, json={'run_ids': [a['run_id'], second['run_id']]})
    assert r.status_code == 409
    # nothing was removed because the whole request rolled back
    assert client.get('/api/v1/quick/runs/%d' % a['run_id'], headers=h).status_code == 200
    assert client.get('/api/v1/quick/runs/%d' % second['run_id'], headers=h).status_code == 200


def test_authorization_cannot_touch_other_users_records(client, actors, world):
    h, body = world
    run = create(client, h, body())
    id = run['run_id']
    assert client.delete('/api/v1/quick/runs/%d' % id, headers=actors['other']['headers']).status_code == 404
    assert client.post('/api/v1/quick/runs/%d/archive' % id, headers=actors['other']['headers']).status_code == 404
    assert client.post('/api/v1/quick/runs/batch-delete', headers=actors['other']['headers'], json={'run_ids': [id]}).status_code == 404
    assert client.delete('/api/v1/quick/runs/%d' % id, headers=actors['viewer']['headers']).status_code == 403


def test_archive_frees_external_id_for_reimport(client, world):
    """The reported pain point: import once, archive, re-import the same IDs."""
    h, body = world
    run = create(client, h, body())

    def confirm_row():
        row = body()
        row.pop('idempotency_key', None)
        row['_line'] = 1
        rows = [row]
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return client.post('/api/v1/quick/batch/confirm', headers=h,
                           json={'rows': rows, 'expected_sha256': digest, 'confirm': True})

    assert confirm_row().status_code == 409
    assert client.post('/api/v1/quick/runs/%d/archive' % run['run_id'], headers=h).status_code == 200
    assert confirm_row().status_code == 201
