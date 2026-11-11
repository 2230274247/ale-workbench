"""Validate representative phase-one wire responses against canonical JSON Schema."""
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator
from app.config import ROOT


def test_phase1_wire_matches_canonical(client, actors):
    contract=yaml.safe_load((ROOT/'api/openapi/openapi.bundled.yaml').read_text(encoding='utf-8'))
    headers=actors['admin']['headers']
    for path in ['/api/v1/auth/me','/api/v1/users','/api/v1/invitations','/api/v1/batches','/api/v1/samples','/api/v1/dashboard/summary','/api/v1/dashboard/recent','/api/v1/auth/setup-status']:
        response=client.get(path,headers=headers)
        assert response.status_code==200
        schema=contract['paths'][path]['get']['responses']['200']['content']['application/json']['schema']
        Draft202012Validator({'$defs':{},**schema,'components':contract['components']}).validate(response.json())
    for name in ['BatchUpdate','SampleUpdate']:
        Draft202012Validator({**contract['components']['schemas'][name],'components':contract['components']}).validate({'nominal_thickness_nm':None,'expected_row_version':1})


def test_password_revokes_every_session(client,actors):
    h=actors['operator']['headers']
    response=client.put('/api/v1/auth/password',headers=h,json={'old_password':'TestPassword123!','new_password':'DifferentPassword123!'})
    assert response.status_code==200
    assert client.get('/api/v1/auth/me',headers=h).status_code==401
    assert client.post('/api/v1/auth/refresh',json={'refresh_token':actors['operator']['pair']['refresh_token']}).status_code==401
