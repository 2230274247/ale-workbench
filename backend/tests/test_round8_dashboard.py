"""Round 8 Stage 3 dashboard endpoints on real MySQL; every write rolls back.

Fixtures create two operators with disjoint records, a viewer and an admin.
Each assertion is derived from the stored rows, not from invented constants.
"""
import hashlib
import json
import uuid
from sqlalchemy import select

from app.db import table
from test_phase4_browser import db, client  # rollback manifests, including production originals

OPERATOR = 'operator'
OTHER = 'other'
VIEWER = 'viewer'
ADMIN = 'admin'


def code(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:14]}'


def sha():
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def make_batch(db, actors, role, label='批次'):
    uid = actors[role]['user']['user_id']
    return db.execute(table('batches').insert().values(
        batch_code=code('R8B'), batch_name=label, owner_user_id=uid)).inserted_primary_key[0]


def make_sample(db, actors, role, bid, label='样品'):
    uid = actors[role]['user']['user_id']
    return db.execute(table('samples').insert().values(
        sample_code=code('R8S'), batch_id=bid, sample_type='coupon', owner_user_id=uid)).inserted_primary_key[0]


def make_plan(db, actors, role, bid, status='draft', when='2031-01-01 00:00:00', title=None):
    return db.execute(table('experiment_plans').insert().values(
        plan_code=code('R8P'), title=title or f'{role} 计划', status=status, priority='normal',
        owner_user_id=actors[role]['user']['user_id'], batch_id=bid, updated_at=when)).inserted_primary_key[0]


def make_process(db, actors, role, bid=None, plan_id=None, log_status='unknown', when='2031-01-01 00:00:00', archived=False):
    return db.execute(table('processes').insert().values(
        process_code=code('R8R'), process_mode='other', operator_user_id=actors[role]['user']['user_id'],
        batch_id=bid, plan_id=plan_id, log_status=log_status, updated_at=when,
        archived_at=when if archived else None)).inserted_primary_key[0]


def make_measurement(db, sid, quality='ok', current=True, when='2031-01-01 00:00:00'):
    return db.execute(table('measurements').insert().values(
        measurement_code=code('R8M'), sample_id=sid, stage='initial', quality_flag=quality,
        is_current=1 if current else 0, updated_at=when)).inserted_primary_key[0]


def make_job(db, actors, role, when='2031-01-01 00:00:00'):
    return db.execute(table('import_jobs').insert().values(
        owner_user_id=actors[role]['user']['user_id'], created_at=when)).inserted_primary_key[0]


def make_item(db, job, status='pending', parse_status='parsed'):
    return db.execute(table('import_items').insert().values(
        job_id=job, filename=f'{code("f")}.xlsx', sha256=sha(), storage_key=sha(),
        status=status, parse_result={'status': parse_status})).inserted_primary_key[0]


def make_source(db, name, parse_status='parsed', sid=None):
    return db.execute(table('source_files').insert().values(
        file_sha256=sha(), file_name=name, file_role='instrument_raw',
        parse_status=parse_status, sample_id=sid)).inserted_primary_key[0]


def get(client, actors, role, path, **query):
    response = client.get(path, headers=actors[role]['headers'], params=query)
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_summary_scope_and_new_endpoint_contract(client, actors, db):
    op_batch = make_batch(db, actors, OPERATOR)
    op_sample = make_sample(db, actors, OPERATOR, op_batch)
    other_batch = make_batch(db, actors, OTHER)
    other_sample = make_sample(db, actors, OTHER, other_batch)
    admin_batch = make_batch(db, actors, ADMIN)
    make_sample(db, actors, ADMIN, admin_batch)

    operator = get(client, actors, OPERATOR, '/api/v1/dashboard/summary')
    other = get(client, actors, OTHER, '/api/v1/dashboard/summary')
    admin = get(client, actors, ADMIN, '/api/v1/dashboard/summary')
    assert operator['batch_count'] == 1 and operator['sample_count'] == 1
    assert other['batch_count'] == 1 and other['sample_count'] == 1
    assert admin['batch_count'] >= 3 and admin['sample_count'] >= 3
    # Existing endpoint shape is preserved.
    assert {'batch_count', 'sample_count', 'measurement_count', 'plan_count', 'process_count', 'generated_at'} <= set(operator)
    # New endpoints answer with a bounded list envelope.
    for path in ('/api/v1/dashboard/todo', '/api/v1/dashboard/recent-experiments', '/api/v1/dashboard/recent-data'):
        payload = get(client, actors, OPERATOR, path)
        assert isinstance(payload['items'], list) and len(payload['items']) <= 20
        assert payload['generated_at']
        assert 'select' not in json.dumps(payload).lower()
    assert get(client, actors, OPERATOR, '/api/v1/dashboard/recent') is not None


