"""Phase-three imports through production routes and rollback-only real MySQL fixtures.

Every original is redirected into pytest's temporary directory. No DB dependency,
parser, import handler or transaction boundary is replaced by a test double.
"""
import hashlib
import io
import shutil
import uuid
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.db import table
from app.original_storage import storage_key
from app.parsers import parse_file

BASE = '/api/v1/imports'
SCIENTIFIC = ('measurements', 'measurement_points', 'source_files',
              'source_file_occurrences', 'instrument_datasets',
              'instrument_channels', 'instrument_datapoints', 'audit_log')
IMPORT_TABLES = ('import_jobs', 'import_items', 'import_confirmations')


@pytest.fixture(autouse=True)
def originals(monkeypatch, tmp_path):
    root = tmp_path / 'originals'
    monkeypatch.setenv('ALE_ORIGINALS_ROOT', str(root))
    yield root
    if root.exists():
        shutil.rmtree(root)


def unique():
    return 'P3I-' + uuid.uuid4().hex[:20]


def workbook(thicknesses=('1', '2', '3'), *, sheets=1, duplicate_no=False):
    book = Workbook()
    book.properties.identifier = unique()  # Avoid accidental collisions with committed originals.
    for index in range(sheets):
        sheet = book.active if index == 0 else book.create_sheet('Repeat')
        sheet.append(['Company:', 'Eoptics'])
        sheet.append(['No', 'x(mm)', 'y(mm)', 'MSE', 'GOF',
                      'layer_1_thickness(nm)', '1#M_0@Einf', 'AOI',
                      'Intensity', 'Height(mm)', 'FitIter', 'FitTime(ms)'])
        for i, value in enumerate(thicknesses):
            sheet.append([1 if duplicate_no else i + 1, str(i), '-0.125', '1.125',
                          '0.9876543210', value, '1.1234567890123456789', '65',
                          '10.125', '0.25', 7, '12.125'])
        sheet.append(['Average', None, None, None, None, '999'])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def sample(db, actors, role='operator'):
    uid = actors[role]['user']['user_id']
    bid = db.execute(table('batches').insert().values(batch_code=unique(),
                     batch_name='Import tests', owner_user_id=uid)).inserted_primary_key[0]
    return db.execute(table('samples').insert().values(sample_code=unique(), batch_id=bid,
                      sample_type='coupon', owner_user_id=uid)).inserted_primary_key[0]


def process(db, actors, sid=None, role='operator'):
    pid = db.execute(table('processes').insert().values(process_code=unique(),
                     process_mode='other', operator_user_id=actors[role]['user']['user_id']
                     )).inserted_primary_key[0]
    if sid is not None:
        db.execute(table('process_samples').insert().values(process_id=pid, sample_id=sid))
    return pid


def rows(db, name):
    t = table(name)
    return [dict(r) for r in db.execute(select(t).order_by(*t.primary_key.columns)).mappings()]


def snapshot(db, names=SCIENTIFIC):
    return {name: rows(db, name) for name in names}


def row(db, name, id):
    t = table(name)
    return dict(db.execute(select(t).where(list(t.primary_key.columns)[0] == id)).mappings().one())


def api(client, actors, method, path='', *, role='operator', status=200, **kwargs):
    response = getattr(client, method)(BASE + path, headers=actors[role]['headers'], **kwargs)
    assert response.status_code == status, response.text
    return response.json()['data']


def preview(client, actors, files=None, **kwargs):
    files = files if files is not None else [('mapping.xlsx', workbook())]
    return api(client, actors, 'post', '/preview', status=kwargs.pop('status', 201),
               files=[('files[]', (name, content, 'application/octet-stream'))
                      for name, content in files], **kwargs)


def choice(item, sid=None, action='import', **kwargs):
    value = {'item_id': item['item_id'], 'action': action}
    if action == 'import':
        value.update(sample_id=sid, stage='initial', stage_seq=0,
                     confirm_units=True, confirm_associations=True)
    value.update(kwargs)
    return value


def confirm(client, actors, job, choices, version=None, **kwargs):
    return api(client, actors, 'post', f"/{job['job_id']}/confirm",
               json={'expected_row_version': version or job['row_version'], 'items': choices},
               **kwargs)


