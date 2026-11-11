"""Bidirectional account journeys on rollback-only MySQL, with offline AI.

Only purpose-specific assertions require migration 0013. Ordinary ownership
journeys use real sessions and remain runnable before that migration is applied.
Original uploads live exclusively in pytest's temporary directory.
"""
import hashlib
import sys
import uuid

import httpx
import pytest
from sqlalchemy import MetaData, select

from app import db as database

from app import ai
from app.ai_provider import Provider
from app.db import table
from app.main import app
from app.security import decode, hasher, new_session
from test_ai import setup_ai, response, PUBLIC
from test_phase3_imports import originals, workbook, choice

BASE = '/api/v1'
DIRECTIONS = ('research', 'testing')


def request(client, accounts, owner, method, path, status=200, **kwargs):
    result = getattr(client, method)(BASE + path, headers=accounts[owner]['headers'], **kwargs)
    assert result.status_code == status, (method, path, result.status_code, result.text)
    return result


def data(client, accounts, owner, method, path, status=200, **kwargs):
    return request(client, accounts, owner, method, path, status, **kwargs).json()['data']


def other(owner):
    return 'testing' if owner == 'research' else 'research'


@pytest.fixture
def db(monkeypatch):
    """Keep pre-0013 owner tests runnable without DDL or fake user/session rows.

    The production metadata gate intentionally rejects a pre-0013 database.
    For these owner-only regressions, use its real reflected schema and replace
    only that gate locally. Purpose-column assertions below still explicitly skip.
    No virtual column, identity override, or authorization helper is installed.
    """
    original = database.metadata
    try:
        schema = original()
    except database.MigrationRequired as exc:
        if '0013_account_purpose.sql' not in str(exc):
            raise
        schema = MetaData()
        schema.reflect(bind=database.engine(), views=False)
        for name in ('users', 'auth_sessions', 'batches', 'samples', 'measurements',
                     'source_file_occurrences', 'import_jobs', 'ai_requests'):
            assert name in schema.tables, f'Missing prerequisite table: {name}'
        for module in tuple(sys.modules.values()):
            if module is not None and getattr(module, '__name__', '').startswith('app.'):
                if getattr(module, 'metadata', None) is original:
                    monkeypatch.setattr(module, 'metadata', lambda: schema)
    connection = database.engine().connect()
    transaction = connection.begin()
    connection.info['e2e_users'] = []
    try:
        yield connection
    finally:
        created_users = list(connection.info.pop('e2e_users'))
        assert transaction.is_active, 'A request escaped the rollback-only outer transaction'
        transaction.rollback()
        connection.close()
        with database.engine().connect() as independent:
            users = schema.tables['users']
            assert not list(independent.scalars(select(users.c.user_id).where(users.c.user_id.in_(created_users)))), 'Test users were committed'


@pytest.fixture
def accounts(db):
    """Two genuine operators; never override authentication or ownership checks."""
    users = table('users')
    result = {}
    password_hash = hasher.hash('IsolationJourney123!')
    for purpose in DIRECTIONS:
        values = dict(username='e2e_' + uuid.uuid4().hex[:20], password_hash=password_hash,
                      role='operator', status='active', token_version=0)
        if 'account_purpose' in users.c:
            values['account_purpose'] = purpose
        uid = db.execute(users.insert().values(**values)).inserted_primary_key[0]
        db.info['e2e_users'].append(uid)
        user = dict(db.execute(select(users).where(users.c.user_id == uid)).mappings().one())
        pair = new_session(db, user)
        user['_session_id'] = decode(pair['access_token'], 'access')['sid']
        result[purpose] = dict(user=user, pair=pair,
                               headers={'Authorization': 'Bearer ' + pair['access_token']})
    return result


