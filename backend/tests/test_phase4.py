"""Phase 4 regressions: batch endpoints, plan archiving, chemistry systems and
step extensions against real MySQL. conftest rolls every write back."""
import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import table

BASE = '/api/v1'
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ale_phase4_migrate_tests', ROOT / 'database/migrate.py')
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


def code(prefix):
    return prefix + '-' + uuid.uuid4().hex[:16]


def api(client, actors, method, path, body=None, role='operator', status=200):
    r = getattr(client, method)(BASE + path, headers=actors[role]['headers'],
                                **({'json': body} if body is not None else {}))
    assert r.status_code == status, r.text
    return r.json()['data'] if status != 204 else None


def batch(client, actors, role='operator'):
    return api(client, actors, 'post', '/batches', {'batch_code': code('P4B'), 'batch_name': 'Phase4'}, role, 201)


def chemistry(client, actors, role='operator'):
    return api(client, actors, 'post', '/chemistry-systems',
               {'system_code': code('SYS'), 'system_name': 'SiN ALE 体系'}, role, 201)


def sample_count(db):
    return db.scalar(select(func.count()).select_from(table('samples')))


def test_batch_samples_creates_twenty_and_rolls_back_on_conflict(client, actors, db):
    b = batch(client, actors)
    parent = api(client, actors, 'post', '/samples',
                 {'sample_code': code('PW'), 'batch_id': b['batch_id'], 'sample_type': 'full_wafer'}, status=201)
    items = [{'sample_code': code('C'), 'display_label': f'C{i:02d}', 'cut_position': '左上',
              'size_desc': '10x10mm'} for i in range(20)]
    out = api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch",
              {'parent_sample_id': parent['sample_id'], 'items': items}, status=201)
    assert out['count'] == 20 and len(out['created']) == 20
    assert {r['sample_code'] for r in out['created']} == {i['sample_code'] for i in items}
    assert all(r['parent_sample_id'] == parent['sample_id'] and r['batch_id'] == b['batch_id'] for r in out['created'])
    assert all(r['owner_user_id'] == actors['operator']['user']['user_id'] for r in out['created'])
    # Each created sample receives its receive transition and an audit row.
    a = table('audit_log')
    audited = db.scalar(select(func.count()).select_from(a).where(
        a.c.entity_type == 'sample', a.c.entity_id.in_([r['sample_id'] for r in out['created']])))
    assert audited == 20
    t = table('sample_transitions')
    assert db.scalar(select(func.count()).select_from(t).where(
        t.c.sample_id.in_([r['sample_id'] for r in out['created']]))) == 20
    # A conflicting code fails the whole batch: no partial insert, no audit.
    before = sample_count(db)
    audits = db.scalar(select(func.count()).select_from(a))
    clash = [{'sample_code': code('C')}, {'sample_code': items[0]['sample_code']}]
    r = client.post(BASE + f"/batches/{b['batch_id']}/samples/batch", headers=actors['operator']['headers'],
                    json={'items': clash})
    assert r.status_code == 409 and items[0]['sample_code'] in r.text
    assert sample_count(db) == before and db.scalar(select(func.count()).select_from(a)) == audits
    # A duplicate inside one request is rejected before any insert.
    duplicate = code('C')
    r = client.post(BASE + f"/batches/{b['batch_id']}/samples/batch", headers=actors['operator']['headers'],
                    json={'items': [{'sample_code': duplicate}, {'sample_code': duplicate}]})
    assert r.status_code == 409 and duplicate in r.text
    assert sample_count(db) == before