def assert_pending(db, job):
    current = row(db, 'import_jobs', job['job_id'])
    assert current['status'] == 'draft' and current['row_version'] == job['row_version']
    assert all(row(db, 'import_items', i['item_id'])['status'] == 'pending' for i in job['items'])


def test_multipart_preview_full_parser_snapshot_no_scientific_writes(db, client, actors, originals):
    sid = sample(db, actors)
    pid = process(db, actors, sid)
    name = row(db, 'samples', sid)['sample_code'] + '-n1.9-k0.001.xlsx'
    content = workbook(sheets=2)
    before = snapshot(db)
    out = preview(client, actors, [(name, content)])
    assert snapshot(db) == before
    assert out['owner_user_id'] == actors['operator']['user']['user_id']
    assert out['status'] == 'draft' and out['row_version'] == 1
    item = out['items'][0]
    assert item['parse_result'] == parse_file(content, name)
    assert len(item['parse_result']['blocks']) == 2
    assert item['status'] == 'pending' and item['confirmation'] is None and item['result'] is None
    assert 'storage_key' not in item
    assert item['sha256'] == hashlib.sha256(content).hexdigest()
    assert (originals / storage_key(item['sha256'])).read_bytes() == content
    hints = item['suggestions']
    assert hints['requires_manual_selection'] and not hints['association_is_fact']
    assert sid in [s['sample_id'] for s in hints['samples']]
    candidate = next(s for s in hints['samples'] if s['sample_id'] == sid)
    assert [p['process_id'] for p in candidate['processes']] == [pid]
    assert api(client, actors, 'get', f"/{out['job_id']}") == out


def test_manual_confirmation_all_points_metadata_and_exact_summaries(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors)
    item = job['items'][0]
    block = item['parse_result']['blocks'][0]
    selected = choice(item, sid, measurement_code=unique(), notes='Reviewed raw map')
    out = confirm(client, actors, job, [selected])
    assert out['pending_count'] == 0 and out['status'] == 'completed' and out['row_version'] == 2
    mid = out['items'][0]['measurement_ids'][0]
    measurement = row(db, 'measurements', mid)
    assert measurement['sample_id'] == sid and measurement['stage_seq'] == 0
    assert measurement['measurement_code'] == selected['measurement_code']
    assert measurement['operator_user_id'] == actors['operator']['user']['user_id']
    assert measurement['point_count'] == 3 and measurement['optical_model_id'] is None
    assert measurement['thickness_mean_nm'] == Decimal('2')
    assert measurement['thickness_sd_nm'] == Decimal('1')
    assert measurement['thickness_min_nm'] == Decimal('1')
    assert measurement['thickness_max_nm'] == Decimal('3')
    assert measurement['mse_mean'] == measurement['mse_max'] == Decimal('1.125')
    # GOF point precision is valid, but summary DECIMAL(14,8) cannot represent it.
    assert measurement['gof_mean'] is None
    provenance = measurement['provenance']
    assert provenance['statistics'] == block['statistics']
    assert provenance['metadata'] == block['metadata']
    assert provenance['summary_not_exactly_representable'] == ['gof_mean']
    assert provenance['locator'] == block['locator']
    assert provenance['parser'] == item['parse_result']['parser']
    assert provenance['parser_version'] == item['parse_result']['version']
    assert provenance['warnings'] == block['warnings']
    assert provenance['confirmation']['notes'] == selected['notes']
    actual = [r for r in rows(db, 'measurement_points') if r['measurement_id'] == mid]
    assert len(actual) == len(block['points'])
    for actual_point, expected in zip(actual, block['points']):
        for key, value in expected.items():
            if key not in actual_point:
                continue
            if isinstance(actual_point[key], Decimal):
                assert actual_point[key] == Decimal(value), key
            else:
                assert actual_point[key] == value, key
        assert actual_point['source_file_id'] == measurement['source_file_id']
    occurrence = next(r for r in rows(db, 'source_file_occurrences') if r['import_item_id'] == item['item_id'])
    assert occurrence['sample_id'] == sid and occurrence['filename'] == item['filename']
    assert occurrence['owner_user_id'] == actors['operator']['user']['user_id']
    assert any(r['action'] == 'insert' and r['entity_type'] == 'measurement'
               and r['entity_id'] == mid for r in rows(db, 'audit_log'))


