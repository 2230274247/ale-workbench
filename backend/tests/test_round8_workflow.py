"""Wizard facts, inheritance, pairing and permissions against rollback-only MySQL."""
import uuid
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, text
from sqlalchemy import select
from test_phase4_browser import db, client, database_manifest, originals_manifest
from app.db import table


def test_workflow_resume_permissions_and_pairing(client, actors, db):
    h=actors['operator']['headers']
    def post(path,body):
        r=client.post('/api/v1'+path,headers=h,json=body)
        assert r.status_code==201,r.text
        return r.json()['data']
    def state(**query):
        r=client.get('/api/v1/workflow/state',headers=h,params=query)
        assert r.status_code==200,r.text
        return r.json()['data']
    tag=uuid.uuid4().hex
    batch=post('/batches',{'batch_code':'WB-'+tag,'batch_name':'Wizard rollback batch'})
    plan=post('/workflow/plans',{'title':'Resume experiment','objective':'Test saved goal','batch_id':batch['batch_id']})
    assert plan['plan_code'].startswith('PL-')
    snap={'step_type':'HF','temperature':{'value':'100','unit':'°C'},'groups':[{'name':'脉冲','fields':[{'name':'时长','value':'12','unit':'ms'}]}]}
    grid={'expected_row_version':plan['row_version'],'steps':[{'key':'one','step_id':None,'step_kind':'HF','step_name':'HF pulse','plan_step_id':None,'parameter_snapshot':snap}],'process_flow':{'version':1,'total_cycles':20,'children':[{'kind':'step','id':'one','step_id':'one','children':[]}]}}
    r=client.put(f"/api/v1/plans/{plan['plan_id']}/process-grid",headers=h,json=grid)
    assert r.status_code==200,r.text
    run=post('/workflow/processes',{'plan_id':plan['plan_id'],'process_mode':'other'})
    second=post('/workflow/processes',{'plan_id':plan['plan_id'],'process_mode':'other'})
    assert second['process_id']!=run['process_id']
    assert not run['is_independent_run'] and run['log_status']=='unknown'
    assert run['steps'][0]['plan_step_id']==r.json()['data']['steps'][0]['step_id']
    assert run['steps'][0]['parameter_snapshot']['temperature']['value'] is None
    assert run['steps'][0]['parameter_snapshot']['groups'][0]['fields'][0]=={'name':'时长','value':None,'unit':'ms'}
    assert run['process_flow']['total_cycles'] is None
    resumed=state(process_id=run['process_id'])
    assert [s['status'] for s in resumed['stages']]==['saved','saved','saved','empty','empty','empty','empty']
    assert state(process_id=run['process_id'])==resumed
    samples=post(f"/batches/{batch['batch_id']}/samples/batch",{'items':[{'sample_code':f'WS-{tag}-{i}'} for i in range(2)]})['created']
    rr=client.post(f"/api/v1/processes/{run['process_id']}/samples/batch",headers=h,json={'sample_ids':[s['sample_id'] for s in samples]})
    assert rr.status_code==201,rr.text
    assert state(process_id=run['process_id'])['stages'][3]['status']=='saved'
    rr=client.post(f"/api/v1/processes/{second['process_id']}/samples/batch",headers=h,json={'sample_ids':[s['sample_id'] for s in samples]})
    assert rr.status_code==201,rr.text
    assert state(process_id=second['process_id'])['stages'][3]['status']=='saved'
    # Same sample, other run: its measurement must never complete this run's stage.
    m=table('measurements')
    base={'sample_id':samples[0]['sample_id'],'stage':'final','stage_seq':1,'is_current':True,'operator_user_id':actors['operator']['user']['user_id']}
    # Use reflected defaults for all other optional measurement columns.
    db.execute(m.insert().values(**base,process_id=second['process_id'],measurement_code='WM-'+tag))
    assert state(process_id=run['process_id'])['stages'][6]['status']=='empty'
    db.execute(m.insert().values(**{**base,'stage_seq':2},process_id=run['process_id'],measurement_code='WM2-'+tag))
    assert state(process_id=run['process_id'])['stages'][6]['status']=='saved'
    hidden=client.get('/api/v1/workflow/state',params={'process_id':run['process_id']},headers=actors['other']['headers'])
    assert hidden.status_code==404
    assert client.post('/api/v1/workflow/plans',headers=actors['viewer']['headers'],json={'title':'Forbidden'}).status_code==403
    assert client.get('/api/v1/workflow/state',params={'process_id':run['process_id']},headers=actors['admin']['headers']).status_code==200
    other=post('/workflow/plans',{'title':'Other'})
    assert client.get('/api/v1/workflow/state',headers=h,params={'plan_id':other['plan_id'],'process_id':run['process_id']}).status_code==422
    independent=post('/workflow/processes',{'process_mode':'other','notes':'Independent saved goal'})
    assert independent['is_independent_run'] and independent['plan_id'] is None
    assert state(process_id=independent['process_id'])['stages'][0]['status']=='saved'
    r=client.patch(f"/api/v1/processes/{independent['process_id']}",headers=h,json={'r1_temp_c':'0','expected_row_version':independent['row_version']})
    assert r.status_code==200,r.text
    assert state(process_id=independent['process_id'])['stages'][5]['status']=='saved'
    assert client.patch(f"/api/v1/processes/{run['process_id']}",headers=h,json={'r1_temp_c':'1','expected_row_version':1}).status_code==409


