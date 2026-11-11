"""Deletion impact preview and record lifecycle (archive / restore / void / delete).

Read-only impact queries never invent counts. Groups whose dependents are partly
outside the caller's visibility return the visible count only plus a generic
flag; hidden names and totals are never disclosed.

Apply actions run inside the request transaction: the parent row is locked
first, the row version is checked (CAS), and an audit entry records the action,
the reason and the prior state. No action ever cascades a delete.
"""
import json
import hashlib
import hmac

from .config import jwt_secret

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, func, or_, select, true

from .common import dbnow, envelope, fail
from .db import get_db, metadata, table
from .records import (PROTECTED_DEPENDENCIES, delete_record, fetch as record_fetch,
                      protect_sample_void, scope as record_scope, serialize_record,
                      void_sample)
from .security import current_user, writer
from . import schemas as S

router = APIRouter(prefix='/api/v1', tags=['Lifecycle'])

KINDS = {
    'batches': ('batches', 'batch_id', 'batch', 'batch_code', '批次'),
    'samples': ('samples', 'sample_id', 'sample', 'sample_code', '样品'),
    'plans': ('experiment_plans', 'plan_id', 'experiment_plan', 'plan_code', '实验计划'),
    'processes': ('processes', 'process_id', 'process', 'process_code', '工艺执行'),
}

# Explicit dependency groups per kind, in display order. Any further table that
# references the record is still scanned and appended so counts are not omitted.
GROUPS = {
    'batches': ['samples', 'experiment_plans', 'processes'],
    'plans': ['experiment_plan_steps', 'processes'],
    'processes': ['process_steps', 'process_samples', 'sample_transitions', 'measurements',
                  'derived_results', 'instrument_datasets'],
}

LABELS = {
    'samples': '样品', 'experiment_plans': '实验计划', 'experiment_plan_steps': '计划步骤',
    'processes': '工艺执行', 'process_steps': '实际步骤', 'process_samples': '工艺样品关联',
    'sample_transitions': '样品流转记录', 'measurements': '测量记录', 'measurement_points': '测量点',
    'derived_results': '派生结果', 'instrument_datasets': '仪器数据集', 'findings': '研究发现',
    'issues': '问题记录', 'issue_links': '问题关联', 'issues_links': '问题关联',
    'attachments': '附件', 'source_files': '原始文件', 'source_file_occurrences': '原始文件引用',
    'recipes': '配方', 'optical_models': '光学模型', 'instrument_channels': '仪器通道',
}

SAMPLE_GROUPS = [
    ('transitions', '样品流转记录', ['sample_transitions'], None),
    ('process_links', '工艺样品关联', ['process_samples'], None),
    ('measurements', '测量记录', ['measurements'], None),
    ('source_occurrences', '原始文件引用', ['source_file_occurrences', 'source_files'], None),
    ('child_samples', '子样品', ['samples'], 'parent_sample_id'),
]


def kind_meta(kind):
    if kind not in KINDS:
        fail(404)
    return KINDS[kind]


def parent(db, kind, id, user, lock=False):
    """Fetch a visible parent row. Plans/processes use the experiment visibility rules."""
    if kind in ('plans', 'processes'):
        from .experiments import fetch as experiment_fetch
        return experiment_fetch(db, kind, id, user, lock, allow_void=True)
    return record_fetch(db, kind, id, user, lock, allow_void=True)


def reopen(db, kind, id, user):
    """Re-read the parent after an update inside the same request.

    The row was locked and version-checked moments earlier, so the locking read
    is still the cheapest way to observe the new version inside this transaction.
    """
    return parent(db, kind, id, user, lock=True)


def _temporal(value):
    return None if value is None else str(value)


def status_summary(kind, row):
    if kind == 'samples':
        return {'status': row.get('status'), 'archived_at': row.get('archived_at'),
                'voided_at': row.get('voided_at'), 'void_reason': row.get('void_reason')}
    return {'status': row.get('log_status') if kind == 'processes' else row.get('status'),
            'archived_at': row.get('archived_at'), 'voided_at': row.get('voided_at'),
            'void_reason': row.get('void_reason')}