def test_derived_summary_never_silently_rounds(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors, [('thirds.xlsx', workbook(('1', '2', '2')))])
    out = confirm(client, actors, job, [choice(job['items'][0], sid)])
    m = row(db, 'measurements', out['items'][0]['measurement_ids'][0])
    assert m['thickness_mean_nm'] is None and m['thickness_sd_nm'] is None
    assert m['thickness_min_nm'] == Decimal('1') and m['thickness_max_nm'] == Decimal('2')
    assert {'thickness_mean_nm', 'thickness_sd_nm', 'gof_mean'} == set(m['provenance']['summary_not_exactly_representable'])
    assert m['provenance']['statistics'] == job['items'][0]['parse_result']['blocks'][0]['statistics']


def test_partial_selection_pending_then_incremental_version(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors, [('one.xlsx', workbook()), ('two.xlsx', workbook(('4', '5')))])
    first = confirm(client, actors, job, [choice(job['items'][0], sid)])
    assert first['row_version'] == 2 and first['pending_count'] == 1 and first['status'] == 'draft'
    pending = row(db, 'import_items', job['items'][1]['item_id'])
    assert pending['status'] == 'pending' and pending['result'] is None and pending['confirmation'] is None
    second_choice = choice(job['items'][1], action='original_only')
    confirm(client, actors, job, [second_choice], status=409)
    second = confirm(client, actors, job, [second_choice], version=2)
    assert second['row_version'] == 3 and second['pending_count'] == 0 and second['status'] == 'completed'
    assert row(db, 'import_items', job['items'][0]['item_id'])['status'] == 'imported'
    assert row(db, 'import_items', job['items'][1]['item_id'])['status'] == 'original_only'
    assert len([r for r in rows(db, 'import_confirmations') if r['job_id'] == job['job_id']]) == 2


def test_identical_normalized_replay_after_later_version_and_different_409(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors, [('one.xlsx', workbook()), ('two.dat', b'other')])
    first_choice = choice(job['items'][0], sid, notes='  reviewed  ')
    first = confirm(client, actors, job, [first_choice])
    confirm(client, actors, job, [choice(job['items'][1], action='skip')], version=2)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    replay_choice = {**first_choice, 'notes': 'reviewed', 'process_id': None}
    assert confirm(client, actors, job, [replay_choice]) == first
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    confirm(client, actors, job, [{**first_choice, 'notes': 'different'}], status=409)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


def test_imported_choice_immutable_even_with_current_version(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors)
    selected = choice(job['items'][0], sid)
    confirm(client, actors, job, [selected])
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    for changed in [choice(job['items'][0], action='skip'), {**selected, 'stage': 'final'},
                    {**selected, 'sample_id': sample(db, actors)}]:
        confirm(client, actors, job, [changed], version=2, status=409)
        assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


@pytest.mark.parametrize('across_jobs', [False, True], ids=['within-job', 'across-jobs'])
def test_duplicate_sha_requires_reason_and_creates_independent_measurement(db, client, actors, across_jobs):
    sid = sample(db, actors)
    content = workbook()
    job = preview(client, actors, [('one.xlsx', content)] if across_jobs else
                  [('one.xlsx', content), ('renamed.xlsx', content)])
    first = confirm(client, actors, job, [choice(job['items'][0], sid)])
    mid = first['items'][0]['measurement_ids'][0]
    second_job = preview(client, actors, [('renamed.xlsx', content)]) if across_jobs else job
    item = second_job['items'][0 if across_jobs else 1]
    version = 1 if across_jobs else 2
    selected = choice(item, sid)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    for fields in [{}, {'confirm_duplicate': True}, {'duplicate_reason': 'Independent repeat'},
                   {'confirm_duplicate': True, 'duplicate_reason': '   '}]:
        confirm(client, actors, second_job, [{**selected, **fields}], version=version,
                status=422 if fields.get('duplicate_reason') == '   ' else 409)
        assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    out = confirm(client, actors, second_job,
                  [{**selected, 'confirm_duplicate': True, 'duplicate_reason': 'Independent repeat'}],
                  version=version)
    newer = row(db, 'measurements', out['items'][0]['measurement_ids'][0])
    original = row(db, 'measurements', mid)
    assert newer['measurement_id'] != mid and newer['source_file_id'] == original['source_file_id']
    assert newer['is_current'] and original['is_current']
    assert newer['supersedes_measurement_id'] is None and original['supersedes_measurement_id'] is None
    assert out['items'][0]['warnings'] == ['Explicit duplicate imported as independent measurement; no supersession']
    assert newer['provenance']['confirmation']['duplicate_reason'] == 'Independent repeat'