def test_todo_excludes_completed_and_counts_match_fixtures(client, actors, db):
    batch = make_batch(db, actors, OPERATOR)
    # Two plans without a run (draft + approved); completed/archived ones never appear.
    draft = make_plan(db, actors, OPERATOR, batch, 'draft', '2031-03-01 10:00:00', '草稿计划')
    approved = make_plan(db, actors, OPERATOR, batch, 'approved', '2031-03-02 10:00:00', '已批准计划')
    make_plan(db, actors, OPERATOR, batch, 'completed', '2031-03-03 10:00:00', '已完成计划')
    make_plan(db, actors, OPERATOR, batch, 'abandoned', '2031-03-04 10:00:00', '已放弃计划')
    make_plan(db, actors, OPERATOR, batch, 'archived', '2031-03-05 10:00:00', '已归档计划')
    with_run = make_plan(db, actors, OPERATOR, batch, 'draft', '2031-03-06 10:00:00', '已有执行计划')
    make_process(db, actors, OPERATOR, batch, with_run, 'ok', '2031-03-06 11:00:00')
    # Only unknown/partial, non-archived runs are pending.
    unknown = make_process(db, actors, OPERATOR, batch, None, 'unknown', '2031-03-07 10:00:00')
    partial = make_process(db, actors, OPERATOR, batch, None, 'partial', '2031-03-08 10:00:00')
    make_process(db, actors, OPERATOR, batch, None, 'ok', '2031-03-09 10:00:00')
    make_process(db, actors, OPERATOR, batch, None, 'aborted', '2031-03-10 10:00:00')
    make_process(db, actors, OPERATOR, batch, None, 'unknown', '2031-03-11 10:00:00', archived=True)
    # Import work: one draft job with two pending items, one completed job, one rejected item.
    job = make_job(db, actors, OPERATOR, '2031-03-12 10:00:00')
    make_item(db, job, 'pending', 'parsed')
    make_item(db, job, 'pending', 'original_only')
    done = make_job(db, actors, OPERATOR, '2031-03-13 10:00:00')
    make_item(db, done, 'imported', 'parsed')
    rejected_job = make_job(db, actors, OPERATOR, '2031-03-14 10:00:00')
    make_item(db, rejected_job, 'pending', 'rejected')
    # Measurements needing review: current suspect/abnormal only.
    sample = make_sample(db, actors, OPERATOR, batch)
    suspect = make_measurement(db, sample, 'suspect', True, '2031-03-15 10:00:00')
    abnormal = make_measurement(db, sample, 'abnormal', True, '2031-03-16 10:00:00')
    make_measurement(db, sample, 'ok', True, '2031-03-17 10:00:00')
    make_measurement(db, sample, 'suspect', False, '2031-03-18 10:00:00')
    make_measurement(db, sample, 'excluded', True, '2031-03-19 10:00:00')

    payload = get(client, actors, OPERATOR, '/api/v1/dashboard/todo')
    counts = payload['counts']
    assert counts['plan_without_process'] == 2
    assert counts['process_log'] == 2
    assert counts['import_pending'] == 2  # two draft jobs with pending items (main + rejected)
    assert counts['import_failure'] == 1
    assert counts['measurement_review'] == 2
    assert counts['issue'] == 0  # issue ledger is admin-only
    assert payload['total'] == sum(counts.values())
    kinds = [item['kind'] for item in payload['items']]
    assert 'plan_without_process' in kinds and 'process_log' in kinds
    assert 'import_pending' in kinds and 'import_failure' in kinds and 'measurement_review' in kinds
    entity_ids = {(item['kind'], item['entity_id']) for item in payload['items']}
    assert ('plan_without_process', draft) in entity_ids
    assert ('plan_without_process', approved) in entity_ids
    assert ('process_log', unknown) in entity_ids and ('process_log', partial) in entity_ids
    assert ('measurement_review', suspect) in entity_ids and ('measurement_review', abnormal) in entity_ids
    # Completed plans/runs are absent.
    assert ('plan_without_process', with_run) not in entity_ids
    for item in payload['items']:
        assert item['path'] and isinstance(item['query'], dict)
        assert item['detail'] and item['updated_at']
    # Newest first.
    stamps = [item['updated_at'] for item in payload['items']]
    assert stamps == sorted(stamps, reverse=True)


