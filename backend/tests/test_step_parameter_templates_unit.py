"""Isolated SQLite route tests: no workbench database, sessions or production writes."""
import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool
from app import step_templates as m

DEFINITION = {'step_type': '自定义暴露', 'temperature': {'value': None, 'unit': '°C'},
              'groups': [{'name': '源', 'fields': [{'name': '名称', 'value': 'XeF2', 'unit': None}]}]}

@pytest.fixture
def sandbox(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    metadata = MetaData()
    templates = Table('step_parameter_templates', metadata, Column('template_id', Integer, primary_key=True),
                      Column('template_name', String), Column('owner_user_id', Integer),
                      Column('definition', JSON), Column('row_version', Integer))
    metadata.create_all(engine)
    monkeypatch.setattr(m, 'table', lambda name: templates)
    monkeypatch.setattr(m, 'audit', lambda *args: None)
    actor = {'user_id': 1, 'role': 'operator'}
    def user():
        return actor.copy()
    def writer():
        if actor['role'] not in ('operator', 'admin'):
            m.fail(403)
        return actor.copy()
    def db():
        with engine.begin() as conn:
            yield conn
    app = FastAPI()
    @app.middleware('http')
    async def context(request, call_next):
        request.state.request_id = 'test'
        return await call_next(request)
    app.include_router(m.router)
    app.dependency_overrides[m.current_user] = user
    app.dependency_overrides[m.writer] = writer
    app.dependency_overrides[m.get_db] = db
    with TestClient(app) as client:
        yield client, actor
    engine.dispose()

def create(client):
    response = client.post('/api/v1/step-parameter-templates', json={'template_name': '通用源', 'definition': DEFINITION})
    assert response.status_code == 201
    return response.json()['data']

def test_crud_version_and_independent_copy(sandbox):
    client, actor = sandbox
    row = create(client)
    snapshot = copy.deepcopy(row['definition'])
    changed = copy.deepcopy(DEFINITION)
    changed['groups'][0]['fields'][0]['value'] = 'Ar'
    path = f"/api/v1/step-parameter-templates/{row['template_id']}"
    assert client.patch(path, json={'expected_row_version': 1, 'definition': changed}).json()['data']['row_version'] == 2
    assert snapshot['groups'][0]['fields'][0]['value'] == 'XeF2'
    assert client.patch(path, json={'expected_row_version': 1, 'template_name': 'stale'}).status_code == 409
    assert client.delete(path, params={'expected_row_version': 1}).status_code == 409
    assert client.delete(path).status_code == 422
    assert client.delete(path, params={'expected_row_version': 2}).status_code == 204
    assert client.get(path).status_code == 404

def test_owner_admin_and_reader_policy(sandbox):
    client, actor = sandbox
    row = create(client)
    path = f"/api/v1/step-parameter-templates/{row['template_id']}"
    actor['user_id'] = 2
    assert client.get(path).status_code == 404
    assert client.get('/api/v1/step-parameter-templates').json()['data'] == []
    assert client.patch(path, json={'expected_row_version': 1, 'template_name': 'other'}).status_code == 404
    actor['role'] = 'admin'
    assert client.get(path).status_code == 200
    actor.update(user_id=1, role='viewer')
    assert client.get(path).status_code == 200
    assert client.delete(path, params={'expected_row_version': 1}).status_code == 403
    assert client.post('/api/v1/step-parameter-templates', json={'template_name': 'forbidden', 'definition': DEFINITION}).status_code == 403

@pytest.mark.parametrize('edit', [
    lambda d: d.update(step_type=''),
    lambda d: d['groups'].append(copy.deepcopy(d['groups'][0])),
    lambda d: d['groups'][0]['fields'].append(copy.deepcopy(d['groups'][0]['fields'][0])),
    lambda d: d['groups'][0]['fields'][0].update(value=True),
])
def test_invalid_snapshot(sandbox, edit):
    client, _ = sandbox
    definition = copy.deepcopy(DEFINITION)
    edit(definition)
    assert client.post('/api/v1/step-parameter-templates', json={'template_name': 'invalid', 'definition': definition}).status_code == 422

def test_update_null_and_keyword_paging(sandbox):
    client, _ = sandbox
    row = create(client)
    path = f"/api/v1/step-parameter-templates/{row['template_id']}"
    assert client.patch(path, json={'expected_row_version': 1, 'definition': None}).status_code == 422
    assert client.get('/api/v1/step-parameter-templates', params={'keyword': '%'}).json()['data'] == []
    response = client.get('/api/v1/step-parameter-templates', params={'keyword': '通用', 'size': 1}).json()
    assert response['meta']['total'] == 1
    assert response['data'][0]['template_id'] == row['template_id']
