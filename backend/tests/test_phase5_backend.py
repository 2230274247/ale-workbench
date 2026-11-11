"""Phase 5 integration: real MySQL; all fixture writes roll back."""
import importlib.util
import logging
from pathlib import Path
import uuid
import pytest
from sqlalchemy import select
from app.db import table
from app.main import app

BASE='/api/v1'
ROOT=Path(__file__).resolve().parents[2]
def code():return 'P5-'+uuid.uuid4().hex[:20]
def api(client,actors,method,path,body=None,role='operator',status=200):
    response=getattr(client,method)(BASE+path,headers=actors[role]['headers'],**({'json':body} if body is not None else {}))
    assert response.status_code==status,response.text
    return response.json()['data'] if status!=204 else None

def batch(client,actors):return api(client,actors,'post','/batches',{'batch_code':code(),'batch_name':'第五轮','status':'quarantined'},status=201)
def plan(client,actors,**extra):return api(client,actors,'post','/plans',{'plan_code':code(),'title':'第五轮',**extra},status=201)
def run(client,actors,**extra):return api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other',**extra},status=201)
SNAPSHOT={'step_type':'自由类型','temperature':{'value':'275.00','unit':'°C'},'groups':[{'name':'反应','fields':[{'name':'压力','value':'5.000','unit':'Pa'},{'name':'未知','value':None,'unit':None}]}]}

def test_snapshot_template_crud_is_independent_of_history(client,actors):
    template=api(client,actors,'post','/step-parameter-templates',{'template_name':'通用参数','definition':SNAPSHOT},status=201)
    path=f"/step-parameter-templates/{template['template_id']}"
    assert template['row_version']==1 and template['definition']==SNAPSHOT
    api(client,actors,'get',path,role='other',status=404)
    api(client,actors,'post','/step-parameter-templates',{'template_name':'x','definition':SNAPSHOT},role='viewer',status=403)
    p=plan(client,actors)
    ps=api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':1,'step_kind':'other','parameter_snapshot':template['definition']},status=201)
    r=run(client,actors,plan_id=p['plan_id'],steps=[{'step_index':1,'step_kind':'other','plan_step_id':ps['step_id'],'parameter_snapshot':template['definition']}])
    assert ps['parameter_snapshot']==r['steps'][0]['parameter_snapshot']==SNAPSHOT
    updated=api(client,actors,'patch',path,{'expected_row_version':1,'definition':{'step_type':'新类型'}})
    assert updated['row_version']==2
    api(client,actors,'patch',path,{'expected_row_version':1,'template_name':'stale'},status=409)
    api(client,actors,'delete',path+'?expected_row_version=2',status=204)
    assert api(client,actors,'get',f"/plans/{p['plan_id']}")['steps'][0]['parameter_snapshot']==SNAPSHOT
    assert api(client,actors,'get',f"/processes/{r['process_id']}")['steps'][0]['parameter_snapshot']==SNAPSHOT
    api(client,actors,'patch',f"/process-steps/{r['steps'][0]['step_id']}",{'parameter_snapshot':None,'expected_row_version':r['row_version']})
    assert api(client,actors,'get',f"/processes/{r['process_id']}")['steps'][0]['parameter_snapshot'] is None

@pytest.mark.parametrize('kind',['batches','processes'])
def test_archive_keeps_scientific_state_checks_permissions_and_versions(client,actors,kind):
    item=batch(client,actors) if kind=='batches' else run(client,actors,log_status='partial')
    pk='batch_id' if kind=='batches' else 'process_id'
    state='status' if kind=='batches' else 'log_status'
    path=f"/{kind}/{item[pk]}/archive"
    api(client,actors,'post',path,{},status=422)
    api(client,actors,'post',path,{'expected_row_version':item['row_version']},role='viewer',status=403)
    api(client,actors,'post',path,{'expected_row_version':item['row_version']},role='other',status=404)
    archived=api(client,actors,'post',path,{'expected_row_version':item['row_version']})
    assert archived['archived_at'] and archived[state]==item[state]
    assert archived['row_version']==item['row_version']+1
    api(client,actors,'post',path,{'expected_row_version':item['row_version']},status=409)
    again=api(client,actors,'post',path,{'expected_row_version':archived['row_version']})
    assert again['row_version']==archived['row_version'] and again['archived_at']==archived['archived_at']
    assert any(x[pk]==item[pk] and x['archived_at'] for x in api(client,actors,'get',f'/{kind}'))

