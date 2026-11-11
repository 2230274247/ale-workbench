"""Account-purpose contracts and real MySQL API tests; no DDL, all writes roll back."""
import threading
import uuid
from datetime import timedelta

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.exc import DBAPIError

from app import schemas as S
from app.auth import me
from app.common import dbnow
from app.config import environment
from app.db import engine, metadata, table, get_db
from app.main import app
from app.security import hasher, new_session, limiter

PASSWORD = 'PurposeTestPassword123!'

def username():
    return 'purpose_' + uuid.uuid4().hex[:20]

@pytest.mark.parametrize('role,purpose', [
    ('admin','management'), ('operator','research'), ('operator','testing'),
    ('viewer','research'), ('viewer','testing'),
])
def test_create_valid_combinations(role, purpose):
    body = S.UserCreate(username=username(), password=PASSWORD, role=role, account_purpose=purpose)
    assert body.account_purpose == purpose


def test_create_defaults_and_register_cannot_choose_purpose():
    assert S.UserCreate(username=username(), password=PASSWORD, role='admin').account_purpose == 'management'
    assert S.UserCreate(username=username(), password=PASSWORD).account_purpose == 'research'
    assert S.InvitationCreate().account_purpose == 'research'
    for field, value in [('account_purpose','testing'), ('role','admin')]:
        with pytest.raises(ValidationError):
            S.Register(username=username(), password=PASSWORD, invite_code='x', **{field:value})

@pytest.mark.parametrize('role,purpose', [
    ('admin','research'), ('admin','testing'), ('operator','management'),
    ('viewer','management'), ('viewer',None), ('viewer','invalid'),
])
def test_create_rejects_invalid_combinations(role, purpose):
    with pytest.raises(ValidationError):
        S.UserCreate(username=username(), password=PASSWORD, role=role, account_purpose=purpose)

@pytest.mark.parametrize('payload', [
    {'role':'admin'}, {'account_purpose':'management'}, {'account_purpose':None},
    {'account_purpose':'invalid'},
])
def test_invitation_rejects_management(payload):
    with pytest.raises(ValidationError):
        S.InvitationCreate(**payload)


def test_environment_defaults(monkeypatch):
    for key in ('ALE_ENVIRONMENT','ALE_ENVIRONMENT_LABEL','ALE_INSTANCE_ID'):
        monkeypatch.delenv(key, raising=False)
    assert environment() == {'name':'production','label':'生产环境','instance_id':'ale-workbench-production'}

@pytest.mark.parametrize('name', ['production','testing'])
def test_me_environment_only_uses_configuration(monkeypatch, name):
    monkeypatch.setenv('ALE_ENVIRONMENT', name)
    monkeypatch.setenv('ALE_ENVIRONMENT_LABEL', '显式环境标签')
    monkeypatch.setenv('ALE_INSTANCE_ID', 'configured-instance')
    for port in (80, 5173, 18000):
        request = Request({'type':'http','method':'GET','path':'/api/v1/auth/me',
                           'headers':[], 'server':('localhost',port)})
        request.state.request_id = 'purpose-test'
        for role,purpose in [('admin','management'),('operator','testing'),('viewer','research')]:
            data = me(request, {'role':role,'account_purpose':purpose})['data']
            assert data['environment'] == {'name':name,'label':'显式环境标签','instance_id':'configured-instance'}
            assert data['data_scope'] == ('all' if role == 'admin' else 'own')


def test_invalid_environment_rejected(monkeypatch):
    monkeypatch.setenv('ALE_ENVIRONMENT','staging')
    with pytest.raises(RuntimeError, match='ALE_ENVIRONMENT'):
        environment()

@pytest.fixture
def purpose_db():
    # Check actual schema before metadata(): its strict guard must not mask this skip.
    inspector = inspect(engine())
    missing = [name + '.account_purpose' for name in ('users','invitations')
               if 'account_purpose' not in {c['name'] for c in inspector.get_columns(name)}]
    if missing:
        pytest.skip('0013_account_purpose.sql has not been applied: ' + ', '.join(missing))
    metadata.cache_clear()
    metadata()
    connection = engine().connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()

@pytest.fixture
def purpose_client(purpose_db):
    lock = threading.Lock()
    def override():
        with lock:
            with purpose_db.begin_nested():
                yield purpose_db
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override
    limiter.entries.clear()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

@pytest.fixture
def purpose_actors(purpose_db):
    result = {}
    users = table('users')
    for role,purpose in [('admin','management'),('operator','research'),('viewer','testing')]:
        uid = purpose_db.execute(users.insert().values(
            username=username(), password_hash=hasher.hash(PASSWORD), role=role,
            account_purpose=purpose, status='active', token_version=0)).inserted_primary_key[0]
        user = dict(purpose_db.execute(select(users).where(users.c.user_id==uid)).mappings().one())
        pairs = [new_session(purpose_db,user), new_session(purpose_db,user)]
        result[role] = {'user':user,'pairs':pairs,'headers':{'Authorization':'Bearer '+pairs[0]['access_token']}}
    return result


