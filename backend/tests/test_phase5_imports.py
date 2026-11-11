"""Import-only fifth-round regressions; MySQL writes use rollback fixtures."""
import hashlib
import uuid

import pytest
from sqlalchemy import select
from app.db import table, engine
from app.original_storage import storage_key, store_original, lock_original, originals_root
from test_phase3_imports import (originals, preview, confirm, choice, sample, process,
                                snapshot, row, api, workbook, SCIENTIFIC, IMPORT_TABLES)


def delete(client, actors, job, status=200, role='operator', version=None):
    return api(client, actors, 'delete', f"/{job['job_id']}", status=status, role=role,
               params={'expected_row_version': version or job['row_version']})


def test_delete_pending_and_skipped_without_scientific_changes(db, client, actors, originals):
    for skip in (False, True):
        job = preview(client, actors, [('raw.dat', uuid.uuid4().bytes)])
        if skip:
            confirm(client, actors, job, [choice(job['items'][0], action='skip')])
            job['row_version'] = 2
        before = snapshot(db)
        assert delete(client, actors, job)['deleted']
        api(client, actors, 'get', f"/{job['job_id']}", status=404)
        assert snapshot(db) == before
        # GC must wait until the outer rollback fixture ends, never pre-commit.
        assert (originals / storage_key(job['items'][0]['sha256'])).exists()


@pytest.mark.parametrize('role,status', [('other',404),('admin',404),('viewer',403)])
def test_delete_personal_writer_only(db, client, actors, originals, role, status):
    job = preview(client, actors, [('raw.dat', uuid.uuid4().bytes)])
    before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
    delete(client, actors, job, status=status, role=role)
    assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before


def test_delete_stale_and_formal_tasks_preserves_rows_and_bytes(db, client, actors, originals):
    sid = sample(db, actors)
    for action in ('import', 'original_only'):
        job = preview(client, actors)
        confirm(client, actors, job, [choice(job['items'][0],sid,action=action)])
        before = snapshot(db, SCIENTIFIC + IMPORT_TABLES)
        delete(client, actors, job, status=409)
        delete(client, actors, job, status=409, version=2)
        assert snapshot(db, SCIENTIFIC + IMPORT_TABLES) == before
        assert (originals / storage_key(job['items'][0]['sha256'])).exists()


@pytest.mark.parametrize('name,content', [('rga.dat',b'RGA\x00\xff\x01'),('xps.xml',b'<Chart><Series/></Chart>'),('unknown.bin',b'\x00\xfffull bytes')])
def test_archive_unknown_pending_complete_and_unassociated(db, client, actors, originals, name, content):
    sid = sample(db, actors)
    job = preview(client, actors, [(name,content)])
    item = job['items'][0]
    before = snapshot(db)
    confirm(client, actors, job, [choice(item, action='original_only',sample_id=sid,confirm_associations=True)],status=422)
    assert snapshot(db) == before
    out = confirm(client, actors, job, [choice(item, action='original_only')])
    source = row(db,'source_files',out['items'][0]['source_file_id'])
    assert source['parse_status']=='pending' and source['sample_id'] is None
    assert source['file_sha256']==hashlib.sha256(content).hexdigest()
    assert source['size_bytes']==len(content)
    assert (originals / storage_key(item['sha256'])).read_bytes()==content
    o=table('source_file_occurrences')
    occurrence=db.execute(select(o).where(o.c.import_item_id==item['item_id'])).mappings().one()
    assert occurrence['sample_id'] is None
    for name in ('measurements','measurement_points','instrument_datasets','instrument_channels','instrument_datapoints'):
        assert snapshot(db)[name]==before[name]


def test_delete_shared_bytes_preserves_formal_source(db,client,actors,originals):
    content=workbook();sid=sample(db,actors)
    formal=preview(client,actors,[('formal.xlsx',content)])
    confirm(client,actors,formal,[choice(formal['items'][0],sid)])
    temporary=preview(client,actors,[('temporary.xlsx',content)])
    before=snapshot(db)
    delete(client,actors,temporary)
    assert snapshot(db)==before
    assert (originals / storage_key(temporary['items'][0]['sha256'])).read_bytes()==content


def test_named_options_search_and_scoped_associations(db,client,actors,originals):
    sid=sample(db,actors);pid=process(db,actors,sid)
    foreign=sample(db,actors,'other')
    code=row(db,'samples',sid)['sample_code']
    out=api(client,actors,'get','/options/samples',params={'keyword':code})
    assert [s['sample_id'] for s in out]==[sid]
    out=api(client,actors,'get',f'/options/samples/{sid}')
    assert out['sample']['sample_code']==code
    assert [p['process_id'] for p in out['processes']]==[pid]
    api(client,actors,'get',f'/options/samples/{foreign}',status=404)


def test_post_transaction_gc_and_sha_lock_serialization(originals):
    # No scientific writes or committed fixture data: exercise reset GC directly
    # with unique bytes, checking rollback handling and independent connections.
    content=uuid.uuid4().bytes;sha,key=store_original(content)
    with engine().connect() as first:
        assert lock_original(first,sha)
        with engine().connect() as other:
            assert not lock_original(other,sha,timeout=0)
        first.info.setdefault('ale_original_cleanup',{})[sha]=originals_root()
        first.rollback()
        assert (originals/key).exists()
    assert not (originals/key).exists()
    with engine().connect() as second:
        assert lock_original(second,sha,timeout=0)


def test_actionable_measurement_code_validation_is_atomic(db,client,actors,originals):
    sid=sample(db,actors)
    job=preview(client,actors,[('multi.xlsx',workbook(sheets=2))])
    before=snapshot(db, SCIENTIFIC+IMPORT_TABLES)
    out=confirm(client,actors,job,[choice(job['items'][0],sid,measurement_code='X'*80)],status=422)
    assert snapshot(db,SCIENTIFIC+IMPORT_TABLES)==before
    code='P5-'+uuid.uuid4().hex
    single=preview(client,actors)
    confirm(client,actors,single,[choice(single['items'][0],sid,measurement_code=code)])
    another=preview(client,actors)
    before=snapshot(db,SCIENTIFIC+IMPORT_TABLES)
    confirm(client,actors,another,[choice(another['items'][0],sid,measurement_code=code)],status=409)
    assert snapshot(db,SCIENTIFIC+IMPORT_TABLES)==before
