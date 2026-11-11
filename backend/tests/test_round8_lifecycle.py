"""Lifecycle real MySQL boundaries; all rows and originals fingerprinted on rollback."""
import uuid
import json
import pytest
from sqlalchemy import select, event
from test_phase4_browser import db, client
from test_phase5_sample_void import fresh, call, code
from app.db import table


def create(client, actors, kind):
    if kind == 'samples': return fresh(client, actors)
    body = {'batches': {'batch_code':code(),'batch_name':'lifecycle rollback'},
            'plans': {'plan_code':code(),'title':'lifecycle rollback'},
            'processes': {'process_code':code(),'process_mode':'other','log_status':'unknown'}}[kind]
    return call(client, actors, 'post', '/'+kind, body, status=201)

KEY={'batches':'batch_id','samples':'sample_id','plans':'plan_id','processes':'process_id'}

def preview(client, actors, kind, row, role='operator'):
    return call(client,actors,'get',f'/lifecycle/{kind}/{row[KEY[kind]]}/impact',role=role)

def body(impact, action, **kw):
    return dict(action=action,expected_row_version=impact['row_version'],preview_token=impact['preview_token'],
                operation_id=uuid.uuid4().hex,reason='误建/验收回滚',**kw)

def apply(client,actors,kind,row,payload,status=200,role='operator'):
    return call(client,actors,'post',f'/lifecycle/{kind}/{row[KEY[kind]]}/apply',payload,status=status,role=role)

@pytest.mark.parametrize('kind',list(KEY))
def test_void_all_kinds_receipt_only_and_exact_recovery(client,actors,db,kind):
    row=create(client,actors,kind); info=preview(client,actors,kind,row)
    assert 'void' in info['actions']
    payload=body(info,'void'); result=apply(client,actors,kind,row,payload)
    assert result['voided_at'] and result['void_reason']=='误建/验收回滚'
    again=apply(client,actors,kind,row,payload)
    assert again['row_version']==result['row_version']
    assert preview(client,actors,kind,row)['actions']==[]
    apply(client,actors,kind,row,{**payload,'reason':'different'},409)
    call(client,actors,'patch',f'/{kind}/{row[KEY[kind]]}',{'expected_row_version':result['row_version'],'notes':'rewrite'},status=409)
    rows=call(client,actors,'get','/'+kind)
    assert all(x[KEY[kind]]!=row[KEY[kind]] for x in rows)
    rows=call(client,actors,'get','/'+kind+'?include_voided=true')
    assert any(x[KEY[kind]]==row[KEY[kind]] for x in rows)
    if kind=='samples':
        t=table('sample_transitions')
        assert len(list(db.execute(select(t).where(t.c.sample_id==row['sample_id']))))==1

@pytest.mark.parametrize('kind',list(KEY))
def test_archive_restore_cas_permissions(client,actors,db,kind):
    row=create(client,actors,kind)
    if kind=='plans':
        p=table('experiment_plans');db.execute(p.update().where(p.c.plan_id==row['plan_id']).values(status='approved'))
    info=preview(client,actors,kind,row);payload=body(info,'archive')
    apply(client,actors,kind,row,payload,403,role='viewer')
    apply(client,actors,kind,row,payload,404,role='other')
    apply(client,actors,kind,row,{**payload,'expected_row_version':999},409)
    archived=apply(client,actors,kind,row,payload)
    info=preview(client,actors,kind,row);assert info['actions']==['restore']
    restored=apply(client,actors,kind,row,body(info,'restore'))
    assert restored['row_version']==archived['row_version']+1
    if kind=='plans':assert restored['status']=='approved'
    else:assert restored['archived_at'] is None


def test_batch_selected_samples_snapshot_and_atomic_rollback(client,actors,db):
    sample=fresh(client,actors); batch=call(client,actors,'get',f"/batches/{sample['batch_id']}")
    info=preview(client,actors,'batches',batch)
    assert info['sample_counts']['candidates']==[{'sample_id':sample['sample_id'],'sample_code':sample['sample_code'],'row_version':1}]
    payload=body(info,'archive_with_dependents',include_sample_ids=[sample['sample_id']],sample_versions={sample['sample_id']:1})
    # Changed sample version cannot silently use the previous confirmation.
    call(client,actors,'patch',f"/samples/{sample['sample_id']}",{'expected_row_version':1,'notes':'concurrent'})
    apply(client,actors,'batches',batch,payload,409)
    info=preview(client,actors,'batches',batch)
    payload=body(info,'archive_with_dependents',include_sample_ids=[sample['sample_id']],sample_versions={sample['sample_id']:2})
    # Force failure after sample updates; request savepoint must restore everything.
    def reject(conn,cursor,statement,params,context,many):
        if statement.startswith('UPDATE batches SET'):raise RuntimeError('synthetic late write failure')
    event.listen(db,'before_cursor_execute',reject)
    try:apply(client,actors,'batches',batch,payload,500)
    finally:event.remove(db,'before_cursor_execute',reject)
    s=call(client,actors,'get',f"/samples/{sample['sample_id']}");assert s['archived_at'] is None and s['row_version']==2
    result=apply(client,actors,'batches',batch,payload)
    assert result['archived_at']
    assert call(client,actors,'get',f"/samples/{sample['sample_id']}")['archived_at']
    assert apply(client,actors,'batches',batch,payload)['row_version']==result['row_version']


