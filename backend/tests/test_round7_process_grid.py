"""Real MySQL grid acceptance; all writes rolled back by fixtures."""
import copy
import uuid
from sqlalchemy import select
from app.db import table


def snapshot(kind='自定义氩气预处理', value='12', unit='ms'):
    return {'step_type':kind,'temperature':{'value':None,'unit':'K'},'groups':[{'name':'脉冲','fields':[{'name':'时长','value':value,'unit':unit}]},{'name':'源','fields':[{'name':'名称','value':'Ar','unit':None}]}]}


def setup(client, actors):
    h=actors['operator']['headers']
    p=client.post('/api/v1/plans',headers=h,json={'plan_code':'R7-'+uuid.uuid4().hex[:20],'title':'通用流程'}).json()['data']
    return h,p


def grid(version, steps):
    return {'expected_row_version':version,'steps':steps,'process_flow':{'version':1,'total_cycles':None,'children':[{'kind':'group','id':'g1','name':'Ar / Xe 组合','repeat':3,'children':[{'kind':'group','id':'g2','name':'嵌套脉冲','repeat':None,'children':[{'kind':'step','id':'n'+str(i),'step_id':s['key']} for i,s in enumerate(steps)]}]}]}}


def test_nested_grid_cas_units_templates_ownership_and_rollback(client, actors, db):
    h,p=setup(client,actors)
    steps=[{'key':'a','step_kind':'任意分类 α','step_name':'Ar 活化','parameter_snapshot':snapshot()}, {'key':'b','step_kind':'用户 B 的 Xe 处理','step_name':'Xe 等待','parameter_snapshot':snapshot('Xe','0.5','s')}]
    body=grid(p['row_version'],steps)
    path=f"/api/v1/plans/{p['plan_id']}/process-grid"
    response=client.put(path,headers=h,json=body)
    assert response.status_code==200,response.text
    saved=response.json()['data'];assert saved['row_version']==p['row_version']+1
    assert saved['process_flow']['total_cycles'] is None
    assert saved['process_flow']['children'][0]['children'][0]['repeat'] is None
    assert [s['parameter_snapshot']['groups'][0]['fields'][0]['unit'] for s in saved['steps']]==['ms','s']
    ids=[s['step_id'] for s in saved['steps']]
    assert client.put(path,headers=h,json=body).status_code==409
    assert client.put(path,headers=actors['other']['headers'],json=body).status_code==404
    assert client.put(path,headers=actors['viewer']['headers'],json=body).status_code==403
    assert client.get(path.rsplit('/process-grid',1)[0],headers=h).json()['data']==saved
    template=client.post('/api/v1/step-parameter-templates',headers=h,json={'template_name':'Xe 自定义类型','definition':steps[1]['parameter_snapshot']})
    assert template.status_code==201,template.text
    tid=template.json()['data']['template_id']
    assert client.get(f'/api/v1/step-parameter-templates/{tid}',headers=h).json()['data']['definition']==steps[1]['parameter_snapshot']
    assert client.get(f'/api/v1/step-parameter-templates/{tid}',headers=actors['other']['headers']).status_code==404
    # Reverse existing rows, preserving their IDs and legacy columns.
    t=table('experiment_plan_steps');db.execute(t.update().where(t.c.step_id==ids[0]).values(planned_parameters={'cycles':9},custom_parameters={'old':{'value':'kept'}}))
    update=grid(saved['row_version'],[{**steps[1],'step_id':ids[1]},{**steps[0],'step_id':ids[0]}])
    again=client.put(path,headers=h,json=update);assert again.status_code==200,again.text
    newer=again.json()['data'];assert [s['step_id'] for s in newer['steps']]==ids[::-1]
    assert newer['steps'][1]['planned_parameters']=={'cycles':9}
    assert newer['steps'][1]['custom_parameters']=={'old':{'value':'kept'}}
    # Failure after staging a new row must roll back every row and parent version.
    bad=copy.deepcopy(update);bad['expected_row_version']=newer['row_version'];bad['process_flow']['children'][0]['children'][0]['children'][0]['step_id']='missing'
    assert client.put(path,headers=h,json=bad).status_code==422
    assert client.get(path.rsplit('/process-grid',1)[0],headers=h).json()['data']==newer
    # Legacy single-row additions and deletions maintain the anchored flow.
    single=client.post(f"/api/v1/plans/{p['plan_id']}/steps",headers=h,json={'step_index':3,'step_kind':'自由分类 C','parameter_snapshot':snapshot()})
    assert single.status_code==201,single.text
    added=single.json()['data'];parent=client.get(f"/api/v1/plans/{p['plan_id']}",headers=h).json()['data']
    assert parent['process_flow']['children'][-1]['step_id']==added['step_id']
    assert client.delete(f"/api/v1/plan-steps/{added['step_id']}",headers=h,params={'expected_row_version':parent['row_version']}).status_code==204


