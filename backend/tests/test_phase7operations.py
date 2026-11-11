"""Round 7 operations: real MySQL rollback; synthetic provider only, no live key/network."""
import json
import uuid
import httpx
import pytest
from sqlalchemy import select, func
from app import ai
from app.ai_provider import Provider, ProviderError, validate_endpoint
from app.db import table
from test_ai import setup_ai, response, PUBLIC
from test_phase4_browser import db, client, world


def test_models_actual_metadata_only():
    payload = {'data': [{'id': 'synthetic-a', 'name': 'Synthetic name', 'context_window': 8192,
        'max_output_tokens': 1024, 'input_modalities': ['text'], 'output_modalities': ['text'],
        'effort': {'supported_levels': ['high'], 'default_level': 'high'},
        'api_capabilities': {'anthropic_messages': {'system_prompt_update': 'in-history'}},
        'invented': 'drop'}, {'id': 'synthetic-b'}, {'id': 'invalid key'},
        {'id': 'synthetic-c', 'name': 3, 'context_window': True, 'input_modalities': ['<script>']} ]}
    provider = Provider(httpx.MockTransport(lambda req: httpx.Response(200, json=payload)), PUBLIC)
    models = provider.models({'base_url': 'https://api.deepseek.com'}, 'synthetic-secret')
    assert models[0]['name'] == 'Synthetic name' and models[0]['context_window'] == 8192
    assert 'invented' not in models[0]
    assert models[1] == {'id': 'synthetic-b'} and models[2] == {'id': 'synthetic-c'}


def test_test_before_enable_permissions_and_endpoint_key_binding(client, db, actors, setup_ai):
    from app.main import app
    seen = []
    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=response('Synthetic generic greeting'))
    app.dependency_overrides[ai.get_provider] = lambda: Provider(httpx.MockTransport(handler), PUBLIC)
    headers = actors['admin']['headers']
    cfg = client.get('/api/v1/ai/config', headers=headers).json()['data']
    fields = set(ai.AISettings.model_fields) | {'revision'}
    body = {k: v for k,v in cfg.items() if k in fields}; body['enabled'] = False
    assert client.put('/api/v1/ai/config', headers=headers, json=body).status_code == 200
    r = client.post('/api/v1/ai/test', headers=headers, json={'request_id':str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()['data']['status'] == 'completed', r.text
    assert len(seen) == 1
    sent = json.loads(seen[0].content)
    assert 'tools' not in sent and 'Do not access scientific data' in sent['messages'][-1]['content']
    assert client.post('/api/v1/ai/test', headers=actors['operator']['headers'], json={'request_id':str(uuid.uuid4())}).status_code == 403
    cfg = client.get('/api/v1/ai/config', headers=headers).json()['data']
    body = {k:v for k,v in cfg.items() if k in fields}
    body.update(base_url='https://api.deepseek.com', provider_options={'thinking':{'type':'disabled'}}, model='')
    saved = client.put('/api/v1/ai/config', headers=headers, json=body)
    assert saved.status_code == 200 and saved.json()['data']['key_configured'] is False
    assert saved.json()['data']['discovered_models'] == []
    assert client.get('/api/v1/ai/models', headers=headers).status_code == 409
    assert len(seen) == 1


def test_atomic_20_samples_ownership_conflict_and_void(client, db, actors, world):
    headers = actors['operator']['headers']; bid = world['batch_id']
    prefix = 'P7-' + uuid.uuid4().hex[:12]
    samples = table('samples')
    before = db.scalar(select(func.count()).select_from(samples))
    items = [{'sample_code':f'{prefix}-{i:02}', 'sample_type':'coupon', 'display_label':f'{i:02}', 'surface_state':'synthetic shared', 'size_desc':'10 mm'} for i in range(1,21)]
    result = client.post(f'/api/v1/batches/{bid}/samples/batch', headers=headers, json={'parent_sample_id':world['parent'], 'items':items})
    assert result.status_code == 201, result.text
    assert result.json()['data']['count'] == 20
    assert db.scalar(select(func.count()).select_from(samples)) == before + 20
    created = result.json()['data']['created']
    assert all(x['owner_user_id'] == actors['operator']['user']['user_id'] for x in created)
    collision = [dict(items[0], sample_code=prefix+'-new'), items[1]]
    assert client.post(f'/api/v1/batches/{bid}/samples/batch', headers=headers, json={'items':collision}).status_code == 409
    assert db.scalar(select(func.count()).select_from(samples)) == before + 20
    assert client.post(f'/api/v1/batches/{bid}/samples/batch', headers=actors['other']['headers'], json={'items':[dict(items[0],sample_code=prefix+'-other')]}).status_code in (403,404)
    sample = created[0]
    stale = client.patch(f'/api/v1/samples/{sample["sample_id"]}',headers=headers,json={'expected_row_version':sample['row_version']+99,'display_label':'stale'})
    assert stale.status_code == 409
    void = client.post(f'/api/v1/samples/{sample["sample_id"]}/void',headers=headers,json={'expected_row_version':sample['row_version'],'reason':'Round7 synthetic test cleanup intent'})
    assert void.status_code == 200, void.text
    assert client.post(f'/api/v1/batches/{bid}/samples/batch',headers=headers,json={'parent_sample_id':sample['sample_id'],'items':[dict(items[0],sample_code=prefix+'-child')]}).status_code in (409,422)
    print('SAMPLE BASELINE',before,'CREATED',20,'ALL WRITES ROLLED BACK BY FIXTURE')


@pytest.mark.parametrize('endpoint',['http://api.deepseek.com','https://127.0.0.1','https://169.254.169.254','https://user:pass@api.deepseek.com','https://api.deepseek.com?key=secret'])
def test_phase7_endpoint_rejects_unsafe(endpoint):
    with pytest.raises(ValueError): validate_endpoint(endpoint)


def test_phase7_dns_rebinding_never_sends_key():
    sent=[]
    provider=Provider(httpx.MockTransport(lambda request: sent.append(request)),lambda host:['127.0.0.1'])
    with pytest.raises(ProviderError) as error:
        provider.models({'base_url':'https://provider.example'},'synthetic-secret')
    assert error.value.code=='endpoint_not_public' and not sent
