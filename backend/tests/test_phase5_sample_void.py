"""Sample void boundaries against real MySQL; fixture/API writes always roll back."""
import json
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from app.db import table
from app.main import app
from app.records import require_active_sample
from fastapi import HTTPException

BASE='/api/v1'
def code():return 'SV-'+uuid.uuid4().hex[:20]
def call(client,actors,method,path,body=None,role='operator',status=200):
    r=getattr(client,method)(BASE+path,headers=actors[role]['headers'],**({'json':body} if body is not None else {}))
    assert r.status_code==status,r.text
    return r.json()['data'] if status!=204 else None

def fresh(client,actors,**extra):
    b=call(client,actors,'post','/batches',{'batch_code':code(),'batch_name':'void rollback'},status=201)
    return call(client,actors,'post','/samples',{'sample_code':code(),'batch_id':b['batch_id'],**extra},status=201)
def void(client,actors,s,**kw):
    return call(client,actors,'post',f"/samples/{s['sample_id']}/void",{'expected_row_version':s['row_version'],'reason':'误建重复样品'},**kw)
def stored(db,name,key,id):return dict(db.execute(select(table(name)).where(table(name).c[key]==id)).mappings().one())

def test_void_preserves_science_history_and_audits_metadata(client,actors,db):
    s=fresh(client,actors,nominal_thickness_nm='12.340',notes='keep',exclude_from_analysis=True,exclude_reason='keep exclusion')
    sid=s['sample_id'];before=stored(db,'samples','sample_id',sid)
    t=table('sample_transitions');history=list(db.execute(select(t).where(t.c.sample_id==sid)).mappings())
    v=void(client,actors,s)
    assert v['voided_at'].endswith('+00:00') and v['void_reason']=='误建重复样品'
    assert v['voided_by_user_id']==actors['operator']['user']['user_id'] and v['row_version']==s['row_version']+1
    after=stored(db,'samples','sample_id',sid)
    for k in before:
        if k not in ('voided_at','void_reason','voided_by_user_id','row_version','updated_at'):assert before[k]==after[k]
    assert list(db.execute(select(t).where(t.c.sample_id==sid)).mappings())==history
    a=table('audit_log');logs=list(db.execute(select(a).where(a.c.entity_type=='sample',a.c.entity_id==sid,a.c.field_name=='void_metadata')).mappings())
    assert len(logs)==1 and logs[0]['action']=='update' and logs[0]['user_id']==v['voided_by_user_id']
    old,new=json.loads(logs[0]['old_value']),json.loads(logs[0]['new_value'])
    assert old==dict(voided_at=None,void_reason=None,voided_by_user_id=None,row_version=1)
    assert new['void_reason']==v['void_reason'] and new['row_version']==2
    assert void(client,actors,v)==v
    assert db.scalar(select(a.c.audit_id).where(a.c.entity_type=='sample',a.c.entity_id==sid,a.c.field_name=='void_metadata').order_by(a.c.audit_id.desc()))==logs[0]['audit_id']
    void(client,actors,s,status=409)
    call(client,actors,'post',f'/samples/{sid}/void',{'expected_row_version':2,'reason':'改写'},status=409)
    assert call(client,actors,'get',f'/samples/{sid}')['void_reason']==v['void_reason']
    assert not any(x['sample_id']==sid for x in call(client,actors,'get',f"/samples?batch_id={s['batch_id']}"))
    assert any(x['sample_id']==sid for x in call(client,actors,'get',f"/samples?batch_id={s['batch_id']}&include_voided=true"))
    assert call(client,actors,'get',f"/batches/{s['batch_id']}/samples")==[]
    assert len(call(client,actors,'get',f"/batches/{s['batch_id']}/samples?include_voided=true"))==1
    call(client,actors,'delete',f'/samples/{sid}',role='admin',status=409)
    call(client,actors,'post','/samples',{'batch_id':s['batch_id'],'sample_code':s['sample_code']},status=409)

@pytest.mark.parametrize('body',[{}, {'reason':'x'}, {'expected_row_version':1}, {'expected_row_version':True,'reason':'x'}, {'expected_row_version':0,'reason':'x'}, {'expected_row_version':1,'reason':'  \n '}, {'expected_row_version':1,'reason':'x'*2001}, {'expected_row_version':1,'reason':'x','status':'lost'}])
def test_void_strict_request(client,actors,body):
    s=fresh(client,actors);call(client,actors,'post',f"/samples/{s['sample_id']}/void",body,status=422)

@pytest.mark.parametrize('role,status',[('viewer',403),('other',404),('admin',200)])
def test_void_authorization(client,actors,role,status):
    s=fresh(client,actors);void(client,actors,s,role=role,status=status)

