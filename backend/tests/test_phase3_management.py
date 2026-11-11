"""Management API checks using shared real-MySQL rollback fixtures."""
import hashlib
import uuid
from urllib.parse import unquote

import pytest
from sqlalchemy import select
from app.db import metadata, table
from app.main import app
from app import measurement_management as management

BASE = '/api/v1'


@pytest.fixture(autouse=True)
def management_routes():
    if 'source_file_occurrences' not in metadata().tables:
        pytest.skip('Phase-three migration has not been applied')
    # The parent registers this router in production; support independent work too.
    before = list(app.router.routes)
    if not any(getattr(r, 'path', '') == BASE + '/measurements' for r in before):
        app.include_router(management.router)
        added = app.router.routes[len(before):]
        # Register ahead of the production SPA catch-all.
        app.router.routes[:] = added + before
    yield
    app.router.routes[:] = before


def code():
    return 'P3M-' + uuid.uuid4().hex[:20]


def call(client, actors, method, path, body=None, role='operator', status=200):
    response = getattr(client, method)(BASE + path, headers=actors[role]['headers'],
                                      **({'json': body} if body is not None else {}))
    assert response.status_code == status, response.text
    return response.json()['data']


def sample(db, actors, role='operator'):
    uid = actors[role]['user']['user_id']
    bid = db.execute(table('batches').insert().values(batch_code=code(), batch_name='Management',
                                                    owner_user_id=uid)).inserted_primary_key[0]
    return db.execute(table('samples').insert().values(sample_code=code(), batch_id=bid,
                      sample_type='coupon', owner_user_id=uid)).inserted_primary_key[0]


def measurement(db, sid, **values):
    return db.execute(table('measurements').insert().values(measurement_code=code(), sample_id=sid,
                      stage='initial', **values)).inserted_primary_key[0]


def snapshot(db, name, key, id):
    t = table(name)
    return dict(db.execute(select(t).where(t.c[key] == id)).mappings().one())


def test_quality_validation_scope_and_scientific_immutability(db, client, actors):
    sid = sample(db, actors)
    mid = measurement(db, sid, thickness_mean_nm='12.345678', provenance={'sheet': 'raw'})
    t = table('measurement_points')
    pid = db.execute(t.insert().values(measurement_id=mid, point_no=1, thickness_nm='12.345678',
                     raw_values={'thickness': '12.345678'}, source_row=8)).inserted_primary_key[0]
    before = snapshot(db, 'measurements', 'measurement_id', mid)
    point = snapshot(db, 'measurement_points', 'point_id', pid)
    for body in [
        {'quality_flag': 'suspect'},
        {'expected_row_version': True, 'quality_flag': 'suspect'},
        {'expected_row_version': '1', 'quality_flag': 'suspect'},
        {'expected_row_version': 1, 'quality_flag': None},
        {'expected_row_version': 1, 'thickness_mean_nm': '9.000000'},
        {'expected_row_version': 1, 'stage': 'final'},
        {'expected_row_version': 1},
    ]:
        call(client, actors, 'patch', f'/measurements/{mid}', body, status=422)
        assert snapshot(db, 'measurements', 'measurement_id', mid) == before
    call(client, actors, 'get', f'/measurements/{mid}', role='other', status=404)
    call(client, actors, 'get', f'/measurements/{mid}/points', role='other', status=404)
    call(client, actors, 'patch', f'/measurements/{mid}',
         {'expected_row_version': 1, 'quality_flag': 'suspect'}, role='viewer', status=403)
    out = call(client, actors, 'patch', f'/measurements/{mid}',
               {'expected_row_version': 1, 'quality_flag': 'suspect', 'quality_note': 'Inspect fit'})
    assert out['row_version'] == 2 and out['quality_flag'] == 'suspect'
    assert out['thickness_mean_nm'] == '12.345678'
    assert out['provenance'] == {'sheet': 'raw'} and out['points'][0]['raw_values'] == point['raw_values']
    assert snapshot(db, 'measurement_points', 'point_id', pid) == point
    call(client, actors, 'patch', f'/measurements/{mid}',
         {'expected_row_version': 1, 'quality_note': None}, status=409)
    rows = call(client, actors, 'get', f'/measurements?sample_id={sid}&current=true&quality=suspect')
    assert [r['measurement_id'] for r in rows] == [mid]


def test_supersession_atomic_versions_dependencies_and_chain(db, client, actors):
    sid = sample(db, actors)
    old, new, newest = [measurement(db, sid) for _ in range(3)]
    foreign = measurement(db, sample(db, actors))
    dr = table('derived_results')
    rid = db.execute(dr.insert().values(result_code=code(), result_kind='uniformity', sample_id=sid,
                    before_measurement_id=old)).inserted_primary_key[0]
    body = dict(replacement_measurement_id=new, expected_row_version=1,
                expected_replacement_row_version=1, reason='Remeasured with better fit')
    for changes, status in [({'expected_replacement_row_version': 2}, 409),
                            ({'replacement_measurement_id': foreign}, 422),
                            ({'replacement_measurement_id': old}, 422),
                            ({'reason': '   '}, 422), ({'is_current': False}, 422)]:
        call(client, actors, 'post', f'/measurements/{old}/supersede', {**body, **changes}, status=status)
        assert snapshot(db, 'measurements', 'measurement_id', old)['row_version'] == 1
        assert snapshot(db, 'measurements', 'measurement_id', new)['row_version'] == 1
        assert snapshot(db, 'derived_results', 'result_id', rid)['is_valid']
    out = call(client, actors, 'post', f'/measurements/{old}/supersede', body)
    assert out['is_current'] is False and out['row_version'] == 2
    assert out['supersede_reason'] == body['reason']
    assert out['replacement']['supersedes_measurement_id'] == old
    assert out['replacement']['row_version'] == 2
    assert not snapshot(db, 'derived_results', 'result_id', rid)['is_valid']
    call(client, actors, 'post', f'/measurements/{old}/supersede', body, status=409)
    call(client, actors, 'post', f'/measurements/{new}/supersede',
         {**body, 'replacement_measurement_id': newest, 'expected_row_version': 2})
    assert snapshot(db, 'measurements', 'measurement_id', newest)['supersedes_measurement_id'] == new
    call(client, actors, 'post', f'/measurements/{newest}/supersede',
         {**body, 'replacement_measurement_id': old}, status=409)


