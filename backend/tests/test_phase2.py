"""Phase 2 integration tests against real MySQL, all writes rolled back by conftest."""
import uuid
import pytest
from sqlalchemy import select,func
from app.db import table

BASE='/api/v1'
def code():return 'P2-'+uuid.uuid4().hex[:20]
def api(client,actors,method,path,body=None,role='operator',status=200):
    r=getattr(client,method)(BASE+path,headers=actors[role]['headers'],**({'json':body} if body is not None else {}))
    assert r.status_code==status,r.text
    return r.json()['data'] if status!=204 else None

def setup(client,actors,role='operator',batch=True):
    b=api(client,actors,'post','/batches',{'batch_code':code(),'batch_name':'Phase2'},role,201)
    samples=[api(client,actors,'post','/samples',{'sample_code':code(),'batch_id':b['batch_id']},role,201) for _ in range(2)]
    plan=api(client,actors,'post','/plans',{'plan_code':code(),'title':'Phase2','batch_id':b['batch_id'] if batch else None},role,201)
    run=api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'pre_expose_then_react','plan_id':plan['plan_id'],'batch_id':b['batch_id'] if batch else None,'samples':[{'sample_id':s['sample_id']} for s in samples],'steps':[{'step_index':1,'step_kind':'o3_purge'},{'step_index':2,'step_kind':'hf_purge'}]},role,201)
    return b,samples,plan,run

def event(client,actors,s,run,kind,target,step=None,**extra):
    current=api(client,actors,'get',f"/samples/{s['sample_id']}")
    body=dict(expected_row_version=current['row_version'],event_type=kind,to_status=target,process_id=run['process_id'] if run else None,step_id=step,**extra)
    return api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",body,status=201)

def test_plan_mapping_unknowns_and_versions(client,actors):
    b,ss,p,r=setup(client,actors)
    ps=api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':1,'step_kind':'o3_purge','planned_parameters':{'cycles':50,'actual_temp_c':'275.00','o3_delta_p_kpa':'5.0000','o3_generator_o2_flow_set_sccm':'20.000'}},status=201)
    assert ps['planned_parameters']['cycles']==50
    st=api(client,actors,'post',f"/processes/{r['process_id']}/steps",{'step_index':3,'step_kind':'o3_purge','plan_step_id':ps['step_id']},status=201)
    assert st['cycles'] is None and st['actual_temp_c'] is None and st['o3_delta_p_kpa'] is None
    for method,body in [('patch',{'step_note':'changed'}),('delete',None)]:
        api(client,actors,method,f"/plan-steps/{ps['step_id']}",body,status=409)
    current=api(client,actors,'get',f"/plans/{p['plan_id']}")
    api(client,actors,'patch',f"/plans/{p['plan_id']}",{'title':'stale','expected_row_version':p['row_version']},status=409)
    out=api(client,actors,'patch',f"/plans/{p['plan_id']}",{'title':'valid','expected_row_version':current['row_version']})
    assert out['row_version']==current['row_version']+1
    api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':2,'step_kind':'purge','planned_parameters':{'unknown':10}},status=422)
    api(client,actors,'post',f"/processes/{r['process_id']}/steps",{'step_index':4,'step_kind':'purge','duration_s':1.5},status=422)
    api(client,actors,'post',f"/processes/{r['process_id']}/steps",{'step_index':4,'step_kind':'purge','cycles':-1},status=422)
    api(client,actors,'post','/plans',{'plan_code':code(),'title':'dates','planned_start':'2026-10-15','planned_end':'2026-10-14'},status=422)

def test_shared_chamber_nodes_repeat_participation_history(client,actors):
    b,ss,p,r=setup(client,actors)
    for s in ss:
        assert api(client,actors,'get',f"/samples/{s['sample_id']}")['status']=='available'
        event(client,actors,s,r,'load','in_process',event_at=None)
    event(client,actors,ss[0],r,'unload','available',r['steps'][0]['step_id'],event_at='2026-10-15T12:00:00+08:00')
    assert api(client,actors,'get',f"/samples/{ss[1]['sample_id']}")['status']=='in_process'
    event(client,actors,ss[1],r,'unload','quarantined',r['steps'][1]['step_id'],event_at='2020-01-01T00:00:00Z')
    r2=api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'hf_only','samples':[{'sample_id':ss[0]['sample_id']}]},status=201)
    event(client,actors,ss[0],r2,'load','in_process')
    event(client,actors,ss[0],r2,'unload','consumed')
    history=api(client,actors,'get',f"/samples/{ss[0]['sample_id']}/transitions")
    assert [x['event_type'] for x in history]==['receive','load','unload','load','unload']
    assert history[1]['event_at'] is None
    assert history[2]['event_at']=='2026-10-15T04:00:00+00:00'
    assert [x['transition_id'] for x in history]==sorted(x['transition_id'] for x in history)
    assert history[-1]['to_status']=='consumed'