def test_actual_saved_facts_include_repeats_and_legacy_values():
    from app.workflow import has_actual
    assert not has_actual({'steps': [], 'process_flow': {'total_cycles': None, 'children': []}})
    assert has_actual({'steps': [], 'process_flow': {'total_cycles': 0, 'children': []}})
    assert has_actual({'steps': [], 'process_flow': {'children': [{'kind': 'group', 'repeat': None, 'children': [{'kind': 'group', 'repeat': 2, 'children': []}]}]}})
    assert not has_actual({'steps': [{'delta_p_unit': 'Pa', 'custom_parameters': {'x': {'value': None, 'unit': 'ms'}}}]})
    assert has_actual({'steps': [{'custom_parameters': {'x': {'value': '0', 'unit': 'ms'}}}]})
    # Historical columns are not the current source when a snapshot exists.
    assert not has_actual({'steps': [{'pulse_s': 10, 'parameter_snapshot': {'temperature': {'value': None}, 'groups': []}}]})


def test_state_scopes_hidden_parent_ids_before_pairing(client, actors, db):
    from test_phase5_sample_void import call
    own = call(client, actors, 'post', '/workflow/processes', {'process_mode': 'other'}, status=201)
    hidden = client.post('/api/v1/workflow/plans', headers=actors['other']['headers'], json={'title': 'Hidden plan'}).json()['data']
    for query in ({'plan_id': hidden['plan_id']}, {'plan_id': hidden['plan_id'], 'process_id': own['process_id']}):
        response = client.get('/api/v1/workflow/state', headers=actors['operator']['headers'], params=query)
        assert response.status_code == 404, response.text
    assert client.get('/api/v1/workflow/state').status_code == 401
    for bad in ('0', '-1', 'bad'):
        assert client.get('/api/v1/workflow/state', headers=actors['operator']['headers'], params={'process_id': bad}).status_code == 422
    before = call(client, actors, 'get', f"/processes/{own['process_id']}")
    for _ in range(3):
        state = call(client, actors, 'get', f"/workflow/state?process_id={own['process_id']}")
        assert [s['status'] for s in state['stages']] == ['empty', 'saved', 'empty', 'empty', 'empty', 'empty', 'empty']
    assert call(client, actors, 'get', f"/processes/{own['process_id']}") == before


