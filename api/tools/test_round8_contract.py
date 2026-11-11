"""Round8 canonical/generated/live-wire parity; rollback-only MySQL fixtures."""
import copy
import importlib.util
import json
import sys
import uuid
from pathlib import Path
import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from conftest import actors
from test_phase4_browser import db, client
from app import schemas as runtime, workflow
SPEC=yaml.safe_load((ROOT/'api/openapi/openapi.bundled.yaml').read_text(encoding='utf-8'))
module=importlib.util.spec_from_file_location('round8_generated',ROOT/'api/models/python/schemas.py')
G=importlib.util.module_from_spec(module);sys.modules[module.name]=G;module.loader.exec_module(G)

def validate(name,value):
 schema={**SPEC['components']['schemas'][name],'components':SPEC['components']}
 Draft202012Validator(schema,format_checker=FormatChecker()).validate(value)
 TypeAdapter(getattr(G,name)).validate_python(value)

def test_request_parity():
 base=dict(action='archive',expected_row_version=1,preview_token='a'*64,operation_id='a'*16)
 pairs=[(runtime.LifecycleApply,G.LifecycleApply,[base,{**base,'reason':'  reason  '},{**base,'sample_versions':{'1':2},'include_sample_ids':[1]}, {},{**base,'extra':1},{**base,'expected_row_version':True},{**base,'expected_row_version':'1'},{**base,'include_sample_ids':[True]},{**base,'sample_versions':{'1':True}},{**base,'action':'invented'}]),
 (workflow.StartPlan,G.WorkflowStartPlan,[{'title':'Goal'},{'title':'Goal','plan_code':'explicit'}, {},{'title':'x','owner_user_id':1}]),
 (workflow.StartProcess,G.WorkflowStartProcess,[{'process_mode':'other'},{'process_mode':'other','steps':[]},{},{'process_mode':'other','operator_user_id':1}])]
 count=0
 for actual,generated,cases in pairs:
  assert set(actual.model_fields)==set(generated.model_fields)
  assert {k for k,v in actual.model_fields.items() if v.is_required()}=={k for k,v in generated.model_fields.items() if v.is_required()}
  for value in cases:
   results=[]
   for model in (actual,generated):
    try:results.append(model.model_validate(value).model_dump(mode='json'))
    except (ValueError,TypeError):results.append(None)
   assert (results[0] is None)==(results[1] is None),(actual.__name__,value)
   if results[0] is not None:
    for code in ('plan_code','process_code'):
     if code not in value:
      for result in results:result.pop(code,None)
    assert results[0]==results[1]
   count+=1
 print('ROUND8 REQUEST PARITY: 3 actual/generated models; %d positive/negative fixtures PASS'%count)

def test_wire_contracts(client,actors,db):
 headers=actors['operator']['headers'];count=0
 def call(method,path,body=None,role=None):
  nonlocal count
  r=client.request(method,'/api/v1'+path,headers=actors[role]['headers'] if role else headers,json=body)
  assert r.status_code in (200,201),(path,r.status_code)
  # Resolve actual path placeholders, independent of FastAPI response annotations.
  route='/api/v1'+path.split('?')[0]
  for template,item in SPEC['paths'].items():
   import re
   if re.fullmatch(re.sub(r'\{[^}]+\}',r'[^/]+',template),route) and method.lower() in item:
    schema=item[method.lower()]['responses'][str(r.status_code)]['content']['application/json']['schema']
    Draft202012Validator({**schema,'components':SPEC['components']},format_checker=FormatChecker()).validate(r.json());break
  else:raise AssertionError(route)
  count+=1;return r.json()['data']
 tag=uuid.uuid4().hex
 batch=call('POST','/batches',{'batch_code':'CT-'+tag,'batch_name':'Contract rollback'})
 sample=call('POST','/samples',{'sample_code':'CS-'+tag,'batch_id':batch['batch_id'],'sample_type':'coupon'})
 plan=call('POST','/workflow/plans',{'title':'Contract rollback','batch_id':batch['batch_id']})
 process=call('POST','/workflow/processes',{'process_mode':'other','plan_id':plan['plan_id']})
 validate('WorkflowPlanDetail',plan);validate('WorkflowProcessDetail',process)
 for query in ('','?plan_id='+str(plan['plan_id']),'?process_id='+str(process['process_id'])):
  validate('WorkflowState',call('GET','/workflow/state'+query))
 # Populate every dashboard variant using rollback-only rows, with no original files written.
 from test_round8_dashboard import make_job,make_item,make_measurement,make_source,make_plan
 from app.db import table
 from sqlalchemy import select
 job=make_job(db,actors,'operator');make_item(db,job,parse_status='rejected')
 make_measurement(db,sample['sample_id'],quality='suspect')
 make_source(db,'contract-rollback.dat',parse_status='failed',sid=sample['sample_id'])
 make_plan(db,actors,'operator',batch['batch_id'])
 db.execute(table('issues').insert().values(issue_code='CI-'+tag[:12],title='Contract rollback',severity='high',status='open'))
 for suffix,name in [('todo','DashboardTodo'),('recent-experiments','DashboardRecentExperiments'),('recent-data','DashboardRecentData')]:
  for role in ('operator','admin','viewer'):
   value=call('GET','/dashboard/'+suffix,role=role);validate(name,value)
   with pytest.raises(Exception):validate(name,{**value,'invented':True})
 for kind,row,pk in [('batches',batch,'batch_id'),('samples',sample,'sample_id'),('plans',plan,'plan_id'),('processes',process,'process_id')]:
  path=f"/lifecycle/{kind}/{row[pk]}";info=call('GET',path+'/impact');validate('LifecycleImpact',info)
  for action in ('archive','restore'):
   payload=dict(action=action,expected_row_version=info['row_version'],preview_token=info['preview_token'],operation_id=uuid.uuid4().hex)
   value=call('POST',path+'/apply',payload);validate('LifecycleApplyResult',value)
   with pytest.raises(Exception):validate('LifecycleApplyResult',{**value,'invented':True})
   info=call('GET',path+'/impact')
  call('GET','/'+kind+'?include_voided=true')
 # Exercise delete receipt union without touching persistent records.
 fresh=call('POST','/workflow/plans',{'title':'Unused rollback'})
 p=f"/lifecycle/plans/{fresh['plan_id']}";info=call('GET',p+'/impact',role='admin')
 value=call('POST',p+'/apply',dict(action='delete',expected_row_version=info['row_version'],preview_token=info['preview_token'],operation_id=uuid.uuid4().hex),role='admin')
 validate('LifecycleApplyResult',value)
 print('ROUND8 LIVE WIRE: %d responses PASS; strict JSON Schema + generated Pydantic; all four kinds archive/restore, delete receipt, wizard and dashboard roles'%count)
