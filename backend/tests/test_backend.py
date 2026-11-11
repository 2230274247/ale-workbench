import uuid
from sqlalchemy import select
from app.db import table
from app.schemas import BatchCreate,BatchUpdate
from pydantic import ValidationError
import pytest

def code():return 'TEST-'+uuid.uuid4().hex[:20]
def batch(client,actor):
    r=client.post('/api/v1/batches',headers=actor['headers'],json={'batch_code':code(),'batch_name':'Test batch'})
    assert r.status_code==201,r.text
    return r.json()['data']

def test_strict_decimal_and_unknown_fields():
    for value in (1,1.25,'NaN','1e2','0.0001','1000000000.000'):
        with pytest.raises(ValidationError):BatchCreate(batch_code='T',batch_name='T',nominal_thickness_nm=value)
    assert str(BatchUpdate(nominal_thickness_nm='1.230').nominal_thickness_nm)=='1.230'
    with pytest.raises(ValidationError):BatchCreate(batch_code='T',batch_name='T',owner_user_id=1)

def test_scopes_versions_and_validation(client,actors):
    own=batch(client,actors['operator']);other=batch(client,actors['other'])
    h=actors['operator']['headers']
    assert client.get(f"/api/v1/batches/{other['batch_id']}",headers=h).status_code==404
    rows=client.get('/api/v1/batches',headers=h).json()['data']
    assert all(r['owner_user_id']==actors['operator']['user']['user_id'] for r in rows)
    assert client.get('/api/v1/batches?sort=password_hash',headers=h).status_code==422
    assert client.get('/api/v1/batches?size=201',headers=h).status_code==422
    assert client.patch(f"/api/v1/batches/{own['batch_id']}",headers=h,json={'expected_row_version':own['row_version'],'batch_name':'Updated'}).status_code==200
    assert client.patch(f"/api/v1/batches/{own['batch_id']}",headers=h,json={'expected_row_version':own['row_version'],'batch_name':'Stale'}).status_code==409
    assert client.post('/api/v1/batches',headers=actors['viewer']['headers'],json={'batch_code':code(),'batch_name':'X'}).status_code==403
    assert client.delete(f"/api/v1/batches/{own['batch_id']}",headers=h).status_code==403

def test_sample_inherits_and_parent_dependencies(client,actors,db):
    b=batch(client,actors['operator']);h=actors['admin']['headers']
    r=client.post('/api/v1/samples',headers=h,json={'sample_code':code(),'batch_id':b['batch_id'],'sample_type':'parent_wafer'})
    assert r.status_code==201,r.text
    parent=r.json()['data'];assert parent['owner_user_id']==actors['operator']['user']['user_id']
    r=client.post('/api/v1/samples',headers=h,json={'sample_code':code(),'batch_id':b['batch_id'],'parent_sample_id':parent['sample_id']})
    assert r.status_code==201
    child=r.json()['data']
    assert client.delete(f"/api/v1/samples/{parent['sample_id']}",headers=h).status_code==409
    assert client.patch(f"/api/v1/samples/{child['sample_id']}",headers=h,json={'parent_sample_id':None}).status_code==422
    assert client.patch(f"/api/v1/samples/{child['sample_id']}",headers=h,json={'exclude_from_analysis':True}).status_code==422
    assert client.delete(f"/api/v1/batches/{b['batch_id']}",headers=h).status_code==409
    # Sample ownership is independently required, even when its batch is visible.
    s=table('samples');db.execute(s.update().where(s.c.sample_id==child['sample_id']).values(owner_user_id=actors['other']['user']['user_id']))
    assert client.get(f"/api/v1/samples/{child['sample_id']}",headers=actors['operator']['headers']).status_code==404

def test_refresh_rotation_logout_and_origin(client,actors):
    pair=actors['operator']['pair']
    r=client.post('/api/v1/auth/refresh',json={'refresh_token':pair['refresh_token']})
    assert r.status_code==200,r.text
    new=r.json()['data']
    assert client.post('/api/v1/auth/refresh',json={'refresh_token':pair['refresh_token']}).status_code==401
    assert client.post('/api/v1/auth/refresh',headers={'Origin':'https://evil.example'},json={}).status_code==403
    assert client.post('/api/v1/auth/refresh',headers={'Origin':'http://localhost:5173'},json={}).status_code==200
    assert client.post('/api/v1/auth/logout',headers={'Authorization':'Bearer '+new['access_token']},json={}).status_code==200
    assert client.get('/api/v1/auth/me',headers=actors['operator']['headers']).status_code==401

def test_invitation_atomic_consumption_and_session_revocation(client,actors,db):
    h=actors['admin']['headers']
    r=client.post('/api/v1/invitations',headers=h,json={'role':'viewer'})
    assert r.status_code==201,r.text
    invitation=r.json()['data'];invite=invitation['invite_code']
    assert 'code_hash' not in str(client.get('/api/v1/invitations',headers=h).json())
    duplicate={'username':actors['operator']['user']['username'],'password':'TestPassword123!','invite_code':invite}
    assert client.post('/api/v1/auth/register',json=duplicate).status_code==409
    duplicate['username']='test_'+uuid.uuid4().hex[:20]
    r=client.post('/api/v1/auth/register',json=duplicate);assert r.status_code==201,r.text
    assert r.json()['data']['role']=='viewer'
    duplicate['username']='test_'+uuid.uuid4().hex[:20]
    assert client.post('/api/v1/auth/register',json=duplicate).status_code==409
    uid=actors['operator']['user']['user_id']
    assert client.patch(f'/api/v1/users/{uid}',headers=h,json={'status':'disabled'}).status_code==200
    assert client.get('/api/v1/auth/me',headers=actors['operator']['headers']).status_code==401
    assert client.patch(f"/api/v1/users/{actors['admin']['user']['user_id']}",headers=h,json={'role':'viewer'}).status_code==409

def test_safe_errors_and_unknown_api(client,actors):
    sentinel='DO_NOT_LEAK_SECRET'
    r=client.post('/api/v1/auth/login',json={'username':'x','password':sentinel,'unknown':sentinel})
    assert r.status_code==422
    assert sentinel not in r.text
    assert r.json()['request_id'] and r.json()['timestamp']
    assert client.get('/api/v1/not-a-route').status_code==404
    assert client.get('/api/v1/dashboard/recent',headers=actors['operator']['headers']).status_code==200


def test_public_http_smoke():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app,raise_server_exceptions=False) as c:
        assert c.get('/health').status_code==200
        assert c.get('/api/v1/missing').status_code==404
        assert c.get('/openapi.json').status_code==200
        assert c.get('/api-contract').status_code==200
        r=c.post('/api/v1/auth/login',json={'username':'x','password':'SECRET','extra':'SECRET'})
        assert r.status_code==422
        assert 'SECRET' not in r.text