@pytest.mark.parametrize('kind,body,pk,code_key,entity', [
    ('plans', {'title': 'Lost response', 'objective': 'Exact intent'}, 'plan_id', 'plan_code', 'experiment_plan'),
    ('processes', {'process_mode': 'other', 'notes': 'Exact intent'}, 'process_id', 'process_code', 'process'),
])
def test_start_receipt_replay_and_conflicts(client, actors, db, kind, body, pk, code_key, entity):
    body = {**body, code_key: 'REC-' + uuid.uuid4().hex}
    url = '/api/v1/workflow/' + kind
    h = actors['operator']['headers']
    first = client.post(url, headers=h, json=body)
    assert first.status_code == 201, first.text
    saved = first.json()['data']
    a = table('audit_log')
    count = db.scalar(select(func.count()).select_from(a))
    # Exact request reordered in JSON, including after mutable record content changes.
    field = 'title' if kind == 'plans' else 'notes'
    changed = client.patch('/api/v1/' + kind + '/' + str(saved[pk]), headers=h,
                           json={field: 'Later edit', 'expected_row_version': saved['row_version']})
    assert changed.status_code == 200, changed.text
    count = db.scalar(select(func.count()).select_from(a))
    replay = client.post(url, headers=h, json=dict(reversed(list(body.items()))))
    assert replay.status_code == 201, replay.text
    assert replay.json()['data'][pk] == saved[pk]
    assert replay.json()['data'][field] == 'Later edit'
    assert db.scalar(select(func.count()).select_from(a)) == count
    # Receipt compares original request content, never a subset/current record.
    for extra in ({field: 'Different intent'}, {'batch_id': None}):
        mismatch = client.post(url, headers=h, json={**body, **extra})
        assert mismatch.status_code == 409, mismatch.text
    for role in ('other', 'admin'):
        hidden = client.post(url, headers=actors[role]['headers'], json=body)
        assert hidden.status_code == 409, hidden.text
        assert pk not in hidden.json().get('data', {})
    assert client.post(url, headers=actors['viewer']['headers'], json=body).status_code == 403
    assert client.post(url, json=body).status_code == 401
    # Existing generic explicit-code creation is never adopted by the wizard.
    generic = {**body, code_key: 'OLD-' + uuid.uuid4().hex}
    r = client.post('/api/v1/' + kind, headers=h, json=generic)
    assert r.status_code == 201, r.text
    assert client.post(url, headers=h, json=generic).status_code == 409
    assert client.post('/api/v1/' + kind, headers=h, json=generic).status_code == 409
    receipt = db.scalar(select(a.c.new_value).where(a.c.entity_type == entity,
        a.c.entity_id == saved[pk], a.c.field_name == 'workflow_start'))
    assert set(json.loads(receipt)) == {'version', 'fingerprint'}
    assert len(json.loads(receipt)['fingerprint']) == 64


@pytest.mark.parametrize('kind,payload,pk,code_key', [
    ('plans', {'title': 'Concurrent intent'}, 'plan_id', 'plan_code'),
    ('processes', {'process_mode': 'other'}, 'process_id', 'process_code'),
])
def test_simultaneous_start_requests(client, actors, db, kind, payload, pk, code_key):
    payload = {**payload, code_key: 'CON-' + uuid.uuid4().hex}
    barrier = threading.Barrier(2)
    def send():
        barrier.wait(timeout=5)
        return client.post('/api/v1/workflow/' + kind, headers=actors['operator']['headers'], json=payload)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: send(), range(2)))
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]
    assert results[0].json()['data'][pk] == results[1].json()['data'][pk]
    t = table('experiment_plans' if kind == 'plans' else 'processes')
    assert db.scalar(select(func.count()).select_from(t).where(t.c[code_key] == payload[code_key])) == 1