def test_todo_operator_scope_and_admin_visibility(client, actors, db):
    op_batch = make_batch(db, actors, OPERATOR)
    other_batch = make_batch(db, actors, OTHER)
    op_plan = make_plan(db, actors, OPERATOR, op_batch, 'draft', '2031-04-01 10:00:00', '本人计划')
    other_plan = make_plan(db, actors, OTHER, other_batch, 'draft', '2031-04-02 10:00:00', '他人计划')
    op_run = make_process(db, actors, OPERATOR, op_batch, None, 'unknown', '2031-04-03 10:00:00')
    other_run = make_process(db, actors, OTHER, other_batch, None, 'unknown', '2031-04-04 10:00:00')
    op_sample = make_sample(db, actors, OPERATOR, op_batch)
    other_sample = make_sample(db, actors, OTHER, other_batch)
    op_measure = make_measurement(db, op_sample, 'suspect', True, '2031-04-05 10:00:00')
    other_measure = make_measurement(db, other_sample, 'abnormal', True, '2031-04-06 10:00:00')
    op_job = make_job(db, actors, OPERATOR, '2031-04-07 10:00:00')
    make_item(db, op_job, 'pending', 'parsed')
    other_job = make_job(db, actors, OTHER, '2031-04-08 10:00:00')
    make_item(db, other_job, 'pending', 'parsed')

    operator = get(client, actors, OPERATOR, '/api/v1/dashboard/todo')
    ids = {(item['kind'], item['entity_id']) for item in operator['items']}
    assert ('plan_without_process', op_plan) in ids and ('plan_without_process', other_plan) not in ids
    assert ('process_log', op_run) in ids and ('process_log', other_run) not in ids
    assert ('measurement_review', op_measure) in ids and ('measurement_review', other_measure) not in ids
    assert operator['counts']['import_pending'] == 1
    assert other_job not in {item['entity_id'] for item in operator['items'] if item['kind'] == 'import_pending'}

    admin = get(client, actors, ADMIN, '/api/v1/dashboard/todo')
    admin_ids = {(item['kind'], item['entity_id']) for item in admin['items']}
    assert ('plan_without_process', op_plan) in admin_ids and ('plan_without_process', other_plan) in admin_ids
    assert ('process_log', op_run) in admin_ids and ('process_log', other_run) in admin_ids
    assert ('measurement_review', op_measure) in admin_ids and ('measurement_review', other_measure) in admin_ids
    # Import jobs stay personal even for an admin; only the admin's own jobs appear.
    assert admin['counts']['import_pending'] == 0

    viewer = get(client, actors, VIEWER, '/api/v1/dashboard/todo')
    assert viewer['items'] == [] and viewer['total'] == 0
    assert viewer['counts']['plan_without_process'] == 0


