"""Sample↔experiment links, per-sample cycles, editable code and safe deletion.

Runs on the independent *_test database; every write is rolled back.
"""
import uuid

from sqlalchemy import select

from app.db import table


def api(client, actors, method, path, status=200, role='operator', **kwargs):
    response = getattr(client, method)('/api/v1' + path, headers=actors[role]['headers'], **kwargs)
    assert response.status_code == status, (method, path, response.status_code, response.text)
    return response.json().get('data')


def make_batch(db, actors, role='operator'):
    tag = uuid.uuid4().hex[:10]
    return db.execute(table('batches').insert().values(
        batch_code=f'SLB-{tag}', batch_name='双向关联测试批次',
        owner_user_id=actors[role]['user']['user_id'])).inserted_primary_key[0]


def make_sample(db, actors, bid, label='S', role='operator'):
    tag = uuid.uuid4().hex[:10]
    return db.execute(table('samples').insert().values(
        sample_code=f'SL-{label}-{tag}', batch_id=bid, sample_type='coupon',
        status='available', owner_user_id=actors[role]['user']['user_id'])).inserted_primary_key[0]


def make_process(db, actors, bid, equipment_cycles=None, role='operator'):
    tag = uuid.uuid4().hex[:10]
    return db.execute(table('processes').insert().values(
        process_code=f'SLP-{tag}', process_mode='other',
        operator_user_id=actors[role]['user']['user_id'], batch_id=bid,
        log_status='unknown', full_ale_cycles=equipment_cycles)).inserted_primary_key[0]


def link(db, pid, sid, cycles, position=None):
    db.execute(table('process_samples').insert().values(
        process_id=pid, sample_id=sid, full_ale_cycles=cycles,
        chamber_position=position, is_control=0))


def event(db, pid, sid, kind, step_id=None):
    db.execute(table('sample_transitions').insert().values(
        sample_id=sid, to_status='in_process' if kind == 'load' else 'available',
        event_type=kind, process_id=pid, step_id=step_id))


def measurement(db, pid, sid, mean):
    tag = uuid.uuid4().hex[:8]
    return db.execute(table('measurements').insert().values(
        measurement_code=f'SLM-{tag}', sample_id=sid, process_id=pid,
        stage='after_ale', is_current=1, thickness_mean_nm=mean)).inserted_primary_key[0]


def test_sample_code_edit_keeps_history(client, actors, db):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    pid = make_process(db, actors, bid)
    link(db, pid, sid, 100)
    measurement(db, pid, sid, '10.500')
    old = db.execute(select(table('samples').c.sample_code).where(
        table('samples').c.sample_id == sid)).scalar()
    new = 'RENAMED-' + uuid.uuid4().hex[:8]
    detail = api(client, actors, 'patch', f'/samples/{sid}',
                 json={'sample_code': new, 'expected_row_version': 1})
    assert detail['sample_code'] == new and detail['sample_id'] == sid
    loaded = api(client, actors, 'get', f'/samples/{sid}')
    assert loaded['sample_code'] == new
    assert len(loaded['experiments']) == 1 and loaded['experiments'][0]['measurement_count'] == 1
    assert loaded['experiments'][0]['process_id'] == pid
    audit = db.execute(select(table('audit_log')).where(
        table('audit_log').c.entity_type == 'sample',
        table('audit_log').c.entity_id == sid,
        table('audit_log').c.field_name == 'sample_code')).mappings().all()
    assert audit and old in audit[-1]['old_value'] and new in audit[-1]['new_value']
    # Another sample cannot take the same visible code.
    other = make_sample(db, actors, bid, 'O')
    api(client, actors, 'patch', f'/samples/{other}',
        status=409, json={'sample_code': new, 'expected_row_version': 1})


def test_same_sample_two_executions_keep_independent_cycles_and_measurements(client, actors, db):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    first = make_process(db, actors, bid, equipment_cycles=100)
    second = make_process(db, actors, bid, equipment_cycles=100)
    from test_core_product_alignment import system
    chemistry=system(db,actors,'重复执行的已确认体系')
    p=table('processes');db.execute(p.update().where(p.c.process_id.in_([first,second])).values(chemistry_system_id=chemistry))
    link(db, first, sid, 100)
    link(db, second, sid, 100)
    for pid in (first,second):
        event(db,pid,sid,'load')
        event(db,pid,sid,'unload')
    measurement(db, first, sid, '10.500')
    measurement(db, second, sid, '9.800')
    detail = api(client, actors, 'get', f'/samples/{sid}')
    assert [row['process_id'] for row in detail['experiments']] == [first, second]
    assert [row['full_ale_cycles'] for row in detail['experiments']] == [100, 100]
    assert {k:v for k,v in detail['participation_summary'].items() if k!='cycle_groups'} == {
        'recorded_cycles': 200, 'participation_count': 2,
        'recorded_participations': 2, 'missing_participations': 0, 'complete': True}
    one = api(client, actors, 'get', f'/processes/{first}')
    assert one['samples'][0]['full_ale_cycles'] == 100
    assert one['samples'][0]['cumulative_recorded_cycles'] == 200
    assert one['samples'][0]['measurement_count'] == 1