def test_legacy_inheritance_clears_values_units_and_mapping(client, actors, db):
    h = actors['operator']['headers']
    r = client.post('/api/v1/workflow/plans', headers=h, json={'title': 'Legacy structure'})
    assert r.status_code == 201, r.text
    plan = r.json()['data']
    r = client.post(f"/api/v1/plans/{plan['plan_id']}/steps", headers=h, json={
        'step_index': 1, 'step_kind': 'hf_purge', 'step_name': 'Legacy HF',
        'planned_parameters': {'pulse_s': '0.125', 'delta_p': '2.5', 'delta_p_unit': 'mTorr',
                               'actual_temp_c': '95', 'cycles': 8},
        'custom_parameters': {'dose': {'value': '7', 'unit': 'µs', 'note': 'planned only'}},
        'step_note': 'planned scientific notes'})
    assert r.status_code == 201, r.text
    step = r.json()['data']
    p = table('experiment_plans')
    db.execute(p.update().where(p.c.plan_id == plan['plan_id']).values(process_flow={
        'version': 1, 'total_cycles': 99, 'children': [{'kind': 'group', 'id': 'outer', 'name': 'Outer', 'repeat': 4,
        'children': [{'kind': 'group', 'id': 'inner', 'name': 'Inner', 'repeat': 3, 'children': [
        {'kind': 'step', 'id': 's', 'step_id': step['step_id'], 'children': []}]}]}]}))
    before = client.get(f"/api/v1/plans/{plan['plan_id']}", headers=h).json()['data']
    payload = {'process_code': 'LEG-' + uuid.uuid4().hex, 'plan_id': plan['plan_id'], 'process_mode': 'other'}
    client._transport.raise_server_exceptions = True
    r = client.post('/api/v1/workflow/processes', headers=h, json=payload)
    assert r.status_code == 201, r.text
    run = r.json()['data']; actual = run['steps'][0]
    snap = actual['parameter_snapshot']
    assert snap['step_type'] == 'Legacy HF'
    assert snap['temperature'] == {'value': None, 'unit': '°C'}
    groups = {g['name']: g['fields'] for g in snap['groups']}
    assert groups['脉冲'] == [{'name': '时长（原始字段 s）', 'value': None, 'unit': 's'}]
    assert groups['压差'] == [{'name': '压差', 'value': None, 'unit': 'mTorr'}]
    assert groups['历史自定义参数'] == [{'name': 'dose', 'value': None, 'unit': 'µs'}]
    assert all(f['value'] is None for g in snap['groups'] for f in g['fields'])
    assert actual['custom_parameters'] == {'dose': {'value': None, 'unit': 'µs', 'note': None}}
    assert actual['plan_step_id'] == step['step_id']
    assert actual['step_note'] == f"计划步骤映射：#{step['step_id']}（计划值不复制，实际值请独立填写）"
    assert all(actual[k] is None for k in ('pulse_s', 'delta_p', 'cycles', 'actual_temp_c'))
    flow = run['process_flow']
    assert flow['total_cycles'] is None
    assert flow['children'][0]['repeat'] is None
    assert flow['children'][0]['children'][0]['repeat'] is None
    assert flow['children'][0]['children'][0]['children'][0]['step_id'] == actual['step_id']
    from app.workflow import has_actual
    assert not has_actual(run)
    after = client.get(f"/api/v1/plans/{plan['plan_id']}", headers=h).json()['data']
    assert after['steps'] == before['steps'] and after['process_flow'] == before['process_flow']
    # Receipt is independent of later plan edits/inheritance expansion.
    ps = table('experiment_plan_steps')
    db.execute(ps.update().where(ps.c.step_id == step['step_id']).values(step_name='Later plan edit'))
    replay = client.post('/api/v1/workflow/processes', headers=h, json=payload)
    assert replay.status_code == 201 and replay.json()['data']['process_id'] == run['process_id']
    assert replay.json()['data']['steps'] == run['steps']


def test_runtime_workflow_operations_use_strict_canonical_contract():
    from app.main import app, canonical_contract
    app.openapi_schema = None
    runtime = app.openapi()
    for path in ('/api/v1/workflow/plans', '/api/v1/workflow/processes'):
        canonical = canonical_contract()['paths'][path]['post']
        assert runtime['paths'][path]['post'] == {**canonical, 'x-implementation-status': 'implemented'}
    # Adjacent legacy routes keep their generated runtime validation schemas.
    assert runtime['paths']['/api/v1/plans']['post']['requestBody']['content']['application/json']['schema']['$ref'].endswith('/PlanCreate')