def test_batch_samples_validates_parent_bounds_and_permissions(client, actors, db):
    b = batch(client, actors)
    coupon = api(client, actors, 'post', '/samples', {'sample_code': code('K'), 'batch_id': b['batch_id']}, status=201)
    other = batch(client, actors)
    foreign = api(client, actors, 'post', '/samples',
                  {'sample_code': code('W'), 'batch_id': other['batch_id'], 'sample_type': 'full_wafer'}, status=201)
    for parent_id in (coupon['sample_id'], foreign['sample_id']):
        api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch",
            {'parent_sample_id': parent_id, 'items': [{'sample_code': code('C')}]}, status=422)
    api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch", {'items': []}, status=422)
    api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch",
        {'items': [{'sample_code': code('C')} for _ in range(51)]}, status=422)
    api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch",
        {'items': [{'sample_code': code('C'), 'exclude_from_analysis': True}]}, status=422)
    api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch",
        {'items': [{'sample_code': code('C'), 'status': 'in_process'}]}, status=409)
    # A batch owned by somebody else is invisible, so it reads as missing.
    r = client.post(BASE + f"/batches/{other['batch_id']}/samples/batch", headers=actors['other']['headers'],
                    json={'items': [{'sample_code': code('C')}]})
    assert r.status_code == 404
    api(client, actors, 'post', f"/batches/{b['batch_id']}/samples/batch",
        {'items': [{'sample_code': code('C')}]}, role='viewer', status=403)


def test_batch_links_bind_many_samples_with_single_parent_bump(client, actors, db):
    b = batch(client, actors)
    samples = [api(client, actors, 'post', '/samples', {'sample_code': code('S'), 'batch_id': b['batch_id']}, status=201)
               for _ in range(3)]
    run = api(client, actors, 'post', '/processes',
              {'process_code': code('R'), 'process_mode': 'other', 'batch_id': b['batch_id']}, status=201)
    out = api(client, actors, 'post', f"/processes/{run['process_id']}/samples/batch",
              {'sample_ids': [s['sample_id'] for s in samples], 'is_control': True,
               'chamber_position': 'left'}, status=201)
    assert out['count'] == 3
    assert all(link['is_control'] is True and link['chamber_position'] == 'left' for link in out['created'])
    assert all(link['sample']['sample_code'] for link in out['created'])
    current = api(client, actors, 'get', f"/processes/{run['process_id']}")
    assert current['row_version'] == run['row_version'] + 1
    a = table('audit_log')
    assert db.scalar(select(func.count()).select_from(a).where(
        a.c.entity_type == 'process_sample',
        a.c.entity_id.in_([link['process_sample_id'] for link in out['created']]))) == 3
    # Re-binding an existing sample is a conflict, and the whole request rolls back.
    before = db.scalar(select(func.count()).select_from(table('process_samples')).where(
        table('process_samples').c.process_id == run['process_id']))
    fresh = api(client, actors, 'post', '/samples', {'sample_code': code('S'), 'batch_id': b['batch_id']}, status=201)
    r = client.post(BASE + f"/processes/{run['process_id']}/samples/batch", headers=actors['operator']['headers'],
                    json={'sample_ids': [fresh['sample_id'], samples[0]['sample_id']]})
    assert r.status_code == 409 and str(samples[0]['sample_id']) in r.text
    assert db.scalar(select(func.count()).select_from(table('process_samples')).where(
        table('process_samples').c.process_id == run['process_id'])) == before
    # Duplicates inside one request collapse, and cross-batch samples are rejected.
    out2 = api(client, actors, 'post', f"/processes/{run['process_id']}/samples/batch",
               {'sample_ids': [fresh['sample_id'], fresh['sample_id']]}, status=201)
    assert out2['count'] == 1
    other = batch(client, actors)
    stranger = api(client, actors, 'post', '/samples', {'sample_code': code('S'), 'batch_id': other['batch_id']}, status=201)
    api(client, actors, 'post', f"/processes/{run['process_id']}/samples/batch",
        {'sample_ids': [stranger['sample_id']]}, status=422)


def test_batch_links_respect_history_and_viewer_scope(client, actors):
    b = batch(client, actors)
    sample = api(client, actors, 'post', '/samples', {'sample_code': code('S'), 'batch_id': b['batch_id']}, status=201)
    run = api(client, actors, 'post', '/processes',
              {'process_code': code('R'), 'process_mode': 'other', 'batch_id': b['batch_id'],
               'samples': [{'sample_id': sample['sample_id']}]}, status=201)
    api(client, actors, 'post', f"/samples/{sample['sample_id']}/transitions",
        {'expected_row_version': sample['row_version'], 'event_type': 'load', 'to_status': 'in_process',
         'process_id': run['process_id']}, status=201)
    fresh = api(client, actors, 'post', '/samples', {'sample_code': code('S'), 'batch_id': b['batch_id']}, status=201)
    api(client, actors, 'post', f"/processes/{run['process_id']}/samples/batch",
        {'sample_ids': [fresh['sample_id']]}, status=409)
    api(client, actors, 'post', f"/processes/{run['process_id']}/samples/batch",
        {'sample_ids': [fresh['sample_id']]}, role='viewer', status=403)


