"""Two independent MySQL transactions; committed fixtures are deleted in finally."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.db import engine, table
from app import experiments as E, schemas as S, transitions as T


@pytest.fixture
def committed_run():
    ids={};tag='P2LOCK-'+uuid.uuid4().hex
    def insert(db,name,**values):
        pk=db.execute(table(name).insert().values(**values)).inserted_primary_key[0]
        ids[name]=pk
        return pk
    try:
        with engine().begin() as db:
            uid=insert(db,'users',username=tag,role='admin',account_purpose='management')
            bid=insert(db,'batches',batch_code=tag,batch_name=tag,owner_user_id=uid)
            sid=insert(db,'samples',sample_code=tag,batch_id=bid,owner_user_id=uid)
            pid=insert(db,'experiment_plans',plan_code=tag,title=tag,batch_id=bid,owner_user_id=uid)
            rid=insert(db,'processes',process_code=tag,process_mode='other',plan_id=pid,batch_id=bid,operator_user_id=uid)
            psid=insert(db,'experiment_plan_steps',plan_id=pid,step_index=1,step_kind='wait')
            stid=insert(db,'process_steps',process_id=rid,step_index=1,step_kind='wait')
            lid=insert(db,'process_samples',process_id=rid,sample_id=sid)
        yield ids,{'user_id':uid,'role':'admin'}
    finally:
        with engine().begin() as db:
            # Delete only this test's rows, in reverse dependency order.
            a=table('audit_log')
            if 'users' in ids:db.execute(a.delete().where(a.c.user_id==ids['users']))
            t=table('sample_transitions')
            if 'samples' in ids:db.execute(t.delete().where(t.c.sample_id==ids['samples']))
            for name in ('process_samples','process_steps','processes','experiment_plan_steps','experiment_plans','samples','batches','users'):
                if name in ids:
                    t=table(name);db.execute(t.delete().where(list(t.primary_key.columns)[0]==ids[name]))


def after_commit(first,second):
    """Second request starts while first holds its locks; it must finish afterward."""
    entered=threading.Event();done=threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine().begin() as db:
            first(db)
            def worker():
                try:
                    with engine().begin() as other:
                        # Establish a read before waiting, exposing stale RR snapshots.
                        other.execute(select(table('process_steps').c.step_id).limit(1)).first()
                        entered.set()
                        return second(other)
                finally:done.set()
            pending=pool.submit(worker)
            assert entered.wait(5)
            assert not done.wait(.2), 'Competing mutation bypassed parent lock'
        return pending.result(timeout=10)


@pytest.mark.parametrize('target',['process','step','link'])
def test_history_committed_while_patch_waits_cannot_be_overwritten(committed_run,target):
    ids,user=committed_run;rid=ids['processes']
    def first(db):
        T.transition(db,ids['samples'],S.TransitionCreate(expected_row_version=1,event_type='process',to_status='available',process_id=rid),user)
    def second(db):
        with pytest.raises(HTTPException) as error:
            if target=='process':E.patch_parent(db,'processes',rid,S.ProcessUpdate(notes='overwrite'),user)
            elif target=='step':E.change_child(db,'step',ids['process_steps'],S.ProcessStepUpdate(duration_s='2.000'),user)
            else:E.change_child(db,'link',ids['process_samples'],S.ProcessSampleUpdate(is_control=True),user)
        assert error.value.status_code==409
        assert 'recorded history' in str(error.value.detail)
    after_commit(first,second)
    with engine().connect() as db:
        assert db.scalar(select(table('process_steps').c.duration_s).where(table('process_steps').c.step_id==ids['process_steps'])) is None


def test_mapping_insert_and_plan_step_patch_serialize_and_see_committed_mapping(committed_run):
    ids,user=committed_run
    def first(db):E.change_child(db,'step',ids['process_steps'],S.ProcessStepUpdate(plan_step_id=ids['experiment_plan_steps']),user)
    def second(db):
        with pytest.raises(HTTPException) as error:
            E.change_child(db,'plan_step',ids['experiment_plan_steps'],S.PlanStepUpdate(step_note='overwrite'),user)
        assert error.value.status_code==409
    after_commit(first,second)


def test_plan_patch_and_process_patch_follow_same_lock_order(committed_run):
    ids,user=committed_run
    def first(db):E.patch_parent(db,'plans',ids['experiment_plans'],S.PlanUpdate(title='changed'),user)
    def second(db):return E.patch_parent(db,'processes',ids['processes'],S.ProcessUpdate(notes='changed'),user)
    result=after_commit(first,second)
    assert result['notes']=='changed'
