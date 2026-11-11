"""Round 8 Stage 1: the 2D process grid is the only primary editor.

Real MySQL, SAVEPOINT per request plus an outer rollback fixture: every row the
tests create is rolled back, and the shared browser fixture proves the 43 tables
and the 5 production originals are byte-identical afterwards.
"""
import uuid

from sqlalchemy import select

from app.db import table
from test_phase4_browser import db, client  # rollback manifests, including production originals


def snapshot(kind='自定义处理', value='12', unit='ms', source='Ar'):
    return {
        'step_type': kind,
        'temperature': {'value': None, 'unit': '°C'},
        'groups': [
            {'name': '源', 'fields': [{'name': '名称', 'value': source, 'unit': None},
                                       {'name': '流量', 'value': '20', 'unit': 'sccm'}]},
            {'name': '脉冲', 'fields': [{'name': '时长', 'value': value, 'unit': unit}]},
        ],
    }


def columns(prefix, count=3):
    return [
        {'key': f'{prefix}-{i}', 'step_kind': f'任意分类 {i}', 'step_name': f'{prefix} 步骤 {i}',
         'parameter_snapshot': snapshot(f'任意分类 {i}', str(10 + i), 's' if i % 2 else 'ms', f'源物质 {i}')}
        for i in range(1, count + 1)
    ]


def flow(steps, total=7):
    return {
        'version': 1,
        'total_cycles': total,
        'children': [{'kind': 'group', 'id': 'g-root', 'name': '组合循环', 'repeat': 4,
                      'children': [{'kind': 'step', 'id': f'node-{s["key"]}', 'step_id': s['key']} for s in steps]}],
    }


def resubmit(saved):
    """Rebuild the PUT payload from a detail response: keys replace numeric step IDs."""
    keys = {s['step_id']: f'k{s["step_id"]}' for s in saved['steps']}
    steps = [{'key': keys[s['step_id']], 'step_id': s['step_id'], 'step_kind': s['step_kind'],
              'step_name': s['step_name'], 'parameter_snapshot': s['parameter_snapshot']} for s in saved['steps']]
    def visit(nodes):
        out = []
        for n in nodes:
            if n['kind'] == 'step':
                out.append({'kind': 'step', 'id': n['id'], 'step_id': keys[n['step_id']]})
            else:
                out.append({'kind': 'group', 'id': n['id'], 'name': n['name'], 'repeat': n['repeat'], 'children': visit(n['children'])})
        return out
    return {'steps': steps, 'process_flow': {'version': 1, 'total_cycles': saved['process_flow']['total_cycles'],
                                             'children': visit(saved['process_flow']['children'])}}


def plan_record(client, actors):
    h = actors['operator']['headers']
    p = client.post('/api/v1/plans', headers=h, json={'plan_code': 'R8-' + uuid.uuid4().hex[:20], 'title': '第八轮网格计划'}).json()['data']
    return h, p


def assert_grid(saved, steps):
    assert [s['step_name'] for s in saved['steps']] == [s['step_name'] for s in steps]
    assert [s['step_kind'] for s in saved['steps']] == [s['step_kind'] for s in steps]
    assert [s['parameter_snapshot'] for s in saved['steps']] == [s['parameter_snapshot'] for s in steps]
    assert saved['process_flow']['total_cycles'] == 7
    assert saved['process_flow']['children'][0]['repeat'] == 4
    assert [n['step_id'] for n in saved['process_flow']['children'][0]['children']] == [s['step_id'] for s in saved['steps']]


def test_plan_grid_three_columns_custom_row_units_and_reload(client, actors, db):
    h, p = plan_record(client, actors)
    steps = columns('计划')
    # A custom row is a normal grid row; it exists per column with its own unit.
    for step in steps:
        step['parameter_snapshot']['groups'].append({'name': '自定义', 'fields': [{'name': '信号', 'value': '3.5', 'unit': 'arb'}]})
    body = {'expected_row_version': p['row_version'], 'steps': steps, 'process_flow': flow(steps)}
    response = client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()['data']
    assert_grid(saved, steps)
    assert len(saved['steps']) == 3
    assert [s['parameter_snapshot']['groups'][-1]['fields'][0]['unit'] for s in saved['steps']] == ['arb'] * 3
    # Changing a unit is a value edit only; no conversion is applied.
    assert [s['parameter_snapshot']['groups'][1]['fields'][0]['value'] for s in saved['steps']] == ['11', '12', '13']
    assert [s['parameter_snapshot']['groups'][1]['fields'][0]['unit'] for s in saved['steps']] == ['s', 'ms', 's']
    # Full reload from the detail endpoint returns exactly what was saved.
    assert client.get(f"/api/v1/plans/{p['plan_id']}", headers=h).json()['data'] == saved
    # Stale version still guards history.
    assert client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h, json=body).status_code == 409