def is_archived(kind, row):
    if kind == 'plans':
        return row.get('status') == 'archived'
    return row.get('archived_at') is not None


def owner_id(kind, row):
    return row.get('operator_user_id') if kind == 'processes' else row.get('owner_user_id')


def can_manage(user, row, kind):
    """Restore is allowed for admin and the record owner."""
    return user['role'] == 'admin' or owner_id(kind, row) == user['user_id']


def dependency_scope_for(name, user):
    """Visibility predicate for one dependent table, or None when unknowable.

    None means the table has no trustworthy scope rule; the caller then reports
    the group as restricted with no count (fail closed).
    """
    if user is None or user['role'] == 'admin':
        return true()
    if name in ('batches', 'samples'):
        return record_scope(name, user)
    if name in ('experiment_plans', 'processes', 'experiment_plan_steps', 'process_steps', 'process_samples'):
        from .experiments import visible
        if name == 'experiment_plans':
            return visible('plans', user)
        if name == 'processes':
            return visible('processes', user)
        parent_name, pk, kind_name = (('experiment_plans', 'plan_id', 'plans') if name == 'experiment_plan_steps'
                                      else ('processes', 'process_id', 'processes'))
        return table(name).c[pk].in_(select(table(parent_name).c[pk]).where(visible(kind_name, user)))
    if name == 'sample_transitions':
        return table(name).c.sample_id.in_(select(table('samples').c.sample_id).where(record_scope('samples', user)))
    if name in ('measurements', 'measurement_points', 'instrument_datasets', 'source_files', 'source_file_occurrences'):
        from .measurement_management import (dataset_scope, measurement_scope,
                                             occurrence_scope, source_scope)
        if name == 'measurement_points':
            m = table('measurements')
            return table(name).c.measurement_id.in_(select(m.c.measurement_id).where(measurement_scope(user)))
        return {'measurements': measurement_scope, 'instrument_datasets': dataset_scope,
                'source_files': source_scope, 'source_file_occurrences': occurrence_scope}[name](user)
    return None


def predicates_for(candidate, target, kind, pk, id, extra=None, skip=()):
    """Same FK + polymorphic scan as protect_delete, plus an optional extra predicate."""
    pk_name = pk if isinstance(pk, str) else pk.name
    predicates = []
    for constraint in candidate.foreign_key_constraints:
        # Reflected MetaData instances may hand out equal-but-not-identical
        # Table objects, so compare by name rather than identity.
        if constraint.referred_table.name != target.name:
            continue
        predicates.extend(candidate.c[link.parent.name] == id
                          for link in constraint.elements
                          if link.column.name == pk_name and link.parent.name not in skip)
    if 'entity_type' in candidate.c and 'entity_id' in candidate.c:
        entity = {'batches': 'batch', 'samples': 'sample', 'plans': 'experiment_plan',
                  'experiment_plans': 'experiment_plan', 'processes': 'process',
                  'process_steps': 'process_step'}.get(kind, kind)
        predicates.append(and_(candidate.c.entity_type == entity, candidate.c.entity_id == id))
    if extra is not None:
        predicates.append(extra)
    return predicates


def counted(db, candidate, predicate):
    return db.scalar(select(func.count()).select_from(select(candidate).where(predicate).subquery())) or 0


def scoped_count(db, name, predicate, user):
    """Return (visible_count, restricted) without ever leaking a hidden total."""
    candidate = table(name)
    total = counted(db, candidate, predicate)
    if not total:
        return 0, False
    if user is None or user['role'] == 'admin':
        return total, False
    scope_predicate = dependency_scope_for(name, user)
    if scope_predicate is None:
        return 0, True
    visible = counted(db, candidate, and_(predicate, scope_predicate))
    return visible, visible < total


