"""Final deletion acceptance: real MySQL, rollback-only DB, temporary originals."""
import hashlib
import json
import uuid

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import ROOT
from app.db import engine, metadata, table
from app.original_storage import (_has_references, lock_original, storage_key,
                                  store_original)
from test_phase3_imports import (originals, sample, preview, confirm, choice,
                                snapshot, row)
from test_phase5_backend import api, run, code
from test_phase5_imports import delete


def database_fingerprint(connection):
    return {t.name: hashlib.sha256(json.dumps(
        [dict(r) for r in connection.execute(select(t).order_by(*t.primary_key.columns)).mappings()],
        default=str, sort_keys=True).encode()).hexdigest() for t in metadata().tables.values()}


def originals_fingerprint():
    root = ROOT / 'storage' / 'originals'
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture(scope='module', autouse=True)
def unchanged_production():
    with engine().connect() as connection:
        baseline = database_fingerprint(connection)
    original_baseline = originals_fingerprint()
    yield
    with engine().connect() as connection:
        assert database_fingerprint(connection) == baseline
    assert originals_fingerprint() == original_baseline
    print(f'PRODUCTION FINGERPRINTS VERIFIED: {len(baseline)} tables and '
          f'{len(original_baseline)} original files unchanged (rows only; auto-increment counters excluded)')


def insert(db, name, **values):
    return db.execute(table(name).insert().values(**values)).inserted_primary_key[0]


def all_rows(db):
    return snapshot(db, tuple(metadata().tables))


@pytest.mark.parametrize('dependency', ['step', 'binding', 'transition', 'measurement',
                                       'legacy_source', 'attachment', 'issue'])
def test_each_real_process_dependency_blocks_delete_and_archive_retains_it(db, client, actors, dependency):
    sid = sample(db, actors)
    proc = run(client, actors)
    pid = proc['process_id']
    if dependency == 'step':
        insert(db, 'process_steps', process_id=pid, step_index=1, step_kind='other')
    elif dependency == 'binding':
        insert(db, 'process_samples', process_id=pid, sample_id=sid)
    elif dependency == 'transition':
        insert(db, 'sample_transitions', sample_id=sid, process_id=pid,
               to_status='in_process', event_type='load')
    elif dependency in ('measurement', 'legacy_source'):
        source = insert(db, 'source_files', file_sha256=uuid.uuid4().hex * 2,
                        file_name='legacy.xlsx', file_role='instrument_raw', sample_id=sid)
        mid = insert(db, 'measurements', measurement_code=code(), sample_id=sid,
                     process_id=pid, stage='initial', stage_seq=0,
                     source_file_id=source, operator_user_id=actors['operator']['user']['user_id'])
        if dependency == 'legacy_source':
            insert(db, 'measurement_points', measurement_id=mid, point_no=1,
                   source_file_id=source)
            assert row(db, 'measurements', mid)['import_item_id'] is None
    elif dependency == 'attachment':
        insert(db, 'attachments', file_name='history.dat', entity_type='process', entity_id=pid)
    else:
        iid = insert(db, 'issues', issue_code=code()[:32], title='History')
        insert(db, 'issues_links', issue_id=iid, entity_type='process', entity_id=pid, relation='related')
    before = all_rows(db)
    api(client, actors, 'delete', f'/processes/{pid}?expected_row_version=1', status=409)
    assert all_rows(db) == before
    archived = api(client, actors, 'post', f'/processes/{pid}/archive', {'expected_row_version':1})
    assert archived['archived_at'] and archived['log_status'] == proc['log_status']
    after = all_rows(db)
    for name in before:
        if name not in ('processes', 'audit_log'):
            assert after[name] == before[name], name
    api(client, actors, 'delete', f'/processes/{pid}?expected_row_version=2', status=409)
    assert all_rows(db) == after


@pytest.mark.parametrize('role,status', [('viewer',403), ('other',404)])
def test_process_delete_permissions_no_mutation(db, client, actors, role, status):
    proc = run(client, actors)
    before = all_rows(db)
    api(client, actors, 'delete', f"/processes/{proc['process_id']}?expected_row_version=1", role=role, status=status)
    assert all_rows(db) == before


def test_empty_process_delete_cas_archive_and_parent_row_lock(db, client, actors):
    proc = run(client, actors)
    pid = proc['process_id']
    # A second physical connection cannot mutate a parent locked by this request transaction.
    with engine().connect() as second:
        with pytest.raises(DBAPIError) as error:
            second.execute(text('SELECT process_id FROM processes WHERE process_id=:id FOR UPDATE NOWAIT'), {'id':pid})
        assert error.value.orig.args[0] == 3572
    api(client, actors, 'post', f'/processes/{pid}/archive', {'expected_row_version':1})
    before = all_rows(db)
    api(client, actors, 'delete', f'/processes/{pid}?expected_row_version=1', status=409)
    assert all_rows(db) == before
    # Round8: archived records are retained; restore an unused draft explicitly first.
    api(client, actors, 'delete', f'/processes/{pid}?expected_row_version=2', status=409)
    from test_round8_lifecycle import preview as lifecycle_preview, body as lifecycle_body, apply as lifecycle_apply
    info = lifecycle_preview(client,actors,'processes',proc)
    restored = lifecycle_apply(client,actors,'processes',proc,lifecycle_body(info,'restore'))
    api(client, actors, 'delete', f'/processes/{pid}?expected_row_version={restored["row_version"]}', status=204)
    api(client, actors, 'get', f'/processes/{pid}', status=404)