def test_scoped_counts_hidden_shared_ids_and_dependency_change(client,actors,db):
    sample=fresh(client,actors); batch=call(client,actors,'get',f"/batches/{sample['batch_id']}")
    p=table('processes'); hidden=db.execute(p.insert().values(process_code=code(),process_mode='other',batch_id=batch['batch_id'],operator_user_id=actors['other']['user']['user_id'])).inserted_primary_key[0]
    info=preview(client,actors,'batches',batch)
    assert info['restricted']
    assert not any(g['type']=='processes' for g in info['groups'])
    assert hidden not in [x.get('process_id') for x in info['shared']['shared_samples']]
    payload=body(info,'archive')
    db.execute(table('samples').insert().values(sample_code=code(),batch_id=batch['batch_id'],owner_user_id=actors['operator']['user']['user_id']))
    apply(client,actors,'batches',batch,payload,409)

@pytest.mark.parametrize('kind',['batches','plans','processes'])
def test_safe_unused_delete_admin_and_replay(client,actors,db,kind):
    row=create(client,actors,kind);info=preview(client,actors,kind,row,role='admin')
    assert 'delete' in info['actions'];payload=body(info,'delete')
    result=apply(client,actors,kind,row,payload,role='admin');assert result['deleted']
    assert apply(client,actors,kind,row,payload,role='admin')['deleted']


def test_process_references_never_cascade_samples_batch_history(client,actors,db):
    sample=fresh(client,actors);run=create(client,actors,'processes')
    call(client,actors,'post',f"/processes/{run['process_id']}/samples",{'sample_id':sample['sample_id']},status=201)
    info=preview(client,actors,'processes',run,role='admin')
    assert not info['delete_allowed'] and 'void' not in info['actions']
    apply(client,actors,'processes',run,body(info,'delete'),409,role='admin')
    call(client,actors,'delete',f"/processes/{run['process_id']}",status=409)
    assert call(client,actors,'get',f"/samples/{sample['sample_id']}")['sample_id']==sample['sample_id']
    assert call(client,actors,'get',f"/batches/{sample['batch_id']}")['batch_id']==sample['batch_id']


def test_batch_sample_locks_real_second_connection_and_science_block(client,actors,db):
    from app.db import engine
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    sample=fresh(client,actors);batch=call(client,actors,'get',f"/batches/{sample['batch_id']}")
    info=preview(client,actors,'batches',batch)
    payload=body(info,'archive_with_dependents',include_sample_ids=[sample['sample_id']],sample_versions={sample['sample_id']:1})
    apply(client,actors,'batches',batch,payload)
    with engine().connect() as second:
        for name,key,id in [('batches','batch_id',batch['batch_id']),('samples','sample_id',sample['sample_id'])]:
            with pytest.raises(DBAPIError) as error:
                second.execute(text(f'SELECT {key} FROM {name} WHERE {key}=:id FOR UPDATE NOWAIT'),{'id':id})
            assert error.value.orig.args[0]==3572
    # Restore does not rewrite receipt, then a scientific reference prevents void.
    info=preview(client,actors,'samples',sample)
    restored=apply(client,actors,'samples',sample,body(info,'restore'))
    db.execute(table('measurements').insert().values(measurement_code=code(),sample_id=sample['sample_id'],stage='initial'))
    info=preview(client,actors,'samples',sample)
    assert 'void' not in info['actions'] and not info['delete_allowed']
    apply(client,actors,'samples',sample,body(info,'void'),409)

from test_migrations import mysql, migrate


def test_additive_migration_replay_preserves_rows_and_enforces_metadata(mysql):
    import pymysql
    with mysql.cursor() as cur:
        cur.execute('CREATE TABLE users (user_id BIGINT UNSIGNED PRIMARY KEY)')
        cur.execute('CREATE TABLE batches (batch_id BIGINT UNSIGNED PRIMARY KEY, status VARCHAR(24))')
        cur.execute("INSERT INTO batches VALUES(1,'quarantined')")
        for replay in range(2):
            for filename in ('0011_record_lifecycle.sql','0012_lifecycle_all_records.sql'):
                for statement in migrate.split_statements((migrate.ROOT/'database/migrations'/filename).read_text()):
                    if statement.strip() and not migrate._is_comment_only(statement):
                        migrate.execute_resumable(cur,migrate.re.sub(r'^\s*(?:--[^\n]*(?:\n|$)\s*)+','',statement))
            migrate.validate_sample_lifecycle(cur,'0011')
            migrate.validate_all_lifecycle(cur,'0012')
            cur.execute('SELECT status,voided_at,void_reason,voided_by_user_id FROM batches WHERE batch_id=1')
            assert cur.fetchone()==('quarantined',None,None,None)
        with pytest.raises(pymysql.MySQLError):
            cur.execute("UPDATE batches SET voided_at=UTC_TIMESTAMP() WHERE batch_id=1")
