"""EPC prediction & visualization: pure OLS math, deterministic calculator,
and the scientific boundary — prediction refuses when no confirmed training rows exist."""
from app.epc import fit_linear, _min_rows


def test_min_rows_floor_and_slack():
    assert _min_rows(7) == 12
    assert _min_rows(3) == 8
    assert _min_rows(30) == 35


def test_fit_linear_exact_line():
    features = ['x']
    rows = [{'x': float(i), 'y_epc_a_per_cycle': 3.0 + 2.0 * i} for i in range(1, 21)]
    fit = fit_linear(features, rows, target='y_epc_a_per_cycle')
    assert fit['status'] == 'ok'
    assert fit['n'] == 20
    assert abs(fit['intercept'] - 3.0) < 1e-6
    assert abs(fit['coefficients']['x'] - 2.0) < 1e-6
    assert abs(fit['r_squared'] - 1.0) < 1e-6
    assert fit['rmse'] < 1e-6


def test_fit_linear_refuses_too_few_rows():
    features = ['a', 'b', 'c', 'd']
    rows = [{'a': 1.0, 'b': 2.0, 'c': 3.0, 'd': 4.0, 'y_epc_a_per_cycle': 1.0}]
    assert fit_linear(features, rows, target='y_epc_a_per_cycle')['status'] == 'insufficient_data'


def test_calculator_derivation(client, actors):
    r = client.get('/api/v1/epc/calculator',
                   params={'before_nm': 100, 'after_nm': 90, 'cycles': 10},
                   headers=actors['operator']['headers'])
    assert r.status_code == 200, r.text
    d = r.json()['data']
    assert d['kind'] == 'deterministic_derivation'
    assert abs(d['thickness_loss_nm'] - 10.0) < 1e-9
    assert abs(d['epc_a_per_cycle'] - 10.0) < 1e-9


def test_calculator_rejects_invalid_cycles(client, actors):
    r = client.get('/api/v1/epc/calculator',
                   params={'before_nm': 100, 'after_nm': 90, 'cycles': 0},
                   headers=actors['operator']['headers'])
    assert r.status_code == 422


def test_epc_requires_auth(client):
    assert client.get('/api/v1/epc/results').status_code in (401, 403)


def test_results_envelope_and_training_breakdown(client, actors):
    r = client.get('/api/v1/epc/results', headers=actors['operator']['headers'])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['code'] == 0
    data = body['data']
    assert set(['rows', 'summary', 'training']) <= set(data)
    assert 'eligible_count' in data['training']
    assert 'exclusion_counts' in data['training']
    assert 'reason_labels' in data['training']


def test_predict_refuses_without_confirmed_training_rows(client, actors):
    r = client.get('/api/v1/epc/predict',
                   params={'r1_c': 200, 'n2_sccm': 50, 'pressure_pa': 1000, 'effective_cycles': 30, 'before_nm': 50},
                   headers=actors['operator']['headers'])
    assert r.status_code == 200, r.text
    d = r.json()['data']
    assert d['status'] == 'insufficient_data'
    assert 'predicted_epc_a_per_cycle' not in d
    assert d['message']