def test_pending_deletion_can_be_rolled_back_without_losing_bytes(db, client, actors, originals):
    job = preview(client, actors, [('pending.dat', uuid.uuid4().bytes)])
    before = all_rows(db)
    sha = job['items'][0]['sha256']
    boundary = db.begin_nested()
    delete(client, actors, job)
    assert (originals / storage_key(sha)).exists()
    boundary.rollback()
    assert all_rows(db) == before
    assert (originals / storage_key(sha)).exists()


def test_delete_integrity_failure_rolls_back_ledger_and_items(db, client, actors, originals):
    job = preview(client, actors, [('skip.dat', uuid.uuid4().bytes)])
    confirm(client, actors, job, [choice(job['items'][0], action='skip')])
    job['row_version'] = 2
    before = all_rows(db)
    def fail_final_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('DELETE FROM import_jobs'):
            raise IntegrityError(statement, {}, RuntimeError('injected final-row FK race'))
    event.listen(db, 'before_cursor_execute', fail_final_delete)
    try:
        delete(client, actors, job, status=409)
    finally:
        event.remove(db, 'before_cursor_execute', fail_final_delete)
    assert all_rows(db) == before
    assert (originals / storage_key(job['items'][0]['sha256'])).exists()


@pytest.mark.parametrize('reference', ['measurement', 'occurrence'])
def test_pending_status_cannot_bypass_formal_references(db, client, actors, originals, reference):
    sid = sample(db, actors)
    job = preview(client, actors, [('original.dat', uuid.uuid4().bytes)])
    item = job['items'][0]
    source = insert(db, 'source_files', file_sha256=item['sha256'], file_name='original.dat', file_role='instrument_raw')
    if reference == 'measurement':
        insert(db, 'measurements', measurement_code=code(), sample_id=sid,
               stage='initial', stage_seq=0, import_item_id=item['item_id'], source_file_id=source)
    else:
        insert(db, 'source_file_occurrences', source_file_id=source, import_item_id=item['item_id'],
               owner_user_id=actors['operator']['user']['user_id'], filename='original.dat')
    before = all_rows(db)
    delete(client, actors, job, status=409)
    assert all_rows(db) == before
    assert (originals / storage_key(item['sha256'])).exists()


@pytest.mark.parametrize('reference', ['import_items', 'source_files', 'attachments', 'batches'])
def test_gc_reference_guard_includes_legacy_and_attachment_sha(db, actors, originals, reference):
    sha, key = store_original(uuid.uuid4().bytes)
    uid = actors['operator']['user']['user_id']
    assert lock_original(db, sha)
    # Use the real MySQL cursor used by pool cleanup, within the rollback fixture.
    with db.connection.cursor() as cursor:
        assert not _has_references(cursor, sha)
    if reference == 'import_items':
        job_id = insert(db, 'import_jobs', owner_user_id=uid)
        insert(db, 'import_items', job_id=job_id, filename='shared.dat', sha256=sha,
               storage_key=key, parse_result={})
    elif reference == 'source_files':
        insert(db, 'source_files', file_sha256=sha, file_name='legacy.dat', file_role='instrument_raw')
    elif reference == 'attachments':
        insert(db, 'attachments', file_sha256=sha, file_name='attachment.dat')
    else:
        insert(db, 'batches', batch_code=code(), batch_name='Legacy ZIP', source_zip_sha256=sha)
    with db.connection.cursor() as cursor:
        assert _has_references(cursor, sha)
    assert (originals / key).exists()


def test_shared_pending_jobs_delete_only_requested_task(db, client, actors, originals):
    content = uuid.uuid4().bytes
    first = preview(client, actors, [('first.dat', content)])
    other = preview(client, actors, [('second.dat', content)], role='other')
    delete(client, actors, first)
    assert row(db, 'import_jobs', other['job_id'])['owner_user_id'] == actors['other']['user']['user_id']
    assert (originals / storage_key(first['items'][0]['sha256'])).read_bytes() == content
    with db.connection.cursor() as cursor:
        assert _has_references(cursor, first['items'][0]['sha256'])


def test_import_delete_sha_race_returns_conflict_then_retries(db, client, actors, originals):
    sha, key = store_original(uuid.uuid4().bytes)
    job_id = insert(db, 'import_jobs', owner_user_id=actors['operator']['user']['user_id'])
    insert(db, 'import_items', job_id=job_id, filename='race.dat', sha256=sha, storage_key=key, parse_result={})
    job = {'job_id':job_id, 'row_version':1}
    with engine().connect() as second:
        assert lock_original(second, sha)
        before = all_rows(db)
        delete(client, actors, job, status=409)
        assert all_rows(db) == before
        assert (originals / key).exists()
    delete(client, actors, job)
    assert (originals / key).exists()  # Physical cleanup awaits transaction completion.
