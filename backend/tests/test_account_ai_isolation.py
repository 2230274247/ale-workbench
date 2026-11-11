"""Account AI isolation: mocked providers and rollback-only MySQL transactions."""
import uuid
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import ai
from app.ai_provider import Provider, ProviderError
from app.db import table
from test_ai import setup_ai, response, PUBLIC
from test_ai_tools import research
from test_phase4_browser import db


@pytest.fixture
def account_purposes(monkeypatch):
    # Independent of whether the parent account_purpose migration is applied.
    original = ai.active_user
    purposes = {}
    def fresh(db, user):
        row = original(db, user)
        return {**row, 'account_purpose': purposes.get(row['user_id'], row.get('account_purpose', 'research'))}
    monkeypatch.setattr(ai, 'active_user', fresh)
    return purposes


def configure(db, cfg, **changes):
    cfg = ai.settings_dict(ai.AISettings.model_validate({**cfg, **changes}))
    db.execute(table('ai_config').update().values(settings=cfg))
    return cfg


def body():
    return ai.ChatBody(request_id=uuid.uuid4(), message='Read my samples')


def denied(code, callback):
    with pytest.raises(HTTPException) as exc:
        callback()
    assert exc.value.status_code == code
    return exc.value


@pytest.mark.parametrize('account,overrides,purpose,expected', [
    ('testing', {}, 'chat', 'testing_external_send_denied'),
    ('testing', {'research_ai_allowed': True}, 'chat', 'testing_external_send_denied'),
    ('testing', {'external_send_allowed': True}, 'chat', None),
    ('testing', {}, 'models', 'testing_external_send_denied'),
    ('management', {}, 'chat', None),
    ('management', {'research_ai_allowed': False}, 'chat', 'research_ai_denied'),
    ('management', {'research_ai_allowed': True}, 'chat', None),
    ('management', {'research_ai_allowed': False}, 'models', None),
    ('management', {'research_ai_allowed': False}, 'test', None),
    ('research', {'research_ai_allowed': False}, 'chat', 'research_ai_denied'),
])
def test_policy_defaults(account, overrides, purpose, expected):
    config = {'user_policies': {'1': overrides}}
    assert ai.access_denial(config, {'user_id': 1, 'role': 'admin', 'account_purpose': account}, purpose) == expected
    assert ai.access_denial({}, {'user_id': 1, 'role': 'operator'}) is None


def test_policy_validation_and_zero_budget():
    with pytest.raises(ValidationError): ai.AISettings(user_policies={'01': {}})
    with pytest.raises(ValidationError): ai.AISettings(user_policies={'1': {'monthly_token_limit': -1}})
    cfg = ai.settings_dict(ai.AISettings(user_policies={'1': {'monthly_budget': 0, 'monthly_token_limit': 0}}))
    assert ai.user_budget(cfg, 1) == {'monthly_budget': Decimal(0), 'monthly_token_limit': 0}
    assert ai.user_budget(cfg, 2)['monthly_token_limit'] == 2000000


def test_provider_denial_precedes_dns():
    seen = []
    provider = Provider(httpx.MockTransport(lambda r: seen.append(r)), resolver=lambda h: seen.append(h))
    with pytest.raises(ProviderError) as exc:
        provider.request({'_external_send_allowed': False}, 'unused', '/models')
    assert exc.value.code == 'external_send_denied'
    assert seen == []


def test_testing_blocks_before_reservation_and_no_outbound(setup_ai, db, actors, account_purposes):
    user = actors['operator']['user']
    account_purposes[user['user_id']] = 'testing'
    sent = []
    provider = Provider(httpx.MockTransport(lambda r: sent.append(r)), PUBLIC)
    request = body()
    denied(403, lambda: ai.run(user, request, 'chat', provider))
    assert not sent
    assert db.scalar(select(table('ai_requests').c.request_id).where(table('ai_requests').c.request_id == str(request.request_id))) is None
    configure(db, setup_ai, user_policies={str(user['user_id']): {'external_send_allowed': True}})
    held, _ = ai.reserve(user, request, 'chat')
    assert held['account_purpose'] == 'testing'
    # Administrator revocation between reservation and outbound must fence execution.
    configure(db, setup_ai)
    with pytest.raises(ProviderError) as exc: ai.before_outbound(user, held, [], str(request.request_id))
    assert exc.value.code == 'testing_external_send_denied'