def blocked_sample_ids(db, sample_ids):
    """Sample IDs among `sample_ids` that have any scientific reference.

    This is the void-safety scan minus the void-specific status/transition
    restrictions: every FK and polymorphic reference counts, audit history does
    not, and transition rows only count when they point at an experiment.
    Bulk queries keep the cost independent of the number of samples.
    """
    sample_ids = sorted(set(sample_ids))
    if not sample_ids:
        return set()
    target = table('samples')
    blocked = set()
    for candidate in metadata().tables.values():
        if candidate.name in ('audit_log', 'samples', 'sample_transitions'):
            continue
        for constraint in candidate.foreign_key_constraints:
            if constraint.referred_table is not target:
                continue
            for link in constraint.elements:
                if link.column is not target.c.sample_id:
                    continue
                blocked.update(db.scalars(select(candidate.c[link.parent.name]).where(
                    candidate.c[link.parent.name].in_(sample_ids)).distinct()))
        if 'entity_type' in candidate.c and 'entity_id' in candidate.c:
            blocked.update(db.scalars(select(candidate.c.entity_id).where(
                candidate.c.entity_type == 'sample', candidate.c.entity_id.in_(sample_ids)).distinct()))
    transitions = table('sample_transitions')
    blocked.update(db.scalars(select(transitions.c.sample_id).where(
        transitions.c.sample_id.in_(sample_ids),
        or_(transitions.c.process_id.isnot(None), transitions.c.step_id.isnot(None),
            transitions.c.measurement_id.isnot(None))).distinct()))
    return {int(value) for value in blocked if value is not None}


def shared_info(db, kind, id, row, user):
    """Samples used by more than one process and plans with more than one process."""
    from .experiments import visible
    result = {'shared_samples': [], 'shared_plans': []}
    links = table('process_samples')
    if kind in ('batches', 'samples', 'processes'):
        q = (select(links.c.sample_id, func.count(func.distinct(links.c.process_id)).label('n'))
             .group_by(links.c.sample_id)
             .having(func.count(func.distinct(links.c.process_id)) > 1))
        if kind == 'samples':
            q = q.where(links.c.sample_id == id)
        elif kind == 'batches':
            q = q.where(links.c.sample_id.in_(select(table('samples').c.sample_id).where(table('samples').c.batch_id == id)))
        else:
            q = q.where(links.c.sample_id.in_(select(links.c.sample_id).where(links.c.process_id == id)))
        if user['role'] != 'admin':
            q = q.where(links.c.sample_id.in_(select(table('samples').c.sample_id).where(record_scope('samples', user))))
            q = q.where(links.c.process_id.in_(select(table('processes').c.process_id).where(visible('processes', user))))
        result['shared_samples'] = [{'sample_id': int(row_[0]), 'process_count': int(row_[1])} for row_ in db.execute(q)]
    p = table('processes')
    plan_id = row.get('plan_id') if kind == 'processes' else (id if kind == 'plans' else None)
    if kind == 'batches':
        q = select(p.c.plan_id, func.count().label('n')).where(p.c.plan_id.isnot(None), p.c.batch_id == id).group_by(p.c.plan_id).having(func.count() > 1)
        if user['role'] != 'admin':
            q = q.where(p.c.process_id.in_(select(p.c.process_id).where(visible('processes', user))))
        if user['role'] != 'admin':
            q = q.where(p.c.plan_id.in_(select(table('experiment_plans').c.plan_id).where(visible('plans', user))))
        result['shared_plans'] = [{'plan_id': int(row_[0]), 'process_count': int(row_[1])} for row_ in db.execute(q)]
    elif plan_id is not None:
        q = select(func.count()).select_from(p).where(p.c.plan_id == plan_id)
        if user['role'] != 'admin':
            q = q.where(p.c.process_id.in_(select(p.c.process_id).where(visible('processes', user))))
        count = db.scalar(q) or 0
        if count > 1 and (user['role'] == 'admin' or db.scalar(select(table('experiment_plans').c.plan_id).where(table('experiment_plans').c.plan_id == plan_id, visible('plans', user)))):
            result['shared_plans'] = [{'plan_id': int(plan_id), 'process_count': int(count)}]
    return result