def test_mysql_create_and_read_purpose(purpose_client, purpose_actors):
    client = purpose_client
    headers = purpose_actors['admin']['headers']
    for role,purpose in [('admin','management'),('operator','testing'),('viewer','research')]:
        payload = {'username':username(),'password':PASSWORD,'role':role}
        if role != 'admin':
            payload['account_purpose'] = purpose
        response = client.post('/api/v1/users', headers=headers, json=payload)
        assert response.status_code == 201, response.text
        user = response.json()['data']
        assert user['account_purpose'] == purpose
        assert client.get(f"/api/v1/users/{user['user_id']}",headers=headers).json()['data']['account_purpose'] == purpose
        assert 'password_hash' not in user
    for role in ('operator','viewer'):
        assert client.post('/api/v1/users',headers=purpose_actors[role]['headers'],
                           json={'username':username(),'password':PASSWORD}).status_code == 403

@pytest.mark.parametrize('role,purpose', [('operator','research'),('operator','testing'),('viewer','research'),('viewer','testing')])
def test_mysql_invitation_inheritance(purpose_client, purpose_actors, purpose_db, role, purpose):
    client = purpose_client
    response = client.post('/api/v1/invitations',headers=purpose_actors['admin']['headers'],
                           json={'role':role,'account_purpose':purpose})
    assert response.status_code == 201, response.text
    invitation = response.json()['data']
    assert invitation['account_purpose'] == purpose
    payload = {'username':username(),'password':PASSWORD,'invite_code':invitation['invite_code']}
    assert client.post('/api/v1/auth/register',json={**payload,'account_purpose':'research'}).status_code == 422
    response = client.post('/api/v1/auth/register',json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['data']['account_purpose'] == purpose
    assert response.json()['data']['role'] == role
    payload['username'] = username()
    assert client.post('/api/v1/auth/register',json=payload).status_code == 409

@pytest.mark.parametrize('changes', [
    {'account_purpose':'testing'},
    {'role':'viewer'},
    {'role':'admin','account_purpose':'management'},
    {'status':'disabled'},
])
def test_mysql_purpose_role_status_changes_revoke_all_sessions(purpose_client, purpose_actors, purpose_db, changes):
    client = purpose_client
    actor = purpose_actors['operator']
    uid = actor['user']['user_id']
    response = client.patch(f'/api/v1/users/{uid}', headers=purpose_actors['admin']['headers'], json=changes)
    assert response.status_code == 200, response.text
    users, sessions = table('users'), table('auth_sessions')
    updated = purpose_db.execute(select(users).where(users.c.user_id==uid)).mappings().one()
    assert updated['token_version'] == actor['user']['token_version'] + 1
    assert all(row['revoked_at'] for row in purpose_db.execute(select(sessions).where(sessions.c.user_id==uid)).mappings())
    for pair in actor['pairs']:
        assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+pair['access_token']}).status_code == 401
        assert client.post('/api/v1/auth/refresh',json={'refresh_token':pair['refresh_token']}).status_code == 401

@pytest.mark.parametrize('changes', [
    {'account_purpose':'management'}, {'account_purpose':None}, {'role':None},
    {'role':'admin'}, {'role':'viewer','account_purpose':'management'},
])
def test_mysql_patch_validates_merged_combination(purpose_client, purpose_actors, purpose_db, changes):
    actor = purpose_actors['operator']
    uid = actor['user']['user_id']
    response = purpose_client.patch(f'/api/v1/users/{uid}',headers=purpose_actors['admin']['headers'],json=changes)
    assert response.status_code == 422, response.text
    assert purpose_client.get('/api/v1/auth/me',headers=actor['headers']).status_code == 200
    user = purpose_db.execute(select(table('users')).where(table('users').c.user_id==uid)).mappings().one()
    assert user['account_purpose'] == 'research'
    assert user['role'] == 'operator'
    assert user['token_version'] == actor['user']['token_version']


def test_mysql_unchanged_purpose_preserves_session(purpose_client, purpose_actors):
    actor = purpose_actors['operator']
    response = purpose_client.patch(f"/api/v1/users/{actor['user']['user_id']}",
        headers=purpose_actors['admin']['headers'],json={'account_purpose':'research','display_name':'Updated'})
    assert response.status_code == 200, response.text
    assert purpose_client.get('/api/v1/auth/me',headers=actor['headers']).status_code == 200

@pytest.mark.parametrize('role,purpose', [('admin','testing'),('viewer','management'),('operator','invalid')])
def test_mysql_user_check_constraint(purpose_db, role, purpose):
    # MySQL 3819 surfaces through SQLAlchemy as OperationalError, not IntegrityError.
    with pytest.raises(DBAPIError) as error:
        with purpose_db.begin_nested():
            purpose_db.execute(table('users').insert().values(username=username(),password_hash='unused',
                role=role,account_purpose=purpose,status='active',token_version=0))
    assert error.value.orig.args[0] == 3819


def test_mysql_invitation_check_constraint(purpose_db, purpose_actors):
    with pytest.raises(DBAPIError) as error:
        with purpose_db.begin_nested():
            purpose_db.execute(table('invitations').insert().values(code_hash=uuid.uuid4().hex*2,
                role='viewer',account_purpose='management',created_by=purpose_actors['admin']['user']['user_id'],
                expires_at=dbnow()+timedelta(hours=1),created_at=dbnow()))
    assert error.value.orig.args[0] == 3819
