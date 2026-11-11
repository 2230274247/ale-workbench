"""Real MySQL tests. Every fixture rolls its writes back; no DDL or committed seed data."""
import os
import uuid

if os.getenv('ALE_REQUIRE_TEST_DB') == '1':
    _db_name = os.getenv('ALE_DB_NAME', 'ale_workbench')
    if not _db_name.endswith('_test'):
        raise RuntimeError('ALE_REQUIRE_TEST_DB=1 requires an independent test database ending with _test')
import threading
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import engine, metadata, get_db, table
from app.security import hasher,new_session,limiter,decode

@pytest.fixture
def db():
    try:
        metadata()
    except RuntimeError:
        pytest.skip('Parent phase-one database migration has not been applied')
    connection=engine().connect();transaction=connection.begin()
    try:yield connection
    finally:
        transaction.rollback();connection.close()

@pytest.fixture
def client(db):
    lock=threading.Lock()
    def override():
        # SAVEPOINT makes API failures roll back exactly as production request transactions do.
        with lock:
            with db.begin_nested():yield db
    app.dependency_overrides[get_db]=override
    limiter.entries.clear()
    with TestClient(app,raise_server_exceptions=False) as c:yield c
    app.dependency_overrides.clear()

@pytest.fixture
def actors(db):
    result={};u=table('users')
    for role in ('admin','operator','viewer','other'):
        name='test_'+uuid.uuid4().hex[:20]
        role_name='operator' if role=='other' else role
        # 0013: an admin account is management by definition; ordinary actors are research.
        purpose='management' if role_name=='admin' else 'research'
        uid=db.execute(u.insert().values(username=name,password_hash=hasher.hash('TestPassword123!'),role=role_name,account_purpose=purpose,status='active',token_version=0)).inserted_primary_key[0]
        user=dict(db.execute(select(u).where(u.c.user_id==uid)).mappings().one())
        pair=new_session(db,user)
        user['_session_id']=decode(pair['access_token'],'access')['sid']
        result[role]={'user':user,'pair':pair,'headers':{'Authorization':'Bearer '+pair['access_token']}}
    return result