def test_archive_is_idempotent_and_delete_is_blocked_by_runs(client, actors):
    plan = api(client, actors, 'post', '/plans', {'plan_code': code('PL'), 'title': 'Archive'}, status=201)
    out = api(client, actors, 'post', f"/plans/{plan['plan_id']}/archive",
              {'expected_row_version': plan['row_version']})
    assert out['status'] == 'archived' and out['row_version'] == plan['row_version'] + 1
    again = api(client, actors, 'post', f"/plans/{plan['plan_id']}/archive", {})
    assert again['status'] == 'archived' and again['row_version'] == out['row_version']
    api(client, actors, 'post', f"/plans/{plan['plan_id']}/archive",
        {'expected_row_version': plan['row_version']}, status=409)
    found = api(client, actors, 'get', f"/plans?status=archived&keyword={plan['plan_code']}")
    assert [p['plan_id'] for p in found] == [plan['plan_id']]
    api(client, actors, 'post', f"/plans/{plan['plan_id']}/archive", {}, role='viewer', status=403)
    # A plan with runs still cannot be deleted; archiving is the intended path.
    linked = api(client, actors, 'post', '/plans', {'plan_code': code('PL'), 'title': 'Linked'}, status=201)
    api(client, actors, 'post', '/processes',
        {'process_code': code('R'), 'process_mode': 'other', 'plan_id': linked['plan_id']}, status=201)
    api(client, actors, 'delete', f"/plans/{linked['plan_id']}", status=409)
    assert api(client, actors, 'post', f"/plans/{linked['plan_id']}/archive", {})['status'] == 'archived'
    # Archived is a normal editable status, not a lock.
    api(client, actors, 'patch', f"/plans/{plan['plan_id']}",
        {'title': 'still editable', 'expected_row_version': again['row_version']})
    api(client, actors, 'delete', f"/plans/{plan['plan_id']}", status=204)