def test_archive_historical_process_and_counted_delete_protection(client,actors,db):
    b=batch(client,actors)
    s=api(client,actors,'post','/samples',{'sample_code':code(),'batch_id':b['batch_id']},status=201)
    p=plan(client,actors,batch_id=b['batch_id'])
    r=run(client,actors,plan_id=p['plan_id'],batch_id=b['batch_id'],samples=[{'sample_id':s['sample_id']}],steps=[{'step_index':1,'step_kind':'other','parameter_snapshot':SNAPSHOT}])
    api(client,actors,'post',f"/samples/{s['sample_id']}/transitions",{'event_type':'load','to_status':'in_process','process_id':r['process_id'],'expected_row_version':s['row_version']},status=201)
    current=api(client,actors,'get',f"/processes/{r['process_id']}")
    archived=api(client,actors,'post',f"/processes/{r['process_id']}/archive",{'expected_row_version':current['row_version']})
    assert archived['steps']==current['steps'] and archived['samples']==current['samples']
    assert archived['log_status']==current['log_status']
    problem=api(client,actors,'delete',f"/processes/{r['process_id']}",status=409)
    # History protection runs before counted dependencies and must expose no counts.
    assert problem['detail']=='已有科研或样品流转历史关联，不能覆盖历史工艺，请保留记录（Run has recorded history; historical data cannot be overwritten）'
    assert not any(character.isdigit() for character in problem['detail'])
    assert ' 条' not in problem['detail']
    problem=api(client,actors,'delete',f"/batches/{b['batch_id']}",role='admin',status=409)
    for label in ['样品 1 条','实验计划 1 条','工艺执行 1 条']:assert label in problem['detail']
    api(client,actors,'patch',f"/process-steps/{r['steps'][0]['step_id']}",{'parameter_snapshot':{'step_type':'overwrite'}},status=409)
    assert db.scalar(select(table('samples').c.status).where(table('samples').c.sample_id==s['sample_id']))=='in_process'

@pytest.mark.parametrize('own_count',[0,1])
def test_dependency_errors_hide_admin_runs_and_mapped_steps(client,actors,db,own_count):
    from fastapi import HTTPException
    from app.records import protect_delete
    from app.experiments import used_child
    p=plan(client,actors)
    ps=api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':1,'step_kind':'other'},status=201)
    # Admin legitimately owns runs on an operator-owned plan.
    runs=[]
    for role in ['admin','admin']+['operator']*own_count:
        runs.append(api(client,actors,'post','/processes',{
            'process_code':code(),'process_mode':'other','plan_id':p['plan_id'],
            'steps':[{'step_index':1,'step_kind':'other','plan_step_id':ps['step_id']}]},role=role,status=201))
    detail=api(client,actors,'get',f"/plans/{p['plan_id']}")
    assert detail['process_count']==own_count
    for r in runs[:2]:api(client,actors,'get',f"/processes/{r['process_id']}",status=404)
    def errors(role):
        return [api(client,actors,'delete',f"/plans/{p['plan_id']}",role=role,status=409)['detail'],
                api(client,actors,'delete',f"/plan-steps/{ps['step_id']}",role=role,status=409)['detail'],
                api(client,actors,'patch',f"/plan-steps/{ps['step_id']}",{'step_name':'blocked'},role=role,status=409)['detail']]
    operator=errors('operator')
    for message in operator:
        assert message.count('另有受权限保护的关联记录')==1
        assert '2 条' not in message and f'{2+own_count} 条' not in message
    if own_count:
        assert '工艺执行 1 条' in operator[0]
        assert all('实际步骤共 1 条' in message for message in operator[1:])
    else:
        assert '工艺执行' not in operator[0]
        assert all('实际步骤' not in message for message in operator[1:])
    admin=errors('admin')
    assert f'工艺执行 {2+own_count} 条' in admin[0]
    assert all(f'实际步骤共 {2+own_count} 条' in message for message in admin[1:])
    assert all('受权限保护' not in message for message in admin)
    # Existing context-free backend callers keep the full diagnostic contract.
    with pytest.raises(HTTPException) as exc:protect_delete(db,'experiment_plans',p['plan_id'])
    assert f'工艺执行 {2+own_count} 条' in exc.value.detail
    with pytest.raises(HTTPException) as exc:used_child(db,'plan_step',ps)
    assert f'实际步骤共 {2+own_count} 条' in exc.value.detail
    assert api(client,actors,'get',f"/plans/{p['plan_id']}")['row_version']==detail['row_version']
    assert api(client,actors,'get',f"/plans/{p['plan_id']}/steps")[0]['step_name'] is None