def test_issue_todo_is_admin_only(client, actors, db):
    issues = table('issues')
    issue_id = db.execute(issues.insert().values(
        issue_code=code('ISS'), title='真实问题', severity='high', status='open',
        updated_at='2031-05-01 10:00:00')).inserted_primary_key[0]
    resolved = db.execute(issues.insert().values(
        issue_code=code('ISS'), title='已解决', severity='high', status='resolved',
        updated_at='2031-05-02 10:00:00')).inserted_primary_key[0]
    admin = get(client, actors, ADMIN, '/api/v1/dashboard/todo')
    assert ('issue', issue_id) in {(item['kind'], item['entity_id']) for item in admin['items']}
    assert ('issue', resolved) not in {(item['kind'], item['entity_id']) for item in admin['items']}
    assert admin['counts']['issue'] >= 1
    assert get(client, actors, OPERATOR, '/api/v1/dashboard/todo')['counts']['issue'] == 0


def test_recent_experiments_ordering_scope_and_continue_target(client, actors, db):
    batch = make_batch(db, actors, OPERATOR)
    other_batch = make_batch(db, actors, OTHER)
    old_plan = make_plan(db, actors, OPERATOR, batch, 'draft', '2031-06-01 10:00:00', '最早计划')
    new_plan = make_plan(db, actors, OPERATOR, batch, 'approved', '2031-06-03 10:00:00', '最新计划')
    run = make_process(db, actors, OPERATOR, batch, new_plan, 'partial', '2031-06-02 10:00:00')
    other_plan = make_plan(db, actors, OTHER, other_batch, 'draft', '2031-06-04 10:00:00', '他人计划')
    other_run = make_process(db, actors, OTHER, other_batch, other_plan, 'unknown', '2031-06-05 10:00:00')

    payload = get(client, actors, OPERATOR, '/api/v1/dashboard/recent-experiments')
    order = [(item['kind'], item['entity_id']) for item in payload['items']]
    assert order == [('plan', new_plan), ('process', run), ('plan', old_plan)]
    assert other_plan not in {item['entity_id'] for item in payload['items'] if item['kind'] == 'plan'}
    assert other_run not in {item['entity_id'] for item in payload['items'] if item['kind'] == 'process'}
    plan_item = next(item for item in payload['items'] if item['kind'] == 'plan' and item['entity_id'] == new_plan)
    # An approved plan continues by starting a run from the plan (Stage 4 route remains /experiments/new).
    assert plan_item['continue_path'] == '/processes' and plan_item['continue_query']['create'] == '1'
    assert plan_item['continue_query']['plan_id'] == new_plan
    assert plan_item['path'] == '/plans' and plan_item['query'] == {'plan_id': new_plan}
    run_item = next(item for item in payload['items'] if item['kind'] == 'process')
    assert run_item['continue_path'] == '/processes' and run_item['continue_query'] == {'process_id': run}
    assert run_item['can_continue'] is True
    # A viewer sees only their own (empty) list but gets the same envelope.
    assert get(client, actors, VIEWER, '/api/v1/dashboard/recent-experiments')['items'] == []
    admin_items = get(client, actors, ADMIN, '/api/v1/dashboard/recent-experiments')['items']
    admin_ids = {item['entity_id'] for item in admin_items}
    assert {new_plan, old_plan, run, other_plan, other_run} <= admin_ids
    assert len(admin_items) <= 20