@pytest.fixture
def journey(db, client, accounts, originals):
    """Build both complete chains through production API writes, not seeded science."""
    result = {}
    tag = 'E2E-' + uuid.uuid4().hex[:12]
    for index, owner in enumerate(DIRECTIONS):
        batch = data(client, accounts, owner, 'post', '/batches', 201,
                     json={'batch_code': f'{tag}-{owner}', 'batch_name': f'{owner} private batch'})
        bid = batch['batch_id']
        samples = data(client, accounts, owner, 'post', f'/batches/{bid}/samples/batch', 201,
                       json={'items': [{'sample_code': f'{tag}-{owner}-{n}'} for n in range(3)]})
        assert samples['count'] == 3
        ids = [s['sample_id'] for s in samples['created']]
        plan = data(client, accounts, owner, 'post', '/plans', 201,
                    json={'plan_code': f'{tag}-{owner}', 'title': f'{owner} private plan', 'batch_id': bid})
        process = data(client, accounts, owner, 'post', '/processes', 201,
                       json={'process_code': f'{tag}-{owner}', 'process_mode': 'other',
                             'batch_id': bid, 'plan_id': plan['plan_id'], 'log_status': 'partial'})
        pid = process['process_id']
        links = data(client, accounts, owner, 'post', f'/processes/{pid}/samples/batch', 201,
                     json={'sample_ids': ids[:2]})
        assert links['count'] == 2
        content = workbook(tuple(str(10 + index * 10 + n) for n in range(3)))
        job = data(client, accounts, owner, 'post', '/imports/preview', 201,
                   files=[('files[]', (f'{owner}-private.xlsx', content, 'application/octet-stream'))])
        confirmed = data(client, accounts, owner, 'post', f"/imports/{job['job_id']}/confirm",
                         json={'expected_row_version': job['row_version'],
                               'items': [choice(job['items'][0], ids[0], process_id=pid)]})
        imported = confirmed['items'][0]
        mid = imported['measurement_ids'][0]
        data(client, accounts, owner, 'patch', f'/measurements/{mid}',
             json={'expected_row_version': 1, 'quality_flag': 'suspect', 'quality_note': 'review imported original'})
        pending = data(client, accounts, owner, 'post', '/imports/preview', 201,
                       files=[('files[]', (f'{owner}-pending.xlsx', workbook(), 'application/octet-stream'))])
        result[owner] = dict(batch=bid, sample=ids[0], samples=ids, plan=plan['plan_id'], process=pid,
                             measurement=mid, source=imported['source_file_id'], job=job['job_id'],
                             item=job['items'][0]['item_id'], pending=pending, content=content,
                             sha256=hashlib.sha256(content).hexdigest())
    result['tag'] = tag
    return result