def test_actual_mapping_keeps_values_independent_and_source_ids(client, actors, db):
    h,p=setup(client,actors)
    ps=client.post(f"/api/v1/plans/{p['plan_id']}/steps",headers=h,json={'step_index':1,'step_kind':'任意 B','parameter_snapshot':snapshot(value='planned')}).json()['data']
    response=client.post('/api/v1/processes',headers=h,json={'process_code':'R7-'+uuid.uuid4().hex[:20],'process_mode':'other','plan_id':p['plan_id'],'steps':[{'step_index':1,'step_kind':'任意 B','plan_step_id':ps['step_id'],'parameter_snapshot':snapshot(value=None)}],'process_flow':{'version':1,'total_cycles':None,'children':[{'kind':'group','id':'actual-g','name':'实际未知重复','repeat':None,'children':[{'kind':'step','id':'actual-s','step_id':'index:1'}]}]}})
    assert response.status_code==201,response.text
    actual=response.json()['data'];s=actual['steps'][0]
    assert s['parameter_snapshot']['groups'][0]['fields'][0]['value'] is None
    assert actual['process_flow']['children'][0]['children'][0]['step_id']==s['step_id']
    db.execute(table('process_steps').update().where(table('process_steps').c.step_id==s['step_id']).values(pulse_s='2.500',custom_parameters={'legacy':{'value':'preserved'}}))
    body=grid(actual['row_version'],[{'key':'actual','step_id':s['step_id'],'step_kind':s['step_kind'],'step_name':'实际 Xe','plan_step_id':ps['step_id'],'parameter_snapshot':snapshot(value='actual')}])
    response=client.put(f"/api/v1/processes/{actual['process_id']}/process-grid",headers=h,json=body)
    assert response.status_code==200,response.text
    saved=response.json()['data']['steps'][0]
    assert saved['step_id']==s['step_id'] and saved['plan_step_id']==ps['step_id']
    assert saved['pulse_s']=='2.500' and saved['custom_parameters']=={'legacy':{'value':'preserved'}}
    assert client.get(f"/api/v1/plans/{p['plan_id']}",headers=h).json()['data']['steps'][0]['parameter_snapshot']['groups'][0]['fields'][0]['value']=='planned'


def test_bounded_flow_validation(client,actors):
    h,p=setup(client,actors)
    body=grid(p['row_version'],[]);path=f"/api/v1/plans/{p['plan_id']}/process-grid"
    body['process_flow']['total_cycles']=-1
    assert client.put(path,headers=h,json=body).status_code==422
    body['process_flow']['total_cycles']=None
    node=body['process_flow']['children'][0]
    for i in range(5):
        child={'kind':'group','id':f'deep{i}','name':'deep','repeat':1,'children':[]};node['children']=[child];node=child
    assert client.put(path,headers=h,json=body).status_code==422