def test_recent_data_quality_hints_scope_and_ordering(client, actors, db):
    batch = make_batch(db, actors, OPERATOR)
    other_batch = make_batch(db, actors, OTHER)
    sample = make_sample(db, actors, OPERATOR, batch)
    other_sample = make_sample(db, actors, OTHER, other_batch)
    ok = make_measurement(db, sample, 'ok', True, '2031-07-01 10:00:00')
    suspect = make_measurement(db, sample, 'suspect', True, '2031-07-02 10:00:00')
    superseded = make_measurement(db, sample, 'ok', False, '2031-07-03 10:00:00')
    other_measure = make_measurement(db, other_sample, 'abnormal', True, '2031-07-04 10:00:00')
    job = make_job(db, actors, OPERATOR, '2031-07-05 10:00:00')
    make_item(db, job, 'pending', 'parsed')
    other_job = make_job(db, actors, OTHER, '2031-07-06 10:00:00')
    make_item(db, other_job, 'pending', 'parsed')
    failed = make_source(db, '解析失败原件.xlsx', 'failed', sample)
    pending = make_source(db, '待解析原件.xlsx', 'pending', sample)
    other_source = make_source(db, '他人原件.xlsx', 'parsed', other_sample)

    payload = get(client, actors, OPERATOR, '/api/v1/dashboard/recent-data')
    stamps = [item['occurred_at'] for item in payload['items']]
    assert stamps == sorted(stamps, reverse=True)
    by_kind = {}
    for item in payload['items']:
        by_kind.setdefault(item['kind'], []).append(item)
    measure_items = {item['entity_id']: item for item in by_kind.get('measurement', [])}
    assert set(measure_items) == {ok, suspect, superseded}
    assert measure_items[ok]['hint'] is None
    assert '疑似异常' in measure_items[suspect]['hint']
    assert '已被取代' in measure_items[superseded]['hint']
    assert other_measure not in measure_items
    source_items = {item['entity_id']: item for item in by_kind.get('source_file', [])}
    assert source_items[failed]['hint'] and '解析失败' in source_items[failed]['hint']
    assert source_items[pending]['hint'] and '待处理' in source_items[pending]['hint']
    assert other_source not in source_items
    jobs = [item['entity_id'] for item in by_kind.get('import_job', [])]
    assert job in jobs and other_job not in jobs
    assert '待确认' in next(item['hint'] for item in by_kind['import_job'] if item['entity_id'] == job)
    for item in payload['items']:
        assert item['path'] and isinstance(item['query'], dict)
        assert item['title']
    assert get(client, actors, VIEWER, '/api/v1/dashboard/recent-data')['items'] == []
    admin_items = get(client, actors, ADMIN, '/api/v1/dashboard/recent-data')['items']
    assert {ok, suspect, superseded, other_measure} <= {item['entity_id'] for item in admin_items if item['kind'] == 'measurement'}
    assert len(admin_items) <= 20


def test_limit_is_bounded_and_tolerates_small_values(client, actors, db):
    batch = make_batch(db, actors, OPERATOR)
    for index in range(6):
        make_plan(db, actors, OPERATOR, batch, 'draft', f'2031-08-0{index + 1} 10:00:00', f'计划 {index}')
    limited = get(client, actors, OPERATOR, '/api/v1/dashboard/recent-experiments', limit=2)
    assert len(limited['items']) == 2
    assert get(client, actors, OPERATOR, '/api/v1/dashboard/todo', limit=1)['items']
    for path in ('/api/v1/dashboard/todo', '/api/v1/dashboard/recent-experiments', '/api/v1/dashboard/recent-data'):
        response = client.get(path, headers=actors[OPERATOR]['headers'], params={'limit': 21})
        assert response.status_code == 422, (path, response.status_code)


def test_hidden_records_never_leak_through_counts_or_lists(client, actors, db):
    other_batch = make_batch(db, actors, OTHER, '秘密批次')
    other_sample = make_sample(db, actors, OTHER, other_batch, '秘密样品')
    other_plan = make_plan(db, actors, OTHER, other_batch, 'draft', '2031-09-01 10:00:00', '秘密计划')
    other_run = make_process(db, actors, OTHER, other_batch, other_plan, 'unknown', '2031-09-02 10:00:00')
    make_measurement(db, other_sample, 'abnormal', True, '2031-09-03 10:00:00')
    job = make_job(db, actors, OTHER, '2031-09-04 10:00:00')
    make_item(db, job, 'pending', 'parsed')
    make_source(db, '秘密原件.xlsx', 'failed', other_sample)

    viewer = get(client, actors, VIEWER, '/api/v1/dashboard/todo')
    assert viewer['items'] == []
    for key in ('plan_without_process', 'process_log', 'import_pending', 'import_failure', 'measurement_review', 'issue'):
        assert viewer['counts'][key] == 0
    for path in ('/api/v1/dashboard/recent-experiments', '/api/v1/dashboard/recent-data'):
        body = get(client, actors, VIEWER, path)
        assert body['items'] == []
        text = json.dumps(body, ensure_ascii=False)
        for secret in ('秘密批次', '秘密样品', '秘密计划', '秘密原件', str(other_plan), str(other_run), str(job)):
            assert secret not in text
    summary = get(client, actors, VIEWER, '/api/v1/dashboard/summary')
    assert summary['batch_count'] == 0 and summary['sample_count'] == 0
    assert summary['plan_count'] == 0 and summary['process_count'] == 0 and summary['measurement_count'] == 0
    assert summary['source_file_count'] == 0