@pytest.mark.parametrize('point_only', [False, True], ids=['measurement-source', 'legacy-point-source'])
@pytest.mark.parametrize('confirm_foreign_duplicate', [False, True])
def test_invisible_owner_sha_never_changes_confirmation(db, client, actors, point_only, confirm_foreign_duplicate):
    content = workbook()
    foreign_sid = sample(db, actors, 'other')
    foreign = preview(client, actors, [('foreign.xlsx', content)], role='other')
    first = confirm(client, actors, foreign,
                    [choice(foreign['items'][0], foreign_sid)], role='other')
    foreign_mid = first['items'][0]['measurement_ids'][0]
    if point_only:
        m = table('measurements')
        db.execute(m.update().where(m.c.measurement_id == foreign_mid).values(source_file_id=None))
    sid = sample(db, actors)
    own = preview(client, actors, [('own.xlsx', content)])
    assert own['status'] == 'draft' and own['items'][0]['status'] == 'pending'
    assert own['items'][0]['parse_result'] == parse_file(content, 'own.xlsx')
    selected = choice(own['items'][0], sid)
    if confirm_foreign_duplicate:
        selected.update(confirm_duplicate=True, duplicate_reason='Uploader supplied reason')
    out = confirm(client, actors, own, [selected])
    assert out['status'] == 'completed' and out['items'][0]['warnings'] == []
    assert out['items'][0]['source_file_id'] == first['items'][0]['source_file_id']
    assert out['items'][0]['measurement_ids'] != [foreign_mid]
    # Once visible scientific data exists, both source routes must require consent.
    again = preview(client, actors, [('again.xlsx', content)])
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    confirm(client, actors, again, [choice(again['items'][0], sid)], status=409)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


def test_worker_failure_draft_retains_original_and_blocks_scientific_import(db, client, actors, monkeypatch, originals):
    from app import imports
    from app.import_worker import _failure
    async def failed(content, filename):
        return _failure(content, filename, 'parser_timeout', 'Preview parsing exceeded 20 seconds; retain original or retry.')
    monkeypatch.setattr(imports, 'parse_preview', failed)
    content = workbook()
    sid = sample(db, actors)
    job = preview(client, actors, [('timeout.xlsx', content)])
    item = job['items'][0]
    assert item['parse_result']['blocking_issues'][0]['code'] == 'parser_timeout'
    assert item['status'] == 'pending' and job['status'] == 'draft'
    assert (originals / storage_key(item['sha256'])).read_bytes() == content
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    confirm(client, actors, job, [choice(item, sid)], status=422)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    out = confirm(client, actors, job, [choice(item, action='original_only')])
    assert out['items'][0]['measurement_ids'] == []
    # Lock files are still rejected if the parser process is unavailable.
    preview(client, actors, [('~$lock.xlsx', b'lock')], status=422)


def test_visible_legacy_point_source_requires_duplicate_reason(db, client, actors):
    sid = sample(db, actors)
    content = workbook()
    job = preview(client, actors, [('first.xlsx', content)])
    first = confirm(client, actors, job, [choice(job['items'][0], sid)])
    m = table('measurements')
    db.execute(m.update().where(m.c.measurement_id == first['items'][0]['measurement_ids'][0]).values(source_file_id=None))
    again = preview(client, actors, [('again.xlsx', content)])
    confirm(client, actors, again, [choice(again['items'][0], sid)], status=409)


def test_same_filename_different_sha_warning_personal_and_within_batch(client, actors):
    name = unique() + '.dat'
    preview(client, actors, [(name, b'first')], role='other')
    own = preview(client, actors, [(name, b'second')])
    assert 'same_name_different_sha' not in {w['code'] for w in own['items'][0]['parse_result']['warnings']}
    repeated = preview(client, actors, [(name, b'third'), (name, b'fourth')])
    assert all('same_name_different_sha' in {w['code'] for w in i['parse_result']['warnings']}
               for i in repeated['items'])
    assert repeated['items'][0]['sha256'] != repeated['items'][1]['sha256']