@pytest.mark.parametrize('hidden_parent',['batch','plan','sample'])
def test_dependency_counts_require_visible_process_parents(client,actors,db,hidden_parent):
    from fastapi import HTTPException
    from app.records import protect_delete
    from app.experiments import used_child
    b=batch(client,actors)
    s=api(client,actors,'post','/samples',{'sample_code':code(),'batch_id':b['batch_id']},status=201)
    p=plan(client,actors,batch_id=b['batch_id'])
    ps=api(client,actors,'post',f"/plans/{p['plan_id']}/steps",{'step_index':1,'step_kind':'other'},status=201)
    r=run(client,actors,plan_id=p['plan_id'],batch_id=b['batch_id'],samples=[{'sample_id':s['sample_id']}],
          steps=[{'step_index':1,'step_kind':'other','plan_step_id':ps['step_id']}])
    name,pk,id={'batch':('batches','batch_id',b['batch_id']),
                'plan':('experiment_plans','plan_id',p['plan_id']),
                'sample':('samples','sample_id',s['sample_id'])}[hidden_parent]
    t=table(name)
    db.execute(t.update().where(t.c[pk]==id).values(owner_user_id=actors['admin']['user']['user_id']))
    api(client,actors,'get',f"/processes/{r['process_id']}",status=404)
    for target,identifier,label in [('experiment_plans',p['plan_id'],'工艺执行'),
                                    ('experiment_plan_steps',ps['step_id'],'实际步骤')]:
        with pytest.raises(HTTPException) as exc:protect_delete(db,target,identifier,actors['operator']['user'])
        assert '另有受权限保护的关联记录' in exc.value.detail and label not in exc.value.detail
    with pytest.raises(HTTPException) as exc:used_child(db,'plan_step',ps,actors['operator']['user'])
    assert '另有受权限保护的关联记录' in exc.value.detail and '实际步骤' not in exc.value.detail


def test_unknown_dependency_visibility_is_conservative(client,actors,db):
    p=plan(client,actors)
    t=table('attachments')
    db.execute(t.insert().values(file_name='restricted',entity_type='experiment_plan',entity_id=p['plan_id']))
    message=api(client,actors,'delete',f"/plans/{p['plan_id']}",status=409)['detail']
    assert '另有受权限保护的关联记录' in message and '附件' not in message and '1 条' not in message
    admin=api(client,actors,'delete',f"/plans/{p['plan_id']}",role='admin',status=409)['detail']
    assert '附件 1 条' in admin and '受权限保护' not in admin


@pytest.mark.parametrize('endpoint,field,label',[('/plans','batch_id','批次'),('/processes','batch_id','批次'),('/processes','plan_id','实验计划'),('/processes','chemistry_system_id','化学体系')])
def test_reference_errors_do_not_distinguish_hidden_and_missing(client,actors,endpoint,field,label):
    if field=='batch_id':hidden=batch(client,actors)['batch_id']
    elif field=='plan_id':hidden=plan(client,actors)['plan_id']
    else:hidden=api(client,actors,'post','/chemistry-systems',{'system_code':code(),'system_name':'hidden'},status=201)['system_id']
    def error(id):
        payload={'plan_code':code(),'title':'test'} if endpoint=='/plans' else {'process_code':code(),'process_mode':'other'}
        payload[field]=id
        return api(client,actors,'post',endpoint,payload,role='other',status=404)['detail']
    assert error(hidden)==error(9223372036854775807)
    assert label in error(hidden) and field in error(hidden)