def test_chemistry_system_crud_species_templates_and_permissions(client, actors, db):
    system = chemistry(client, actors)
    assert system['status'] == 'active' and system['row_version'] == 1
    assert system['owner']['user_id'] == actors['operator']['user']['user_id']
    assert system['species'] == [] and system['templates'] == []
    detail = api(client, actors, 'get', f"/chemistry-systems/{system['system_id']}")
    assert detail['system_code'] == system['system_code']
    patched = api(client, actors, 'patch', f"/chemistry-systems/{system['system_id']}",
                  {'system_name': 'renamed', 'status': 'experimental',
                   'expected_row_version': system['row_version']})
    assert patched['system_name'] == 'renamed' and patched['status'] == 'experimental'
    api(client, actors, 'patch', f"/chemistry-systems/{system['system_id']}",
        {'system_name': 'stale', 'expected_row_version': system['row_version']}, status=409)
    api(client, actors, 'patch', f"/chemistry-systems/{system['system_id']}",
        {'status': 'invalid', 'expected_row_version': patched['row_version']}, status=422)
    api(client, actors, 'patch', f"/chemistry-systems/{system['system_id']}",
        {'status': None, 'expected_row_version': patched['row_version']}, status=422)
    api(client, actors, 'patch', f"/chemistry-systems/{system['system_id']}",
        {'unknown_field': 'x', 'expected_row_version': patched['row_version']}, status=422)
    # Nullable fields accept an explicit null.
    cleared = api(client, actors, 'patch', f"/chemistry-systems/{system['system_id']}",
                  {'description': None, 'expected_row_version': patched['row_version']})
    assert cleared['description'] is None
    api(client, actors, 'post', '/chemistry-systems',
        {'system_code': system['system_code'], 'system_name': 'dup'}, status=409)
    species = api(client, actors, 'post', f"/chemistry-systems/{system['system_id']}/species",
                  {'species_code': 'O3', 'species_name': '臭氧', 'formula': 'O3',
                   'role': 'reactant', 'default_unit': 'sccm'}, status=201)
    assert species['role'] == 'reactant'
    api(client, actors, 'post', f"/chemistry-systems/{system['system_id']}/species",
        {'species_code': 'O3', 'species_name': 'dup', 'role': 'reactant'}, status=409)
    api(client, actors, 'post', f"/chemistry-systems/{system['system_id']}/species",
        {'species_code': 'X1', 'species_name': 'bad role', 'role': 'catalyst'}, status=422)
    template = api(client, actors, 'post', f"/chemistry-systems/{system['system_id']}/step-templates",
                   {'template_code': code('T'), 'template_name': 'O3-HF-TMA 循环',
                    'steps': [{'name': 'O3 暴露', 'kind': 'o3_purge', 'loop_count': 10,
                               'parameters': [{'key': 'duration_s', 'label': '时长', 'unit': 's'}]},
                              {'name': 'HF 吹扫', 'kind': 'hf_purge', 'loop_count': 50,
                               'parameters': [{'key': 'delta_p', 'label': '压差', 'unit': 'Pa'}]}]}, status=201)
    assert [s['name'] for s in template['steps']] == ['O3 暴露', 'HF 吹扫']
    assert template['steps'][0]['parameters'][0]['key'] == 'duration_s'
    for bad in [{'steps': []}, {'steps': [{'name': 'x' * 129, 'kind': 'k'}]},
                {'steps': [{'name': 'a', 'kind': 'k', 'loop_count': 0}]},
                {'steps': [{'name': 'a', 'kind': 'k', 'loop_count': 100001}]},
                {'steps': [{'name': 'a', 'kind': 'k', 'parameters': [{'key': 'bad key', 'label': 'l'}]}]},
                {'steps': [{'name': 'a', 'kind': 'k', 'parameters': [{'key': 'k', 'label': 'l' * 65}]}]}]:
        body = {'template_code': code('T'), 'template_name': 'bad', **bad}
        api(client, actors, 'post', f"/chemistry-systems/{system['system_id']}/step-templates", body, status=422)
    api(client, actors, 'post', f"/chemistry-systems/{system['system_id']}/step-templates",
        {'template_code': template['template_code'], 'template_name': 'dup',
         'steps': [{'name': 'a', 'kind': 'k'}]}, status=409)
    updated = api(client, actors, 'patch', f"/step-templates/{template['template_id']}",
                  {'template_name': 'renamed', 'steps': [{'name': 'only', 'kind': 'wait'}]})
    assert updated['template_name'] == 'renamed' and len(updated['steps']) == 1
    patched_species = api(client, actors, 'patch', f"/species/{species['species_id']}",
                          {'default_unit': 'Pa', 'role': 'purge'})
    assert patched_species['default_unit'] == 'Pa' and patched_species['role'] == 'purge'
    # Visibility: owner and admin only; a missing system is 404, never 403.
    sid = system['system_id']
    path = f'/chemistry-systems/{sid}'
    assert client.get(BASE + path, headers=actors['other']['headers']).status_code == 404
    admin_detail = client.get(BASE + path, headers=actors['admin']['headers'])
    assert admin_detail.status_code == 200
    assert {s['species_code'] for s in admin_detail.json()['data']['species']} == {'O3'}
    assert client.get(BASE + path, headers=actors['viewer']['headers']).status_code == 404
    assert client.get(BASE + '/chemistry-systems', headers=actors['other']['headers']).json()['data'] == []
    api(client, actors, 'post', '/chemistry-systems', {'system_code': code('X'), 'system_name': 'x'},
        role='viewer', status=403)
    api(client, actors, 'post', f"/chemistry-systems/{sid}/species",
        {'species_code': 'N2', 'species_name': '氮气', 'role': 'carrier'}, role='viewer', status=403)
    # Deleting children requires admin; the system itself is protected by runs.
    api(client, actors, 'delete', f"/species/{species['species_id']}", role='operator', status=403)
    api(client, actors, 'delete', f"/step-templates/{template['template_id']}", role='operator', status=403)
    api(client, actors, 'delete', f"/step-templates/{template['template_id']}", role='admin', status=204)
    api(client, actors, 'delete', f"/chemistry-systems/{sid}", role='admin', status=204)
    assert client.get(BASE + f'/chemistry-systems/{sid}', headers=actors['operator']['headers']).status_code == 404