@pytest.mark.parametrize('owner', DIRECTIONS)
def test_bidirectional_lists_ids_original_sha_and_analysis(client, accounts, journey, owner):
    mine, hidden = journey[owner], journey[other(owner)]
    for path, key, field in [('/batches', 'batch', 'batch_id'), ('/samples', 'sample', 'sample_id'),
                              ('/plans', 'plan', 'plan_id'), ('/processes', 'process', 'process_id'),
                              ('/measurements', 'measurement', 'measurement_id'),
                              ('/source-files', 'source', 'file_id'), ('/imports', 'job', 'job_id')]:
        rows = data(client, accounts, owner, 'get', path + '?size=200')
        ids = {row[field] for row in rows}
        assert mine[key] in ids and hidden[key] not in ids, (owner, path, ids)
        detail = data(client, accounts, owner, 'get', f'{path}/{mine[key]}')
        assert detail[field] == mine[key]
        request(client, accounts, owner, 'get', f'{path}/{hidden[key]}', 404)
    own_download = request(client, accounts, owner, 'get', f"/source-files/{mine['source']}/content")
    assert own_download.content == mine['content']
    assert hashlib.sha256(own_download.content).hexdigest() == mine['sha256']
    assert 'no-store' in own_download.headers['cache-control']
    assert f'{owner}-private.xlsx' in own_download.headers['content-disposition']
    request(client, accounts, owner, 'get', f"/source-files/{hidden['source']}/content", 404)
    source = data(client, accounts, owner, 'get', f"/source-files/{mine['source']}")
    assert source['file_sha256'] == mine['sha256']
    assert {o['owner_user_id'] for o in source['occurrences']} == {accounts[owner]['user']['user_id']}
    points = data(client, accounts, owner, 'get', f"/measurements/{mine['measurement']}/points")
    assert len(points) == 3
    request(client, accounts, owner, 'get', f"/measurements/{hidden['measurement']}/points", 404)
    calculation = {'sources': [{'kind': 'measurement', 'id': mine['measurement'], 'expected_row_version': 2}]}
    calculated = data(client, accounts, owner, 'post', '/analysis/calculate', json=calculation)
    assert calculated['series'][0]['source']['sample_id'] == mine['sample']
    saved = data(client, accounts, owner, 'post', '/analysis/save', 201,
                 json={'label': f'{owner} result', 'calculation': calculation})
    rid = saved['result_id']
    assert data(client, accounts, owner, 'get', f'/analysis/saved/{rid}')['is_valid']
    request(client, accounts, other(owner), 'get', f'/analysis/saved/{rid}', 404)
    mixed = {'sources': calculation['sources'] + [{'kind': 'measurement', 'id': hidden['measurement']}]}
    request(client, accounts, owner, 'post', '/analysis/calculate', 404, json=mixed)
    mixed['sources'][1]['expected_row_version'] = 2
    mixed.update(before_index=0, after_index=1, confirm_pair=True)
    request(client, accounts, owner, 'post', '/analysis/save', 404,
            json={'label': 'mixed must fail', 'calculation': mixed})
    rows = data(client, accounts, owner, 'get', '/analysis/measurements')
    assert mine['measurement'] in {r['measurement_id'] for r in rows}
    assert hidden['measurement'] not in {r['measurement_id'] for r in rows}


@pytest.mark.parametrize('owner', DIRECTIONS)
def test_cross_table_import_and_batch_requests_are_atomic(db, client, accounts, journey, owner):
    mine, hidden = journey[owner], journey[other(owner)]
    job = mine['pending']
    body = {'expected_row_version': job['row_version'],
            'items': [choice(job['items'][0], hidden['sample'], process_id=hidden['process'])]}
    request(client, accounts, owner, 'post', f"/imports/{job['job_id']}/confirm", 404, json=body)
    # A visible sample cannot smuggle a foreign execution into its provenance.
    body['items'] = [choice(job['items'][0], mine['sample'], process_id=hidden['process'])]
    request(client, accounts, owner, 'post', f"/imports/{job['job_id']}/confirm", 404, json=body)
    request(client, accounts, other(owner), 'post', f"/imports/{job['job_id']}/confirm", 404, json=body)
    after = data(client, accounts, owner, 'get', f"/imports/{job['job_id']}")
    assert after['row_version'] == job['row_version'] and after['status'] == 'draft'
    assert after['items'][0]['status'] == 'pending'
    for path in (f"/batches/{hidden['batch']}/samples", f"/processes/{hidden['process']}/samples",
                 f"/imports/options/samples/{hidden['sample']}"):
        request(client, accounts, owner, 'get', path, 404)
    request(client, accounts, owner, 'post', f"/batches/{hidden['batch']}/samples/batch", 404,
            json={'items': [{'sample_code': 'DENIED-' + uuid.uuid4().hex[:16]}]})
    # One valid link followed by a foreign sample must leave no partial insert,
    # parent version bump, or audit entry after the request's SAVEPOINT rolls back.
    unmeasured = data(client, accounts, owner, 'post', '/processes', 201,
                      json={'process_code': 'E2E-BIND-' + uuid.uuid4().hex[:12],
                            'process_mode': 'other', 'batch_id': mine['batch']})
    binding_process = unmeasured['process_id']
    links, proc, audit = table('process_samples'), table('processes'), table('audit_log')
    before_links = list(db.execute(select(links).where(links.c.process_id == binding_process)).mappings())
    before_version = db.scalar(select(proc.c.row_version).where(proc.c.process_id == binding_process))
    before_audit = list(db.execute(select(audit).where(audit.c.user_id == accounts[owner]['user']['user_id'])).mappings())
    request(client, accounts, owner, 'post', f"/processes/{binding_process}/samples/batch", 404,
            json={'sample_ids': [mine['samples'][2], hidden['sample']]})
    assert list(db.execute(select(links).where(links.c.process_id == binding_process)).mappings()) == before_links
    assert db.scalar(select(proc.c.row_version).where(proc.c.process_id == binding_process)) == before_version
    assert list(db.execute(select(audit).where(audit.c.user_id == accounts[owner]['user']['user_id'])).mappings()) == before_audit
    created = data(client, accounts, owner, 'post', f"/processes/{binding_process}/samples/batch", 201,
                   json={'sample_ids': [mine['samples'][2]]})
    assert created['count'] == 1
    assert created['created'][0]['sample_id'] == mine['samples'][2]


