"""Synchronize Round7 contract from actual request models; never connects to DB."""
import ast
import copy
import inspect
import re
import sys
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend'))
from app import scientificanalysis as analysis, process_flow as flow, schemas as runtime

NAMES = {'Source':'AnalysisSource','Selection':'AnalysisSelection','Calculate':'AnalysisCalculate',
         'PairRequest':'PairingRequest','SaveRequest':'AnalysisSave','FlowNode':'FlowNode',
         'ProcessFlow':'ProcessFlow','GridStep':'GridStep','ProcessGridSave':'ProcessGridSave'}
MODELS = [analysis.Source, analysis.Selection, analysis.Calculate, analysis.PairRequest, analysis.SaveRequest,
          flow.FlowNode, flow.ProcessFlow, runtime.GridStep, runtime.ProcessGridSave]

def load(path): return yaml.safe_load(path.read_text(encoding='utf-8'))
def save(path, data): path.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False,width=120),encoding='utf-8')
def ref(name):return {'$ref':'#/components/schemas/'+name}
def obj(props, required=None):return {'type':'object','additionalProperties':False,'properties':props,'required':list(props) if required is None else required}
def array(item):return {'type':'array','items':item}
def nullable(item):return {'anyOf':[item,{'type':'null'}]}
def literal(value):return {'type':'boolean' if isinstance(value,bool) else 'integer' if isinstance(value,int) else 'string','enum':[value]}
S={'type':'string'}; B={'type':'boolean'}; I={'type':'integer','minimum':0}; D={'type':'string','pattern':r'^-?\d+(?:\.\d+)?$'}


def sync_step_metadata(domain):
    """Response-only authority metadata shared by planned and actual steps."""
    metadata = {
        'parameter_source': {'type':'string','enum':['parameter_snapshot','legacy_fields'],
                             'description':'当前参数来源；非空快照优先，旧字段保持原值。'},
        'legacy_parameters': {'type':'object','additionalProperties':True,
                              'description':'原样返回已记录旧字段及custom_parameters；不推断单位或转换数值。'},
        'legacy_parameters_status': {'type':'string','enum':['historical_readonly','current'],
                                     'description':'存在快照时旧值仅供历史读取，否则仍为当前参数。'},
        'parameter_conflict': {'type':'boolean',
                               'description':'非空快照与非空旧参数同时存在；不表示已推断数值是否相等。'},
    }
    for name in ('PlanStep','ProcessStep'):
        schema=domain[name]
        for field,definition in metadata.items():
            schema['properties'][field]={**copy.deepcopy(definition),'readOnly':True,'x-db-column':False}
            if field not in schema['required']:schema['required'].append(field)


