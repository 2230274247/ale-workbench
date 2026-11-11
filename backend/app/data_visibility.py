"""Visibility of associated records and response-only minimum projections."""
from sqlalchemy import or_, select, true
from .db import table
from .records import scope
from .experiments import visible
from .common import fail


def model_scope(user):
    m, b = table('optical_models'), table('batches')
    if user['role'] == 'admin':
        return true()
    return or_(m.c.applicable_batch_id.is_(None), m.c.applicable_batch_id.in_(
        select(b.c.batch_id).where(scope('batches', user))))


def optical_model(db, id, user, sample=None):
    m = table('optical_models')
    row = db.execute(select(m).where(m.c.model_id == id, model_scope(user))).mappings().first()
    if row is None:
        fail(422, 'Optical model does not exist or is not visible')
    if sample is not None and row['applicable_batch_id'] not in (None, sample['batch_id']):
        fail(422, 'Optical model does not apply to the selected sample batch')
    return dict(row)


def reference_visible(db, kind, id, user):
    if id is None or user['role'] == 'admin':
        return True
    names = {'process': ('processes', 'process_id'), 'sample': ('samples', 'sample_id'),
             'batch': ('batches', 'batch_id'), 'model': ('optical_models', 'model_id'),
             'measurement': ('measurements', 'measurement_id'), 'item': ('import_items', 'item_id')}
    name, key = names[kind]; t = table(name)
    if kind == 'process':
        condition = visible('processes', user)
    elif kind in ('sample', 'batch'):
        condition = scope(name, user)
    elif kind == 'model':
        condition = model_scope(user)
    elif kind == 'measurement':
        s = table('samples')
        condition = t.c.sample_id.in_(select(s.c.sample_id).where(scope('samples', user)))
    else:
        j = table('import_jobs')
        condition = t.c.job_id.in_(select(j.c.job_id).where(j.c.owner_user_id == user['user_id']))
    return db.execute(select(t.c[key]).where(t.c[key] == id, condition)).first() is not None


def project(db, row, user, kind):
    """Copy, never mutate scientific rows used for writes or fingerprints."""
    result = dict(row)
    if user['role'] == 'admin':
        return result
    hidden = set()
    refs = {'process_id': 'process', 'measurement_id': 'measurement',
            'supersedes_measurement_id': 'measurement', 'sample_id': 'sample',
            'batch_id': 'batch', 'optical_model_id': 'model', 'import_item_id': 'item'}
    for field, refkind in refs.items():
        if result.get(field) is not None and not reference_visible(db, refkind, result[field], user):
            result[field] = None
            hidden.add(field)
    if kind == 'occurrence':
        if row['owner_user_id'] != user['user_id']:
            for field in ('import_item_id', 'owner_user_id', 'filename', 'notes'):
                result[field] = None
        return result
    if 'operator_user_id' in result and result['operator_user_id'] != user['user_id']:
        result['operator_user_id'] = None
    if 'process_id' in hidden and 'cumulative_cycles' in result:
        result['cumulative_cycles'] = None
    if hidden:
        for field in ('provenance', 'import_locator', 'supersede_reason', 'quality_note',
                      'acquisition_params', 'mapping_note', 'external_ref', 'title'):
            if field in result:
                result[field] = None
    return result


def project_import_item(db, row, user):
    """Hide saved association context after access changes, without rewriting history."""
    result = dict(row)
    confirmation = result.get('confirmation') or {}
    refs = {'sample_id': 'sample', 'process_id': 'process',
            'optical_model_id': 'model', 'pair_measurement_id': 'measurement'}
    hidden = any(confirmation.get(field) is not None and
                 not reference_visible(db, kind, confirmation[field], user)
                 for field, kind in refs.items())
    saved_result = result.get('result') or {}
    hidden = hidden or any(not reference_visible(db, 'measurement', id, user)
                           for id in saved_result.get('measurement_ids', []))
    if hidden:
        # Free text and warnings may describe the revoked associations as well.
        result['confirmation'] = None
        result['result'] = None
    return result


def require_snapshot_visibility(db, note, user):
    """Historical dependencies must still be readable before any snapshot is returned."""
    refs = {'id': 'measurement', 'sample_id': 'sample', 'process_id': 'process',
            'optical_model_id': 'model', 'import_item_id': 'item'}
    sources = list(note.get('sources', [])) + list(note['request']['sources'])
    for source in sources:
        for field, kind in refs.items():
            id = source.get(field)
            if field == 'id' and source.get('kind') == 'import_item':
                kind = 'item'
            if id is not None and not reference_visible(db, kind, id, user):
                fail(404)
        for dependency, fields in (('sample_dependency', {'sample_id': 'sample', 'batch_id': 'batch'}),
                                   ('recorded_conditions', {'process_id': 'process'}),
                                   ('optical_model', {'model_id': 'model', 'applicable_batch_id': 'batch'})):
            for field, kind in fields.items():
                id = (source.get(dependency) or {}).get(field)
                if id is not None and not reference_visible(db, kind, id, user):
                    fail(404)
