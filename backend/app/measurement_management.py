"""Scoped measurement, original-file, and instrument-dataset management."""
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, or_, select, true

from .common import audit, envelope, fail, page_result
from .db import get_db, table
from .experiments import fetch as experiment, visible as experiment_scope
from .records import fetch as record, ordered, scope as record_scope
from .security import current_user, writer
from .data_visibility import project
from .original_storage import read_verified, storage_key

router = APIRouter(prefix='/api/v1', tags=['Measurements'])
Stage = Literal['initial', 'after_o2_plasma', 'after_o3_pre', 'after_ale',
                'after_hf_only', 'after_o3_only', 'intermediate', 'final', 'other']
Quality = Literal['ok', 'suspect', 'abnormal', 'excluded']
Positive = Annotated[int, Field(gt=0, strict=True)]


class QualityUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_row_version: Positive
    quality_flag: Quality = 'ok'
    quality_note: Annotated[str, Field(max_length=20000)] | None = None

    @model_validator(mode='after')
    def has_change(self):
        if not self.model_fields_set.intersection({'quality_flag', 'quality_note'}):
            raise ValueError('Supply quality_flag or quality_note')
        return self


class Supersede(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    replacement_measurement_id: Positive
    expected_row_version: Positive
    expected_replacement_row_version: Positive
    reason: Annotated[str, Field(min_length=1, max_length=20000)]

    @field_validator('reason')
    @classmethod
    def reason_required(cls, value):
        if not value.strip():
            raise ValueError('A supersession reason is required')
        return value.strip()


def sample_ids(user):
    s = table('samples')
    return select(s.c.sample_id).where(record_scope('samples', user))


def measurement_scope(user):
    return table('measurements').c.sample_id.in_(sample_ids(user))


def measurement(db, id, user, lock=False):
    t = table('measurements')
    q = select(t).where(t.c.measurement_id == id, measurement_scope(user))
    row = db.execute(q.with_for_update() if lock else q).mappings().first()
    if row is None:
        fail(404)
    return {**row, 'is_current': bool(row['is_current'])}


def points(db, id):
    t = table('measurement_points')
    return [{**r, 'is_outlier': bool(r['is_outlier'])} for r in db.execute(
        select(t).where(t.c.measurement_id == id).order_by(t.c.point_no, t.c.point_id)
    ).mappings()]


def detail(db, id, user):
    row = named_measurement(db,measurement(db, id, user),user)
    row['points'] = points(db, id)
    return row


def named_measurement(db,row,user):
    # Resolve labels only after hidden associations have been removed.
    result=project(db,row,user,'measurement')
    s,p,pl,model=table('samples'),table('processes'),table('experiment_plans'),table('optical_models')
    result['sample_code']=db.scalar(select(s.c.sample_code).where(s.c.sample_id==result['sample_id'],record_scope('samples',user)))
    result['process_code']=None;result['plan_title']=None
    if result.get('process_id'):
        run=db.execute(select(p.c.process_code,pl.c.title).outerjoin(pl,p.c.plan_id==pl.c.plan_id).where(p.c.process_id==result['process_id'],experiment_scope('processes',user))).first()
        if run:result['process_code'],result['plan_title']=run
    result['optical_model_name']=db.scalar(select(model.c.model_name).where(model.c.model_id==result['optical_model_id'])) if result.get('optical_model_id') else None
    return result


@router.get('/measurements')
def list_measurements(request: Request, page: int = Query(1, ge=1),
                      size: int = Query(20, ge=1, le=200), sort: str | None = None,
                      sample_id: int | None = Query(None, gt=0),
                      process_id: int | None = Query(None, gt=0), stage: Stage | None = None,
                      current: bool | None = None, quality: Quality | None = None,
                      is_current: bool | None = None, quality_flag: Quality | None = None,
                      user=Depends(current_user), db=Depends(get_db)):
    t = table('measurements')
    q = select(t).where(measurement_scope(user))
    for key, value in [('sample_id', sample_id), ('process_id', process_id), ('stage', stage),
                       ('is_current', current), ('quality_flag', quality),
                       ('is_current', is_current), ('quality_flag', quality_flag)]:
        if value is not None:
            q = q.where(t.c[key] == value)
    q = ordered(q, t, sort, '-created_at', {'measurement_id', 'measurement_code', 'sample_id',
                'process_id', 'stage', 'stage_seq', 'measured_at', 'created_at', 'updated_at',
                'quality_flag', 'thickness_mean_nm'})
    rows, meta = page_result(db, q, page, size)
    for row in rows:
        row['is_current'] = bool(row['is_current'])
    rows = [named_measurement(db,row,user) for row in rows]
    return envelope(request, rows, meta)


@router.get('/measurements/{id}')
def get_measurement(id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    return envelope(request, detail(db, id, user))


@router.get('/measurements/{id}/points')
def get_points(id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    measurement(db, id, user)
    return envelope(request, points(db, id))


def lock_measurements(db, ids, user):
    """Discover first; acquire all plans, all processes, sample, then measurements.

    Recheck parent associations after locking so a concurrent reparent cannot
    silently bypass the hierarchy. The sample lock serializes supersession chains.
    """
    initial = {id: measurement(db, id, user) for id in sorted(set(ids))}
    process_ids = sorted({r['process_id'] for r in initial.values() if r['process_id'] is not None})
    processes = {id: experiment(db, 'processes', id, user) for id in process_ids}
    plans = sorted({r['plan_id'] for r in processes.values() if r['plan_id'] is not None})
    for id in plans:
        experiment(db, 'plans', id, user, True)
    process_table = table('processes')
    for id in process_ids:
        # Plans have already been acquired as a group. Avoid rediscovering and
        # locking a new plan after taking the first process lock.
        locked = db.execute(select(process_table).where(
            process_table.c.process_id == id, experiment_scope('processes', user)
        ).with_for_update()).mappings().first()
        if locked is None:
            fail(404)
        if locked['plan_id'] != processes[id]['plan_id']:
            fail(409, 'Run plan was changed; reload and retry')
    for id in sorted({r['sample_id'] for r in initial.values()}):
        record(db, 'samples', id, user, True)
    result = {}
    for id, before in initial.items():
        row = measurement(db, id, user, True)
        if any(row[key] != before[key] for key in ('sample_id', 'process_id')):
            fail(409, 'Measurement associations changed; reload and retry')
        result[id] = row
    return result


def check_version(row, expected):
    if row['row_version'] != expected:
        fail(409, 'Record was changed; reload and retry')


def invalidate(db, ids):
    t = table('derived_results')
    db.execute(t.update().where(or_(t.c.before_measurement_id.in_(ids),
                                   t.c.after_measurement_id.in_(ids))).values(is_valid=False))


def update_measurement(db, row, values):
    t = table('measurements')
    changed = db.execute(t.update().where(t.c.measurement_id == row['measurement_id'],
                        t.c.row_version == row['row_version']).values(
                            **values, row_version=row['row_version'] + 1))
    if changed.rowcount != 1:
        fail(409, 'Record was changed; reload and retry')


@router.patch('/measurements/{id}')
def patch_measurement(id: int, body: QualityUpdate, request: Request,
                      user=Depends(writer), db=Depends(get_db)):
    row = lock_measurements(db, [id], user)[id]
    check_version(row, body.expected_row_version)
    values = body.model_dump(exclude_unset=True, exclude={'expected_row_version'})
    update_measurement(db, row, values)
    if any(row[k] != v for k, v in values.items()):
        invalidate(db, [id])
    audit(db, user['user_id'], 'update', 'measurement', id)
    return envelope(request, detail(db, id, user))


@router.post('/measurements/{id}/supersede')
def supersede_measurement(id: int, body: Supersede, request: Request,
                          user=Depends(writer), db=Depends(get_db)):
    replacement_id = body.replacement_measurement_id
    if id == replacement_id:
        fail(422, 'A measurement cannot replace itself')
    rows = lock_measurements(db, [id, replacement_id], user)
    old, replacement = rows[id], rows[replacement_id]
    check_version(old, body.expected_row_version)
    check_version(replacement, body.expected_replacement_row_version)
    if old['sample_id'] != replacement['sample_id']:
        fail(422, 'Replacement must belong to the same sample')
    if not old['is_current'] or not replacement['is_current']:
        fail(409, 'Both measurements must currently be current')
    if replacement['supersedes_measurement_id'] is not None:
        fail(409, 'Replacement already supersedes a measurement')
    t = table('measurements')
    if db.execute(select(t.c.measurement_id).where(
            t.c.supersedes_measurement_id.in_([id, replacement_id])).limit(1)).first():
        fail(409, 'A measurement has already been superseded')
    # Follow the retained history as well: malformed legacy chains must not form a cycle.
    seen = {replacement_id}
    cursor = old
    while cursor is not None:
        mid = cursor['measurement_id']
        if mid in seen:
            fail(409, 'Supersession would create or extend a cycle')
        seen.add(mid)
        prior = cursor['supersedes_measurement_id']
        cursor = db.execute(select(t.c.measurement_id, t.c.supersedes_measurement_id).where(
            t.c.measurement_id == prior)).mappings().first() if prior is not None else None
    update_measurement(db, old, {'is_current': False, 'supersede_reason': body.reason})
    update_measurement(db, replacement, {'supersedes_measurement_id': id})
    invalidate(db, [id, replacement_id])
    for mid in (id, replacement_id):
        audit(db, user['user_id'], 'update', 'measurement', mid)
    result = detail(db, id, user)
    result['replacement'] = project(db, measurement(db, replacement_id, user), user, 'measurement')
    return envelope(request, result)


def occurrence_scope(user):
    o = table('source_file_occurrences')
    if user['role'] == 'admin':
        return true()
    return or_(o.c.owner_user_id == user['user_id'], o.c.sample_id.in_(sample_ids(user)))


def dataset_scope(user):
    t = table('instrument_datasets')
    if user['role'] == 'admin':
        return true()
    return or_(t.c.sample_id.in_(sample_ids(user)),
               and_(t.c.sample_id.is_(None), t.c.operator_user_id == user['user_id']))


def source_scope(user):
    f, o, m, p, d = (table(n) for n in ('source_files', 'source_file_occurrences',
                                       'measurements', 'measurement_points', 'instrument_datasets'))
    if user['role'] == 'admin':
        return true()
    return or_(
        select(o.c.occurrence_id).where(o.c.source_file_id == f.c.file_id, occurrence_scope(user)).exists(),
        f.c.sample_id.in_(sample_ids(user)),
        select(m.c.measurement_id).where(m.c.source_file_id == f.c.file_id, measurement_scope(user)).exists(),
        select(p.c.point_id).join(m, p.c.measurement_id == m.c.measurement_id).where(
            p.c.source_file_id == f.c.file_id, measurement_scope(user)).exists(),
        # Legacy dataset links grant original-file access through sample scope only.
        select(d.c.dataset_id).where(d.c.source_file_id == f.c.file_id,
                                    d.c.sample_id.in_(sample_ids(user))).exists())


def source_columns(user):
    f, o = table('source_files'), table('source_file_occurrences')
    visible_name = select(o.c.filename).where(o.c.source_file_id == f.c.file_id,
                     occurrence_scope(user), true() if user['role'] == 'admin' else o.c.owner_user_id == user['user_id']).order_by(o.c.occurrence_id).limit(1).correlate(f).scalar_subquery()
    has_occurrences = select(o.c.occurrence_id).where(o.c.source_file_id == f.c.file_id).correlate(f).exists()
    # Never expose the first uploader's global name/path/notes for a deduplicated file.
    from sqlalchemy import case, func
    safe_name = func.coalesce(visible_name, case((~has_occurrences, f.c.file_name),
                                              else_=f.c.file_sha256))
    return [f.c.file_id, f.c.file_sha256, safe_name.label('file_name'), f.c.file_ext,
            f.c.size_bytes, f.c.is_readonly, f.c.created_at]


def source(db, id, user):
    f = table('source_files')
    row = db.execute(select(*source_columns(user)).where(f.c.file_id == id,
                                                       source_scope(user))).mappings().first()
    if row is None:
        fail(404)
    return {**row, 'is_readonly': bool(row['is_readonly']),
            'storage_key': storage_key(row['file_sha256'])}


@router.get('/source-files')
def list_sources(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                 sample_id: int | None = Query(None, gt=0), user=Depends(current_user), db=Depends(get_db)):
    f, o, m, p, d = (table(n) for n in ('source_files', 'source_file_occurrences',
                                       'measurements', 'measurement_points', 'instrument_datasets'))
    q = select(*source_columns(user)).where(source_scope(user))
    if sample_id is not None:
        record(db, 'samples', sample_id, user)
        q = q.where(or_(f.c.sample_id == sample_id,
            select(o.c.occurrence_id).where(o.c.source_file_id == f.c.file_id,
                o.c.sample_id == sample_id, occurrence_scope(user)).exists(),
            select(m.c.measurement_id).where(m.c.source_file_id == f.c.file_id,
                m.c.sample_id == sample_id).exists(),
            select(p.c.point_id).join(m, m.c.measurement_id == p.c.measurement_id).where(
                p.c.source_file_id == f.c.file_id, m.c.sample_id == sample_id).exists(),
            select(d.c.dataset_id).where(d.c.source_file_id == f.c.file_id,
                d.c.sample_id == sample_id).exists()))
    rows, meta = page_result(db, q.order_by(f.c.created_at.desc(), f.c.file_id), page, size)
    for row in rows:
        row['is_readonly'] = bool(row['is_readonly'])
    return envelope(request, rows, meta)


@router.get('/source-files/{id}')
def get_source(id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = source(db, id, user)
    o = table('source_file_occurrences')
    row['occurrences'] = [project(db, r, user, 'occurrence') for r in db.execute(select(o).where(
        o.c.source_file_id == id, occurrence_scope(user)).order_by(o.c.occurrence_id)).mappings()]
    return envelope(request, row)


@router.get('/source-files/{id}/content')
def source_content(id: int, user=Depends(current_user), db=Depends(get_db)):
    row = source(db, id, user)
    try:
        content = read_verified(row['file_sha256'])
    except FileNotFoundError:
        fail(404, 'Original content is not available in immutable storage')
    except (ValueError, OSError):
        fail(409, 'Original content failed integrity verification')
    # RFC 5987 encoding prevents CR/LF/header injection and supports original Unicode names.
    filename = row['file_name'].replace('\\', '/').rsplit('/', 1)[-1]
    filename = ''.join(c for c in filename if ord(c) >= 32 and ord(c) != 127) or row['file_sha256']
    return Response(content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


@router.get('/instrument-datasets')
def list_datasets(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                  sample_id: int | None = Query(None, gt=0), process_id: int | None = Query(None, gt=0),
                  instrument_type: Literal['xps', 'rga', 'xrr', 'afm', 'sem', 'sims', 'other'] | None = None,
                  sample_mapping_status: Literal['resolved', 'unresolved', 'ambiguous'] | None = None,
                  user=Depends(current_user), db=Depends(get_db)):
    t = table('instrument_datasets')
    q = select(t).where(dataset_scope(user))
    for key, value in [('sample_id', sample_id), ('process_id', process_id),
                       ('instrument_type', instrument_type), ('sample_mapping_status', sample_mapping_status)]:
        if value is not None:
            q = q.where(t.c[key] == value)
    rows, meta = page_result(db, q.order_by(t.c.created_at.desc(), t.c.dataset_id), page, size)
    return envelope(request, [project(db, r, user, 'dataset') for r in rows], meta)


@router.get('/instrument-datasets/{id}')
def get_dataset(id: int, request: Request, include_channels: bool = False,
                include_datapoints: bool = False, user=Depends(current_user), db=Depends(get_db)):
    t = table('instrument_datasets')
    row = db.execute(select(t).where(t.c.dataset_id == id, dataset_scope(user))).mappings().first()
    if row is None:
        fail(404)
    result = project(db, row, user, 'dataset')
    if include_channels or include_datapoints:
        c = table('instrument_channels')
        channels = [dict(r) for r in db.execute(select(c).where(c.c.dataset_id == id).order_by(
            c.c.channel_id)).mappings()]
        if include_datapoints:
            p = table('instrument_datapoints')
            by_channel = {r['channel_id']: [] for r in channels}
            for point in db.execute(select(p).join(c, c.c.channel_id == p.c.channel_id).where(
                    c.c.dataset_id == id).order_by(p.c.channel_id, p.c.point_index, p.c.datapoint_id)).mappings():
                by_channel[point['channel_id']].append(dict(point))
            for channel in channels:
                channel['datapoints'] = by_channel[channel['channel_id']]
        result['channels'] = channels
    return envelope(request, result)