def main():
    rootfile=ROOT/'api/openapi/openapi.yaml'; root=load(rootfile)
    target=ROOT/'api/openapi/components/schemas/measurement.yaml'; schemas=load(target)
    aliases={'Positive':"Annotated[int, Field(strict=True, gt=0)]",'Stage':repr(analysis.Stage).replace('typing.',''),
             'Name':"Annotated[str, Field(min_length=1, max_length=128)]",
             'Reference':"Annotated[int, Field(strict=True, gt=0)] | Annotated[str, Field(min_length=1, max_length=80)]",
             'Repeat':"Annotated[int, Field(strict=True, ge=0, le=1000000)] | None",
             'Id':"Annotated[int, Field(strict=True, gt=0)]",'StepKind':"Annotated[str, Field(min_length=1, max_length=128)]",
             'StepName':"Annotated[str, Field(max_length=128)]"}
    for cls in MODELS:
        document=cls.model_json_schema(ref_template='#/components/schemas/{model}')
        definitions=document.pop('$defs',{})
        if document.get('$ref') == '#/components/schemas/'+cls.__name__:
            document=definitions[cls.__name__]
        definitions[cls.__name__]=document
        for old, schema in definitions.items():
            if old not in NAMES:continue
            if old != cls.__name__ and schemas.get(NAMES[old],{}).get('x-python-definition'):continue
            text=yaml.safe_dump(schema)
            for a,b in NAMES.items():text=text.replace('#/components/schemas/'+a,'#/components/schemas/'+b)
            schemas[NAMES[old]]=yaml.safe_load(text)
        name=NAMES[cls.__name__]; schema=schemas[name]
        schema['x-python-strict']=bool(cls.model_config.get('strict'))
        schema['x-python-strip-whitespace']=bool(cls.model_config.get('str_strip_whitespace'))
        source=inspect.getsource(cls)
        source=re.sub(r'\((Strict|Input)\)', '(ApiBaseModel)', source, count=1)
        for a,b in {**aliases,**NAMES}.items():source=re.sub(r'\b'+a+r'\b',lambda m:b,source)
        lines=source.splitlines(); lines.insert(1,"    model_config = ConfigDict(extra='forbid', strict=%r, str_strip_whitespace=%r)" % (bool(cls.model_config.get('strict')),bool(cls.model_config.get('str_strip_whitespace'))))
        schema['x-python-definition']='\n'.join(lines)
        for field in schema.get('properties',{}).values():field['x-db-column']=False
    from app import step_templates
    chemistryfile=ROOT/'api/openapi/components/schemas/chemistry.yaml'
    chemistry=load(chemistryfile)
    for cls in (step_templates.ParameterField,step_templates.ParameterGroup,step_templates.Temperature,step_templates.ParameterSnapshot):
        source=inspect.getsource(cls)
        source=source.replace('(Input)', '(ApiBaseModel)',1)
        for alias,value in {'Name':aliases['Name'],'Unit':"Annotated[str, Field(max_length=32)]",'Value':"Annotated[str, Field(max_length=2000)]"}.items():
            source=re.sub(r'\b'+alias+r'\b',lambda m:value,source)
        lines=source.splitlines();lines.insert(1,"    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)")
        chemistry[cls.__name__]['x-python-definition']='\n'.join(lines)
    save(chemistryfile,chemistry)
    # Exact derived response projections: decimals are plain strings, not DB-rounded values.
    schemas['AnalysisMetric']=obj({'count':I,'excluded_nonfinite_or_missing':I,**{k:nullable(D) if k=='sd_sample' else D for k in ('mean','min','max','sd_sample','sd_population')}},['count','excluded_nonfinite_or_missing'])
    schemas['AnalysisStatistics']=obj({'point_count':I,'includes_outliers':B,'sd_convention':obj({'sample':S,'population':S}),'decimal_precision':literal(50),'rounding':literal('ROUND_HALF_EVEN'),'db_write_policy':S,**{k:ref('AnalysisMetric') for k in ('thickness_nm','mse','gof')}})
    point={k:nullable(D) for k in ('x_mm','y_mm','thickness_nm','mse','gof')}
    point.update({k:nullable({'type':'integer'}) for k in ('point_no','source_row','source_file_id','point_id')})
    point.update({k:nullable(S) for k in ('outlier_note','source_sheet','source_cell')});point.update(key=S,included=B,is_outlier=B)
    schemas['AnalysisPoint']=obj(point)
    src={'kind':{'type':'string','enum':['measurement','import_item']},'id':{'type':'integer','exclusiveMinimum':0},'block_index':I,'row_version':{'type':'integer'},'label':S,
         **{k:nullable({'type':'integer'}) for k in ('sample_id','stage_seq','optical_model_id','cumulative_cycles','process_id','source_file_id','import_item_id')},
         **{k:nullable(S) for k in ('stage','parser','parser_version','sha256','quality_flag')},'is_current':B,'recorded_conditions':nullable(ref('AnalysisRecordedConditions')),'points_sha256':S,'optical_model':nullable({'type':'object','additionalProperties':True}),'sample_dependency':obj({'sample_id':{'type':'integer'},'batch_id':{'type':'integer'}}),
         'associations_source':{'type':'string','enum':['user_confirmed_preview','unknown']},'locator':{},'formal_measurements_written':literal(False),'model_parameter_columns':array({}),
         'units':obj({k:S for k in ('thickness_nm','x_mm','y_mm','mse','gof')})}
    schemas['AnalysisSourceMetadata']=obj(src,['kind','id','block_index','row_version','label','sample_id','stage','stage_seq','optical_model_id','cumulative_cycles','parser','parser_version','model_parameter_columns','units','points_sha256','optical_model'])
    schemas['AnalysisSeries']=obj({'source':ref('AnalysisSourceMetadata'),'points':array(ref('AnalysisPoint')),'statistics':ref('AnalysisStatistics'),'raw_count':I,'included_count':I,'excluded_count':I,'mapping':obj({'available':B,'actual_xy_point_count':I,'interpolation_available':literal(False),'note':S}),'warnings':array(S)})
    schemas['AnalysisPairPoint']=obj({**{k:D for k in ('x_mm','y_mm','before_nm','after_nm','delta_nm','thickness_nm')},'mse':{'type':'null'},'gof':{'type':'null'},'before_key':S,'after_key':S})
    pair={'pairing_method':literal('same_xy_coordinate'),'direction':literal('after - before'),'model_consistent':literal(True),**{k:I for k in ('paired_point_count','unmatched_before','unmatched_after','ineligible_before','ineligible_after')},**{k:D for k in ('mean_delta_nm','mean_before_nm','mean_after_nm')},'sd_delta_nm':nullable(D),'observation':{'type':'string','enum':['increase','decrease','unchanged']},'interpretation':S,'points':array(ref('AnalysisPairPoint'))}
    schemas['AnalysisPair']=obj(pair)
    schemas['PairingResponse']=obj({**pair,'before_measurement_id':{'type':'integer'},'after_measurement_id':{'type':'integer'},'analysis_version':S,'selection':ref('AnalysisSelection'),'result_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}},[k for k in pair if k!='points']+['before_measurement_id','after_measurement_id','analysis_version','selection','result_sha256'])
    schemas['AnalysisResult']=obj({'analysis_version':S,'decimal_precision':literal(50),'rounding':literal('ROUND_HALF_EVEN'),'request':ref('AnalysisCalculate'),'series':array(ref('AnalysisSeries')),'pair':nullable(ref('AnalysisPair')),'persisted':literal(False),'limits':obj({'max_sources':literal(20),'max_points':literal(20000)}),'scientific_sources_modified':literal(False),'result_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}})
    schemas['AnalysisSaveResult']=obj({'result_id':{'type':'integer'},'persisted':literal(True),'result_sha256':S,'scientific_sources_modified':literal(False)})
    schemas['AnalysisSavedRecord']=obj({'label':S,'request':ref('AnalysisCalculate'),'result_sha256':S,'analysis_version':S,'sources':array(ref('AnalysisSourceMetadata')),'statistics':array(ref('AnalysisStatistics')),'pair':{'anyOf':[obj({k:v for k,v in pair.items() if k!='points'}),obj({})]}})
    schemas['AnalysisSavedResult']=obj({'result_id':{'type':'integer'},'is_valid':B,'invalid_reasons':array(S),'recomputed_result_sha256':nullable(S),'computed_at':{'type':'string','format':'date-time'},'record':ref('AnalysisSavedRecord'),'scientific_sources_modified':literal(False)})
    schemas['AnalysisReadonlyToolMetadata']=obj({'name':literal('scientific_analysis'),'readonly':literal(True),'external_raw_data':literal(False),'function':literal('app.scientificanalysis.calculate'),'request_schema':{'type':'object','additionalProperties':True},'response_projection':array(S),'requires_authenticated_scope':literal(True),'live_ai_registered':literal(False)})
    aifile=ROOT/'api/openapi/components/schemas/ai.yaml'; ai=load(aifile)
    ai['AIModelEffort']=obj({'supported_levels':{'type':'array','maxItems':10,'items':{'type':'string','pattern':'^[a-z_-]{1,32}$'}},'default_level':{'type':'string','pattern':'^[a-z_-]{1,32}$'}},['supported_levels'])
    ai['AIModelCapabilities']=obj({'anthropic_messages':obj({'system_prompt_update':{'type':'string','enum':['leading-only','in-history']}})})
    modelprops={'id':{'type':'string','pattern':'^[A-Za-z0-9_.:/-]{1,128}$'},
                **{k:{'type':'string','minLength':1,'maxLength':128,'pattern':r'^[^\x00-\x1f]+$'} for k in ('name','owned_by')},
                **{k:{'type':'integer','minimum':1,'maximum':1000000000,'x-python-strict':True} for k in ('context_window','max_output_tokens')},
                **{k:{'type':'array','maxItems':8,'items':{'type':'string','pattern':'^[a-z_-]{1,32}$'}} for k in ('input_modalities','output_modalities')},
                'effort':ref('AIModelEffort'),'api_capabilities':ref('AIModelCapabilities')}
    ai['AIModelMetadata']=obj(modelprops,['id'])
    ai['AIModelMetadata']['description']='供应商实际返回并经白名单裁剪的可选元数据；不根据模型ID推断能力。仅GET /ai/models发现结果，不注册科学分析工具。'
    for schema in ai.values():
        if 'models' in schema.get('properties',{}):
            schema['properties']['models']['items']=ref('AIModelMetadata')
    for name in ('AIModelMetadata','AIModelEffort','AIModelCapabilities'):
        for prop in ai[name]['properties'].values():prop['x-db-column']=False
        root['components']['schemas'][name]={'$ref':'./components/schemas/ai.yaml#/'+name}
    save(aifile,ai)
    root['x-prepared-readonly-analysis']=copy.deepcopy(analysis.READONLY_TOOL_METADATA)
    root['x-prepared-readonly-analysis']['description']='准备态内部元数据；未注册到AI供应商或工具执行器，无出站调用。不是API路由。'
    for name in schemas:
        if name.startswith('Analysis') or name in NAMES.values():
            for prop in schemas[name].get('properties',{}).values():prop.setdefault('x-db-column',False)
    save(target,schemas)
    domainfile=ROOT/'api/openapi/components/schemas/domain.yaml'; domain=load(domainfile)
    domain['ProcessStepKind']={'type':'string','minLength':1,'maxLength':128,'description':'自由步骤分类；0010 将计划/执行 step_kind 改为 VARCHAR(128)，无枚举 CHECK。'}
    for name,schema in domain.items():
        props=schema.get('properties',{})
        if 'step_kind' in props:
            previous=props['step_kind']; nullable_kind='anyOf' in previous or isinstance(previous.get('type'),list)
            props['step_kind']=nullable(ref('ProcessStepKind')) if nullable_kind else ref('ProcessStepKind')
            props['step_kind']['x-db-column']=('experiment_plan_steps' if name.startswith('Plan') else 'process_steps')+'.step_kind'
    for name,table in [('ExperimentPlan','experiment_plans'),('Process','processes')]:
        domain[name]['properties']['process_flow']={**nullable(ref('ProcessFlow')),'x-db-column':table+'.process_flow','description':'保存后step_id为真实数据库ID；空值表示旧记录无布局。'}
    domain['ProcessCreate']['properties']['process_flow']={**nullable(ref('ProcessFlow')),'default':None,'x-db-column':'processes.process_flow','description':'创建流程只接受与提交steps的step_index一致的整数引用；保存后解析为实际step_id。'}
    for name,parent,kind in [('PlanGridDetail','ExperimentPlan','plans'),('ProcessGridDetail','Process','processes')]:
        detail={'steps':array(ref('PlanStep' if kind=='plans' else 'ProcessStep')),'batch':nullable(ref('Batch'))}
        if kind=='plans':detail.update(processes=array(ref('Process')),process_count=I,owner=nullable({'type':'object','additionalProperties':True}))
        else:detail.update(samples=array(ref('ProcessSampleLink')),step_count=I,sample_count=I,plan=nullable(ref('ExperimentPlan')),tool=nullable(ref('Tool')))
        domain[name]={'allOf':[ref(parent),{'type':'object','required':list(detail),'properties':detail}]}
        root['components']['schemas'][name]={'$ref':'./components/schemas/domain.yaml#/'+name}
    sync_step_metadata(domain)
    save(domainfile,domain)
    for name in schemas:
        if name.startswith('Analysis') or name in NAMES.values():root['components']['schemas'][name]={'$ref':'./components/schemas/measurement.yaml#/'+name}
    root['components']['schemas']['ProcessStepKind']={'$ref':'./components/schemas/domain.yaml#/ProcessStepKind'}
    def operation(opid,body,response,description,status='200',tag='数据分析'):
        op={'tags':[tag],'operationId':opid,'summary':opid,'description':description,'x-implementation-status':'implemented','responses':{status:{'description':'成功；统一包络','content':{'application/json':{'schema':{'allOf':[ref('ApiEnvelope'),{'type':'object','required':['data'],'properties':{'data':response}}]}}}}}}
        if body:op['requestBody']={'required':True,'content':{'application/json':{'schema':ref(body)}}}
        for code,name in [('401','Unauthorized'),('403','Forbidden'),('404','NotFound'),('409','Conflict'),('422','UnprocessableEntity'),('503','ServiceUnavailable')]:op['responses'][code]={'$ref':'#/components/responses/'+name}
        return op
    shared='真实来源按当前用户权限加载；最多20组/20000测点；十进制字符串，50位ROUND_HALF_EVEN；不插值、不推断关联或机理。'
    root['paths']['/api/v1/analysis/calculate']={'post':operation('calculateScientificAnalysis','AnalysisCalculate',ref('AnalysisResult'),shared+'仅计算，不写科学数据。')}
    # Preserve original operationId while replacing stale planned payload/response.
    mf=ROOT/'api/openapi/paths/measurements.yaml'; paths=load(mf)
    paths['/api/v1/analysis/pair']={'post':operation('pairMeasurements','PairingRequest',ref('PairingResponse'),shared+'必须confirm_pair=true、不同测量、同样品/光学模型，真实XY唯一精确匹配；无匹配/未知或不一致模型返回422。include_points=false省略points。')}
    save(mf,paths)
    root['paths']['/api/v1/analysis/save']={'post':operation('saveScientificAnalysis','AnalysisSave',ref('AnalysisSaveResult'),shared+'admin/operator显式保存派生快照；仅1组正式测量或明确2组配对，必须expected_row_version；记录recipe/摘要/哈希，不修改测量和原件。','201')}
    saved=operation('getSavedScientificAnalysis',None,ref('AnalysisSavedResult'),'按可见样品加载派生快照；重核来源版本/current/quality，过期返回is_valid=false；不重新写入。')
    saved['parameters']=[{'name':'result_id','in':'path','required':True,'schema':{'type':'integer'}}]
    root['paths']['/api/v1/analysis/saved/{result_id}']={'get':saved}
    listing=operation('listAnalysisMeasurements',None,array(ref('Measurement')),shared+'仅当前测量；data数组，顶层meta={limit:200,has_more:boolean}，非分页PageMeta。')
    listing['parameters']=[{'name':k,'in':'query','schema':{'type':'integer','exclusiveMinimum':0}} for k in ('sample_id','batch_id','process_id')]+[{'name':'stage','in':'query','schema':ref('MeasurementStage')}]
    listing['responses']['200']['content']['application/json']['schema']['allOf'][1]['properties']['meta']=obj({'limit':literal(200),'has_more':B})
    root['paths']['/api/v1/analysis/measurements']={'get':listing}
    for kind,model in [('plans','ExperimentPlan'),('processes','Process')]:
        op=operation('save'+('Plan' if kind=='plans' else 'Process')+'Grid','ProcessGridSave',ref('PlanGridDetail' if kind=='plans' else 'ProcessGridDetail'),'原子保存布局与步骤，admin/operator；CAS父expected_row_version，返回完整detail及递增版本。steps.key唯一；process_flow.step_id提交必须是每个key且仅一次；响应替换为真实step_id。现有步骤ID保留；权限/映射/历史保护，冲突409。最多500节点、32组、4层嵌套、1MiB。计划steps不得填写plan_step_id。',tag='实验计划' if kind=='plans' else '实验执行')
        op['parameters']=[{'name':'id','in':'path','required':True,'schema':{'type':'integer'}}]
        root['paths']['/api/v1/'+kind+'/{id}/process-grid']={'put':op}
    root['info']['version']='1.7.0';root['info']['summary']='第七轮：通用工艺表格与可信科学分析'
    root['info']['description']='当前1.7.0：0010通用step_kind、process_flow与两个grid PUT；5个科学分析操作（既有pair转implemented）。准备态只读分析元数据未接入live AI工具。AI models为实际供应商发现/账本操作，不是分析工具注册。Windows实际重启和真实DeepSeek连通未在本次验证。\n\n'+root['info']['description'][root['info']['description'].find('当前1.6.0：'):].replace('光学模型和分析等仍 planned','光学模型等仍 planned')
    save(rootfile,root)

if __name__=='__main__':main()