@pytest.mark.parametrize('role', ['other', 'admin', 'viewer'])
def test_jobs_personal_even_admin_cannot_read_or_confirm(db, client, actors, role):
    job = preview(client, actors)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    api(client, actors, 'get', f"/{job['job_id']}", role=role, status=404)
    confirm(client, actors, job, [choice(job['items'][0], action='skip')], role=role,
            status=403 if role == 'viewer' else 404)
    assert job['job_id'] not in [j['job_id'] for j in api(client, actors, 'get', role=role)]
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


def test_suggestions_never_leak_foreign_samples_even_to_admin(db, client, actors):
    foreign = sample(db, actors)
    name = row(db, 'samples', foreign)['sample_code'] + '.xlsx'
    job = preview(client, actors, [(name, workbook())], role='admin')
    assert foreign not in [s['sample_id'] for s in job['items'][0]['suggestions']['samples']]


def test_process_must_be_bound_to_selected_sample(db, client, actors):
    sid = sample(db, actors)
    other_sid = sample(db, actors)
    pid = process(db, actors, other_sid)
    job = preview(client, actors)
    selected = choice(job['items'][0], sid, process_id=pid)
    before = snapshot(db)
    confirm(client, actors, job, [selected], status=422)
    assert snapshot(db) == before
    db.execute(table('process_samples').insert().values(process_id=pid, sample_id=sid))
    out = confirm(client, actors, job, [selected])
    assert row(db, 'measurements', out['items'][0]['measurement_ids'][0])['process_id'] == pid


def test_forbidden_sample_and_process_scope_rolls_back(db, client, actors):
    sid = sample(db, actors)
    foreign_sid = sample(db, actors, 'other')
    foreign_pid = process(db, actors, foreign_sid, 'other')
    job = preview(client, actors)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    for selected in [choice(job['items'][0], foreign_sid),
                     choice(job['items'][0], sid, process_id=foreign_pid),
                     choice(job['items'][0], action='original_only', sample_id=foreign_sid,
                            confirm_associations=True)]:
        confirm(client, actors, job, [selected], status=404)
        assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


@pytest.mark.parametrize('missing', ['sample_id', 'stage', 'confirm_units', 'confirm_associations'])
def test_manual_selection_and_acknowledgements_required(db, client, actors, missing):
    sid = sample(db, actors)
    job = preview(client, actors)
    selected = choice(job['items'][0], sid)
    selected.pop(missing)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    confirm(client, actors, job, [selected], status=422)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


@pytest.mark.parametrize('kind', ['duplicate-points', 'unrepresentable-decimal', 'invalid-thickness'])
def test_blocking_issues_retain_original_only_without_measurement(db, client, actors, kind):
    content = workbook(duplicate_no=True) if kind == 'duplicate-points' else workbook(
        ('30.0000001',) if kind == 'unrepresentable-decimal' else ('NaN',))
    sid = sample(db, actors)
    job = preview(client, actors, [('blocked.xlsx', content)])
    item = job['items'][0]
    assert item['parse_result']['status'] == 'needs_confirmation'
    assert item['parse_result']['blocks'][0]['blocking_issues']
    before = snapshot(db)
    confirm(client, actors, job, [choice(item, sid)], status=422)
    assert snapshot(db) == before
    out = confirm(client, actors, job, [choice(item, action='original_only')])
    assert out['items'][0]['measurement_ids'] == []
    assert rows(db, 'measurements') == before['measurements']
    assert rows(db, 'measurement_points') == before['measurement_points']
    assert row(db, 'import_items', item['item_id'])['parse_result'] == item['parse_result']


@pytest.mark.parametrize('name', ['../escape.xlsx', '/absolute.xlsx', 'C:escape.xlsx',
                                 'folder/child.xlsx', '..', '.', 'a' * 256 + '.xlsx'])
def test_malformed_upload_paths_rejected_atomically(db, client, actors, originals, name):
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    preview(client, actors, [('valid.dat', b'first'), (name, b'invalid')], status=422)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    assert not list(originals.rglob('*'))


def test_lock_file_rejects_entire_preview_before_originals(db, client, actors, originals):
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    preview(client, actors, [('valid.xlsx', workbook()), ('~$locked.xlsx', b'lock')], status=422)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    assert not list(originals.rglob('*'))


