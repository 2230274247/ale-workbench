"""Synchronize Round8 contracts against actual routes/models. No database writes."""
import copy
import inspect
import sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import schemas as runtime, workflow
from gen_models import flatten_object
from validate_contract import bundle, SPEC_FILE

def load(p):return yaml.safe_load(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(yaml.safe_dump(d,allow_unicode=True,sort_keys=False,width=120),encoding='utf-8')
def ref(n):return {'$ref':'#/components/schemas/'+n}
def obj(p,required=None):return {'type':'object','additionalProperties':False,'properties':p,'required':list(p) if required is None else required}
def arr(s):return {'type':'array','items':s}
def null(s):return {'anyOf':[s,{'type':'null'}]}
def enum(*values):return {'type':'string','enum':list(values)}
S={'type':'string'};B={'type':'boolean'};I={'type':'integer','minimum':0};ID={'type':'integer','exclusiveMinimum':0};DT={'type':'string','format':'date-time'}

def main():
 rootfile=ROOT/'api/openapi/openapi.yaml';root=load(rootfile)
 domainfile=ROOT/'api/openapi/components/schemas/domain.yaml';domain=load(domainfile)
 for name,table in [('Batch','batches'),('Sample','samples'),('ExperimentPlan','experiment_plans'),('Process','processes')]:
  fields={'voided_at':null(DT),'void_reason':null({'type':'string','maxLength':2000}),'voided_by_user_id':null(ID)}
  if name=='Sample':fields.update(archived_at=null(DT),archived_by_user_id=null(ID))
  if name=='ExperimentPlan':fields['archive_previous_status']=null({'type':'string','maxLength':24})
  for key,value in fields.items():
   domain[name]['properties'][key]={**value,'readOnly':True,'x-db-column':table+'.'+key}
   if key not in domain[name]['required']:domain[name]['required'].append(key)
 save(domainfile,domain)
 spec=bundle(SPEC_FILE);all_schemas=spec['components']['schemas'];schemas={}
 # Strict record projections match select(table), including every nullable column.
 for name in ('Batch','Sample','ExperimentPlan','Process'):
  record=copy.deepcopy(all_schemas[name]);record['properties'].pop('batch_code',None) if name=='Sample' else None
  record['required']=list(record['properties']);record['additionalProperties']=False
  if name=='Process':
   record['properties']['is_independent_run']={'anyOf':[B,{'type':'integer','enum':[0,1]}]}
  for flag in ('anomaly_flag','exclude_from_analysis'):
   if flag in record['properties']:record['properties'][flag]={'anyOf':[B,{'type':'integer','enum':[0,1]}]}
  schemas['Lifecycle'+name]=record
 schemas['WorkflowOwner']=obj({'user_id':ID,'username':S,'display_name':null(S)})
 for name,base in [('WorkflowPlanDetail','PlanGridDetail'),('WorkflowProcessDetail','ProcessGridDetail')]:
  detail=flatten_object(all_schemas[base],all_schemas);detail['additionalProperties']=False
  parent='LifecycleExperimentPlan' if name=='WorkflowPlanDetail' else 'LifecycleProcess'
  detail['properties'].update(copy.deepcopy(schemas[parent]['properties']))
  detail['required']=list(detail['properties'])
  detail['properties']['batch']=null(ref('LifecycleBatch'))
  if name=='WorkflowPlanDetail':detail['properties']['processes']=arr(ref('LifecycleProcess'))
  else:detail['properties']['plan']=null(ref('LifecycleExperimentPlan'))
  if name=='WorkflowPlanDetail':detail['properties']['owner']=null(ref('WorkflowOwner'))
  schemas[name]=detail
 for name,parent,model in [('WorkflowStartPlan','PlanCreate',workflow.StartPlan),('WorkflowStartProcess','ProcessCreate',workflow.StartProcess)]:
  schemas[name]=copy.deepcopy(all_schemas[parent]);schema=schemas[name]
  code='plan_code' if parent=='PlanCreate' else 'process_code'
  schema['required']=[k for k in schema.get('required',[]) if k!=code]
  schema.pop('x-python-definition',None)
  if name=='WorkflowStartProcess':schema['properties']['log_status']['default']='unknown'
  schema['x-python-definition']=f"class {name}({parent}):\n    {code}: Annotated[str, Field(min_length=1, max_length=64)] = Field(default_factory=lambda: '{'PL-' if parent=='PlanCreate' else 'EX-'}' + uuid.uuid4().hex)"+ ("\n    log_status: Literal['ok','partial','aborted','unknown'] = 'unknown'" if parent=='ProcessCreate' else '')
  if parent=='ProcessCreate':
   schema['x-python-definition']+=\
    '\n    steps: list[ProcessStepCreate] = Field(default_factory=list)\n    samples: list[ProcessSampleCreate] = Field(default_factory=list)'
 lifecycle=runtime.LifecycleApply.model_json_schema(ref_template='#/components/schemas/{model}')
 lifecycle.pop('$defs',None)
 lifecycle['x-python-definition']=inspect.getsource(runtime.LifecycleApply).replace('(Input)', '(ApiBaseModel)',1).replace('    preview_token:', "    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)\n    preview_token:")
 # strict integer constraints must survive Pydantic schema generation.
 lifecycle['properties']['expected_row_version']['x-python-strict']=True
 lifecycle['properties']['include_sample_ids']['anyOf'][0]['items']['x-python-strict']=True
 lifecycle['properties']['sample_versions']['additionalProperties']['x-python-strict']=True
 schemas['LifecycleApply']=lifecycle
 actions=enum('archive','archive_with_dependents','void','delete','restore')
 schemas['LifecycleGroup']=obj({'type':S,'label':S,'count':I,'restricted':B,'deletable_hint':B})
 schemas['LifecycleStatus']=obj({'status':null(S),'archived_at':null(DT),'voided_at':null(DT),'void_reason':null(S)})
 schemas['LifecycleSampleCandidate']=obj({'sample_id':ID,'sample_code':S,'row_version':ID})
 schemas['LifecycleSampleCounts']=obj({'total':I,'available':I,'unused_candidates':I,'candidates':arr(ref('LifecycleSampleCandidate'))})
 schemas['LifecycleSharedSample']=obj({'sample_id':ID,'process_count':I})
 schemas['LifecycleSharedPlan']=obj({'plan_id':ID,'process_count':I})
 schemas['LifecycleShared']=obj({'shared_samples':arr(ref('LifecycleSharedSample')),'shared_plans':arr(ref('LifecycleSharedPlan'))})
 schemas['LifecycleImpact']=obj({'kind':enum('batches','samples','plans','processes'),'id':ID,'code':null(S),'row_version':ID,
  'status':ref('LifecycleStatus'),'archived':B,'can_restore':B,'groups':arr(ref('LifecycleGroup')),'restricted':B,
  'restricted_flag':null(S),'shared':ref('LifecycleShared'),'sample_counts':null(ref('LifecycleSampleCounts')),
  'dependencies_total_visible':I,'delete_blocked':B,'delete_allowed':B,'delete_permitted':B,'void_allowed':B,
  'actions':arr(actions),'preview_token':{'type':'string','pattern':'^[a-f0-9]{64}$'}})
 deleted=[]
 for name,pk,code in [('Batch','batch_id','batch_code'),('Sample','sample_id','sample_code'),('Plan','plan_id','plan_code'),('Process','process_id','process_code')]:
  n='LifecycleDeleted'+name;schemas[n]=obj({pk:ID,code:S,'deleted':{'type':'boolean','enum':[True]}});deleted.append(ref(n))
 schemas['LifecycleApplyResult']={'oneOf':[ref('Lifecycle'+n) for n in ('Batch','Sample','ExperimentPlan','Process')]+deleted}
 schemas['WorkflowStage']=obj({'key':enum('goal','plan','matrix','samples','execution','actual','measurement'),'status':enum('saved','empty')})
 schemas['WorkflowState']=obj({'plan':null(ref('WorkflowPlanDetail')),'process':null(ref('WorkflowProcessDetail')),
  'measurements':arr(ref('Measurement')),'stages':{'type':'array','items':ref('WorkflowStage'),'minItems':7,'maxItems':7}})
 todo_kinds=('plan_without_process','process_log','import_pending','import_failure','measurement_review','issue')
 # Concrete query objects prevent arbitrary navigation payloads in generated types.
 def query(**fields):return obj(fields)
 todo=[]
 for kind,key,path in [('plan_without_process','plan_id','/plans'),('process_log','process_id','/processes'),('import_pending','job','/imports'),('import_failure','job','/imports'),('measurement_review','id','/measurements'),('issue',None,None)]:
  fields={'kind':enum(kind),'entity_id':ID,'code':null(S),'title':S,'detail':S,'status':S,'updated_at':null(DT),
   'path':{'type':'null'} if path is None else enum(path),'query':{'type':'null'} if key is None else query(**{key:ID})}
  if kind=='issue':fields['severity']=S
  n='DashboardTodo'+''.join(w.title() for w in kind.split('_'));schemas[n]=obj(fields);todo.append(ref(n))
 schemas['DashboardTodoItem']={'oneOf':todo}
 schemas['DashboardTodo']=obj({'generated_at':DT,'total':I,'counts':obj({k:I for k in todo_kinds}),'items':arr(ref('DashboardTodoItem'))})
 common={'entity_id':ID,'code':S,'title':S,'status':S,'batch_id':null(ID),'updated_at':null(DT),'can_continue':B,'continue_label':S}
 schemas['DashboardRecentPlan']=obj({**common,'kind':enum('plan'),'path':enum('/plans'),'query':query(plan_id=ID),'continue_path':enum('/plans','/processes'),
  'continue_query':{'oneOf':[query(plan_id=ID),obj({'create':enum('1'),'plan_id':ID,'batch_id':ID},['create','plan_id'])]}})
 schemas['DashboardRecentProcess']=obj({**common,'kind':enum('process'),'plan_id':null(ID),'archived':B,'path':enum('/processes'),'query':query(process_id=ID),'continue_path':enum('/processes'),'continue_query':query(process_id=ID)})
 schemas['DashboardRecentExperimentItem']={'oneOf':[ref('DashboardRecentPlan'),ref('DashboardRecentProcess')]}
 schemas['DashboardRecentExperiments']=obj({'generated_at':DT,'items':arr(ref('DashboardRecentExperimentItem'))})
 common={'entity_id':ID,'code':null(S),'title':S,'status':S,'hint':null(S),'occurred_at':null(DT)}
 for kind,path,key,extra in [('import_job','/imports','job',{}),('measurement','/measurements','id',{'stage':ref('MeasurementStage'),'sample_id':ID}),('source_file','/source-files','id',{'size_bytes':null(I)})]:
  n='DashboardRecent'+''.join(w.title() for w in kind.split('_'));schemas[n]=obj({**common,'kind':enum(kind),'path':enum(path),'query':query(**{key:ID}),**extra})
 schemas['DashboardRecentDataItem']={'oneOf':[ref('DashboardRecentImportJob'),ref('DashboardRecentMeasurement'),ref('DashboardRecentSourceFile')]}
 schemas['DashboardRecentData']=obj({'generated_at':DT,'items':arr(ref('DashboardRecentDataItem'))})
 for name,schema in schemas.items():
  for field in schema.get('properties',{}).values():field.setdefault('x-db-column',False)
  root['components']['schemas'][name]={'$ref':'./components/schemas/round8.yaml#/'+name}
 save(ROOT/'api/openapi/components/schemas/round8.yaml',schemas)
 def operation(opid,response,body=None,status='200',tag='首页'):
  envelope=obj({'code':{'type':'integer','enum':[0]},'message':S,'data':ref(response),'request_id':{'type':'string','format':'uuid'},'timestamp':DT})
  op={'tags':[tag],'operationId':opid,'summary':opid,'x-implementation-status':'implemented','responses':{status:{'description':'成功；真实记录统一包络','content':{'application/json':{'schema':envelope}}}}}
  for c,n in [('401','Unauthorized'),('403','Forbidden'),('404','NotFound'),('409','Conflict'),('422','UnprocessableEntity'),('503','ServiceUnavailable')]:op['responses'][c]={'$ref':'#/components/responses/'+n}
  if body:op['requestBody']={'required':True,'content':{'application/json':{'schema':ref(body)}}}
  return op
 from fastapi.openapi.utils import get_openapi
 from app.main import app
 actual=get_openapi(title=app.title,version=app.version,routes=app.routes)
 new=[('/api/v1/lifecycle/{kind}/{id}/impact','get','getLifecycleImpact','LifecycleImpact',None,'200','生命周期'),
 ('/api/v1/lifecycle/{kind}/{id}/apply','post','applyLifecycle','LifecycleApplyResult','LifecycleApply','200','生命周期'),
 ('/api/v1/workflow/plans','post','startWorkflowPlan','WorkflowPlanDetail','WorkflowStartPlan','201','实验向导'),
 ('/api/v1/workflow/processes','post','startWorkflowProcess','WorkflowProcessDetail','WorkflowStartProcess','201','实验向导'),
 ('/api/v1/workflow/state','get','getWorkflowState','WorkflowState',None,'200','实验向导'),
 ('/api/v1/dashboard/todo','get','getDashboardTodo','DashboardTodo',None,'200','首页'),
 ('/api/v1/dashboard/recent-experiments','get','getDashboardRecentExperiments','DashboardRecentExperiments',None,'200','首页'),
 ('/api/v1/dashboard/recent-data','get','getDashboardRecentData','DashboardRecentData',None,'200','首页')]
 for path,method,opid,response,body,status,tag in new:
  op=operation(opid,response,body,status,tag);op['parameters']=copy.deepcopy(actual['paths'][path][method].get('parameters',[]))
  if '/lifecycle/' in path:
   op['description']='kind 仅支持 batches/samples/plans/processes，其他值404。影响预览按可见范围返回；应用需预览token、operation_id和父版本CAS。恢复权限及当前可执行action以预览为准；同operation_id相同payload可重试；无级联删除。'
  if '/workflow/' in path:
   op['description']='既有计划/执行记录作为草稿。缺省编码由服务端生成。关联计划仅复制步骤骨架和单位，未知实际值保持null。state只按真实保存记录计算7阶段。'
  root['paths'][path]={method:op}
 # Sync filters from actual signatures, preserve existing operationIds and responses.
 for path in ('/api/v1/batches','/api/v1/samples','/api/v1/batches/{id}/samples','/api/v1/plans','/api/v1/processes'):
  entry=root['paths'][path]
  if '$ref' in entry:
   file,pointer=entry['$ref'].split('#');target=ROOT/'api/openapi'/file;data=load(target);key=pointer.lstrip('/').replace('~1','/').replace('~0','~');op=data[key]['get']
  else:op=entry['get'];target=None
  names={p.get('name') for p in op.get('parameters',[])}
  for p in actual['paths'][path]['get'].get('parameters',[]):
   if p['name'] in ('include_voided','include_archived'):
    if p['name'] in names:op['parameters']=[p if old.get('name')==p['name'] else old for old in op['parameters']]
    else:op.setdefault('parameters',[]).append(p)
  if target:save(target,data)
 for tag in ('生命周期','实验向导'):
  if not any(t['name']==tag for t in root['tags']):root['tags'].append({'name':tag})
 root['info']['version']='1.8.0';root['info']['summary']='第八轮：记录生命周期、实验向导与首页聚合'
 old=root['info']['description'];old=old[old.find('当前1.7.0：'):] if '当前1.7.0：' in old else old
 root['info']['description']='当前1.8.0：0011/0012增量生命周期元数据；生命周期影响预览/应用、实验向导和三个首页聚合，共8个新增实际操作。四类记录include_voided，样品另有include_archived；作废与归档不改写科学观测。\n\n'+old
 save(rootfile,root)
 print('Round8 sync: 8 operations; %d schemas; actual filters and additive lifecycle fields'%len(schemas))
if __name__=='__main__':main()