def test_management_science_denied_but_admin_operations_work(setup_ai, db, actors, account_purposes, client):
    user = actors['admin']['user']
    account_purposes[user['user_id']] = 'management'
    configure(db, setup_ai, user_policies={str(user['user_id']): {'research_ai_allowed': False}})
    denied(403, lambda: ai.reserve(user, body(), 'chat'))
    assert client.get('/api/v1/ai/config', headers=actors['admin']['headers']).status_code == 200
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'data': [{'id': 'fixture-model'}]})
    result = ai.run(user, ai.TestBody(request_id=uuid.uuid4()), 'models', Provider(httpx.MockTransport(handle), PUBLIC))
    assert result['status'] == 'completed' and len(seen) == 1
    denied(403, lambda: ai.execute_tool(db, {**user, 'account_purpose': 'management'}, 'search_records', {}))


@pytest.mark.parametrize('kind', ['tokens', 'money'])
def test_user_pending_budget_blocks_only_owner(setup_ai, db, actors, kind):
    tokens, cost = ai.reservation(setup_ai, 'chat')
    changes = {'user_monthly_token_limit': tokens if kind == 'tokens' else 2000000,
               'user_monthly_budget': str(cost) if kind == 'money' else '10'}
    configure(db, setup_ai, **changes)
    first, second = actors['operator']['user'], actors['other']['user']
    held, _ = ai.reserve(first, body(), 'chat')
    denied(429, lambda: ai.reserve(first, body(), 'chat'))
    assert ai.reserve(second, body(), 'chat')[0]
    usage = ai.user_usage(db, held['period'], first['user_id'])[first['user_id']]
    assert usage['reserved_tokens'] == tokens and usage['reserved_cost'] == cost


def test_user_accounting_measured_settlement_and_usage_private(setup_ai, db, actors, client):
    first, second = actors['operator']['user'], actors['other']['user']
    request = body()
    held, _ = ai.reserve(first, request, 'chat')
    ai.before_outbound(first, held, [], str(request.request_id))
    ai.checkpoint_call(held, str(request.request_id), measured=ai.parse_usage(response(), setup_ai))
    result = {'status': 'failed', 'answer': None, 'sources': [], 'tool_trace': []}
    ai.finish(first, request, held, result, {}, False, 1, [], [])
    ai.reserve(second, body(), 'chat')
    usage = client.get('/api/v1/ai/usage/me', headers=actors['operator']['headers']).json()['data']
    assert usage['scope'] == 'current_user' and usage['owner_user_id'] == first['user_id']
    assert usage['charged_tokens'] == 110 and usage['reserved_tokens'] == 0
    assert 'users' not in usage
    assert client.get('/api/v1/ai/usage', headers=actors['operator']['headers']).status_code == 403


def test_budget_reduction_respects_existing_user_liabilities(setup_ai, db, actors, client):
    owner = actors['operator']['user']['user_id']
    ai.reserve(actors['operator']['user'], body(), 'chat')
    cfg = client.get('/api/v1/ai/config', headers=actors['admin']['headers']).json()['data']
    payload = {k: cfg[k] for k in ai.AISettings.model_fields}
    payload.update(revision=cfg['revision'], user_policies={str(owner): {'monthly_token_limit': 0}})
    assert client.put('/api/v1/ai/config', headers=actors['admin']['headers'], json=payload).status_code == 409