@pytest.mark.parametrize('owner', DIRECTIONS)
def test_home_aggregates_and_refresh_keep_the_same_owner(client, accounts, journey, owner):
    mine, hidden = journey[owner], journey[other(owner)]
    summary = data(client, accounts, owner, 'get', '/dashboard/summary')
    for key, expected in {'batch_count': 1, 'sample_count': 3, 'plan_count': 1, 'process_count': 1,
                          'measurement_count': 1, 'source_file_count': 1, 'derived_result_count': 0}.items():
        assert summary[key] == expected, (owner, key, summary)
    todo = data(client, accounts, owner, 'get', '/dashboard/todo')
    assert todo['counts']['process_log'] == 1
    assert todo['counts']['measurement_review'] == 1
    assert todo['counts']['import_pending'] == 1
    assert {(r['kind'], r['entity_id']) for r in todo['items']} == {
        ('process_log', mine['process']), ('measurement_review', mine['measurement']),
        ('import_pending', mine['pending']['job_id'])}
    experiments = data(client, accounts, owner, 'get', '/dashboard/recent-experiments')['items']
    assert {(r['kind'], r['entity_id']) for r in experiments} == {('plan', mine['plan']), ('process', mine['process'])}
    recent_data = data(client, accounts, owner, 'get', '/dashboard/recent-data')['items']
    assert {(r['kind'], r['entity_id']) for r in recent_data} == {
        ('measurement', mine['measurement']), ('source_file', mine['source']),
        ('import_job', mine['job']), ('import_job', mine['pending']['job_id'])}
    recent = data(client, accounts, owner, 'get', '/dashboard/recent?limit=50')
    assert recent
    for entry in recent:
        assert entry['entity_id'] in ({mine['batch']} if entry['entity_type'] == 'batch' else set(mine['samples']))
    # The shared TestClient now carries a refresh cookie for the *other* user.
    # An explicit refresh body must still rotate the correct account's session.
    foreign = accounts[other(owner)]
    client.cookies.set('ale_refresh', foreign['pair']['refresh_token'], path='/api/v1/auth')
    original_refresh = accounts[owner]['pair']['refresh_token']
    rotated = data(client, accounts, owner, 'post', '/auth/refresh', json={'refresh_token': original_refresh})
    assert decode(rotated['access_token'], 'access')['sub'] == str(accounts[owner]['user']['user_id'])
    refreshed = {**accounts, owner: {**accounts[owner], 'headers': {'Authorization': 'Bearer ' + rotated['access_token']}}}
    me = data(client, refreshed, owner, 'get', '/auth/me')
    assert me['user']['user_id'] == accounts[owner]['user']['user_id']
    assert me['user']['role'] == 'operator' and me['data_scope'] == 'own'
    assert {r['sample_id'] for r in data(client, refreshed, owner, 'get', '/samples')} == set(mine['samples'])
    request(client, refreshed, owner, 'get', f"/samples/{hidden['sample']}", 404)
    after_summary = data(client, refreshed, owner, 'get', '/dashboard/summary')
    assert {k: v for k, v in after_summary.items() if k != 'generated_at'} == {
        k: v for k, v in summary.items() if k != 'generated_at'}
    request(client, accounts, owner, 'post', '/auth/refresh', 401, json={'refresh_token': original_refresh})
    # Rotating one account never consumes the other's refresh token.
    foreign_pair = data(client, accounts, other(owner), 'post', '/auth/refresh',
                        json={'refresh_token': foreign['pair']['refresh_token']})
    assert decode(foreign_pair['access_token'], 'access')['sub'] == str(foreign['user']['user_id'])