def test_chemistry_system_delete_blocked_by_referencing_run(client, actors, db):
    system = chemistry(client, actors)
    api(client, actors, 'post', '/processes',
        {'process_code': code('R'), 'process_mode': 'other', 'chemistry_system_id': system['system_id']}, status=201)
    api(client, actors, 'delete', f"/chemistry-systems/{system['system_id']}", role='admin', status=409)
    # A system whose owner was removed (NULL) stays admin-only, never public.
    orphan = chemistry(client, actors)
    t = table('chemistry_systems')
    db.execute(t.update().where(t.c.system_id == orphan['system_id']).values(owner_user_id=None))
    assert client.get(BASE + f"/chemistry-systems/{orphan['system_id']}",
                      headers=actors['operator']['headers']).status_code == 404
    assert client.get(BASE + f"/chemistry-systems/{orphan['system_id']}",
                      headers=actors['admin']['headers']).status_code == 200
    assert orphan['system_id'] not in [r['system_id'] for r in
                                       api(client, actors, 'get', '/chemistry-systems')]
    api(client, actors, 'delete', f"/chemistry-systems/{orphan['system_id']}", role='admin', status=204)


def test_process_chemistry_system_reference_and_visibility(client, actors):
    system = chemistry(client, actors)
    run = api(client, actors, 'post', '/processes',
              {'process_code': code('R'), 'process_mode': 'other', 'chemistry_system_id': system['system_id']}, status=201)
    assert run['chemistry_system_id'] == system['system_id']
    detail = api(client, actors, 'get', f"/processes/{run['process_id']}")
    assert detail['chemistry_system_id'] == system['system_id']
    api(client, actors, 'patch', f"/processes/{run['process_id']}",
        {'chemistry_system_id': None, 'expected_row_version': run['row_version']})
    api(client, actors, 'patch', f"/processes/{run['process_id']}",
        {'chemistry_system_id': 999999999, 'expected_row_version': run['row_version'] + 1}, status=422)
    # A system owned by somebody else is invisible to the writer.
    other = chemistry(client, actors, role='other')
    api(client, actors, 'post', '/processes',
        {'process_code': code('R'), 'process_mode': 'other', 'chemistry_system_id': other['system_id']}, status=404)
    api(client, actors, 'post', '/processes',
        {'process_code': code('R'), 'process_mode': 'other', 'chemistry_system_id': 0}, status=422)


def test_step_name_and_custom_parameters_round_trip_and_validation(client, actors):
    plan = api(client, actors, 'post', '/plans', {'plan_code': code('PL'), 'title': 'Steps'}, status=201)
    step = api(client, actors, 'post', f"/plans/{plan['plan_id']}/steps",
               {'step_index': 1, 'step_kind': 'other', 'step_name': 'O3 暴露',
                'custom_parameters': {'duration_s': {'value': '10.5', 'unit': 's', 'note': 'measured'},
                                      'delta_p': {'value': 80, 'unit': 'Pa'}}}, status=201)
    assert step['step_name'] == 'O3 暴露'
    assert step['custom_parameters'] == {'duration_s': {'value': '10.5', 'unit': 's', 'note': 'measured'},
                                         'delta_p': {'value': '80', 'unit': 'Pa'}}
    listed = api(client, actors, 'get', f"/plans/{plan['plan_id']}/steps")
    assert listed[0]['custom_parameters']['delta_p']['value'] == '80'
    plan_now = api(client, actors, 'get', f"/plans/{plan['plan_id']}")
    cleared = api(client, actors, 'patch', f"/plan-steps/{step['step_id']}",
                  {'step_name': None, 'custom_parameters': None,
                   'expected_row_version': plan_now['row_version']})
    assert cleared['step_name'] is None and cleared['custom_parameters'] is None
    run = api(client, actors, 'post', '/processes', {'process_code': code('R'), 'process_mode': 'other'}, status=201)
    run_step = api(client, actors, 'post', f"/processes/{run['process_id']}/steps",
                   {'step_index': 1, 'step_kind': 'other', 'step_name': 'HF 吹扫',
                    'custom_parameters': {'delta_p': {'value': 80}}}, status=201)
    assert run_step['step_name'] == 'HF 吹扫' and run_step['custom_parameters']['delta_p']['value'] == '80'
    for body in [{'step_name': 'x' * 129}, {'custom_parameters': {'bad key': {'value': '1'}}},
                 {'custom_parameters': {f'k{i}': {'value': '1'} for i in range(33)}},
                 {'custom_parameters': {'k': {'value': True}}},
                 {'custom_parameters': {'k': {'value': '1', 'unit': 'x' * 25}}},
                 {'custom_parameters': {'k': {'value': '1', 'note': 'x' * 256}}},
                 {'custom_parameters': {'k': {'value': ['a']}}},
                 {'custom_parameters': 'not-a-dict'}]:
        api(client, actors, 'post', f"/plans/{plan['plan_id']}/steps",
            {'step_index': 2, 'step_kind': 'other', **body}, status=422)
    # Values that are valid still accept every allowed scalar shape.
    ok = api(client, actors, 'post', f"/plans/{plan['plan_id']}/steps",
             {'step_index': 3, 'step_kind': 'other',
              'custom_parameters': {'a': {'value': 1}, 'b': {'value': 1.5}, 'c': {'value': 'text'},
                                    'd': {'value': None, 'note': 'empty on purpose'}}}, status=201)
    assert ok['custom_parameters']['a']['value'] == '1'
    assert ok['custom_parameters']['d'] == {'value': None, 'note': 'empty on purpose'}