def occurrence(db, actors, fid, filename, role, sid=None):
    uid = actors[role]['user']['user_id']
    job = db.execute(table('import_jobs').insert().values(owner_user_id=uid)).inserted_primary_key[0]
    sha = snapshot(db, 'source_files', 'file_id', fid)['file_sha256']
    item = db.execute(table('import_items').insert().values(job_id=job, filename=filename, sha256=sha,
                      storage_key=sha, parse_result={})).inserted_primary_key[0]
    return db.execute(table('source_file_occurrences').insert().values(source_file_id=fid,
        import_item_id=item, owner_user_id=uid, sample_id=sid, filename=filename)).inserted_primary_key[0]


def test_original_dedup_occurrence_visibility_and_verified_content(db, client, actors, monkeypatch):
    content = b'immutable original'
    sha = hashlib.sha256(content).hexdigest()
    fid = db.execute(table('source_files').insert().values(file_sha256=sha,
                     file_name='OTHER-OWNER-SECRET.xlsx', rel_path='../../must-not-read',
                     file_role='instrument_raw')).inserted_primary_key[0]
    occurrence(db, actors, fid, 'OTHER-OWNER-SECRET.xlsx', 'other')
    call(client, actors, 'get', f'/source-files/{fid}', status=404)
    own = occurrence(db, actors, fid, 'authorized original.xlsx', 'operator')
    out = call(client, actors, 'get', f'/source-files/{fid}')
    assert out['file_name'] == 'authorized original.xlsx'
    assert [o['occurrence_id'] for o in out['occurrences']] == [own]
    assert 'OTHER-OWNER-SECRET' not in str(out) and 'rel_path' not in out
    rows = call(client, actors, 'get', '/source-files')
    assert next(r for r in rows if r['file_id'] == fid)['file_name'] == 'authorized original.xlsx'
    requested = []
    def verified(key):
        requested.append(key)
        return content
    monkeypatch.setattr(management, 'read_verified', verified)
    response = client.get(BASE + f'/source-files/{fid}/content', headers=actors['operator']['headers'])
    assert response.status_code == 200 and response.content == content and requested == [sha]
    assert 'authorized original.xlsx' in unquote(response.headers['content-disposition'])
    def corrupt(key):
        raise ValueError('hash mismatch')
    monkeypatch.setattr(management, 'read_verified', corrupt)
    call(client, actors, 'get', f'/source-files/{fid}/content', status=409)
    call(client, actors, 'get', f'/source-files/{fid}/content', role='viewer', status=404)


def test_legacy_sources_and_instrument_dataset_read_scope(db, client, actors):
    sid = sample(db, actors)
    sha = hashlib.sha256(code().encode()).hexdigest()
    fid = db.execute(table('source_files').insert().values(file_sha256=sha,
                     file_name='legacy.vgd', file_role='xps_raw')).inserted_primary_key[0]
    uid = actors['operator']['user']['user_id']
    ds = table('instrument_datasets')
    did = db.execute(ds.insert().values(dataset_code=code(), instrument_type='xps', sample_id=sid,
                     source_file_id=fid, operator_user_id=uid)).inserted_primary_key[0]
    channel = db.execute(table('instrument_channels').insert().values(dataset_id=did,
                        channel_code='Si2p')).inserted_primary_key[0]
    db.execute(table('instrument_datapoints').insert().values(channel_id=channel,
               point_index=1, x_value='100.00000000', y_value='15.00000000'))
    assert call(client, actors, 'get', f'/source-files/{fid}')['file_name'] == 'legacy.vgd'
    call(client, actors, 'get', f'/source-files/{fid}', role='other', status=404)
    out = call(client, actors, 'get', f'/instrument-datasets/{did}?include_channels=true&include_datapoints=true')
    assert out['channels'][0]['datapoints'][0]['x_value'] == '100.00000000'
    call(client, actors, 'get', f'/instrument-datasets/{did}', role='other', status=404)
    unresolved = db.execute(ds.insert().values(dataset_code=code(), instrument_type='rga',
                            operator_user_id=uid)).inserted_primary_key[0]
    assert call(client, actors, 'get', f'/instrument-datasets/{unresolved}')['sample_id'] is None
    call(client, actors, 'get', f'/instrument-datasets/{unresolved}', role='other', status=404)
    assert call(client, actors, 'get', f'/instrument-datasets?sample_id={sid}')[0]['dataset_id'] == did
    call(client, actors, 'post', '/instrument-datasets', {}, status=405)
