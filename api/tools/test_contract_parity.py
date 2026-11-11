"""Read-only 1.8 contract/model parity, schema fixtures and migrated-DB checks.
Run after validate_contract.py and gen_models.py; --no-db skips live SELECTs.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, TypeAdapter, ValidationError

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'api/tools'))
from app import ai, schemas as backend
from validate_contract import bundle, SPEC_FILE, check_phase1_contract


def main():
    module_spec = importlib.util.spec_from_file_location('ale_generated', ROOT / 'api/models/python/schemas.py')
    generated = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = generated
    module_spec.loader.exec_module(generated)
    spec = bundle(SPEC_FILE)
    errors = check_phase1_contract(spec)
    assert not errors, errors
    ops = {(p, m): o for p, item in spec['paths'].items() for m, o in item.items()
           if m in ('get', 'post', 'put', 'patch', 'delete')}
    print(f'ROUTES: {sum(o["x-implementation-status"] == "implemented" for o in ops.values())} implemented; '
          f'{sum(o["x-implementation-status"] == "planned" for o in ops.values())} planned; AST parity PASS')
    model_count = 0
    for obj in vars(generated).values():
        if isinstance(obj, type) and obj is not BaseModel and issubclass(obj, BaseModel):
            obj.model_json_schema(); model_count += 1
    print(f'PYTHON: {model_count} model JSON schemas constructible')
    uid = '12345678-1234-1234-1234-123456789abc'
    cases = {
        'SampleVoid': [{'expected_row_version': 1, 'reason': '  mistake  '}, {},
                       {'expected_row_version': True, 'reason': 'x'}, {'expected_row_version': '1', 'reason': 'x'},
                       {'expected_row_version': 1, 'reason': '   '}, {'expected_row_version': 1, 'reason': 'x', 'status': 'lost'}],
        'AIContext': [{'kind': 'none'}, {'kind': 'sample', 'id': 1}, {'kind': 'sample'},
                      {'kind': 'none', 'id': 1}, {'kind': 'sample', 'id': '1'}, {'kind': 'sample', 'id': True},
                      {'kind': 'sample', 'id': 9223372036854775808}],
        'AIChatRequest': [{'request_id': uid, 'message': ' hi '}, {'request_id': uid, 'message': 'hi', 'context': {'kind': 'sample', 'id': 2}},
                          {'request_id': uid, 'message': '  '}, {'request_id': 'bad', 'message': 'hi'},
                          {'request_id': uid, 'message': 'x' * 4001}, {'request_id': uid, 'message': 'hi', 'role': 'admin'},
                          {'request_id': uid, 'message': 'hi', 'context': {'kind': 'sample', 'id': '1'}}],
        'AITestRequest': [{'request_id': uid}, {}, {'request_id': uid, 'message': 'no'}],
        'AIConfigWrite': [{'revision': 0, 'base_url':'https://api.deepseek.com'}, {'revision':0,'base_url':'https://API.DEEPSEEK.COM/v1','provider_options':{'thinking':{'type':'disabled'}}}, {'revision': 0}, {'revision': 1, 'api_key': 'test-key-123', 'base_url': 'https://api.example.com/v1/'},
                          {'revision': True}, {'revision': '1'}, {'revision': 0, 'api_key': 'short'},
                          {'revision': 0, 'api_key': 'test-key-123', 'clear_api_key': True},
                          {'revision': 0, 'enabled': True}, {'revision': 0, 'provider_options': {'temperature': 1}},
                          {'revision': 0, 'provider_options': {'thinking': {'type': 'disabled'}}},
                          {'revision': 0, 'base_url': 'http://localhost'}, {'revision': 0, 'base_url': 'https://127.0.0.1'},
                          {'revision': 0, 'model': 'bad model'}, {'revision': 0, 'monthly_budget': '0'},
                          {'revision': 0, 'monthly_budget': '0.000000001'}, {'revision': 0, 'monthly_budget': 12.5},
                          {'revision': 0, 'input_price_per_million': '1', 'cached_input_price_per_million': '2'},
                          {'revision': 0, 'max_tool_rounds': 5}, {'revision': 0, 'daily_call_limit': '20'},
                          {'revision': 0, 'monthly_token_limit': 999}, {'revision': 0, 'key_ciphertext': 'no'}]
    }
    reconcile = dict(reconciliation_id=uid, reason='provider bill checked', evidence='invoice reference 123',
                     actual_prompt_tokens=100, actual_completion_tokens=20, actual_cache_hit_tokens=10, actual_cost='0.00000001')
    cases['AIReconcileRequest'] = [reconcile,
        {**reconcile, 'actual_prompt_tokens': 0, 'actual_completion_tokens': 0, 'actual_cache_hit_tokens': 0, 'actual_cost': 0},
        {**reconcile, 'actual_prompt_tokens': 1000000000, 'actual_completion_tokens': 1000000000, 'actual_cost': '1000000'},
        {**reconcile, 'reason': 'r' * 1000, 'evidence': 'e' * 2000},
        {k: v for k, v in reconcile.items() if k != 'actual_cache_hit_tokens'},
        {**reconcile, 'actual_cost': 12.5}]
    for key, values in {
        'reconciliation_id': ['invalid'], 'reason': ['short', ' ' * 10, 'r' * 1001],
        'evidence': ['short', ' ' * 10, 'e' * 2001],
        'actual_prompt_tokens': [-1, 1000000001, True, '100', 1.5],
        'actual_completion_tokens': [-1, 1000000001, False, '20'],
        'actual_cache_hit_tokens': [-1, 101, 1000000001, True, '10'],
        'actual_cost': ['-0.1', '1000000.00000001', '0.000000001', 'NaN', 'Infinity'],
        'owner_user_id': [1]}.items():
        cases['AIReconcileRequest'].extend({**reconcile, key: value} for value in values)
    cases['AIReconcileRequest'].append({k: v for k, v in reconcile.items() if k != 'evidence'})
    mapping = {'SampleVoid': backend.SampleVoid, 'AIContext': ai.Context, 'AIChatRequest': ai.ChatBody,
               'AITestRequest': ai.TestBody, 'AIConfigWrite': ai.ConfigWrite, 'AIReconcileRequest': ai.ReconcileBody}
    positive = negative = 0
    for name, inputs in cases.items():
        actual, derived = mapping[name], getattr(generated, name)
        assert set(actual.model_fields) == set(derived.model_fields), name
        assert {k for k, f in actual.model_fields.items() if f.is_required()} == {k for k, f in derived.model_fields.items() if f.is_required()}, name
        for data in inputs:
            results = []
            for cls in (actual, derived):
                try: results.append((True, cls.model_validate(copy.deepcopy(data)).model_dump(mode='json')))
                except (ValueError, TypeError): results.append((False, None))
            assert results[0] == results[1], (name, 'accept/default/normalization mismatch')
            if results[0][0]: positive += 1
            else: negative += 1
    secret = generated.AIConfigWrite.model_validate({'revision': 0, 'api_key': 'test-key-123'})
    assert 'test-key-123' not in repr(secret) and 'api_key' not in secret.model_dump()
    assert spec['components']['schemas']['AIConfigWrite']['properties']['api_key']['writeOnly'] is True
    assert not {'api_key', 'key_ciphertext', 'clear_api_key'} & set(spec['components']['schemas']['AIConfig']['properties'])
    print(f'REQUEST PARITY: {positive} positive / {negative} negative cases PASS; secret excluded from dump/repr')
    schemas = spec['components']['schemas']
    def validate(name, value):
        schema = {'$ref': '#/components/schemas/' + name, 'components': {'schemas': schemas}}
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    usage = {k: 0 for k in ('prompt_tokens', 'completion_tokens', 'cache_hit_tokens', 'cache_miss_tokens', 'charged_tokens', 'provider_calls')}
    usage.update(charged_cost='0.00000000', estimated=False, currency='USD')
    pending = {'status': 'pending', 'request_id': uid, 'conversation_id': None, 'answer': None,
               'sources': [], 'tool_trace': [], 'usage': None, 'error': {'code': 'request_in_progress', 'message': 'pending'}}
    completed = {**pending, 'status': 'completed', 'answer': 'hello', 'usage': usage, 'error': None, 'replayed': False}
    failed = {**completed, 'status': 'failed', 'answer': None, 'error': {'code': 'provider_rejected', 'message': 'failed'}}
    replay = {**completed, 'answer': None, 'error': {'code': 'already_completed', 'message': 'new id required'}, 'replayed': True}
    discovery = {**completed, 'answer': None, 'models': [{'id': 'model/v1'}]}
    for value in (pending, completed, failed, replay, discovery):
        validate('AITurnResult', value)
        TypeAdapter(generated.AITurnResult).validate_python(value)
    negatives = [{**pending, 'usage': usage}, {**completed, 'status': 'unknown'}, {**completed, 'usage': None},
                 {**completed, 'key_ciphertext': 'no'}, {**completed, 'sources': [{'kind': 'sql', 'id': 1, 'href': '/bad'}]}]
    for value in negatives:
        try: validate('AITurnResult', value)
        except Exception: pass
        else: raise AssertionError('negative result schema accepted')
    print('RESULT SCHEMAS: 5 positive / 5 negative variants PASS')
    def both_valid(name, value):
        validate(name, value)
        TypeAdapter(getattr(generated, name)).validate_python(value)
    def both_invalid(name, value):
        for check in (lambda: validate(name, value), lambda: TypeAdapter(getattr(generated, name)).validate_python(value)):
            try: check()
            except (ValueError, TypeError, ValidationError, __import__('jsonschema').ValidationError): pass
            else: raise AssertionError((name, 'negative fixture accepted', value))
    recovered = {**failed, 'error': {'code': 'request_recovered', 'message': 'recovered'},
                 'usage': {**usage, 'estimated': True},
                 'recovery': {'recovered': True, 'unknown_calls': 1, 'reconciliation_required': True}}
    both_valid('AITurnResult', recovered)
    both_valid('AITurnResult', {**recovered, 'usage': usage, 'recovery': {**recovered['recovery'], 'reconciliation_required': False}})
    both_invalid('AITurnResult', {**recovered, 'recovery': {**recovered['recovery'], 'unknown_calls': -1}})
    both_invalid('AITurnResult', {**recovered, 'recovery': {**recovered['recovery'], 'original_execution_token': uid}})
    # Build response fixtures from runtime projection and serializer, without DB writes.
    from app.common import clean
    from datetime import datetime
    from decimal import Decimal
    row = dict(request_id=uid, conversation_id=None, purpose='chat', status='failed',
               created_at=datetime(2026, 10, 17), finished_at=datetime(2026, 10, 17),
               owner_user_id=1, period='2026-10', reserved_tokens=64096, reserved_cost=Decimal('0.064096'),
               charged_tokens=120, charged_cost=Decimal('0.00000001'), usage_estimated=0,
               result={'_server': {'lease_expires_at': '2026-10-17T00:03:00', 'heartbeat_at': '2026-10-17T00:00:00',
                       'dispatches': [{'state': 'unknown'}],
                       'recovery': {'at': '2026-10-17T00:03:00', 'unknown_calls': 1, 'original_execution_token': uid},
                       'reconciliations': [{'reconciliation_id': uid, 'at': '2026-10-17T00:04:00', 'actor_user_id': 1,
                          'submission': reconcile, 'original_usage': {k: v for k, v in usage.items() if k in ai.USAGE_FIELDS},
                          'original_result_usage': {**usage, 'estimated': True}}]}})
    owner, administrator = (clean(ai.request_account(row, is_admin)) for is_admin in (False, True))
    both_valid('AIRequestAccountOwner', owner)
    both_valid('AIRequestAccountAdmin', administrator)
    for value in (owner, administrator):
        both_valid('AIRequestAccount', value)
        both_valid('AIRequestList', {'requests': [value], 'limit': 100})
    assert not {'owner_user_id', 'reserved_tokens', 'reserved_cost', 'reconciliation_history', 'period'} & owner.keys()
    assert 'original_execution_token' not in json.dumps(administrator)
    for key, value in [('charged_tokens', -1), ('charged_cost', '-1'), ('dispatched_calls', -1), ('purpose', 'other')]:
        both_invalid('AIRequestAccount', {**owner, key: value})
    both_invalid('AIRequestAccountOwner', administrator)
    both_invalid('AIRequestAccountAdmin', owner)
    both_invalid('AIRequestList', {'requests': [owner] * 101, 'limit': 100})
    both_valid('AIRecoverResult', {'recovered_request_ids': [uid], 'recovered_count': 1})
    both_valid('AIRecoverResult', {'recovered_request_ids': [], 'recovered_count': 0})
    both_invalid('AIRecoverResult', {'recovered_request_ids': ['bad'], 'recovered_count': 1})
    for origin in ('current_context', 'prior_plan', 'model'):
        trace = {'tool': 'record_detail', 'status': 'completed', 'sources': [], 'result_bytes': 10, 'read_only': True, 'origin': origin}
        both_valid('AIToolTrace', trace)
        both_valid('AITurnResult', {**completed, 'tool_trace': [trace]})
    both_invalid('AIToolTrace', {**trace, 'origin': 'prior_answer'})
    both_invalid('AIToolTrace', {**trace, 'read_only': False})
    both_invalid('AITurnResult', {**recovered, 'recovery': {**recovered['recovery'], 'recovered': False}})
    for code in ('provider_auth_failed', 'provider_insufficient_balance', 'provider_rate_limited', 'provider_output_truncated'):
        both_valid('AITurnResult', {**failed, 'error': {'code': code, 'message': 'safe error'}})
    account_policy_checks(spec, generated)
    assert (ROOT/'frontend/src/contracts.d.ts').read_bytes() == (ROOT/'api/models/typescript/api.d.ts').read_bytes()
    print('RECOVERY/ACCOUNTS: runtime owner/admin projections, audit, cost/token bounds, origin and safe-error fixtures PASS')
    print('FRONTEND: contracts.d.ts byte-identical to generated api.d.ts PASS')
    # These enums describe API/UI values, not CHECK constraints on unrelated tables.
    for name in ('AISourceKind', 'AIToolTrace'):
        assert not schemas[name].get('x-db-column')
    assert all(prop.get('x-db-column') is False for prop in schemas['AIConfigWrite']['properties'].values())
    if '--no-db' not in sys.argv:
        sys.path.insert(0, str(ROOT / 'database'))
        from apply_schema import load_admin_creds, connect
        from migrate import validate_sample_void, validate_ai
        user, password = load_admin_creds()
        db = connect(user, password, 'ale_workbench')
        try:
            with db.cursor() as cur:
                cur.execute('START TRANSACTION READ ONLY')
                cur.execute("SELECT version,filename FROM schema_migrations WHERE version IN ('0008','0009') ORDER BY version")
                rows = cur.fetchall(); assert {r[0] for r in rows} == {'0008','0009'}
                validate_sample_void(cur, '0008'); validate_ai(cur, '0009')
                cur.execute('SELECT COUNT(*), SUM(voided_at IS NOT NULL) FROM samples')
                total, voided = cur.fetchone()
                cur.execute('SELECT COUNT(*) FROM samples WHERE (voided_at IS NULL) <> (void_reason IS NULL) OR (voided_at IS NULL) <> (voided_by_user_id IS NULL)')
                assert cur.fetchone()[0] == 0
                print(f'DB READ ONLY: migrations {rows}; actual column/CHECK/FK validation PASS; samples={total}, voided={voided or 0}; metadata coherence PASS')
        finally: db.rollback(); db.close()
    round7_checks(spec, generated, '--no-db' not in sys.argv)
    print('PASS: strict parity and schema checks')


def round7_checks(spec, generated, with_db):
    from app import scientificanalysis as a, process_flow as f
    from app.main import app
    from app.common import clean
    from starlette.requests import Request
    from unittest.mock import patch
    from datetime import datetime
    import hashlib
    models = {'AnalysisSource':a.Source,'AnalysisSelection':a.Selection,'AnalysisCalculate':a.Calculate,
              'PairingRequest':a.PairRequest,'AnalysisSave':a.SaveRequest,'FlowNode':f.FlowNode,
              'ProcessFlow':f.ProcessFlow,'GridStep':backend.GridStep,'ProcessGridSave':backend.ProcessGridSave}
    source={'kind':'measurement','id':1}
    node={'kind':'step','id':'n','step_id':'key'}
    flow={'children':[node]}
    step={'key':'key','step_kind':'自由分类','parameter_snapshot':{'step_type':' 自定义 '}}
    grid={'expected_row_version':1,'steps':[step],'process_flow':flow}
    calc={'sources':[source]}
    fixtures={
        'AnalysisSource':[source,{'kind':'import_item','id':2,'sample_id':1,'confirm_associations':True},
                          {**source,'id':True},{**source,'id':'1'},{**source,'block_index':1},
                          {**source,'sample_id':1},{**source,'confirm_associations':True},{**source,'stage_seq':-1},
                          {**source,'block_index':16},{**source,'block_index':'0'}, {**source,'other':1}],
        'AnalysisSelection':[{}, {'include_outliers':False,'reason':' reviewed '},
                             {'excluded_points':['0:1'],'reason':'x'}, {'include_outliers':False},
                             {'excluded_points':['a','a'],'reason':'x'},{'include_outliers':'true'},
                             {'excluded_points':[''],'reason':'x'},{'excluded_points':['x'*81],'reason':'x'},
                             {'excluded_points':['x']*1001,'reason':'x'},{'reason':'x'*4001}],
        'AnalysisCalculate':[calc,{'sources':[source,{'kind':'measurement','id':2}],'before_index':0,'after_index':1,'confirm_pair':True},
                             {'sources':[]},{'sources':[source]*21},{'sources':[source,source]},
                             {**calc,'before_index':0},{**calc,'before_index':0,'after_index':0,'confirm_pair':True},
                             {**calc,'before_index':0,'after_index':1,'confirm_pair':True},{**calc,'confirm_pair':1}],
        'PairingRequest':[{'before_measurement_id':1,'after_measurement_id':2,'confirm_pair':True},
                          {'before_measurement_id':1,'after_measurement_id':2},
                          {'before_measurement_id':True,'after_measurement_id':2,'confirm_pair':True},
                          {'before_measurement_id':1,'after_measurement_id':2,'confirm_pair':True,'pairing_method':'row'}],
        'AnalysisSave':[{'calculation':calc,'label':' '},{'calculation':calc,'label':'x'},
                        {'calculation':calc,'label':''},{'calculation':calc,'label':'x'*101}],
        'FlowNode':[node,{'kind':'group','id':'g','name':'  组  ','repeat':0},
                    {**node,'name':'x'},{**node,'repeat':1},{**node,'children':[node]},
                    {'kind':'group','id':'g','name':' '},{**node,'step_id':True},
                    {**node,'step_id':0},{**node,'id':''},{**node,'key':'wrong'}],
        'ProcessFlow':[{},flow,{'total_cycles':0},{'total_cycles':1000000},{'total_cycles':True},
                       {'total_cycles':1000001},{'children':[node,node]},
                       {'children':[node,{**node,'id':'n2'}]}, {'version':2}, {'children':[node]*501}],
        'GridStep':[step,{**step,'step_id':5},{**step,'step_kind':' arbitrary / kind '},
                    {**step,'step_kind':''},{**step,'step_kind':'x'*129},{**step,'step_id':True},
                    {**step,'parameter_snapshot':{'step_type':'x','groups':[{'name':'a','fields':[{'name':'x'},{'name':'x'}]}]}},
                    {**step,'parameter_snapshot':{'step_type':'x','temperature':{'value':3}}}],
        'ProcessGridSave':[grid,{**grid,'steps':[],'process_flow':{}},{**grid,'expected_row_version':'1'},
                           {**grid,'steps':[step]*501},{**grid,'extra':1}]
    }
    # Model-level tree limits and nested normalization, distinct from DB/handler constraints.
    for count in (32,33):
        fixtures['ProcessFlow'].append({'children':[{'kind':'group','id':str(i),'name':'g'} for i in range(count)]})
    for depth in (4,5):
        n=copy.deepcopy(node)
        for i in range(depth):n={'kind':'group','id':'g'+str(i),'name':'g','children':[n]}
        fixtures['ProcessFlow'].append({'children':[n]})
    cells=[{'name':str(i),'value':'文'*1800} for i in range(64)]
    big={**step,'parameter_snapshot':{'step_type':'x','groups':[{'name':str(i),'fields':cells} for i in range(4)]}}
    fixtures['GridStep'].append(big)
    # Stay below the snapshot limit but exceed the aggregate grid UTF-8 limit.
    bounded={**step,'parameter_snapshot':{'step_type':'x','groups':[{'name':'g','fields':[{'name':'v','value':'文'*2000}]}]}}
    fixtures['ProcessGridSave'].append({**grid,'steps':[{**bounded,'key':str(i)} for i in range(200)]})

    positives=negatives=0
    for name,values in fixtures.items():
        cls=models[name]; derived=getattr(generated,name)
        assert set(cls.model_fields)==set(derived.model_fields),name
        for value in values:
            outcomes=[]
            for model in (cls,derived):
                try:outcomes.append((True,model.model_validate(copy.deepcopy(value)).model_dump(mode='json')))
                except (ValueError,TypeError):outcomes.append((False,None))
            assert outcomes[0]==outcomes[1],(name,'fixture',values.index(value),'accept/dump mismatch',outcomes[0][0],outcomes[1][0])
            positives+=outcomes[0][0];negatives+=not outcomes[0][0]
    print(f'ROUND7 REQUEST PARITY: {len(models)} models; {positives} positive / {negatives} negative PASS')
    schemas=spec['components']['schemas']
    def check(name,value):
        Draft202012Validator({'$ref':'#/components/schemas/'+name,'components':{'schemas':schemas}},format_checker=FormatChecker()).validate(value)
        TypeAdapter(getattr(generated,name)).validate_python(value)
    raw=[dict(point_no=1,x_mm='0',y_mm='0',thickness_nm='0.1',mse=None,gof=None,is_outlier=False)]
    def load(db,ref,user):
        return dict(kind=ref.kind,id=ref.id,block_index=0,row_version=1,label='fixture',sample_id=1,stage='initial' if ref.id==1 else 'final',stage_seq=0,optical_model_id=1,cumulative_cycles=None,parser=None,parser_version=None,points_sha256='a'*64,optical_model=None,model_parameter_columns=[],units={k:'nm' for k in ('thickness_nm','x_mm','y_mm','mse','gof')}),raw
    req=Request({'type':'http','method':'POST','path':'/fixture','headers':[]});req.state.request_id='fixture'
    responses=0
    with patch.object(a,'load_source',load):
        body=a.Calculate(sources=[a.Source(**source),a.Source(kind='measurement',id=2)],before_index=0,after_index=1,confirm_pair=True)
        result=clean(a.calculate(None,body,{}));check('AnalysisResult',result);responses+=1
        for include in (True,False):
            pair=a.pair_route(a.PairRequest(before_measurement_id=1,after_measurement_id=2,confirm_pair=True,include_points=include),req,{},None)['data']
            check('PairingResponse',pair);assert ('points'in pair)==include;responses+=1
    check('AnalysisSaveResult',{'result_id':1,'persisted':True,'result_sha256':result['result_sha256'],'scientific_sources_modified':False});responses+=1
    record={'label':'fixture','request':result['request'],'result_sha256':result['result_sha256'],'analysis_version':a.VERSION,'sources':[x['source']for x in result['series']],'statistics':[x['statistics']for x in result['series']],'pair':{k:v for k,v in result['pair'].items()if k!='points'}}
    for valid in (True,False):
        check('AnalysisSavedResult',{'result_id':1,'is_valid':valid,'invalid_reasons':[] if valid else ['record_invalidated'],'recomputed_result_sha256':result['result_sha256'],'computed_at':'2026-10-19T00:00:00+00:00','record':record,'scientific_sources_modified':False});responses+=1
    check('AnalysisReadonlyToolMetadata',a.READONLY_TOOL_METADATA);responses+=1
    resolved=f.resolve(f.ProcessFlow.model_validate(flow).model_dump(mode='json'),{'key':7})
    check('ProcessFlow',resolved);assert f.references(resolved)==[7];responses+=1
    # Complete detail projections returned by both atomic grid handlers.
    plan={'plan_id':1,'plan_code':'fixture','title':'fixture','priority':'normal','status':'draft','created_at':'2026-10-19T00:00:00+00:00','row_version':2,'process_flow':resolved,'steps':[],'batch':None,'processes':[],'process_count':0,'owner':None}
    process={'process_id':1,'process_code':'fixture','process_mode':'other','is_independent_run':False,'log_status':'unknown','row_version':2,'process_flow':resolved,'steps':[],'batch':None,'samples':[],'step_count':0,'sample_count':0,'plan':None,'tool':None}
    for value in (plan,process):value.update(voided_at=None,void_reason=None,voided_by_user_id=None)
    plan['archive_previous_status']=None
    for name,value in [('PlanGridDetail',plan),('ProcessGridDetail',process)]:
        check(name,value);responses+=1
    # Validate actual authority projections without any DB writes or unit conversion.
    from app.experiments import step_response
    metadata_fields=('parameter_source','legacy_parameters','legacy_parameters_status','parameter_conflict')
    step_positive=step_negative=0
    for planned,name in ((True,'PlanStep'),(False,'ProcessStep')):
        base={'step_id':7,'plan_id' if planned else 'process_id':1,'step_index':1,
              'step_kind':'自由类型','created_at':'2026-10-19T00:00:00+00:00'}
        legacy={'planned_parameters':{'pulse_s':'2.500'}} if planned else {'pulse_s':'2.500'}
        for snapshot,has_legacy in ((None,False),(None,True),({},False),({'step_type':'x'},True)):
            if snapshot == {}:
                continue
            row={**base,'parameter_snapshot':snapshot,**(legacy if has_legacy else {})}
            if has_legacy:row['custom_parameters']={'legacy_note':{'value':'23.5','unit':'µs'}}
            before=copy.deepcopy(row);value=step_response(row,planned)
            assert row==before
            assert value['parameter_source']==('legacy_fields' if snapshot is None else 'parameter_snapshot')
            assert value['legacy_parameters_status']==('current' if snapshot is None else 'historical_readonly')
            assert value['parameter_conflict']==(snapshot is not None and has_legacy)
            assert value['legacy_parameters']==({'pulse_s':'2.500','custom_parameters':row['custom_parameters']} if has_legacy else {})
            check(name,value);step_positive+=1
        for field in metadata_fields:
            bad={k:v for k,v in value.items() if k!=field}
            try:check(name,bad)
            except Exception:step_negative+=1
            else:raise AssertionError((name,'missing authority metadata',field))
        for field,bad_value in (('parameter_source','inferred'),('legacy_parameters',[]),('legacy_parameters_status','converted'),('parameter_conflict','yes')):
            try:check(name,{**value,field:bad_value})
            except Exception:step_negative+=1
            else:raise AssertionError((name,'invalid authority metadata',field))
    print(f'STEP AUTHORITY METADATA: 2 response models; {step_positive} positive / {step_negative} negative PASS; legacy bytes preserved')
    # Free step kinds preserve exact text; response flows use ID anchors.
    for cls in (backend.PlanStepCreate,backend.ProcessStepCreate):
        name=cls.__name__;derived=getattr(generated,name)
        for kind in ('自定义 / 分类',' ', 'x'*128,'','x'*129):
            outcomes=[]
            for model in (cls,derived):
                try:outcomes.append((True,model.model_validate({'step_index':1,'step_kind':kind}).step_kind))
                except (ValueError,TypeError):outcomes.append((False,None))
            assert outcomes[0]==outcomes[1],(name,'free step_kind')
    print('GENERIC CLASSIFICATION: 2 existing request models; 6 positive / 4 negative step_kind fixtures PASS')
    invalid=0
    for name,value in [('AnalysisResult',{**result,'scientific_sources_modified':True}),('AnalysisResult',{**result,'persisted':True}),('PairingResponse',{**pair,'model_consistent':False}),('AnalysisReadonlyToolMetadata',{**a.READONLY_TOOL_METADATA,'live_ai_registered':True}),('ProcessFlow',{'children':[{'kind':'step','id':'n','key':'key'}]})]:
        try:check(name,value)
        except Exception:invalid+=1
        else:raise AssertionError((name,'invalid response accepted'))
    # Exercise the actual provider metadata whitelist with an in-memory response.
    from app.ai_provider import Provider
    provider=Provider()
    upstream={'id':'model/v1','name':'Model','owned_by':'provider','context_window':128000,'max_output_tokens':8192,
              'input_modalities':['text'],'output_modalities':['text'],
              'effort':{'supported_levels':['low','high'],'default_level':'high'},
              'api_capabilities':{'anthropic_messages':{'system_prompt_update':'in-history'}},'untrusted':'dropped'}
    with patch.object(provider,'request',return_value={'data':[upstream,{'id':'model/v1'},{'id':'bad id'}]}):
        discovered=provider.models({},'fixture-key')
    assert len(discovered)==1 and 'untrusted' not in discovered[0]
    check('AIModelMetadata',discovered[0])
    check('AIModelMetadata',{'id':'minimal'})
    metadata_negative=0
    for field,value in [('context_window',0),('context_window',True),('input_modalities',['TEXT']),('name','bad\nname'),('untrusted','x')]:
        try:check('AIModelMetadata',{**discovered[0],field:value})
        except Exception:metadata_negative+=1
        else:raise AssertionError(('AIModelMetadata',field))
    print(f'AI MODEL METADATA: actual provider whitelist; 2 positive / {metadata_negative} negative PASS; no provider call')
    assert not a.READONLY_TOOL_METADATA['live_ai_registered']
    from app.ai_tools import get_tool_definitions
    assert 'scientific_analysis' not in str(get_tool_definitions())
    print(f'ROUND7 RESPONSES: {responses} positive / {invalid} negative PASS; flow key->ID and prepared-only metadata')
    runtime=app.openapi(); methods={'get','post','put','patch','delete'}
    actual={(p,m)for p,item in runtime['paths'].items()for m in item if m in methods and p.startswith('/api/v1/')}
    documented={(p,m)for p,item in spec['paths'].items()for m,o in item.items()if m in methods and o['x-implementation-status']=='implemented'}
    assert actual==documented,(actual-documented,documented-actual)
    for path,method in actual:
        if path.startswith('/api/v1/analysis/') or path.endswith('/process-grid'):
            assert runtime['paths'][path][method]==spec['paths'][path][method],(path,'runtime/canonical operation mismatch')

    assert app.title=='ALE Workbench 1.8.0' and app.version==spec['info']['version']=='1.8.0'
    # Verify launch readiness; docs are outside this integration's edit scope.
    import re
    launcher=(ROOT/'start-workbench.ps1').read_text(encoding='utf-8-sig')
    def required_routes(text):
        return {(path,method) for path,methods in re.findall(r"'(/api/v1/[^']+)' = @\(([^)]+)\)",text)
                for method in re.findall(r"'([a-z]+)'",methods)}
    ready=required_routes(launcher)
    assert len(ready)==27 and len({p for p,m in ready})==26 and ready<=actual
    assert "$expectedVersion = '1.8.0'" in launcher
    print('STARTER: release 1.8.0; exact 26 paths / 27 required operations PASS (static, no PowerShell execution)')
    assert 'mean_r_nm' not in schemas['PairingResponse']['properties']
    print(f'FULL RUNTIME OPENAPI PARITY: {len(actual)} implemented operations PASS; release/title 1.8.0')
    if with_db:
        sys.path.insert(0,str(ROOT/'database'))
        from apply_schema import load_admin_creds,connect
        from migrate import validate_process_flow,validate_sample_lifecycle,validate_all_lifecycle,migration_files
        user,password=load_admin_creds();db=connect(user,password,'ale_workbench')
        try:
            with db.cursor() as cur:
                cur.execute('START TRANSACTION READ ONLY')
                cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'")
                tables=cur.fetchone()[0];assert tables==43,tables
                cur.execute('SELECT version,filename,sha256 FROM schema_migrations ORDER BY version');rows=cur.fetchall()
                files={p.stem.split('_')[0]:p for p in migration_files()}
                for version,filename,digest in rows:
                    assert files[version].name==filename and hashlib.sha256(files[version].read_bytes()).hexdigest()==digest
                assert '0010'in {r[0]for r in rows}
                validate_process_flow(cur,'0010')
                assert {'0011','0012'} <= {r[0] for r in rows}
                validate_sample_lifecycle(cur,'0011');validate_all_lifecycle(cur,'0012')
                print(f'ROUND7 DB READ ONLY: {tables} tables; {len(rows)} applied migration SHA256 PASS; 0010/0011/0012 column/FK/CHECK validation PASS; no mutations')
        finally:db.rollback();db.close()



def account_policy_checks(spec, generated):
    """Account-purpose and per-user AI contract fixtures; no DB/provider calls."""
    schemas = spec['components']['schemas']
    from decimal import Decimal
    for name, actual in [('AIUserPolicy', ai.AIUserPolicy), ('AISettings', ai.AISettings)]:
        derived = getattr(generated, name)
        assert set(actual.model_fields) == set(derived.model_fields), name
    policy_cases = [{}, {'monthly_budget': None, 'monthly_token_limit': None},
                    {'monthly_budget': '0', 'monthly_token_limit': 0,
                     'research_ai_allowed': True, 'external_send_allowed': False},
                    {'monthly_budget': '1000000', 'monthly_token_limit': 1000000000},
                    {'monthly_budget': '-1'}, {'monthly_budget': '0.000000001'},
                    {'monthly_token_limit': True}, {'monthly_token_limit': '1'},
                    {'monthly_token_limit': -1}, {'monthly_token_limit': 1000000001},
                    {'unknown': True}]
    settings_cases = [{}, {'user_monthly_budget': '0', 'user_monthly_token_limit': 0},
                      {'user_policies': {'1': policy_cases[2], '9223372036854775807': {}}},
                      {'user_policies': {'01': {}}}, {'user_policies': {'0': {}}},
                      {'user_policies': {'9223372036854775808': {}}},
                      {'user_policies': {'1': {'monthly_token_limit': True}}},
                      {'user_monthly_token_limit': '1'}, {'user_monthly_budget': '-1'}]
    count = 0
    for name, actual, cases in [('AIUserPolicy', ai.AIUserPolicy, policy_cases),
                                ('AISettings', ai.AISettings, settings_cases),
                                ('AIConfigWrite', ai.ConfigWrite, [{**v, 'revision': 0} for v in settings_cases])]:
        for value in cases:
            outcomes = []
            for cls in (actual, getattr(generated, name)):
                try: outcomes.append((True, cls.model_validate(copy.deepcopy(value)).model_dump(mode='json')))
                except (ValueError, TypeError): outcomes.append((False, None))
            assert outcomes[0] == outcomes[1], (name, value, 'policy/default parity')
            count += 1
    create = generated.CreateUserRequest
    body = {'username': 'fixture', 'password': 'fixture-password'}
    assert create.model_validate(body).account_purpose == 'research'
    assert create.model_validate({**body, 'role': 'admin'}).account_purpose == 'management'
    for role, purpose in [('admin', 'research'), ('admin', 'testing'), ('viewer', 'management'), ('operator', 'management')]:
        try: create.model_validate({**body, 'role': role, 'account_purpose': purpose})
        except ValidationError: pass
        else: raise AssertionError(('invalid role/purpose accepted', role, purpose))
    for role, purpose in [('admin', 'management'), ('viewer', 'research'), ('operator', 'testing')]:
        assert create.model_validate({**body, 'role': role, 'account_purpose': purpose}).account_purpose == purpose
    for key, value in [('account_purpose', 'testing'), ('role', 'admin')]:
        try: generated.RegisterRequest.model_validate({**body, 'invite_code': 'one-time', key: value})
        except ValidationError: pass
        else: raise AssertionError(('registration accepts extra', key))
    assert generated.CreateInvitationRequest.model_validate({}).account_purpose == 'research'
    try: generated.CreateInvitationRequest.model_validate({'account_purpose': 'management'})
    except ValidationError: pass
    else: raise AssertionError('management invitation accepted')
    try: generated.UserUpdate.model_validate({'role': 'admin', 'account_purpose': 'testing'})
    except ValidationError: pass
    else: raise AssertionError('incompatible update accepted')
    def check(name, value):
        from referencing import Registry, Resource
        registry = Registry().with_resource('urn:ale:contract', Resource.from_contents({'$schema': 'https://json-schema.org/draft/2020-12/schema', **spec}))
        Draft202012Validator({'$ref': 'urn:ale:contract#/components/schemas/' + name}, registry=registry).validate(value)
        getattr(generated, name).model_validate(value)
    user = dict(owner_user_id=1, charged_cost='0', charged_tokens=0, reserved_cost='0',
                reserved_tokens=0, monthly_budget='10', monthly_token_limit=2000000)
    check('AIUserUsage', user)
    check('AIMyUsage', {**user, 'period': '2026-10', 'scope': 'current_user', 'currency': 'USD'})
    for purpose, denial, allowed, external in [('management', 'research_ai_denied', False, True),
                                              ('testing', 'testing_external_send_denied', False, False),
                                              ('research', None, True, True)]:
        check('AIPolicy', dict(account_purpose=purpose, denial_reason=denial,
                              research_ai_allowed=allowed, external_send_allowed=external,
                              monthly_budget='10', monthly_token_limit=2000000))
        actor = dict(user_id=1, role='admin' if purpose == 'management' else 'viewer', account_purpose=purpose)
        assert ai.access_denial({}, actor) == denial
        assert ai.access_denial({'user_policies': {'1': {'research_ai_allowed': True, 'external_send_allowed': True}}}, actor) is None
    check('Environment', {'name': 'testing', 'label': '测试环境', 'instance_id': 'fixture-testing'})
    assert ai.user_budget({'user_monthly_budget': '10', 'user_monthly_token_limit': 2000000,
                           'user_policies': {'1': {'monthly_budget': None, 'monthly_token_limit': None}}}, 1) == {
                               'monthly_budget': Decimal('10'), 'monthly_token_limit': 2000000}
    assert 'users' in schemas['AIUsageSummary']['required']
    assert 'environment' in schemas['CurrentUser']['required']
    assert schemas['CurrentUser']['properties']['admin_global_scope']['type'] == 'boolean'
    print(f'ACCOUNT/USER AI POLICY: {count} runtime/generated parity cases; role-purpose, registration, invitations, effective policy and response fixtures PASS')

if __name__ == '__main__':
    main()
