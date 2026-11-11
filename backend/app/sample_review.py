"""Read-only sample review; explicit pairs only, no inferred treatment intervals."""
import json
from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import select,func

from .db import table
from .data_visibility import project, model_scope

VERSION = 'sample-apparent-1.0.0'


def document(value):
    return json.loads(value) if isinstance(value, str) else value or {}


def interval_cycles(before, after, experiments):
    """A per-sample count is usable only for an unambiguous dated interval."""
    pid = after['process_id']
    run = next((r for r in experiments if r['process_id'] == pid), None)
    if run and run.get('voided_at'):
        return None, '本次执行已作废，不能用于每循环结果'
    if not run or before['process_id'] not in (None, pid):
        return None, '测量未明确包围同一次执行；请核对前后配对及执行归属'
    if before['stage'] != 'initial' or after['stage'] not in ('after_ale', 'final'):
        return None, '阶段不能证明覆盖本次完整处理间隔'
    if any(not value for value in (before['measured_at'], after['measured_at'], run['started_at'], run['ended_at'])):
        return None, '缺少前后测量时间或实际执行起止时间，无法确认处理间隔'
    if not before['measured_at'] <= run['started_at'] <= run['ended_at'] <= after['measured_at'] or before['measured_at'] == after['measured_at']:
        return None, '测量时间没有包围本次实际执行'
    for other in experiments:
        if other['process_id'] == pid:
            continue
        if not other['started_at'] or not other['ended_at']:
            return None, '其他参与执行的时间未知，无法排除区间内的额外处理'
        if other['started_at'] <= after['measured_at'] and other['ended_at'] >= before['measured_at']:
            return None, '前后测量区间内存在其他执行，不能合并为本次循环数'
    cycles = run['full_ale_cycles']
    if cycles is None or cycles <= 0:
        return None, '本样品实际参与循环未记录或不大于零；设备总循环数不能代替'
    if not run.get('cycles_confirmed'):
        return None, '缺少本样品实际参与依据；仅绑定或执行时间不能证明样品已入腔'
    return cycles, None


def review(db, sample_id, user, experiments, excluded=False):
    from .scientificanalysis import calculate, Calculate, VERSION as ANALYSIS_VERSION, decimal_text
    m = table('measurements')
    raw = [dict(r) for r in db.execute(select(m).where(m.c.sample_id == sample_id).order_by(m.c.measured_at.is_(None), m.c.measured_at, m.c.measurement_id)).mappings()]
    by_id = {r['measurement_id']: r for r in raw}
    points=table('measurement_points')
    usable=dict(db.execute(select(points.c.measurement_id,func.count()).where(points.c.measurement_id.in_(list(by_id)),points.c.thickness_nm.is_not(None),points.c.is_outlier==False).group_by(points.c.measurement_id)).all())
    models = {r['model_id']: dict(r) for r in db.execute(select(table('optical_models')).where(model_scope(user))).mappings()}
    history, results = [], []
    for row in raw:
        visible = project(db, row, user, 'measurement')
        provenance = document(row['provenance'])
        statistics = provenance.get('statistics', {})
        entry = {key: visible.get(key) for key in ('measurement_id', 'measurement_code', 'stage', 'measured_at', 'point_count', 'thickness_mean_nm', 'mse_mean', 'quality_flag', 'is_current', 'process_id', 'source_file_id')}
        entry['valid_point_count']=usable.get(row['measurement_id'],0)
        # Exact parser means are kept when the DB summary cannot represent them.
        entry['thickness_mean_nm'] = statistics.get('thickness_nm', {}).get('mean', entry['thickness_mean_nm'])
        entry['mse_mean'] = statistics.get('mse', {}).get('mean', entry['mse_mean'])
        model = models.get(row['optical_model_id'])
        entry['model_name'] = (model.get('model_name') or model.get('model_code')) if model else '未确认 / 不可见'
        entry['model_parameters'] = provenance.get('metadata', {}).get('optical_model', {}).get('parameter_columns', [])
        history.append(entry)
        before_id = provenance.get('confirmation', {}).get('pair_measurement_id')
        if not before_id and row['stage'] == 'initial':
            continue
        result = {'after_measurement_id': row['measurement_id'], 'before_measurement_id': before_id,
                  'after_code': row['measurement_code'], 'before_code': None,
                  'thinning_nm': None, 'epc_nm_per_cycle': None, 'effective_cycles': None,
                  'reason': None, 'epc_reason': None, 'version': VERSION,
                  'analysis_version': ANALYSIS_VERSION, 'direction': 'before - after',
                  'interpretation': '椭偏表观变化 / apparent；正值为表观减薄，负值为表观增厚，不证明 ALE 或反应机制。',
                  'quality_rule': '保留全部原值；结果摘要要求两次测量 current、quality=ok 且无异常标记点。'}
        before = by_id.get(before_id)
        if excluded:
            result['reason'] = '样品已排除常规分析，请先核查排除依据'
        elif before is None:
            result['before_measurement_id'] = None
            result['reason'] = '未确认同样品的前测配对；请在导入高级核查中选择有依据的前测，或在科研分析中明确配对'
        elif not row['is_current'] or not before['is_current'] or any(r['quality_flag'] != 'ok' for r in (before, row)):
            result['reason'] = '前后测量已被重测取代或质量未确认正常，请先核查测点与质量标记'
        else:
            result['before_code'] = before['measurement_code']
            try:
                data = calculate(db, Calculate(sources=[{'kind': 'measurement', 'id': before_id}, {'kind': 'measurement', 'id': row['measurement_id']}], before_index=0, after_index=1, confirm_pair=True), user)
                if any(p['is_outlier'] for series in data['series'] for p in series['points']):
                    result['reason'] = '存在异常标记点；请到科研分析明确纳入/排除依据后保存分析'
                elif any(not s['statistics']['thickness_nm']['count'] for s in data['series']):
                    result['reason'] = '缺少有效膜厚测点'
                else:
                    with localcontext() as context:
                        context.prec = 50
                        a, b = [Decimal(s['statistics']['thickness_nm']['mean']) for s in data['series']]
                        result.update(before_mean_nm=decimal_text(a), after_mean_nm=decimal_text(b), thinning_nm=decimal_text(a-b),
                                      sources=[{k: s['source'].get(k) for k in ('id', 'row_version', 'sha256', 'points_sha256', 'optical_model_id')} for s in data['series']])
                        cycles, why = interval_cycles(before, visible, experiments)
                        result['effective_cycles'], result['epc_reason'] = cycles, why
                        if cycles:
                            result['epc_nm_per_cycle'] = decimal_text((a-b)/cycles)
            except HTTPException as error:
                # A failed comparison must never hide the measurement history.
                result['reason'] = str(error.detail) if error.status_code != 404 else '配对来源或模型不可见，无法计算'
        results.append(result)
    return {'measurements': history, 'results': results, 'version': VERSION}