def test_viewer_reads_own_counts_but_has_no_write_path(client, actors, db):
    batch = make_batch(db, actors, VIEWER)
    sample = make_sample(db, actors, VIEWER, batch)
    plan = make_plan(db, actors, VIEWER, batch, 'draft', '2026-10-01 10:00:00', '只读计划')
    make_measurement(db, sample, 'suspect', True, '2026-10-02 10:00:00')
    summary = get(client, actors, VIEWER, '/api/v1/dashboard/summary')
    assert summary['batch_count'] == 1 and summary['sample_count'] == 1
    todo = get(client, actors, VIEWER, '/api/v1/dashboard/todo')
    assert ('plan_without_process', plan) in {(item['kind'], item['entity_id']) for item in todo['items']}
    assert todo['counts']['measurement_review'] == 1
    assert get(client, actors, VIEWER, '/api/v1/dashboard/recent-experiments')['items'][0]['can_continue'] is False
    # Dashboard endpoints expose reads only.
    for path in ('/api/v1/dashboard/todo', '/api/v1/dashboard/recent-experiments', '/api/v1/dashboard/recent-data'):
        assert client.post(path, headers=actors[VIEWER]['headers'], json={}).status_code == 405


def test_summary_matches_lists_for_unbatched_and_indirect_visible_records(client, actors, db):
    """Counts must use the list scopes, including owner-only and occurrence links."""
    plan = make_plan(db, actors, OPERATOR, None)
    run = make_process(db, actors, OPERATOR)
    hidden_batch = make_batch(db, actors, OTHER)
    make_plan(db, actors, OPERATOR, hidden_batch)  # owned but invisible through hidden batch
    make_process(db, actors, OPERATOR, hidden_batch)
    source = make_source(db, '通过原件出现记录可见.xlsx')
    db.execute(table('source_file_occurrences').insert().values(
        source_file_id=source, import_item_id=make_item(db, make_job(db, actors, OPERATOR)), owner_user_id=actors[OPERATOR]['user']['user_id'],
        filename='通过原件出现记录可见.xlsx'))
    summary = get(client, actors, OPERATOR, '/api/v1/dashboard/summary')
    for key, path in [('plan_count', 'plans'), ('process_count', 'processes'), ('source_file_count', 'source-files')]:
        response = client.get('/api/v1/' + path, headers=actors[OPERATOR]['headers']).json()
        assert summary[key] == response['meta']['total'], (key, summary, response)
    assert summary['plan_count'] == 1 and summary['process_count'] == 1
    assert summary['source_file_count'] == 1


def test_recent_data_keeps_finished_jobs_and_empty_drafts(client, actors, db):
    job = make_job(db, actors, OPERATOR, '2032-01-01 00:00:00')
    make_item(db, job, 'imported')
    empty = make_job(db, actors, OPERATOR, '2032-01-02 00:00:00')
    items = get(client, actors, OPERATOR, '/api/v1/dashboard/recent-data')['items']
    jobs = {i['entity_id']: i for i in items if i['kind'] == 'import_job'}
    assert {job, empty} <= set(jobs)
    assert jobs[job]['hint'] is None and jobs[empty]['hint'] is None