def test_process_grid_three_columns_custom_row_and_reload(client, actors):
    h = actors['operator']['headers']
    steps = columns('实际')
    for step in steps:
        step['parameter_snapshot']['groups'].append({'name': '自定义', 'fields': [{'name': '信号', 'value': None, 'unit': 'arb'}]})
    created = client.post('/api/v1/processes', headers=h, json={
        'process_code': 'R8P-' + uuid.uuid4().hex[:16], 'process_mode': 'other',
        'steps': [{'step_index': i + 1, 'step_kind': s['step_kind'], 'step_name': s['step_name'],
                   'parameter_snapshot': s['parameter_snapshot']} for i, s in enumerate(steps)],
        'process_flow': {'version': 1, 'total_cycles': None,
                         'children': [{'kind': 'step', 'id': f'init-{i}', 'step_id': f'index:{i + 1}'} for i in range(3)]},
    })
    assert created.status_code == 201, created.text
    run = created.json()['data']
    submitted = [{'key': f'p{i}', 'step_id': s['step_id'], 'step_kind': s['step_kind'], 'step_name': s['step_name'],
                  'parameter_snapshot': s['parameter_snapshot']} for i, s in enumerate(run['steps'])]
    body = {'expected_row_version': run['row_version'], 'steps': submitted, 'process_flow': flow(submitted, total=None)}
    response = client.put(f"/api/v1/processes/{run['process_id']}/process-grid", headers=h, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()['data']
    assert len(saved['steps']) == 3
    assert [s['parameter_snapshot']['groups'][1]['fields'][0]['unit'] for s in saved['steps']] == ['s', 'ms', 's']
    assert [s['parameter_snapshot']['groups'][2]['fields'][0]['value'] for s in saved['steps']] == [None, None, None]
    assert client.get(f"/api/v1/processes/{run['process_id']}", headers=h).json()['data'] == saved
    # Explicit null stays NULL; no invented zero.
    assert saved['process_flow']['total_cycles'] is None


def test_template_apply_and_save_are_copies_never_history(client, actors):
    h, p = plan_record(client, actors)
    steps = columns('模板', count=2)
    body = {'expected_row_version': p['row_version'], 'steps': steps, 'process_flow': flow(steps)}
    saved = client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h, json=body).json()['data']
    originals = [s['parameter_snapshot'] for s in saved['steps']]

    definition = snapshot('模板类型', '99.5', 'µs', 'Xe')
    created = client.post('/api/v1/step-parameter-templates', headers=h, json={'template_name': 'R8 模板 ' + uuid.uuid4().hex[:8], 'definition': definition})
    assert created.status_code == 201, created.text
    template = created.json()['data']
    assert template['definition'] == definition

    # Applying is a client-side deep copy; the PUT then persists a copy, not a reference.
    payload = resubmit(saved)
    payload['steps'][0] = {**payload['steps'][0], 'parameter_snapshot': template['definition'], 'step_kind': '模板类型'}
    put = client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h,
                     json={'expected_row_version': saved['row_version'], **payload})
    assert put.status_code == 200, put.text
    after = put.json()['data']
    assert after['steps'][0]['parameter_snapshot'] == definition
    assert after['steps'][1]['parameter_snapshot'] == originals[1]
    # Editing the template later must not rewrite the saved step snapshot.
    patched = client.patch(f"/api/v1/step-parameter-templates/{template['template_id']}", headers=h,
                           json={'expected_row_version': template['row_version'], 'definition': snapshot('模板类型', '1', 'ms', 'Kr')})
    assert patched.status_code == 200, patched.text
    assert client.get(f"/api/v1/plans/{p['plan_id']}", headers=h).json()['data']['steps'][0]['parameter_snapshot'] == definition
    # Templates are owner scoped, so another operator can never see this one.
    assert client.get(f"/api/v1/step-parameter-templates/{template['template_id']}", headers=actors['other']['headers']).status_code == 404