def test_load_exclusivity_stale_versions_and_atomic_failure(client,actors,db):
    _,ss,_,r=setup(client,actors);s=ss[0]
    r2=api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','samples':[{'sample_id':s['sample_id']}]},status=201)
    count=lambda:db.scalar(select(func.count()).select_from(table('sample_transitions')).where(table('sample_transitions').c.sample_id==s['sample_id']))
    before=count();v=s['row_version']
    api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",{'expected_row_version':v,'event_type':'unload','to_status':'available','process_id':r['process_id']},status=409)
    assert count()==before
    event(client,actors,s,r,'load','in_process')
    for body in [dict(expected_row_version=v,event_type='load',to_status='in_process',process_id=r2['process_id']),dict(expected_row_version=v+1,event_type='load',to_status='in_process',process_id=r2['process_id']),dict(expected_row_version=v+1,event_type='unload',to_status='available',process_id=r2['process_id'])]:
        api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",body,status=409)
    assert count()==before+1
    assert api(client,actors,'get',f"/samples/{s['sample_id']}")['row_version']==v+1

def test_records_patch_history_and_no_bypass(client,actors):
    b,ss,p,r=setup(client,actors);s=ss[0]
    out=api(client,actors,'patch',f"/samples/{s['sample_id']}",{'status':'quarantined','notes':'legacy UI'})
    assert out['row_version']==s['row_version']+1 and out['notes']=='legacy UI'
    history=api(client,actors,'get',f"/samples/{s['sample_id']}/transitions")
    assert history[-1]['event_type']=='quarantine' and history[-1]['event_at'] is None
    api(client,actors,'patch',f"/samples/{s['sample_id']}",{'status':'in_process'},status=409)
    api(client,actors,'patch',f"/samples/{s['sample_id']}",{'status':'available'})
    event(client,actors,s,r,'load','in_process')
    api(client,actors,'patch',f"/samples/{s['sample_id']}",{'status':'consumed'},status=409)
    api(client,actors,'post','/samples',{'sample_code':code(),'batch_id':b['batch_id'],'status':'in_process'},status=409)
    api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",{'event_type':'process','to_status':'in_process'},status=422)

def test_permissions_visibility_and_spoofing(client,actors,db):
    b,ss,p,r=setup(client,actors)
    for path in [f"/plans/{p['plan_id']}",f"/processes/{r['process_id']}",f"/processes/{r['process_id']}/samples",f"/samples/{ss[0]['sample_id']}/transitions"]:
        api(client,actors,'get',path,role='other',status=404)
        api(client,actors,'get',path,role='admin')
    for path,body in [('/plans',{'plan_code':code(),'title':'No'}),('/processes',{'process_code':code(),'process_mode':'other'}),(f"/plans/{p['plan_id']}/steps",{'step_index':4,'step_kind':'wait'}),(f"/samples/{ss[0]['sample_id']}/transitions",{'event_type':'receive','to_status':'available','expected_row_version':1})]:
        api(client,actors,'post',path,body,role='viewer',status=403)
    api(client,actors,'post','/plans',{'plan_code':code(),'title':'spoof','owner_user_id':actors['other']['user']['user_id']},status=422)
    api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','operator_user_id':actors['other']['user']['user_id']},status=422)
    api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','plan_id':p['plan_id'],'batch_id':b['batch_id']},role='other',status=404)
    # All linked samples must remain visible, even when operator owns the run.
    t=table('samples');db.execute(t.update().where(t.c.sample_id==ss[0]['sample_id']).values(owner_user_id=actors['other']['user']['user_id']))
    api(client,actors,'get',f"/processes/{r['process_id']}",status=404)
    data=api(client,actors,'get','/processes')
    assert r['process_id'] not in [x['process_id'] for x in data]