def table_groups(db, kind, name, pk, id, user):
    target = table(name)
    groups = []
    listed = set()
    for table_name in GROUPS[kind]:
        candidate = table(table_name)
        preds = predicates_for(candidate, target, kind, pk, id)
        if not preds:
            continue
        listed.add(table_name)
        visible, restricted = scoped_count(db, table_name, or_(*preds), user)
        groups.append({'type': table_name, 'label': LABELS.get(table_name, table_name),
                       'count': visible, 'restricted': restricted,
                       'deletable_hint': visible == 0 and not restricted})
    # Anything else that references the record must still be visible as a group.
    for candidate in metadata().tables.values():
        if candidate.name in listed or candidate.name == 'audit_log':
            continue
        preds = predicates_for(candidate, target, kind, pk, id)
        if not preds:
            continue
        visible, restricted = scoped_count(db, candidate.name, or_(*preds), user)
        if visible or restricted:
            groups.append({'type': candidate.name, 'label': LABELS.get(candidate.name, '其他关联记录'),
                           'count': visible, 'restricted': restricted,
                           'deletable_hint': visible == 0 and not restricted})
    return groups


def sample_groups(db, id, user):
    s = table('samples')
    groups = []
    listed = {'audit_log'}
    for group_type, label, table_names, fk in SAMPLE_GROUPS:
        count, restricted = 0, False
        for table_name in table_names:
            candidate = table(table_name)
            if fk:
                predicate = candidate.c[fk] == id
            else:
                # A sample group counts only its own direct references. Other
                # sample rows are never counted here: child samples have their
                # own group, and the parent link is not a dependency of a child.
                predicate = or_(*predicates_for(candidate, s, 'samples', s.c.sample_id, id,
                                                skip=('parent_sample_id',)))
            visible, group_restricted = scoped_count(db, table_name, predicate, user)
            count += visible
            restricted = restricted or group_restricted
            listed.add(table_name)
        groups.append({'type': group_type, 'label': label, 'count': count,
                       'restricted': restricted, 'deletable_hint': count == 0 and not restricted})
    # Any other scientific reference (source files, derived results, datasets,
    # attachments, issues, ...) must be surfaced; unknown scope stays hidden.
    for candidate in metadata().tables.values():
        if candidate.name in listed or candidate.name == 'audit_log':
            continue
        preds = predicates_for(candidate, s, 'samples', s.c.sample_id, id)
        if not preds:
            continue
        visible, restricted = scoped_count(db, candidate.name, or_(*preds), user)
        if visible or restricted:
            groups.append({'type': candidate.name, 'label': LABELS.get(candidate.name, '其他关联记录'),
                           'count': visible, 'restricted': restricted,
                           'deletable_hint': visible == 0 and not restricted})
    return groups


def batch_sample_counts(db, id, user):
    s = table('samples')
    base = select(s).where(s.c.batch_id == id)
    total = counted(db, s, s.c.batch_id == id)
    visible_total = total if user['role'] == 'admin' else counted(db, s, and_(s.c.batch_id == id, record_scope('samples', user)))
    available_predicate = and_(s.c.batch_id == id, s.c.status == 'available', s.c.voided_at.is_(None))
    if user['role'] != 'admin':
        available_predicate = and_(available_predicate, record_scope('samples', user))
    available = counted(db, s, available_predicate)
    candidates = []
    pool = list(db.execute(base.where(s.c.status == 'available', s.c.voided_at.is_(None),
                                       s.c.archived_at.is_(None)).order_by(s.c.sample_id)).mappings())
    pool = [sample for sample in pool
            if user['role'] == 'admin' or sample['owner_user_id'] == user['user_id']]
    blocked = blocked_sample_ids(db, [sample['sample_id'] for sample in pool])
    for sample in pool:
        if sample['sample_id'] not in blocked and sample_unused(db, sample):
            candidates.append({'sample_id': sample['sample_id'], 'sample_code': sample['sample_code'], 'row_version': sample['row_version']})
    return {'total': visible_total, 'available': available,
            'unused_candidates': len(candidates), 'candidates': candidates}