def test_tools_never_mix_research_testing_records(setup_ai, research, db, actors):
    from app.ai_tools import execute_tool
    first = {**actors['operator']['user'], 'account_purpose': 'research'}
    second = {**actors['other']['user'], 'account_purpose': 'testing'}
    for user, mine, hidden in [(first, 'operator', 'other'), (second, 'other', 'operator')]:
        result = execute_tool(db, user, 'search_records', {'keyword': research['prefix']})
        ids = {r['sample_id'] for r in result['data']['records']}
        assert research[mine]['sample'] in ids and research[hidden]['sample'] not in ids
        denied(404, lambda: execute_tool(db, user, 'record_detail', {'kind': 'sample', 'id': research[hidden]['sample']}))
        quality = execute_tool(db, user, 'quality_hints', {'sample_id': research[mine]['sample']})
        assert quality['data']['facts']['current_measurements'] == 4


def test_per_user_override_does_not_change_other_capacity(setup_ai, db, actors):
    first, second = actors['operator']['user'], actors['other']['user']
    configure(db, setup_ai, user_policies={str(first['user_id']): {'monthly_budget': '0'}})
    denied(429, lambda: ai.reserve(first, body(), 'chat'))
    assert ai.reserve(second, body(), 'chat')[0]


@pytest.mark.parametrize('dispatched', [False, True])
def test_recovery_releases_unused_user_reservations_retains_unknown(setup_ai, db, actors, dispatched):
    from datetime import timedelta
    user = actors['operator']['user']
    request = body()
    held, _ = ai.reserve(user, request, 'chat')
    if dispatched: ai.before_outbound(user, held, [], str(request.request_id))
    req = table('ai_requests')
    row = db.execute(select(req).where(req.c.request_id == str(request.request_id))).mappings().one()
    meta = dict(row['result']['_server'])
    meta['lease_expires_at'] = (ai.dbnow() - timedelta(seconds=1)).isoformat()
    db.execute(req.update().where(req.c.request_id == str(request.request_id)).values(result={'_server': meta}))
    assert str(request.request_id) in ai.recover_stale(db)
    usage = ai.user_usage(db, held['period'], user['user_id'])[user['user_id']]
    assert usage['reserved_tokens'] == 0 and usage['reserved_cost'] == 0
    tokens, cost = ai.reservation(setup_ai, 'test')
    assert usage['charged_tokens'] == (tokens if dispatched else 0)
    assert usage['charged_cost'] == (cost if dispatched else 0)


def test_account_purpose_change_fences_pending_execution(setup_ai, db, actors, account_purposes):
    user = actors['operator']['user']
    request = body()
    held, _ = ai.reserve(user, request, 'chat')
    account_purposes[user['user_id']] = 'testing'
    configure(db, setup_ai, user_policies={str(user['user_id']): {'external_send_allowed': True}})
    with pytest.raises(ProviderError) as exc: ai.before_outbound(user, held, [], str(request.request_id))
    assert exc.value.code == 'authorization_changed'


def test_admin_config_accepts_user_policy_and_policy_is_current_user_only(setup_ai, db, actors, client, account_purposes):
    owner = actors['operator']['user']['user_id']
    other = actors['other']['user']['user_id']
    cfg = client.get('/api/v1/ai/config', headers=actors['admin']['headers']).json()['data']
    payload = {k: cfg[k] for k in ai.AISettings.model_fields}
    payload.update(revision=cfg['revision'], user_policies={str(owner): {
        'monthly_budget': '2.50', 'monthly_token_limit': 500000,
        'external_send_allowed': False, 'research_ai_allowed': True}, str(other): {'monthly_budget': '1'}})
    saved = client.put('/api/v1/ai/config', headers=actors['admin']['headers'], json=payload)
    assert saved.status_code == 200
    assert saved.json()['data']['user_policies'][str(owner)]['monthly_budget'] == '2.50'
    account_purposes[owner] = 'testing'
    policy = client.get('/api/v1/ai/policy', headers=actors['operator']['headers']).json()['data']
    assert policy['denial_reason'] == 'testing_external_send_denied'
    assert policy['monthly_token_limit'] == 500000
    assert 'user_policies' not in policy