def test_zipbomb_expansion_blocked_without_extraction_or_dataset(db, client, actors, originals):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open('xl/worksheets/bomb.xml', 'w') as member:
            for _ in range(101):
                member.write(b'x' * 1024 * 1024)
    content = stream.getvalue()
    assert len(content) < 1024 * 1024
    sid = sample(db, actors)
    before = snapshot(db)
    job = preview(client, actors, [('bomb.xlsx', content)])
    item = job['items'][0]
    assert item['parse_result']['blocks'] == []
    assert {i['code'] for i in item['parse_result']['blocking_issues']} == {'expanded_size_limit'}
    assert snapshot(db) == before
    confirm(client, actors, job, [choice(item, sid)], status=422)
    confirm(client, actors, job, [choice(item, action='original_only')])
    assert rows(db, 'instrument_datasets') == before['instrument_datasets']
    assert [p for p in originals.rglob('*') if p.is_file()] == [originals / storage_key(item['sha256'])]


def test_twenty_file_boundary_and_twenty_first_rejection(db, client, actors):
    before = snapshot(db)
    accepted = preview(client, actors, [(f'{i}.dat', str(i).encode()) for i in range(20)])
    assert len(accepted['items']) == 20 and snapshot(db) == before
    all_before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    preview(client, actors, [(f'{i}.dat', b'x') for i in range(21)], status=400)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == all_before


def test_real_per_file_twenty_mib_boundary_and_oversize(db, client, actors, originals):
    boundary = b'x' * (20 * 1024 * 1024)
    accepted = preview(client, actors, [('limit.bin', boundary)])
    assert accepted['items'][0]['sha256'] == hashlib.sha256(boundary).hexdigest()
    assert (originals / storage_key(accepted['items'][0]['sha256'])).stat().st_size == len(boundary)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    paths = set(originals.rglob('*'))
    preview(client, actors, [('too-large.bin', boundary + b'x')], status=413)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before and set(originals.rglob('*')) == paths


def test_real_total_hundred_mib_boundary_and_overflow(db, client, actors, originals):
    part = b'y' * (20 * 1024 * 1024)
    files = [(f'{i}.bin', part) for i in range(5)]
    accepted = preview(client, actors, files)
    assert len(accepted['items']) == 5
    assert len({i['sha256'] for i in accepted['items']}) == 1
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    paths = set(originals.rglob('*'))
    preview(client, actors, files + [('overflow.bin', b'z')], status=413)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before and set(originals.rglob('*')) == paths


@pytest.mark.parametrize('field', ['wrong', 'files'])
def test_multipart_requires_exact_files_array_field(db, client, actors, field):
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    api(client, actors, 'post', '/preview', status=422, files=[(field, ('a.dat', b'raw'))])
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


def test_viewer_upload_and_unauthenticated_preview_denied(db, client, actors, originals):
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    preview(client, actors, [('raw.dat', b'raw')], role='viewer', status=403)
    assert client.post(BASE + '/preview', files=[('files[]', ('raw.dat', b'raw'))]).status_code == 401
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before and not list(originals.rglob('*'))


def test_selected_valid_then_invalid_rolls_back_every_record(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors, [('valid.xlsx', workbook()), ('invalid.xlsx', workbook(('NaN',)))])
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    confirm(client, actors, job, [choice(i, sid) for i in job['items']], status=422)
    # Includes sources, occurrences, points, measurements, audit and confirmation ledger.
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    assert_pending(db, job)
    out = confirm(client, actors, job, [choice(job['items'][0], sid)])
    assert len(out['items'][0]['measurement_ids']) == 1 and out['pending_count'] == 1


@pytest.mark.parametrize('damage', ['corrupt', 'missing', 'symlink'])
def test_original_hash_integrity_prevents_confirmation(db, client, actors, originals, tmp_path, damage):
    sid = sample(db, actors)
    job = preview(client, actors)
    item = job['items'][0]
    path = originals / storage_key(item['sha256'])
    if damage == 'corrupt':
        path.write_bytes(b'tampered')
    elif damage == 'missing':
        path.unlink()
    else:
        other = tmp_path / 'outside'
        other.write_bytes(b'symlink-target')
        path.unlink()
        path.symlink_to(other)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    confirm(client, actors, job, [choice(item, sid)], status=409)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    assert_pending(db, job)


