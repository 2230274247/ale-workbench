"""Real concurrent MySQL sessions, no committed fixtures or retained originals."""
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.db import engine, table
from app.imports import Confirmation, confirm_job
from app.original_storage import store_original
from app.parsers import parse_file


def test_concurrent_confirm_waits_for_job_lock_and_rollback_removes_all(tmp_path,monkeypatch):
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path))
    tag='P3ROLL-'+uuid.uuid4().hex
    entered=threading.Event();done=threading.Event()
    with engine().connect() as first:
        transaction=first.begin()
        try:
            uid=first.execute(table('users').insert().values(username=tag,role='operator')).inserted_primary_key[0]
            job=first.execute(table('import_jobs').insert().values(owner_user_id=uid)).inserted_primary_key[0]
            content=tag.encode();sha,key=store_original(content)
            item=first.execute(table('import_items').insert().values(job_id=job,filename='original.bin',sha256=sha,storage_key=key,parse_result=parse_file(content,'original.bin'))).inserted_primary_key[0]
            user={'user_id':uid,'role':'operator'}
            body=Confirmation(expected_row_version=1,items=[{'item_id':item,'action':'original_only'}])
            result=confirm_job(first,job,body,user)
            assert result['row_version']==2
            def compete():
                try:
                    with engine().connect() as second:
                        tx=second.begin()
                        try:
                            entered.set()
                            with pytest.raises(HTTPException) as exc:confirm_job(second,job,body,user)
                            assert exc.value.status_code==404
                        finally:tx.rollback()
                finally:done.set()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(compete)
                assert entered.wait(5)
                assert not done.wait(.3), 'Competing confirm bypassed the job row lock'
                transaction.rollback()
                pending.result(timeout=10)
        finally:
            if transaction.is_active:transaction.rollback()
    with engine().connect() as db:
        assert db.execute(select(table('import_jobs')).where(table('import_jobs').c.job_id==job)).first() is None
        assert db.execute(select(table('source_files')).where(table('source_files').c.file_sha256==sha)).first() is None
    for file in tmp_path.rglob('*'):
        if file.is_file():file.unlink()