def delete_allowed_base(db, kind, id, row, user):
    """Read-only probe of the exact protection used by the real delete endpoints.

    Returns False when any FK or polymorphic reference exists, when a process
    carries scientific history, or when a voided sample must be retained.
    """
    if row.get('voided_at') is not None or is_archived(kind, row):
        return False
    if kind == 'plans' and row['status'] != 'draft': return False
    if kind == 'processes' and (any(row.get(k) is not None for k in (
            'started_at', 'ended_at', 'r1_temp_c', 'r2_temp_c', 'n2_flow_sccm',
            'o3_pre_cycles', 'o3_pre_duration_s', 'full_ale_cycles', 'hf_tma_repeats'))
            or row.get('log_status') not in ('unknown', 'ok')): return False
    if kind == 'batches' and row.get('status') != 'active': return False
    if kind == 'samples' and row.get('status') != 'available': return False
    if kind == 'processes':
        from .experiments import immutable_history
        try:
            immutable_history(db, id)
        except HTTPException:
            return False
    name, pk, _, _, _ = kind_meta(kind)
    target = table(name)
    for candidate in metadata().tables.values():
        if candidate.name == 'audit_log':
            continue
        preds = predicates_for(candidate, target, name, pk, id)
        if preds and counted(db, candidate, or_(*preds)):
            return False
    return True


def available_actions(kind, row, result, user):
    actions = []
    if user['role'] == 'viewer':
        return actions
    if row.get('voided_at') is not None:
        # A voided sample is retained for traceability; it can be neither
        # archived nor voided again, and delete is always blocked.
        return actions
    if is_archived(kind, row):
        if can_manage(user, row, kind) and (kind != 'plans' or row.get('archive_previous_status')) and row.get('voided_at') is None:
            actions.append('restore')
        return actions
    actions.append('archive')
    if kind == 'batches':
        actions.append('archive_with_dependents')
    if result['void_allowed']:
        actions.append('void')
    if result['delete_permitted']:
        actions.append('delete')
    return actions


def impact(db, kind, id, user):
    name, pk, _, code_key, noun = kind_meta(kind)
    row = parent(db, kind, id, user)
    result = {
        'kind': kind, 'id': id, 'code': row.get(code_key), 'row_version': row.get('row_version'),
        'status': status_summary(kind, row), 'archived': is_archived(kind, row),
        'can_restore': user['role'] != 'viewer' and is_archived(kind, row) and can_manage(user, row, kind)
                       and row.get('voided_at') is None and (kind != 'plans' or bool(row.get('archive_previous_status'))),
        'groups': [], 'restricted': False, 'restricted_flag': None,
        'shared': shared_info(db, kind, id, row, user),
    }
    if kind == 'samples':
        result['groups'] = sample_groups(db, id, user)
        result['sample_counts'] = None
    else:
        result['groups'] = table_groups(db, kind, name, pk, id, user)
        result['sample_counts'] = batch_sample_counts(db, id, user) if kind == 'batches' else None
    result['restricted'] = any(group['restricted'] for group in result['groups'])
    if result['restricted']:
        result['restricted_flag'] = PROTECTED_DEPENDENCIES
    result['dependencies_total_visible'] = sum(group['count'] for group in result['groups'])
    # Hidden-only groups have no public type/name/count; restricted is the sole
    # signal. Partially visible groups disclose only the caller's visible rows.
    result['groups'] = [{**g, 'restricted': False} for g in result['groups'] if g['count'] or not g['restricted']]
    # Only admins can delete; for everyone else the preview reports the same
    # dependency truth but never advertises a delete action they cannot use.
    result['delete_blocked'] = delete_allowed_base(db, kind, id, row, user) is False
    result['delete_allowed'] = not result['delete_blocked'] and not result['restricted']
    # Batches/samples remain administrator-only for hard delete; plans and
    # processes may be removed by their owner, matching the existing DELETE
    # routes, but only when the dependency probe proves they are unused.
    result['delete_permitted'] = result['delete_allowed'] and (
        user['role'] == 'admin' or
        (kind in ('plans', 'processes') and owner_id(kind, row) == user['user_id']))
    result['void_allowed'] = void_allowed(db, kind, id, row, user)
    result['actions'] = available_actions(kind, row, result, user)
    result['preview_token'] = preview_token(result, user)
    return result