def test_mapped_plan_flow_failure_rolls_back_staged_new_step(client,actors,db):
    h,p=setup(client,actors)
    body=grid(p['row_version'],[{'key':'planned','step_kind':'Xe 任意分类','parameter_snapshot':snapshot()}])
    saved=client.put(f"/api/v1/plans/{p['plan_id']}/process-grid",headers=h,json=body).json()['data']
    sid=saved['steps'][0]['step_id']
    actual=client.post('/api/v1/processes',headers=h,json={'process_code':'R7map-'+uuid.uuid4().hex[:16],'process_mode':'other','plan_id':p['plan_id'],'steps':[{'step_index':1,'step_kind':'Xe 任意分类','plan_step_id':sid}]} )
    assert actual.status_code==201,actual.text
    before=client.get(f"/api/v1/plans/{p['plan_id']}",headers=h).json()['data']
    update=grid(before['row_version'],[{'key':'planned','step_id':sid,'step_kind':'Xe 任意分类','parameter_snapshot':snapshot()},{'key':'new','step_kind':'Ar','parameter_snapshot':snapshot()}])
    response=client.put(f"/api/v1/plans/{p['plan_id']}/process-grid",headers=h,json=update)
    assert response.status_code==409,response.text
    assert client.get(f"/api/v1/plans/{p['plan_id']}",headers=h).json()['data']==before
    print('Late guard rollback verified: staged insert, temporary index rewrite, snapshots and parent all rolled back')


def test_generic_chemistry_names_and_template_classification(client,actors):
    h=actors['other']['headers']
    system=client.post('/api/v1/chemistry-systems',headers=h,json={'system_code':'R7chem-'+uuid.uuid4().hex[:16],'system_name':'Xe / Ar 任意用户 C 体系'})
    assert system.status_code==201,system.text
    sid=system.json()['data']['system_id']
    template=client.post(f'/api/v1/chemistry-systems/{sid}/step-templates',headers=h,json={'template_code':'custom','template_name':'无固定化学前缀','steps':[{'name':'任意长步骤','kind':'用户 C 自定义分类 '+('X'*40),'loop_count':None,'parameters':[]}]})
    assert template.status_code==201,template.text
    detail=client.get(f'/api/v1/chemistry-systems/{sid}',headers=h).json()['data']
    assert detail['templates'][0]['steps'][0]['kind'].endswith('X'*40)
    assert client.get(f'/api/v1/chemistry-systems/{sid}',headers=actors['operator']['headers']).status_code==404


def test_authority_metadata_preserves_conflicting_legacy_on_all_reads(client,actors,db):
    h=actors['operator']['headers']
    r=client.post('/api/v1/processes',headers=h,json={'process_code':'authority-'+uuid.uuid4().hex[:16],'process_mode':'other','steps':[{'step_index':1,'step_kind':'Ar','pulse_s':'2.500','duration_s':'9.000','cycles':7,'parameter_snapshot':snapshot(value='12')}]}).json()['data']
    sid=r['steps'][0]['step_id'];s=r['steps'][0]
    assert s['parameter_source']=='parameter_snapshot'
    assert s['legacy_parameters_status']=='historical_readonly' and s['parameter_conflict']
    assert s['legacy_parameters']['pulse_s']=='2.500'
    assert client.get(f"/api/v1/processes/{r['process_id']}/steps",headers=h).json()['data'][0]==s
    changed=client.patch(f'/api/v1/process-steps/{sid}',headers=h,json={'step_note':'unrelated'}).json()['data']
    assert changed['parameter_source']=='parameter_snapshot' and changed['pulse_s']=='2.500'
    assert changed['parameter_snapshot']==snapshot(value='12')