def test_preview_does_not_overwrite_corrupt_existing_original(db, client, actors, originals):
    content = workbook()
    job = preview(client, actors, [('first.xlsx', content)])
    path = originals / storage_key(job['items'][0]['sha256'])
    path.write_bytes(b'corrupt-existing')
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    preview(client, actors, [('second.xlsx', content)], status=409)
    assert path.read_bytes() == b'corrupt-existing'
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


@pytest.mark.parametrize('name,content', [
    ('rga.txt', b'unknown RGA content'),
    ('legacy.vgd', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1raw'),
    ('chart.xml', b'<Chart><Series/><AxisX Title="Binding energy"/></Chart>'),
    ('broken.xml', b'<broken'),
])
def test_unknown_formats_original_only_never_instrument_dataset(db, client, actors, name, content):
    sid = sample(db, actors)
    before = snapshot(db)
    job = preview(client, actors, [(name, content)])
    item = job['items'][0]
    assert item['parse_result']['blocks'] == [] and item['parse_result']['status'] == 'original_only'
    confirm(client, actors, job, [choice(item, sid)], status=422)
    assert snapshot(db) == before
    out = confirm(client, actors, job, [choice(item, action='original_only')])
    assert out['items'][0]['measurement_ids'] == []
    for table_name in ('measurements', 'measurement_points', 'instrument_datasets',
                       'instrument_channels', 'instrument_datapoints'):
        assert rows(db, table_name) == before[table_name]


def test_multi_block_import_creates_distinct_measurements_with_full_locators(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors, [('multi.xlsx', workbook(sheets=2))])
    out = confirm(client, actors, job, [choice(job['items'][0], sid)])
    ids = out['items'][0]['measurement_ids']
    assert len(ids) == 2 and len(set(ids)) == 2
    measurements = [row(db, 'measurements', mid) for mid in ids]
    assert len({m['measurement_code'] for m in measurements}) == 2
    assert {m['provenance']['locator']['sheet'] for m in measurements} == {'Sheet', 'Repeat'}
    assert all(m['point_count'] == 3 for m in measurements)


def test_skip_creates_no_source_or_measurements_and_other_job_item_rejected(db, client, actors):
    job = preview(client, actors)
    other = preview(client, actors)
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    confirm(client, actors, job, [choice(other['items'][0], action='skip')], status=404)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
    out = confirm(client, actors, job, [choice(job['items'][0], action='skip')])
    assert out['status'] == 'completed' and out['items'][0]['measurement_ids'] == []
    assert snapshot(db) == {k: before[k] for k in SCIENTIFIC}


def test_confirmation_extra_fields_and_duplicate_selection_rejected(db, client, actors):
    job = preview(client, actors)
    selected = choice(job['items'][0], action='skip')
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    for body in [dict(expected_row_version=1, items=[selected, selected]),
                 dict(expected_row_version=1, items=[{**selected, 'owner_user_id': 1}]),
                 dict(expected_row_version=1, items=[selected], status='completed'),
                 dict(expected_row_version=1, items=[])]:
        api(client, actors, 'post', f"/{job['job_id']}/confirm", json=body, status=422)
        assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


def test_outliers_preserved_in_points_and_summary_not_silently_excluded(db, client, actors):
    sid = sample(db, actors)
    job = preview(client, actors, [('outlier.xlsx', workbook(('1', '1', '1', '1', '1', '100')))])
    block = job['items'][0]['parse_result']['blocks'][0]
    assert block['points'][-1]['is_outlier'] and block['statistics']['includes_outliers']
    out = confirm(client, actors, job, [choice(job['items'][0], sid)])
    mid = out['items'][0]['measurement_ids'][0]
    measurement = row(db, 'measurements', mid)
    points = [r for r in rows(db, 'measurement_points') if r['measurement_id'] == mid]
    assert len(points) == 6 and points[-1]['thickness_nm'] == Decimal('100')
    assert points[-1]['is_outlier'] and points[-1]['outlier_note'] == block['points'][-1]['outlier_note']
    assert measurement['quality_flag'] == 'suspect' and measurement['thickness_mean_nm'] == Decimal('17.5')
    assert measurement['provenance']['statistics'] == block['statistics']