@pytest.mark.parametrize('owner', DIRECTIONS)
def test_ai_http_history_and_imported_context_stay_personal(setup_ai, db, client, accounts, journey, monkeypatch, owner):
    """Exercise the HTTP chat/history boundary with a wholly offline provider.

    Explicit per-user external permission lets testing exercise the same data
    path after 0013; default purpose policy is checked separately below.
    """
    cfg = ai.settings_dict(ai.AISettings.model_validate({**setup_ai, 'user_policies': {
        str(accounts[p]['user']['user_id']): {'research_ai_allowed': True, 'external_send_allowed': True}
        for p in DIRECTIONS}}))
    db.execute(table('ai_config').update().values(settings=cfg))
    payloads = []

    def handler(outbound):
        payloads.append(outbound.read().decode())
        return httpx.Response(200, json=response('Checked the selected imported measurement.'))

    provider = Provider(httpx.MockTransport(handler), resolver=PUBLIC)
    app.dependency_overrides[ai.get_provider] = lambda: provider
    try:
        results = {}
        for actor in (owner, other(owner)):
            rid = str(uuid.uuid4())
            result = data(client, accounts, actor, 'post', '/ai/chat', json={
                'request_id': rid, 'message': 'Describe the selected measurement.',
                'context': {'kind': 'measurement', 'id': journey[actor]['measurement']}})
            assert result['status'] == 'completed', result
            assert result['tool_trace'] and result['sources']
            assert data(client, accounts, actor, 'get', f'/ai/requests/{rid}')['request_id'] == rid
            results[actor] = (rid, result)
        mine_id, mine = results[owner]
        foreign_id, foreign = results[other(owner)]
        history = data(client, accounts, owner, 'get', '/ai/requests')['requests']
        assert mine_id in {r['request_id'] for r in history}
        assert foreign_id not in {r['request_id'] for r in history}
        request(client, accounts, owner, 'get', f'/ai/requests/{foreign_id}', 404)
        request(client, accounts, other(owner), 'get', f'/ai/requests/{mine_id}', 404)
        sent_before = len(payloads)
        request(client, accounts, owner, 'post', '/ai/chat', 404, json={
            'request_id': str(uuid.uuid4()), 'conversation_id': foreign['conversation_id'],
            'message': 'Continue the other account conversation.'})
        assert len(payloads) == sent_before
        # Each model request contains only its selected account's measurement code.
        for sent, actor in zip(payloads, (owner, other(owner))):
            own_mid, foreign_mid = journey[actor]['measurement'], journey[other(actor)]['measurement']
            own_row = data(client, accounts, actor, 'get', f'/measurements/{own_mid}')
            foreign_row = data(client, accounts, other(actor), 'get', f'/measurements/{foreign_mid}')
            assert own_row['measurement_code'] in sent
            assert foreign_row['measurement_code'] not in sent
    finally:
        app.dependency_overrides.pop(ai.get_provider, None)


def test_persisted_purposes_survive_me_and_refresh(db, client, accounts):
    if 'account_purpose' not in table('users').c:
        pytest.skip('Migration 0013 account_purpose is not applied; ordinary owner journeys still run')
    for owner in DIRECTIONS:
        assert data(client, accounts, owner, 'get', '/auth/me')['user']['account_purpose'] == owner
        pair = data(client, accounts, owner, 'post', '/auth/refresh',
                    json={'refresh_token': accounts[owner]['pair']['refresh_token']})
        refreshed = {owner: {'headers': {'Authorization': 'Bearer ' + pair['access_token']}}}
        assert data(client, refreshed, owner, 'get', '/auth/me')['user']['account_purpose'] == owner