def test_history_guard_still_409_for_process_grid(client, actors, db):
    h = actors['operator']['headers']
    b = client.post('/api/v1/batches', headers=h, json={'batch_code': 'R8B-' + uuid.uuid4().hex[:16], 'batch_name': '守卫'}).json()['data']
    sample = client.post('/api/v1/samples', headers=h, json={'sample_code': 'R8S-' + uuid.uuid4().hex[:16], 'batch_id': b['batch_id']}).json()['data']
    run = client.post('/api/v1/processes', headers=h, json={
        'process_code': 'R8H-' + uuid.uuid4().hex[:16], 'process_mode': 'other',
        'steps': [{'step_index': 1, 'step_kind': 'Ar', 'parameter_snapshot': snapshot()}],
        'samples': [{'sample_id': sample['sample_id']}],
    }).json()['data']
    db.execute(table('measurements').insert().values(process_id=run['process_id'], sample_id=sample['sample_id'],
                                                     measurement_code=uuid.uuid4().hex, stage='initial'))
    before = client.get(f"/api/v1/processes/{run['process_id']}", headers=h).json()['data']
    steps = [{'key': 'a', 'step_id': run['steps'][0]['step_id'], 'step_kind': 'Ar',
              'step_name': '篡改', 'parameter_snapshot': snapshot(value='1')}]
    response = client.put(f"/api/v1/processes/{run['process_id']}/process-grid", headers=h,
                          json={'expected_row_version': before['row_version'], 'steps': steps, 'process_flow': flow(steps)})
    assert response.status_code == 409, response.text
    assert client.get(f"/api/v1/processes/{run['process_id']}", headers=h).json()['data'] == before


def test_legacy_step_without_snapshot_readable_and_grid_converts_it(client, actors, db):
    h = actors['operator']['headers']
    run = client.post('/api/v1/processes', headers=h, json={
        'process_code': 'R8L-' + uuid.uuid4().hex[:16], 'process_mode': 'other',
        'steps': [{'step_index': 1, 'step_kind': 'o3_purge', 'step_name': '旧记录步骤', 'pulse_s': '2.500', 'duration_s': '9.000', 'cycles': 5}],
    }).json()['data']
    sid = run['steps'][0]['step_id']
    detail = client.get(f"/api/v1/processes/{run['process_id']}", headers=h).json()['data']
    step = detail['steps'][0]
    assert step['step_id'] == sid
    assert step['parameter_snapshot'] is None
    assert step['parameter_source'] == 'legacy_fields'
    assert step['legacy_parameters_status'] == 'current'
    assert step['legacy_parameters']['pulse_s'] == '2.500'
    assert step['legacy_parameters']['cycles'] == 5
    # A legacy step is readable without any snapshot, and the grid can save it as a snapshot
    # while the original legacy bytes stay untouched.
    legacy = {'step_type': '旧记录步骤', 'temperature': {'value': None, 'unit': '°C'},
              'groups': [{'name': '脉冲', 'fields': [{'name': '时长（原始字段 s）', 'value': '2.500', 'unit': 's'}]},
                         {'name': '循环', 'fields': [{'name': '循环数', 'value': '5', 'unit': None}]}]}
    steps = [{'key': 'legacy', 'step_id': sid, 'step_kind': 'o3_purge', 'step_name': '旧记录步骤', 'parameter_snapshot': legacy}]
    response = client.put(f"/api/v1/processes/{run['process_id']}/process-grid", headers=h,
                          json={'expected_row_version': detail['row_version'], 'steps': steps, 'process_flow': flow(steps)})
    assert response.status_code == 200, response.text
    after = response.json()['data']['steps'][0]
    assert after['parameter_snapshot'] == legacy
    assert after['parameter_source'] == 'parameter_snapshot'
    assert after['legacy_parameters_status'] == 'historical_readonly'
    assert after['legacy_parameters']['pulse_s'] == '2.500'
    assert after['legacy_parameters']['cycles'] == 5
    assert after['parameter_conflict'] is True
    # The stored legacy columns themselves are unchanged.
    row = db.execute(select(table('process_steps')).where(table('process_steps').c.step_id == sid)).mappings().one()
    assert str(row['pulse_s']) == '2.500' and str(row['duration_s']) == '9.000' and row['cycles'] == 5
    # A plan step without a snapshot still exposes its planned values read-only.
    h2, p = plan_record(client, actors)
    psid = db.execute(table('experiment_plan_steps').insert().values(plan_id=p['plan_id'], step_index=1, step_kind='o3_purge',
                                                                    step_name='旧计划步骤', planned_parameters={'cycles': 5})).inserted_primary_key[0]
    plan_step = client.get(f"/api/v1/plans/{p['plan_id']}", headers=h).json()['data']['steps'][0]
    assert plan_step['step_id'] == psid and plan_step['parameter_snapshot'] is None
    assert plan_step['parameter_source'] == 'legacy_fields'
    assert plan_step['legacy_parameters']['cycles'] == 5