def test_five_samples_same_chamber_use_their_own_nodes_and_cycles(client, actors, db):
    bid = make_batch(db, actors)
    samples = [make_sample(db, actors, bid, str(index)) for index in range(5)]
    pid = make_process(db, actors, bid, equipment_cycles=500)
    steps = []
    for index in range(1, 6):
        steps.append(db.execute(table('process_steps').insert().values(
            process_id=pid, step_index=index, step_kind='wait')).inserted_primary_key[0])
    for index, sid in enumerate(samples):
        cycles = (index + 1) * 100
        link(db, pid, sid, cycles, position=f'P{index + 1}')
        event(db, pid, sid, 'load', steps[index])
        event(db, pid, sid, 'unload', steps[index])
        measurement(db, pid, sid, str(10 + index))
    run = api(client, actors, 'get', f'/processes/{pid}')
    assert run['full_ale_cycles'] == 500  # equipment total is not the per-sample value
    links = sorted(run['samples'], key=lambda row: row['full_ale_cycles'])
    assert [row['full_ale_cycles'] for row in links] == [100, 200, 300, 400, 500]
    assert [row['cumulative_recorded_cycles'] for row in links] == [100, 200, 300, 400, 500]
    assert all(row['participation_status'] == 'unloaded' for row in links)
    assert [row['load_event']['step_index'] for row in links] == [1, 2, 3, 4, 5]
    assert [row['unload_event']['step_index'] for row in links] == [1, 2, 3, 4, 5]
    for index, sid in enumerate(samples):
        sample = api(client, actors, 'get', f'/samples/{sid}')
        assert sample['experiments'][0]['full_ale_cycles'] == (index + 1) * 100
        assert sample['experiments'][0]['measurement_count'] == 1
        assert sample['participation_summary']['recorded_cycles'] == (index + 1) * 100


def test_missing_cycles_are_not_inferred(client, actors, db):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    pid = make_process(db, actors, bid, equipment_cycles=500)
    link(db, pid, sid, None)
    sample = api(client, actors, 'get', f'/samples/{sid}')
    row = sample['experiments'][0]
    assert row['cycles_recorded'] is False and row['full_ale_cycles'] is None
    assert sample['participation_summary']['recorded_cycles'] == 0
    assert sample['participation_summary']['complete'] is False
    assert sample['participation_summary']['missing_participations'] == 1


def test_owner_can_delete_unused_draft_but_not_linked_records(client, actors, db):
    plan = api(client, actors, 'post', '/plans', 201,
               json={'plan_code': 'SLPLAN-' + uuid.uuid4().hex[:8], 'title': '可删草稿'})
    impact = api(client, actors, 'get', f"/lifecycle/plans/{plan['plan_id']}/impact")
    assert impact['delete_permitted'] is True and 'delete' in impact['actions']
    deleted = api(client, actors, 'post', f"/lifecycle/plans/{plan['plan_id']}/apply",
                  json={'action': 'delete', 'expected_row_version': impact['row_version'],
                        'preview_token': impact['preview_token'],
                        'operation_id': uuid.uuid4().hex, 'reason': '未使用草稿'})
    assert deleted['deleted'] is True
    api(client, actors, 'get', f"/plans/{plan['plan_id']}", status=404)

    bid = make_batch(db, actors)
    linked = api(client, actors, 'post', '/plans', 201,
                 json={'plan_code': 'SLLINK-' + uuid.uuid4().hex[:8], 'title': '有关联', 'batch_id': bid})
    api(client, actors, 'post', '/processes', 201,
        json={'process_code': 'SLRUN-' + uuid.uuid4().hex[:8], 'process_mode': 'other',
              'plan_id': linked['plan_id'], 'batch_id': bid})
    blocked = api(client, actors, 'get', f"/lifecycle/plans/{linked['plan_id']}/impact")
    assert blocked['delete_permitted'] is False and 'delete' not in blocked['actions']
    api(client, actors, 'post', f"/lifecycle/plans/{linked['plan_id']}/apply", status=409,
        json={'action': 'delete', 'expected_row_version': blocked['row_version'],
              'preview_token': blocked['preview_token'],
              'operation_id': uuid.uuid4().hex})

    # Batch hard delete remains administrator-only even for an unused batch.
    batch = make_batch(db, actors)
    preview = api(client, actors, 'get', f'/lifecycle/batches/{batch}/impact')
    assert preview['delete_permitted'] is False
    admin_preview = api(client, actors, 'get', f'/lifecycle/batches/{batch}/impact', role='admin')
    assert admin_preview['delete_permitted'] is True