def test_cross_batch_constraints_and_plan_change(client,actors):
    b,ss,p,r=setup(client,actors);b2,ss2,p2,r2=setup(client,actors)
    api(client,actors,'post',f"/processes/{r['process_id']}/samples",{'sample_id':ss2[0]['sample_id']},status=422)
    for bid in (None,b2['batch_id']):
        api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','plan_id':p['plan_id'],'batch_id':bid},status=422)
    cross=api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','batch_id':None,'samples':[{'sample_id':ss[0]['sample_id']},{'sample_id':ss2[0]['sample_id']}]},status=201)
    assert cross['sample_count']==2
    api(client,actors,'patch',f"/processes/{cross['process_id']}",{'batch_id':b['batch_id']},status=409)
    api(client,actors,'patch',f"/plans/{p['plan_id']}",{'batch_id':b2['batch_id']},status=409)
    ps=api(client,actors,'post',f"/plans/{p2['plan_id']}/steps",{'step_index':1,'step_kind':'wait'},status=201)
    api(client,actors,'post',f"/processes/{r['process_id']}/steps",{'step_index':3,'step_kind':'wait','plan_step_id':ps['step_id']},status=422)

def test_history_blocks_delete_and_remap(client,actors):
    _,ss,p,r=setup(client,actors);step=r['steps'][0]
    event(client,actors,ss[0],r,'load','in_process',step['step_id'])
    event(client,actors,ss[0],r,'unload','available',r['steps'][1]['step_id'])
    for path in [f"/processes/{r['process_id']}",f"/process-steps/{step['step_id']}",f"/process-samples/{r['samples'][0]['process_sample_id']}"]:
        api(client,actors,'delete',path,status=409)
    api(client,actors,'patch',f"/process-steps/{step['step_id']}",{'step_index':3},status=409)
    api(client,actors,'patch',f"/process-steps/{step['step_id']}",{'duration_s':'2.000'},status=409)
    api(client,actors,'delete',f"/plans/{p['plan_id']}",status=409)

def test_unload_boundary_validation_and_observation(client,actors):
    _,ss,_,r=setup(client,actors);_,_,_,other=setup(client,actors);s=ss[0]
    api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",{'expected_row_version':s['row_version'],'event_type':'load','to_status':'in_process','process_id':r['process_id'],'step_id':other['steps'][0]['step_id']},status=422)
    event(client,actors,s,r,'load','in_process',r['steps'][1]['step_id'])
    event(client,actors,s,r,'process','in_process',r['steps'][1]['step_id'])
    cur=api(client,actors,'get',f"/samples/{s['sample_id']}")
    api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",{'expected_row_version':cur['row_version'],'event_type':'unload','to_status':'available','process_id':r['process_id'],'step_id':r['steps'][0]['step_id']},status=409)
    event(client,actors,s,r,'unload','available')

def test_nested_create_atomic_and_audit(client,actors,db):
    _,ss,_,_=setup(client,actors)
    p=table('processes');a=table('audit_log');before=db.scalar(select(func.count()).select_from(p));audits=db.scalar(select(func.count()).select_from(a))
    api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','steps':[{'step_index':1,'step_kind':'wait'},{'step_index':1,'step_kind':'purge'}],'samples':[{'sample_id':ss[0]['sample_id']}]},status=409)
    assert db.scalar(select(func.count()).select_from(p))==before
    assert db.scalar(select(func.count()).select_from(a))==audits
    entities=set(db.scalars(select(a.c.entity_type).where(a.c.user_id==actors['operator']['user']['user_id'])))
    assert {'experiment_plan','process','process_step','process_sample','sample_transition'}<=entities

def test_empty_crud_and_sort_validation(client,actors):
    p=api(client,actors,'post','/plans',{'plan_code':code(),'title':'Empty'},status=201)
    step=api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':1,'step_kind':'wait'},status=201)
    p=api(client,actors,'get',f"/plans/{p['plan_id']}")
    api(client,actors,'patch',f"/plan-steps/{step['step_id']}",{'step_note':'edited','expected_row_version':p['row_version']})
    api(client,actors,'delete',f"/plan-steps/{step['step_id']}",status=204)
    api(client,actors,'delete',f"/plans/{p['plan_id']}",status=204)
    r=api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other'},status=201)
    api(client,actors,'patch',f"/processes/{r['process_id']}",{'expected_row_version':r['row_version'],'notes':'edited'})
    api(client,actors,'patch',f"/processes/{r['process_id']}",{'expected_row_version':r['row_version'],'notes':'stale'},status=409)
    api(client,actors,'delete',f"/processes/{r['process_id']}",status=204)
    for path in ['/plans?sort=owner_user_id','/processes?sort=password_hash','/plans?size=201','/transitions?size=0']:
        api(client,actors,'get',path,status=422)

