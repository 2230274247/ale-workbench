"""EPC (Etch Per Cycle) prediction and results visualization.

Scientific boundary (see AGENTS.md):
  * Raw measured values, deterministic derivations (EPC = 10 * net_thinning / cycles)
    and model predictions are kept strictly separate in the response.
  * Prediction is a transparent ordinary-least-squares model fitted ONLY on rows the
    existing `quick_dataset.eligibility()` contract marks training-eligible. When there
    is insufficient confirmed data it refuses and explains why — it never fabricates a
    metric, never trains on unconfirmed channel mappings, and never sums across
    unconfirmed process systems.

Three capabilities:
  1. /results   — real EPC results + summary series for visualization (no model).
  2. /calculator— deterministic EPC derivation from before/after thickness + cycles.
  3. /predict   — transparent linear prediction on confirmed-eligible rows (refuses
                  with reasons when data is insufficient).
"""
import math
import statistics
from fastapi import APIRouter, Depends, Query, Request
from .common import envelope
from .db import get_db
from .security import current_user
from .quick import selection
from .quick_dataset import wide, REASON_LABELS

router = APIRouter(prefix='/api/v1/epc', tags=['EPC prediction'])

NUMERIC_FEATURES = ['X_r1_c', 'X_r2_c', 'X_n2_sccm', 'X_absolute_pressure_pa', 'X_effective_cycles', 'X_before_measured_nm']


def _min_rows(k: int) -> int:
    return max(8, k + 5)