@pytest.mark.parametrize('kind',['measurement','dataset','source','occurrence','derived','child','attachment','issue','link','transition','initial_context','missing_history','legacy'])
def test_scientific_dependencies_block_without_changes(client,actors,db,kind):
    s=fresh(client,actors,sample_type='parent_wafer');sid=s['sample_id']
    def insert(name,**values):return db.execute(table(name).insert().values(**values)).inserted_primary_key[0]
    if kind=='measurement':insert('measurements',measurement_code=code(),sample_id=sid,stage='initial')
    elif kind=='dataset':insert('instrument_datasets',dataset_code=code(),instrument_type='other',sample_id=sid)
    elif kind in ('source','occurrence'):
        fid=insert('source_files',file_sha256=uuid.uuid4().hex*2,file_name='legacy',file_role='metadata',**({'sample_id':sid} if kind=='source' else {}))
        if kind=='occurrence':
            uid=actors['other']['user']['user_id']
            jid=insert('import_jobs',owner_user_id=uid)
            item=insert('import_items',job_id=jid,filename='legacy',sha256=uuid.uuid4().hex*2,storage_key='rollback',parse_result={})
            insert('source_file_occurrences',source_file_id=fid,import_item_id=item,sample_id=sid,owner_user_id=uid,filename='legacy')
    elif kind=='derived':insert('derived_results',result_code=code(),result_kind='other',sample_id=sid)
    elif kind=='child':call(client,actors,'post','/samples',{'sample_code':code(),'batch_id':s['batch_id'],'parent_sample_id':sid},status=201)
    elif kind=='attachment':insert('attachments',file_name='evidence',entity_type='sample',entity_id=sid,uploaded_by=actors['other']['user']['user_id'])
    elif kind=='issue':
        iid=insert('issues',issue_code=code(),title='hidden',owner_user_id=actors['other']['user']['user_id'])
        insert('issues_links',issue_id=iid,entity_type='sample',entity_id=sid)
    elif kind=='link':
        pid=insert('processes',process_code=code(),process_mode='other',operator_user_id=actors['other']['user']['user_id'])
        insert('process_samples',process_id=pid,sample_id=sid)
    elif kind=='transition':
        call(client,actors,'post',f'/samples/{sid}/transitions',{'event_type':'measure','to_status':'available','expected_row_version':1},status=201)
        s['row_version']=2
    elif kind=='initial_context':
        db.execute(table('sample_transitions').update().where(table('sample_transitions').c.sample_id==sid).values(note='actual receipt context'))
    elif kind=='missing_history':db.execute(table('sample_transitions').delete().where(table('sample_transitions').c.sample_id==sid))
    elif kind=='legacy':db.execute(table('audit_log').delete().where(table('audit_log').c.entity_type=='sample',table('audit_log').c.entity_id==sid))
    before=stored(db,'samples','sample_id',sid)
    void(client,actors,s,status=409)
    assert stored(db,'samples','sample_id',sid)==before

@pytest.mark.parametrize('status',['quarantined','consumed','lost'])
def test_non_available_samples_cannot_void(client,actors,status):void(client,actors,fresh(client,actors,status=status),status=409)

def test_voided_sample_cannot_change_or_parent_or_transition(client,actors,db):
    s=fresh(client,actors,sample_type='parent_wafer');v=void(client,actors,s);sid=s['sample_id']
    for body in [{'notes':'rewrite'},{'status':'quarantined'},{'exclude_from_analysis':True,'exclude_reason':'x'}]:
        call(client,actors,'patch',f'/samples/{sid}',{'expected_row_version':2,**body},status=409)
    call(client,actors,'post','/samples',{'sample_code':code(),'batch_id':s['batch_id'],'parent_sample_id':sid},status=409)
    call(client,actors,'post',f"/batches/{s['batch_id']}/samples/batch",{'parent_sample_id':sid,'items':[{'sample_code':code()}]},status=409)
    call(client,actors,'post',f'/samples/{sid}/transitions',{'expected_row_version':2,'event_type':'receive','to_status':'available'},status=409)
    with pytest.raises(HTTPException) as exc:require_active_sample(db,sid,actors['operator']['user'])
    assert exc.value.status_code==409
    with db.begin_nested():
        with pytest.raises(OperationalError):db.execute(table('samples').update().where(table('samples').c.sample_id==sid).values(void_reason=None))
    spec=client.get('/openapi.json').json()
    assert spec['info']['version']==app.version
    assert 'SampleVoid' in spec['components']['schemas']
    assert any(x['name']=='include_voided' for x in spec['paths']['/api/v1/samples']['get']['parameters'])

# The fixture creates and drops a disposable schema; application data is untouched.
from test_migrations import mysql, migrate

def test_void_migration_replay_and_rejects_wrong_contract(mysql):
    sql=(migrate.ROOT/'database/migrations/0008_sample_void.sql').read_text(encoding='utf-8')
    with mysql.cursor() as cur:
        cur.execute('CREATE TABLE users (user_id BIGINT UNSIGNED PRIMARY KEY)')
        cur.execute("INSERT INTO samples(sample_id,status,row_version) VALUES(1,'consumed',7)")
        for replay in range(2):
            for statement in migrate.split_statements(sql):
                if statement.strip() and not migrate._is_comment_only(statement):
                    migrate.execute_resumable(cur,migrate.re.sub(r'^\s*(?:--[^\n]*(?:\n|$)\s*)+','',statement))
            migrate.validate_sample_void(cur,'0008')
        cur.execute('SELECT status,row_version,voided_at,void_reason,voided_by_user_id FROM samples WHERE sample_id=1')
        assert cur.fetchone()==('consumed',7,None,None,None)
        cur.execute('ALTER TABLE samples DROP CHECK chk_samples_void_metadata')
        cur.execute('ALTER TABLE samples ADD CONSTRAINT chk_samples_void_metadata CHECK (voided_at IS NULL OR void_reason IS NOT NULL)')
        with pytest.raises(RuntimeError,match='CHECK contract mismatch'):migrate.validate_sample_void(cur,'0008')


def test_void_stale_version_and_normalization(client,actors):
    s=fresh(client,actors)
    call(client,actors,'patch',f"/samples/{s['sample_id']}",{'expected_row_version':1,'notes':'corrected'})
    void(client,actors,s,status=409)
    v=call(client,actors,'post',f"/samples/{s['sample_id']}/void",{'expected_row_version':2,'reason':'  误建  '})
    assert v['void_reason']=='误建' and v['row_version']==3


def test_in_process_never_voided(client,actors,db):
    s=fresh(client,actors)
    db.execute(table('samples').update().where(table('samples').c.sample_id==s['sample_id']).values(status='in_process'))
    void(client,actors,s,status=409)