def test_viewer_reads_own_scope_and_history_filters(client,actors,db):
    b,ss,p,r=setup(client,actors)
    uid=actors['viewer']['user']['user_id']
    for name,pk,ids,owner in [('batches','batch_id',[b['batch_id']],'owner_user_id'),('samples','sample_id',[s['sample_id'] for s in ss],'owner_user_id'),('experiment_plans','plan_id',[p['plan_id']],'owner_user_id'),('processes','process_id',[r['process_id']],'operator_user_id')]:
        t=table(name);db.execute(t.update().where(t.c[pk].in_(ids)).values(**{owner:uid}))
    for path in [f"/plans/{p['plan_id']}",f"/processes/{r['process_id']}",f"/samples/{ss[0]['sample_id']}/transitions"]:
        api(client,actors,'get',path,role='viewer')
    api(client,actors,'patch',f"/processes/{r['process_id']}",{'notes':'denied'},role='viewer',status=403)
    api(client,actors,'delete',f"/plans/{p['plan_id']}",role='viewer',status=403)
    data=api(client,actors,'get',f"/transitions?sample_id={ss[0]['sample_id']}&event_type=receive",role='viewer')
    assert len(data)==1 and data[0]['event_at'] is None

def test_resumable_ddl_reads_existing_objects_without_reapplying(db):
    import importlib.util
    import sys
    from app.config import ROOT
    sys.path.insert(0,str(ROOT/'database'))
    spec=importlib.util.spec_from_file_location('phase2_migrate',ROOT/'database/migrate.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    class Cursor:
        def __init__(self):self.commands=[]
        def execute(self,sql,args=None):
            self.commands.append(sql)
            if sql.startswith('ALTER'):raise AssertionError('Existing DDL must be skipped')
            self.result=db.exec_driver_sql(sql.replace('%s','%s'),args).fetchone()
        def fetchone(self):return self.result
    cur=Cursor()
    migration.execute_resumable(cur,'ALTER TABLE processes ADD COLUMN row_version INT UNSIGNED NOT NULL DEFAULT 1')
    migration.execute_resumable(cur,'ALTER TABLE process_steps ADD CONSTRAINT fk_steps_plan_step FOREIGN KEY(plan_step_id) REFERENCES experiment_plan_steps(step_id) ON DELETE RESTRICT')
    assert len(cur.commands)==2
    # A missing object executes the exact SQL from the checksummed migration, no generated alternative.
    class Missing:
        def __init__(self):self.commands=[]
        def execute(self,sql,args=None):self.commands.append(sql)
        def fetchone(self):return (0,)
    missing=Missing();ddl='ALTER TABLE process_steps ADD COLUMN plan_step_id BIGINT UNSIGNED NULL'
    migration.execute_resumable(missing,ddl)
    assert missing.commands[-1]==ddl

@pytest.mark.parametrize('hidden_by',['operator','plan','batch','linked_sample'])
def test_history_redacts_invisible_run_context_without_losing_states(client,actors,db,hidden_by):
    b,ss,p,r=setup(client,actors)
    sid=ss[0]['sample_id'];step=r['steps'][0]['step_id']
    measurement=db.execute(table('measurements').insert().values(measurement_code=code(),sample_id=sid,process_id=r['process_id'],stage='initial')).inserted_primary_key[0]
    event(client,actors,ss[0],r,'load','in_process',step,location='secret chamber',note='private run note',measurement_id=measurement)
    event(client,actors,ss[0],r,'unload','available',step)
    before=api(client,actors,'get',f'/samples/{sid}/transitions')
    assert all(x['context_redacted'] is False for x in before)
    uid=actors['other']['user']['user_id']
    # The queried sample remains visible; only its associated run becomes hidden.
    if hidden_by=='operator':name,pk,id,col='processes','process_id',r['process_id'],'operator_user_id'
    elif hidden_by=='plan':name,pk,id,col='experiment_plans','plan_id',p['plan_id'],'owner_user_id'
    elif hidden_by=='batch':
        other_batch=api(client,actors,'post','/batches',{'batch_code':code(),'batch_name':'Hidden'},'other',201)
        name,pk,id,col='processes','process_id',r['process_id'],'batch_id';uid=other_batch['batch_id']
    else:name,pk,id,col='samples','sample_id',ss[1]['sample_id'],'owner_user_id'
    t=table(name);db.execute(t.update().where(t.c[pk]==id).values(**{col:uid}))
    api(client,actors,'get',f"/processes/{r['process_id']}",status=404)
    for path in (f'/samples/{sid}/transitions',f'/transitions?sample_id={sid}'):
        after=api(client,actors,'get',path)
        assert len(after)==len(before)==3
        assert after[0]==before[0]  # process-less receive remains intact.
        for old,new in zip(before[1:],after[1:]):
            assert new['context_redacted'] is True
            for field in ('process_id','step_id','operator_user_id','location','note','measurement_id'):
                assert new[field] is None
            for field in ('transition_id','sample_id','event_type','from_status','to_status','event_at','created_at'):
                assert new[field]==old[field]
        admin=api(client,actors,'get',path,role='admin')
        assert admin==before
    page=client.get(BASE+f'/transitions?sample_id={sid}&event_type=load&size=1',headers=actors['operator']['headers']).json()
    assert len(page['data'])==1 and page['data'][0]['context_redacted'] is True

@pytest.mark.parametrize('history_kind',['load','process'])
def test_any_run_history_prevents_all_patch_overwrites_atomically(client,actors,db,history_kind):
    _,ss,_,r=setup(client,actors)
    # Unknown step/load boundaries must still freeze the entire run, including
    # untouched steps and sample bindings without their own transition.
    event(client,actors,ss[0],r,history_kind,'in_process' if history_kind=='load' else 'available')
    if history_kind=='load':event(client,actors,ss[0],r,'unload','available')
    original=api(client,actors,'get',f"/processes/{r['process_id']}")
    a=table('audit_log');n=db.scalar(select(func.count()).select_from(a))
    requests=[(f"/processes/{r['process_id']}",{'notes':'overwritten'}),
              (f"/processes/{r['process_id']}",{}),
              (f"/process-steps/{r['steps'][0]['step_id']}",{'duration_s':'2.000'}),
              (f"/process-steps/{r['steps'][1]['step_id']}",{'step_note':'overwritten'}),
              (f"/process-samples/{r['samples'][1]['process_sample_id']}",{'is_control':True})]
    for path,body in requests:
        response=client.patch(BASE+path,headers=actors['operator']['headers'],json=body)
        assert response.status_code==409,response.text
        assert 'recorded history' in response.text and 'cannot be overwritten' in response.text
        assert api(client,actors,'get',f"/processes/{r['process_id']}")==original
        assert db.scalar(select(func.count()).select_from(a))==n

def test_unhistorical_run_and_children_remain_editable(client,actors):
    _,ss,_,r=setup(client,actors)
    api(client,actors,'patch',f"/processes/{r['process_id']}",{'notes':'editable'})
    step=api(client,actors,'patch',f"/process-steps/{r['steps'][0]['step_id']}",{'duration_s':'2.000','step_note':'editable'})
    assert step['duration_s']=='2.000'
    link=api(client,actors,'patch',f"/process-samples/{r['samples'][0]['process_sample_id']}",{'is_control':True})
    assert link['is_control'] is True

def test_mapping_mutations_lock_plan_before_run_and_never_lock_dependency_rows(client,actors,db):
    from sqlalchemy import event as sql_event
    _,_,p,r=setup(client,actors)
    ps=api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':1,'step_kind':'wait'},status=201)
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    sql_event.listen(db,'before_cursor_execute',capture)
    try:
        st=api(client,actors,'post',f"/processes/{r['process_id']}/steps",{'step_index':3,'step_kind':'wait','plan_step_id':ps['step_id']},status=201)
        locks=[s for s in statements if 'FOR UPDATE' in s]
        assert 'FROM experiment_plans' in locks[0]
        assert 'FROM processes' in locks[1]
        assert not any('FROM experiment_plan_steps' in s for s in locks)
        statements.clear()
        api(client,actors,'patch',f"/plan-steps/{ps['step_id']}",{'step_note':'blocked'},status=409)
        locks=[s for s in statements if 'FOR UPDATE' in s]
        assert 'FROM experiment_plans' in locks[0]
        assert not any('FROM process_steps' in s for s in locks)
        statements.clear()
        api(client,actors,'patch',f"/processes/{r['process_id']}",{'notes':'safe'})
        locks=[s for s in statements if 'FOR UPDATE' in s]
        assert next(i for i,s in enumerate(locks) if s.split('FROM ',1)[1].startswith('experiment_plans'))<next(i for i,s in enumerate(locks) if s.split('FROM ',1)[1].startswith('batches'))
    finally:sql_event.remove(db,'before_cursor_execute',capture)