def _gauss(a, b):
    """Solve a*x = b by Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError('singular design matrix')
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x


def fit_linear(features, rows, target='y_epc_a_per_cycle'):
    """Fit y ~ 1 + features on complete rows. Returns a dict with coefs and metrics."""
    X, y = [], []
    for r in rows:
        vals = [r.get(f) for f in features]
        t = r.get(target)
        if any(v is None for v in vals) or t is None:
            continue
        try:
            X.append([1.0] + [float(v) for v in vals])
            y.append(float(t))
        except (TypeError, ValueError):
            continue
    n = len(y)
    k = len(features) + 1
    if n < _min_rows(k):
        return {'status': 'insufficient_data', 'n': n, 'min_required': _min_rows(k),
                'features': features, 'target': target}
    a = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for i in range(n):
        for p in range(k):
            b[p] += X[i][p] * y[i]
            for q in range(k):
                a[p][q] += X[i][p] * X[i][q]
    beta = _gauss(a, b)
    yhat = [sum(X[i][p] * beta[p] for p in range(k)) for i in range(n)]
    ymean = sum(y) / n
    ss_tot = sum((v - ymean) ** 2 for v in y)
    ss_res = sum((y[i] - yhat[i]) ** 2 for i in range(n))
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else None
    rmse = math.sqrt(ss_res / max(1, n - k))
    return {'status': 'ok', 'n': n, 'min_required': _min_rows(k), 'features': features, 'target': target,
            'intercept': beta[0], 'coefficients': {features[i]: beta[i + 1] for i in range(len(features))},
            'r_squared': r2, 'rmse': rmse, 'units': 'Å/cycle' if target == 'y_epc_a_per_cycle' else 'nm'}


def _result_dict(run, r):
    env = run['environment']
    return {
        'run_id': run['run_id'], 'process_code': run['process_code'],
        'result_id': r['result_id'], 'material': r.get('material_name'),
        'equipment': env.get('equipment'),
        'temperature_r1_c': env.get('r1_temperature_c'), 'temperature_r2_c': env.get('r2_temperature_c'),
        'n2_sccm': env.get('n2_flow_sccm'), 'pressure_pa': env.get('chamber_pressure_pa'),
        'effective_cycles': r.get('effective_cycles'),
        'thickness_before_nm': r.get('thickness_before_nm'), 'thickness_after_nm': r.get('thickness_after_nm'),
        'thickness_loss_nm': r.get('thickness_loss_nm'), 'epc_a_per_cycle': r.get('epc_a_per_cycle'),
        'uniformity_pct': r.get('uniformity_pct'), 'reported_epc': r.get('reported_epc'),
        'reported_epc_difference': r.get('reported_epc_difference'),
        'data_nature': r.get('data_nature'), 'quality_status': r.get('quality_status'),
        'result_label': r.get('result_label'), 'before_origin': r.get('before_origin'),
    }


def _summary(rows):
    epc = [r['epc_a_per_cycle'] for r in rows if r['epc_a_per_cycle'] is not None]
    by_material = {}
    for r in rows:
        m = r['material'] or '未确认'
        if r['epc_a_per_cycle'] is not None:
            by_material.setdefault(m, []).append(r['epc_a_per_cycle'])
    material_stats = [{'material': m, 'count': len(v),
                       'mean': statistics.fmean(v) if v else None,
                       'stdev': statistics.pstdev(v) if len(v) > 1 else None,
                       'min': min(v) if v else None, 'max': max(v) if v else None}
                      for m, v in sorted(by_material.items())]

    def series(key):
        pts = [(r[key], r['epc_a_per_cycle']) for r in rows if r.get(key) is not None and r['epc_a_per_cycle'] is not None]
        pts.sort(key=lambda p: p[0])
        return [{'x': x, 'y': y} for x, y in pts]

    return {
        'result_count': len(rows), 'epc_count': len(epc),
        'epc_mean': statistics.fmean(epc) if epc else None,
        'epc_stdev': statistics.pstdev(epc) if len(epc) > 1 else None,
        'epc_min': min(epc) if epc else None, 'epc_max': max(epc) if epc else None,
        'by_material': material_stats,
        'epc_vs_temperature': series('temperature_r1_c'),
        'epc_vs_pressure': series('pressure_pa'),
        'epc_vs_cycles': series('effective_cycles'),
    }


@router.get('/results')
def results(request: Request, db=Depends(get_db), user=Depends(current_user)):
    runs = selection(db, user, dict(request.query_params))
    rows = [_result_dict(run, r) for run in runs for r in run['results']]
    wide_rows = wide(runs)
    eligible = sum(1 for r in wide_rows if r['meta_training_eligible'])
    reasons = {}
    for r in wide_rows:
        for reason in r['meta_exclusion_reasons'].split(';'):
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
    return envelope(request, {
        'rows': rows,
        'summary': _summary(rows),
        'training': {'total_rows': len(wide_rows), 'eligible_count': eligible,
                     'exclusion_counts': reasons,
                     'reason_labels': {k: REASON_LABELS.get(k, k) for k in reasons},
                     'policy': 'real_experiment + approved + confirmed channel mapping; no outcome in X'},
    })


@router.get('/calculator')
def calculator(request: Request, before_nm: float = Query(..., ge=0), after_nm: float = Query(..., ge=0),
               cycles: int = Query(..., gt=0)):
    loss_nm = before_nm - after_nm
    epc = 10.0 * loss_nm / cycles
    return envelope(request, {
        'kind': 'deterministic_derivation',
        'thickness_loss_nm': loss_nm, 'epc_a_per_cycle': epc,
        'units': 'Å/cycle', 'formula': 'EPC = 10 * (before_nm - after_nm) / cycles',
    })


@router.get('/predict')
def predict(request: Request, material: str = Query(''), r1_c: float = Query(None), r2_c: float = Query(None),
            n2_sccm: float = Query(None), pressure_pa: float = Query(None),
            effective_cycles: float = Query(None), before_nm: float = Query(None),
            db=Depends(get_db), user=Depends(current_user)):
    runs = selection(db, user, dict(request.query_params))
    wide_rows = wide(runs)
    eligible = [r for r in wide_rows if r['meta_training_eligible']]
    if not eligible:
        reasons = {}
        for r in wide_rows:
            for reason in r['meta_exclusion_reasons'].split(';'):
                if reason:
                    reasons[reason] = reasons.get(reason, 0) + 1
        return envelope(request, {
            'status': 'insufficient_data', 'eligible_count': 0, 'total_rows': len(wide_rows),
            'exclusion_counts': reasons,
            'reason_labels': {k: REASON_LABELS.get(k, k) for k in reasons},
            'message': '已确认可训练的数据不足，本版本不训练、不生成预测指标。请先确认源通道物理映射与有效周期口径。',
        })
    if material:
        eligible = [r for r in eligible if (r.get('X_material') == material)]
    if not eligible:
        return envelope(request, {'status': 'insufficient_data', 'eligible_count': 0, 'total_rows': len(wide_rows),
                                  'message': '所选材料下没有已确认可训练的数据。'})
    fit = fit_linear(NUMERIC_FEATURES, eligible, target='y_epc_a_per_cycle')
    if fit['status'] != 'ok':
        return envelope(request, {**fit, 'message': '可训练样本仍不足，无法拟合透明模型。'})
    input_vec = {'X_r1_c': r1_c, 'X_r2_c': r2_c, 'X_n2_sccm': n2_sccm,
                 'X_absolute_pressure_pa': pressure_pa, 'X_effective_cycles': effective_cycles,
                 'X_before_measured_nm': before_nm}
    provided = [f for f in NUMERIC_FEATURES if input_vec.get(f) is not None]
    missing = [f for f in NUMERIC_FEATURES if input_vec.get(f) is None]
    if missing:
        alt = fit_linear(provided, eligible, target='y_epc_a_per_cycle') if provided else {'status': 'insufficient_data'}
        if alt.get('status') != 'ok':
            return envelope(request, {'status': 'missing_inputs', 'message': '缺少关键工艺参数，无法预测。',
                                      'missing_features': missing})
        fit = alt
    pred = fit['intercept'] + sum(fit['coefficients'][f] * float(input_vec[f]) for f in fit['features'])
    return envelope(request, {
        'status': 'ok', 'kind': 'model_prediction',
        'predicted_epc_a_per_cycle': pred, 'units': 'Å/cycle',
        'model': {'n': fit['n'], 'features': fit['features'], 'intercept': fit['intercept'],
                  'coefficients': fit['coefficients'], 'r_squared': fit['r_squared'], 'rmse': fit['rmse'],
                  'material': material or None,
                  'note': '线性模型估计值，与原始量测值和确定性派生值分开。'},
        'input': {f: input_vec[f] for f in provided},
    })