def test_tools_pagination_and_missing_reference(client,actors,db):
    t=table('tools')
    prefix=code()
    ids=[db.execute(t.insert().values(tool_code=prefix+str(i),tool_name=prefix+str(i),tool_type='other')).inserted_primary_key[0] for i in range(2)]
    first=client.get(BASE+f'/tools?keyword={prefix}&size=1',headers=actors['viewer']['headers'])
    assert first.status_code==200
    data=first.json();assert data['data'][0]['tool_id']==ids[0] and data['data'][0]['tool_name']==prefix+'0'
    assert len(api(client,actors,'get',f'/tools?keyword={prefix}&size=1&page=2'))==1
    problem=api(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','tool_id':9223372036854775807},status=422)
    assert '设备（tool_id）' in problem['detail']
    assert run(client,actors,tool_id=ids[0])['tool']['tool_name']==prefix+'0'

def test_error_logs_include_context_without_body_or_query(client,actors,caplog):
    with caplog.at_level(logging.WARNING,logger='ale.requests'):
        response=client.post(BASE+'/processes?secret=NEVER_LOG_QUERY',headers=actors['operator']['headers'],json={'process_code':code(),'process_mode':'other','tool_id':9223372036854775807,'notes':'NEVER_LOG_BODY'})
    assert response.status_code==422
    logs='\n'.join(record.getMessage() for record in caplog.records if record.name=='ale.requests')
    assert response.headers['X-Request-ID'] in logs and 'method=POST' in logs and 'path=/api/v1/processes' in logs and 'status=422' in logs
    assert 'NEVER_LOG' not in logs and actors['operator']['pair']['access_token'] not in logs

def test_phase5_live_schema_and_runtime_contract(db):
    spec=importlib.util.spec_from_file_location('phase5_migrate',ROOT/'database/migrate.py')
    migrate=importlib.util.module_from_spec(spec);spec.loader.exec_module(migrate)
    cursor=db.connection.driver_connection.cursor()
    try:
        for version,fn in [('0003',migrate.validate_phase2),('0004',migrate.validate_phase2),('0005',migrate.validate_phase3),('0006',migrate.validate_phase4),('0007',migrate.validate_phase5)]:fn(cursor,version)
    finally:cursor.close()
    contract=app.openapi()
    assert '/api/v1/tools' in contract['paths'] and '/api/v1/step-parameter-templates' in contract['paths']
    for model in ['PlanStepCreate','PlanStepUpdate','ProcessStepCreate','ProcessStepUpdate']:
        assert 'parameter_snapshot' in contract['components']['schemas'][model]['properties']
    assert 'expected_row_version' in contract['components']['schemas']['RecordArchive']['required']

@pytest.mark.parametrize('drift',['column_type','owner_fk_rule','owner_index','audit_check'])
def test_phase5_postvalidation_rejects_metadata_drift_without_ddl(db,drift):
    spec=importlib.util.spec_from_file_location('phase5_drift',ROOT/'database/migrate.py')
    migrate=importlib.util.module_from_spec(spec);spec.loader.exec_module(migrate)
    real=db.connection.driver_connection.cursor()
    class Cursor:
        def execute(self,sql,args=None):
            self.sql=sql;self.args=args
            return real.execute(sql,args)
        def fetchone(self):return real.fetchone()
        def fetchall(self):
            result=list(real.fetchall())
            if drift=='column_type' and 'GENERATION_EXPRESSION' in self.sql and self.args==('process_steps',):
                result=[(row[0],'text',*row[2:]) if row[0]=='parameter_snapshot' else row for row in result]
            if drift=='owner_fk_rule' and 'REFERENTIAL_CONSTRAINTS' in self.sql and self.args==('step_parameter_templates',):
                result=[(*row[:5],'CASCADE',*row[6:]) for row in result]
            if drift=='owner_index' and 'STATISTICS' in self.sql and self.args==('step_parameter_templates',):
                result=[row for row in result if row[0]!='ix_step_parameter_templates_owner']
            if drift=='audit_check' and 'CHECK_CLAUSE' in self.sql and self.args==('audit_log',):
                result=[(row[0],migrate.AUDIT_CHECK_0006,row[2]) if row[0]=='chk_audit_entity' else row for row in result]
            return tuple(result)
    try:
        with pytest.raises(RuntimeError,match='Phase5 schema validation failed'):
            migrate.validate_phase5(Cursor(),'0007')
    finally:real.close()


def test_unhandled_error_keeps_request_id_and_redacts_exception(client,actors,caplog,monkeypatch):
    from app import records
    def explode(*args,**kwargs):raise RuntimeError('NEVER_LOG_EXCEPTION_SECRET')
    monkeypatch.setattr(records,'page_result',explode)
    with caplog.at_level(logging.WARNING,logger='ale.requests'):
        response=client.get(BASE+'/tools',headers=actors['operator']['headers'])
    assert response.status_code==500
    assert response.headers['X-Request-ID']==response.json()['request_id']
    logs='\n'.join(r.getMessage() for r in caplog.records if r.name=='ale.requests')
    assert response.headers['X-Request-ID'] in logs and 'status=500' in logs
    assert 'NEVER_LOG_EXCEPTION_SECRET' not in logs+response.text