def test_plan_and_process_inheritance_copies_structure_and_clears_values(client, actors):
    h, p = plan_record(client, actors)
    steps = columns('继承', count=2)
    body = {'expected_row_version': p['row_version'], 'steps': steps, 'process_flow': flow(steps, total=12)}
    saved = client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h, json=body).json()['data']
    # The browser inheritance helper mirrors this: structure + mapping only, values cleared.
    from app.process_flow import resolve
    draft_steps = []
    for index, s in enumerate(saved['steps'], 1):
        draft_steps.append({'step_index': index, 'step_kind': s['step_kind'], 'step_name': s['step_name'],
                            'plan_step_id': s['step_id'],
                            'parameter_snapshot': {**s['parameter_snapshot'],
                                                   'temperature': {'value': None, 'unit': s['parameter_snapshot']['temperature']['unit']},
                                                   'groups': [{'name': g['name'], 'fields': [{**f, 'value': None} for f in g['fields']]} for g in s['parameter_snapshot']['groups']]}})
    inherited_flow = {'version': 1, 'total_cycles': None, 'children': [{'kind': 'group', 'id': 'g-root', 'name': '组合循环', 'repeat': None,
                        'children': [{'kind': 'step', 'id': f'i{n}', 'step_id': f'index:{n}'} for n in range(1, 3)]}]}
    run = client.post('/api/v1/processes', headers=h, json={'process_code': 'R8I-' + uuid.uuid4().hex[:16], 'process_mode': 'other',
                                                             'plan_id': p['plan_id'], 'steps': draft_steps,
                                                             'process_flow': inherited_flow})
    assert run.status_code == 201, run.text
    actual = run.json()['data']
    assert actual['process_flow']['total_cycles'] is None
    assert actual['process_flow']['children'][0]['repeat'] is None
    assert len(actual['steps']) == 2
    planned_by_id = {s['step_id']: s for s in saved['steps']}
    for step in actual['steps']:
        source = planned_by_id[step['plan_step_id']]
        assert step['parameter_snapshot']['temperature']['value'] is None
        assert all(f['value'] is None for g in step['parameter_snapshot']['groups'] for f in g['fields'])
        assert [f['unit'] for g in step['parameter_snapshot']['groups'] for f in g['fields']] == \
               [f['unit'] for g in source['parameter_snapshot']['groups'] for f in g['fields']]
    # The plan itself keeps its planned values.
    assert client.get(f"/api/v1/plans/{p['plan_id']}", headers=h).json()['data']['steps'][0]['parameter_snapshot'] == steps[0]['parameter_snapshot']


def test_grid_is_the_only_editor_contract_and_legacy_note_preserved(client, actors, db):
    """Grid saves never send step_note, so stored notes survive; no vertical editor exists."""
    h, p = plan_record(client, actors)
    steps = columns('说明', count=1)
    saved = client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h,
                       json={'expected_row_version': p['row_version'], 'steps': steps, 'process_flow': flow(steps)}).json()['data']
    sid = saved['steps'][0]['step_id']
    db.execute(table('experiment_plan_steps').update().where(table('experiment_plan_steps').c.step_id == sid).values(step_note='保留的步骤说明'))
    # Re-saving the grid with a renamed column must keep the note (not part of the grid payload).
    renamed = [{'key': 'x', 'step_id': sid, 'step_kind': '改名分类', 'step_name': '改名步骤', 'parameter_snapshot': snapshot()}]
    again = client.put(f"/api/v1/plans/{p['plan_id']}/process-grid", headers=h,
                       json={'expected_row_version': saved['row_version'], 'steps': renamed, 'process_flow': flow(renamed)})
    assert again.status_code == 200, again.text
    assert again.json()['data']['steps'][0]['step_note'] == '保留的步骤说明'
    assert again.json()['data']['steps'][0]['step_name'] == '改名步骤'