def test_phase4_migration_contract_is_read_only_and_version_scoped():
    """The 0006 validator never writes and never touches other versions."""
    class NoQueries:
        def execute(self, *args):
            raise AssertionError('Unexpected phase4 query')
    for version in ('0001', '0002', '0003', '0004', '0005'):
        migrate.validate_phase4(NoQueries(), version)


def test_phase4_contract_constants_match_the_migration_sql():
    """Guards the frozen 0006 contract without touching the live database."""
    sql = (ROOT / 'database/migrations/0006_general_chemistry.sql').read_text(encoding='utf-8')
    assert set(migrate.PHASE4_NEW_TABLES) <= set(migrate.PHASE4_COLUMNS)
    for table, columns in migrate.PHASE4_COLUMNS.items():
        for column in columns:
            assert f' {column} ' in sql or f'`{column}`' in sql, f'{table}.{column} missing from 0006'
    for (table, name), (column, target, target_column, delete, update) in migrate.PHASE4_FOREIGN_KEYS.items():
        assert f'CONSTRAINT {name} FOREIGN KEY({column}) REFERENCES {target}({target_column})' in sql
        assert f'ON DELETE {delete}' in sql and f'ON UPDATE {update}' in sql
    for (table, name), clause in migrate.PHASE4_CHECKS.items():
        assert name in sql
    # chk_plans_priority predates 0006; the validator only re-checks that the
    # atomic status ALTER left it intact, so it must not appear in this file.
    assert ('experiment_plans', 'chk_plans_priority') in migrate.PHASE4_PLAN_CHECKS
    assert 'chk_plans_priority' not in sql
    for table in migrate.PHASE4_NEW_TABLES:
        assert f'CREATE TABLE IF NOT EXISTS {table}' in sql
    assert 'archived' in migrate.PHASE4_CHECKS[('experiment_plans', 'chk_plans_status')]
    for entity in ('chemistry_system', 'chemistry_species', 'chemistry_step_template'):
        assert f"'{entity}'" in migrate.PHASE4_AUDIT_CHECK and f"'{entity}'" in sql
    # Both CHECK replacements must be single atomic ALTER statements.
    assert 'DROP CHECK chk_plans_status' in sql and 'DROP CHECK chk_audit_entity' in sql
    assert 'ALTER TABLE processes ADD COLUMN chemistry_system_id BIGINT UNSIGNED NULL;' in sql


def test_live_schema_passes_phase4_validation(db):
    """Validate the real migrated database exactly as migrate.py --status does."""
    cursor = db.connection.driver_connection.cursor()
    try:
        migrate.validate_phase4(cursor, '0006')
    finally:
        cursor.close()