def test_all_process_writes_freeze_for_scientific_references_without_transitions(client,actors,db):
    h=actors['operator']['headers']
    b=client.post('/api/v1/batches',headers=h,json={'batch_code':'guard-'+uuid.uuid4().hex[:16],'batch_name':'guard'}).json()['data']
    sample=client.post('/api/v1/samples',headers=h,json={'sample_code':'guard-'+uuid.uuid4().hex[:16],'batch_id':b['batch_id']}).json()['data']
    for reference in ('measurements','instrument_datasets','derived_results','polymorphic_process'):
        r=client.post('/api/v1/processes',headers=h,json={'process_code':'guard-'+uuid.uuid4().hex[:16],'process_mode':'other','steps':[{'step_index':1,'step_kind':'Ar','parameter_snapshot':snapshot()}],'samples':[{'sample_id':sample['sample_id']}]}).json()['data']
        pid=r['process_id'];sid=r['steps'][0]['step_id'];lid=r['samples'][0]['process_sample_id']
        common={'process_id':pid,'sample_id':sample['sample_id']}
        if reference=='measurements':db.execute(table(reference).insert().values(**common,measurement_code=uuid.uuid4().hex,stage='initial'))
        elif reference=='instrument_datasets':db.execute(table(reference).insert().values(**common,dataset_code=uuid.uuid4().hex,instrument_type='other'))
        elif reference=='derived_results':db.execute(table(reference).insert().values(**common,result_code=uuid.uuid4().hex,result_kind='other'))
        else:
            from app.db import metadata
            # Existing generic scientific links must protect the entire run too.
            candidates=[t for t in metadata().tables.values() if 'entity_type' in t.c and 'entity_id' in t.c and t.name!='audit_log']
            assert candidates
            # Exercise the link type with the known minimal attachment schema.
            t=next(t for t in candidates if t.name=='attachments')
            values={'entity_type':'process','entity_id':pid}
            for c in t.c:
                if c.name not in values and not c.nullable and not c.server_default and not c.primary_key:
                    values[c.name]=1 if 'INT' in str(c.type) else 'guard'
            db.execute(t.insert().values(**values))
        before=client.get(f'/api/v1/processes/{pid}',headers=h).json()['data']
        calls=[('patch',f'/processes/{pid}',{'notes':'overwrite'}),('post',f'/processes/{pid}/steps',{'step_index':2,'step_kind':'new'}),('patch',f'/process-steps/{sid}',{'step_note':'overwrite'}),('delete',f'/process-steps/{sid}',None),('post',f'/processes/{pid}/samples',{'sample_id':sample['sample_id']}),('patch',f'/process-samples/{lid}',{'sample_role_note':'overwrite'}),('delete',f'/process-samples/{lid}',None),('delete',f'/processes/{pid}',None),('put',f'/processes/{pid}/process-grid',grid(before['row_version'],[]))]
        for method,path,body in calls:
            response=client.request(method,'/api/v1'+path,headers=h,**({'json':body} if body is not None else {}))
            assert response.status_code==409,(reference,method,path,response.text)
            assert ' 条' not in response.text
            assert client.get(f'/api/v1/processes/{pid}',headers=h).json()['data']==before


def test_empty_process_editable_and_multiple_executions_stay_independent(client,actors):
    h,p=setup(client,actors)
    runs=[]
    for _ in range(2):
        r=client.post('/api/v1/processes',headers=h,json={'process_code':'multi-'+uuid.uuid4().hex[:16],'process_mode':'other','plan_id':p['plan_id']}).json()['data'];runs.append(r)
    path=f"/api/v1/processes/{runs[0]['process_id']}"
    assert client.patch(path,headers=h,json={'notes':'empty structure is editable'}).status_code==200
    step=client.post(path+'/steps',headers=h,json={'step_index':1,'step_kind':'Ar'});assert step.status_code==201
    sid=step.json()['data']['step_id']
    assert client.delete(f'/api/v1/process-steps/{sid}',headers=h).status_code==204
    original=client.get(f"/api/v1/processes/{runs[1]['process_id']}",headers=h).json()['data']
    assert original==runs[1]
    updated=client.patch(f"/api/v1/plans/{p['plan_id']}",headers=h,json={'title':'revised plan metadata'})
    assert updated.status_code==200
    assert updated.json()['data']['process_count']==2
    for run in runs:
        after=client.get(f"/api/v1/processes/{run['process_id']}",headers=h).json()['data']
        assert after['steps']==[] and after['plan_id']==p['plan_id']