@router.get('/lifecycle/{kind}/{id}/impact')
def lifecycle_impact(kind: str, id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    kind_meta(kind)
    return envelope(request, impact(db, kind, id, user))


def audit_lifecycle(db, user, entity, id, action, reason, old, new):
    """One audit row per lifecycle action with the prior state and reason.

    The row is written with the request transaction; a failed action leaves no
    audit entry and a successful one always has its reason recorded.
    """
    at = dbnow()
    db.execute(table('audit_log').insert().values(
        user_id=user['user_id'], action='update', entity_type=entity, entity_id=id,
        field_name='lifecycle',
        old_value=json.dumps(old, ensure_ascii=False, default=str),
        new_value=json.dumps({**new, 'lifecycle_action': action, 'reason': reason},
                             ensure_ascii=False, default=str),
        occurred_at=at))


def check_version(row, expected):
    if row['row_version'] != expected:
        fail(409, '记录已变更，请刷新后重试')


def apply_archive(db, kind, id, row, user, reason):
    name, pk, entity, _, _ = kind_meta(kind)
    t = table(name)
    at = dbnow()
    if kind == 'plans':
        if row['status'] == 'archived':
            return reopen(db, kind, id, user)
        values = {'status': 'archived', 'archive_previous_status': row['status'], 'row_version': row['row_version'] + 1}
        old = {'status': row['status']}
    else:
        if row.get('archived_at') is not None:
            return reopen(db, kind, id, user)
        values = {'archived_at': at, 'row_version': row['row_version'] + 1}
        old = {'archived_at': _temporal(row.get('archived_at'))}
        if kind == 'samples':
            values['archived_by_user_id'] = user['user_id']
    changed = db.execute(t.update().where(t.c[pk] == id, t.c.row_version == row['row_version']).values(**values))
    if changed.rowcount != 1:
        fail(409, '记录已变更，请刷新后重试')
    audit_lifecycle(db, user, entity, id, 'archive', reason, old, values)
    return reopen(db, kind, id, user)


def apply_restore(db, kind, id, row, user, reason):
    name, pk, entity, _, _ = kind_meta(kind)
    if row.get('voided_at') is not None:
        fail(409, '已作废记录不能恢复；作废记录必须保留')
    if not is_archived(kind, row):
        return reopen(db, kind, id, user)
    t = table(name)
    if kind == 'plans':
        if not row.get('archive_previous_status'):
            fail(409, '历史归档缺少原状态证据，不能自动恢复')
        values = {'status': row['archive_previous_status'], 'archive_previous_status': None, 'row_version': row['row_version'] + 1}
        old = {'status': row['status']}
    else:
        values = {'archived_at': None, 'row_version': row['row_version'] + 1}
        old = {'archived_at': _temporal(row.get('archived_at'))}
        if kind == 'samples':
            values['archived_by_user_id'] = None
    changed = db.execute(t.update().where(t.c[pk] == id, t.c.row_version == row['row_version']).values(**values))
    if changed.rowcount != 1:
        fail(409, '记录已变更，请刷新后重试')
    audit_lifecycle(db, user, entity, id, 'restore', reason, old, values)
    return reopen(db, kind, id, user)


def archive_with_dependents(db, kind, id, row, body, user):
    """Archive a batch and only the explicitly listed, unused samples of that batch."""
    name, pk, entity, _, _ = kind_meta(kind)
    if kind != 'batches':
        fail(422, '仅批次支持连同未使用样品一起归档')
    sample_ids = sorted(set(body.include_sample_ids or []))
    s = table('samples')
    query = select(s).where(s.c.sample_id.in_(sample_ids), s.c.batch_id == id)
    if user['role'] != 'admin':
        # Hidden samples must not be confirmed or named; they simply fail closed.
        query = query.where(record_scope('samples', user))
    selected = {r['sample_id']: dict(r) for r in db.execute(query.order_by(s.c.sample_id).with_for_update()).mappings()} if sample_ids else {}
    blocking, pending = [], []
    for sample_id in sample_ids:
        sample = selected.get(sample_id)
        if sample is None:
            # Echo the supplied ID only; never confirm whether a hidden record exists.
            blocking.append({'sample_id': sample_id, 'sample_code': None})
            continue
        if user['role'] != 'admin' and sample.get('owner_user_id') != user['user_id']:
            blocking.append({'sample_id': sample_id, 'sample_code': sample['sample_code']})
            continue
        if body.sample_versions.get(sample_id) != sample['row_version']:
            fail(409, '所选样品已变更，请重载预览')
        if not sample_unused(db, sample):
            fail(409, '所选样品已使用或存在关联，不能批量归档')
        if sample.get('voided_at') is not None:
            blocking.append({'sample_id': sample_id, 'sample_code': sample['sample_code']})
            continue
        if sample.get('archived_at') is not None:
            continue  # idempotent: already archived, nothing to do
        pending.append(sample)
    unsafe = blocked_sample_ids(db, [sample['sample_id'] for sample in pending])
    archivable = []
    for sample in pending:
        if sample['sample_id'] in unsafe:
            blocking.append({'sample_id': sample['sample_id'], 'sample_code': sample['sample_code']})
        else:
            archivable.append(sample)
    if blocking:
        codes = [item['sample_code'] for item in blocking if item['sample_code']]
        detail = '、'.join(codes) if codes else '存在不可归档的样品'
        fail(409, '以下样品存在科研关联或不可归档，不能随批次归档：' + detail)
    at = dbnow()
    for sample in archivable:
        changed = db.execute(s.update().where(s.c.sample_id == sample['sample_id'], s.c.row_version == sample['row_version'])
                             .values(archived_at=at, archived_by_user_id=user['user_id'], row_version=sample['row_version'] + 1))
        if changed.rowcount != 1:
            fail(409, '记录已变更，请刷新后重试')
        audit_lifecycle(db, user, 'sample', sample['sample_id'], 'archive_with_dependents', body.reason,
                        {'archived_at': None}, {'archived_at': at})
    t = table(name)
    changed = db.execute(t.update().where(t.c[pk] == id, t.c.row_version == row['row_version'])
                         .values(archived_at=at, row_version=row['row_version'] + 1))
    if changed.rowcount != 1:
        fail(409, '记录已变更，请刷新后重试')
    audit_lifecycle(db, user, entity, id, 'archive_with_dependents', body.reason,
                    {'archived_at': None},
                    {'archived_at': at, 'sample_ids': [sample['sample_id'] for sample in archivable]})
    return reopen(db, kind, id, user)


def sample_unused(db, row):
    try:
        protect_sample_void(db, row)
        return True
    except HTTPException:
        return False


def void_allowed(db, kind, id, row, user):
    if row.get('voided_at') or is_archived(kind, row): return False
    if kind == 'samples': return sample_unused(db, row)
    # A logical void is reserved for a mistaken, unused draft. Archive preserves
    # real work, even where SQL ON DELETE CASCADE would otherwise permit removal.
    return delete_allowed_base(db, kind, id, row, user)


def preview_token(result, user):
    payload = json.dumps({'user_id': user['user_id'], 'role': user['role'], 'impact': result},
                         sort_keys=True, default=str, ensure_ascii=False).encode()
    return hmac.new(jwt_secret().encode(), payload, hashlib.sha256).hexdigest()


def operation_record(db, user, entity, id, operation_id):
    a = table('audit_log')
    for row in db.execute(select(a).where(a.c.entity_type == entity, a.c.entity_id == id,
                        a.c.user_id == user['user_id'], a.c.field_name == 'lifecycle_operation')
                        .order_by(a.c.audit_id.desc())).mappings():
        value = json.loads(row['new_value'])
        if value.get('operation_id') == operation_id: return value
    return None


@router.post('/lifecycle/{kind}/{id}/apply')
def lifecycle_apply(kind: str, id: int, body: S.LifecycleApply, request: Request,
                    user=Depends(writer), db=Depends(get_db)):
    name, pk, entity, code_key, noun = kind_meta(kind)
    action = body.action
    # A successful request whose response was lost can be replayed with its exact
    # operation ID and payload. The parent lock serializes simultaneous retries.
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    try:
        row = parent(db, kind, id, user, lock=True)
    except HTTPException as exc:
        saved = operation_record(db, user, entity, id, body.operation_id) if exc.status_code == 404 else None
        if not saved or saved['action'] != 'delete': raise
        if saved['fingerprint'] != fingerprint: fail(409, '操作标识已用于其他请求')
        return envelope(request, saved['result'])
    saved = operation_record(db, user, entity, id, body.operation_id)
    if saved:
        if saved['fingerprint'] != fingerprint: fail(409, '操作标识已用于其他请求')
        return envelope(request, saved['result'])
    check_version(row, body.expected_row_version)
    # Hold selected sample locks in ID order before recalculating impact. All
    # association writers use these same sample locks.
    if action == 'archive_with_dependents':
        if kind != 'batches': fail(422, '仅批次支持所选样品归档')
        for sid in sorted(set(body.include_sample_ids or [])):
            sample = parent(db, 'samples', sid, user, lock=True)
            if sample['batch_id'] != id: fail(409, '所选样品不属于此批次')
    elif body.include_sample_ids or body.sample_versions:
        fail(422, '此操作不接受样品选择')
    current = impact(db, kind, id, user)
    if not hmac.compare_digest(body.preview_token, current['preview_token']):
        fail(409, '影响预览已变化，请重载核对后重试')
    if action not in current['actions']: fail(409, '当前状态或关联不允许此操作')
    if action == 'void' and not body.reason: fail(422, '作废必须填写原因')
    if action == 'delete':
        # Never cascade through scientific children. The sole receipt of a proven
        # unused sample is retained as evidence by choosing void instead.
        t = table(name)
        changed = db.execute(t.delete().where(t.c[pk] == id, t.c.row_version == row['row_version']))
        if changed.rowcount != 1: fail(409, '记录已变更')
        result = {pk: id, code_key: row[code_key], 'deleted': True}
        audit_lifecycle(db, user, entity, id, action, body.reason, row, result)
    elif action == 'void':
        if kind == 'samples':
            void_sample(id, S.SampleVoid(expected_row_version=body.expected_row_version, reason=body.reason), request, user, db)
        else:
            values = dict(voided_at=dbnow(), void_reason=body.reason, voided_by_user_id=user['user_id'], row_version=row['row_version'] + 1)
            t = table(name)
            changed = db.execute(t.update().where(t.c[pk] == id, t.c.row_version == row['row_version']).values(**values))
            if changed.rowcount != 1: fail(409, '记录已变更')
            audit_lifecycle(db, user, entity, id, action, body.reason, status_summary(kind, row), values)
        result = serialize_record(reopen(db, kind, id, user))
    elif action == 'archive':
        result = serialize_record(apply_archive(db, kind, id, row, user, body.reason))
    elif action == 'archive_with_dependents':
        if not body.include_sample_ids: fail(422, '请明确选择要归档的未使用样品')
        result = serialize_record(archive_with_dependents(db, kind, id, row, body, user))
    else:
        result = serialize_record(apply_restore(db, kind, id, row, user, body.reason))
    db.execute(table('audit_log').insert().values(user_id=user['user_id'], action='update',
        entity_type=entity, entity_id=id, field_name='lifecycle_operation',
        new_value=json.dumps({'operation_id': body.operation_id, 'fingerprint': fingerprint,
                              'action': action, 'result': result}, ensure_ascii=False, default=str), occurred_at=dbnow()))
    return envelope(request, result)
