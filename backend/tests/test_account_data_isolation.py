"""Account isolation against real MySQL; conftest rolls back every outer transaction."""
import json
import sys
import pytest
from sqlalchemy import MetaData, select
from app import db as database
from app.db import table
from app.imports import suggestions
from test_phase3_imports import originals, sample, process, unique, workbook, choice
from test_phase3_management import occurrence



@pytest.fixture
def db(monkeypatch):
    """Owner-only regression gate for the real pre-0013 schema; never apply DDL."""
    original = database.metadata
    try:
        schema = original()
    except database.MigrationRequired as exc:
        if '0013_account_purpose.sql' not in str(exc):
            raise
        schema = MetaData()
        schema.reflect(bind=database.engine(), views=False)
        for name, columns in {
            'users': ('user_id', 'token_version'),
            'auth_sessions': ('session_id', 'revoked_at'),
            'batches': ('owner_user_id',), 'samples': ('owner_user_id', 'batch_id'),
            'measurements': ('sample_id', 'optical_model_id', 'provenance'),
            'import_items': ('confirmation', 'result'),
            'import_confirmations': ('confirmation_hash', 'result'),
            'source_file_occurrences': ('owner_user_id', 'import_item_id'),
        }.items():
            assert name in schema.tables and all(c in schema.tables[name].c for c in columns), name
        for module in tuple(sys.modules.values()):
            if module is not None and getattr(module, '__name__', '').startswith('app.'):
                if getattr(module, 'metadata', None) is original:
                    monkeypatch.setattr(module, 'metadata', lambda: schema)
    connection = database.engine().connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        try:
            assert transaction.is_active, 'A request escaped the rollback-only transaction'
        finally:
            transaction.rollback()
            connection.close()


def get(client, actors, path, role='operator', status=200):
    r = client.get('/api/v1'+path, headers=actors[role]['headers'])
    assert r.status_code == status, r.text
    return r.json().get('data')


def insert(db, name, **values):
    return db.execute(table(name).insert().values(**values)).inserted_primary_key[0]


def batch(db, sid):
    s=table('samples')
    return db.scalar(select(s.c.batch_id).where(s.c.sample_id==sid))


def model(db, bid=None):
    return insert(db,'optical_models',model_code=unique(),model_name=unique(),applicable_batch_id=bid)


def measurement(db, sid, **values):
    return insert(db,'measurements',measurement_code=unique(),sample_id=sid,stage='initial',**values)


def preview(client, actors):
    r=client.post('/api/v1/imports/preview',headers=actors['operator']['headers'],
                  files=[('files[]',('isolation.xlsx',workbook(),'application/octet-stream'))])
    assert r.status_code==201,r.text
    return r.json()['data']


def test_model_suggestions_visible_batches_and_admin(db,client,actors):
    own, other=sample(db,actors),sample(db,actors,'other')
    global_id, own_id, other_id=model(db),model(db,batch(db,own)),model(db,batch(db,other))
    for role, expected in [('operator',{global_id,own_id}),('other',{global_id,other_id}),
                           ('viewer',{global_id}),('admin',{global_id,own_id,other_id})]:
        result=suggestions(db,unique(),actors[role]['user'])
        ids={x['model_id'] for x in result['optical_models']} & {global_id,own_id,other_id}
        assert ids==expected
    code=db.scalar(select(table('samples').c.sample_code).where(table('samples').c.sample_id==other))
    assert other not in {x['sample_id'] for x in suggestions(db,code,actors['admin']['user'])['samples']}
    assert other not in {x['sample_id'] for x in suggestions(db,code,actors['operator']['user'])['samples']}


@pytest.mark.parametrize('foreign_owner',[True,False])
def test_confirmation_model_requires_visible_and_matching_sample_batch(db,client,actors,originals,foreign_owner):
    sid=sample(db,actors);other=sample(db,actors,'other' if foreign_owner else 'operator')
    mid=model(db,batch(db,other));job=preview(client,actors)
    body={'expected_row_version':job['row_version'],'items':[choice(job['items'][0],sid,optical_model_id=mid)]}
    r=client.post(f"/api/v1/imports/{job['job_id']}/confirm",json=body,headers=actors['operator']['headers'])
    assert r.status_code==422,r.text
    item=table('import_items')
    assert db.scalar(select(item.c.status).where(item.c.item_id==job['items'][0]['item_id']))=='pending'
    for good in (model(db),model(db,batch(db,sid))):
        # Independent jobs avoid scientific duplicate confirmation.
        job=preview(client,actors)
        r=client.post(f"/api/v1/imports/{job['job_id']}/confirm",headers=actors['operator']['headers'],
            json={'expected_row_version':job['row_version'],'items':[choice(job['items'][0],sid,optical_model_id=good)]})
        assert r.status_code==200,r.text


def test_dataset_operator_never_overrides_foreign_sample(db,client,actors):
    own,foreign=sample(db,actors),sample(db,actors,'other')
    uid=actors['operator']['user']['user_id']
    hidden=insert(db,'instrument_datasets',dataset_code=unique(),instrument_type='xps',sample_id=foreign,operator_user_id=uid)
    visible=insert(db,'instrument_datasets',dataset_code=unique(),instrument_type='rga',sample_id=own,operator_user_id=actors['other']['user']['user_id'])
    unresolved=insert(db,'instrument_datasets',dataset_code=unique(),instrument_type='rga',operator_user_id=uid)
    get(client,actors,f'/instrument-datasets/{hidden}?include_channels=true&include_datapoints=true',status=404)
    assert get(client,actors,f'/instrument-datasets/{visible}')['dataset_id']==visible
    assert get(client,actors,f'/instrument-datasets/{unresolved}')['dataset_id']==unresolved
    rows=get(client,actors,'/instrument-datasets?size=200')
    assert hidden not in {r['dataset_id'] for r in rows}
    assert get(client,actors,f'/instrument-datasets/{hidden}','admin')['dataset_id']==hidden
    assert get(client,actors,f'/instrument-datasets/{hidden}','other')['dataset_id']==hidden


def test_association_projection_all_read_routes_and_raw_storage_unchanged(db,client,actors):
    own,foreign=sample(db,actors),sample(db,actors,'other')
    pid=process(db,actors,role='other');hidden_measurement=measurement(db,foreign)
    hidden_model=model(db,batch(db,foreign))
    job=insert(db,'import_jobs',owner_user_id=actors['other']['user']['user_id'])
    iid=insert(db,'import_items',job_id=job,filename='SECRET',sha256='c'*64,storage_key='c'*64,parse_result={})
    mid=measurement(db,own,process_id=pid,optical_model_id=hidden_model,import_item_id=iid,
                    supersedes_measurement_id=hidden_measurement,provenance={'secret':'SECRET'},import_locator='SECRET')
    for path in (f'/measurements/{mid}',f'/measurements?sample_id={own}',f'/analysis/measurements?sample_id={own}'):
        result=get(client,actors,path);row=result[0] if isinstance(result,list) else result
        for key in ('process_id','optical_model_id','import_item_id','supersedes_measurement_id','provenance','import_locator'):
            assert row[key] is None,(path,key,row)
        assert 'SECRET' not in json.dumps(row)
    admin=get(client,actors,f'/measurements/{mid}','admin')
    assert admin['process_id']==pid and admin['provenance']=={'secret':'SECRET'}
    did=insert(db,'instrument_datasets',dataset_code=unique(),instrument_type='xps',sample_id=own,
               process_id=pid,measurement_id=hidden_measurement,batch_id=batch(db,foreign),acquisition_params={'secret':'SECRET'},mapping_note='SECRET')
    for path in (f'/instrument-datasets/{did}',f'/instrument-datasets?sample_id={own}'):
        result=get(client,actors,path);row=result[0] if isinstance(result,list) else result
        for key in ('process_id','measurement_id','batch_id','acquisition_params','mapping_note'):
            assert row[key] is None
    assert db.scalar(select(table('measurements').c.process_id).where(table('measurements').c.measurement_id==mid))==pid


def test_occurrence_minimum_projection_and_download_name(db,client,actors):
    own,foreign=sample(db,actors),sample(db,actors,'other')
    fid=insert(db,'source_files',file_sha256=unique().encode().hex().ljust(64,'a')[:64],file_name='SECRET',file_role='instrument_raw')
    oid=occurrence(db,actors,fid,'SECRET','other',own)
    row=get(client,actors,f'/source-files/{fid}')
    assert row['file_name']!='SECRET'
    visible=next(o for o in row['occurrences'] if o['occurrence_id']==oid)
    assert all(visible[k] is None for k in ('filename','notes','owner_user_id','import_item_id'))
    assert visible['sample_id']==own
    # Personal archive ownership does not expose a foreign sample identifier.
    own_oid=occurrence(db,actors,fid,'my original','operator',foreign)
    row=get(client,actors,f'/source-files/{fid}')
    assert next(o for o in row['occurrences'] if o['occurrence_id']==own_oid)['sample_id'] is None
    assert get(client,actors,f'/source-files/{fid}','admin')['occurrences'][0]['filename']=='SECRET'


def test_transition_measurement_and_step_context_redacted(db,client,actors):
    own,foreign=sample(db,actors),sample(db,actors,'other')
    mid=measurement(db,foreign);pid=process(db,actors,role='other')
    step=insert(db,'process_steps',process_id=pid,step_index=1,step_kind='wait')
    ids=[insert(db,'sample_transitions',sample_id=own,from_status='available',to_status='available',
                event_type='measure',measurement_id=mid,note='SECRET'),
         insert(db,'sample_transitions',sample_id=own,from_status='available',to_status='available',
                event_type='process',step_id=step,note='SECRET')]
    for path in (f'/samples/{own}/transitions',f'/transitions?sample_id={own}'):
        rows=get(client,actors,path)
        for r in rows:
            if r['transition_id'] in ids:
                assert r['context_redacted']
                assert all(r[k] is None for k in ('measurement_id','step_id','note'))
                assert r['to_status']=='available'
    assert all(not r['context_redacted'] for r in get(client,actors,f'/samples/{own}/transitions','admin'))


@pytest.mark.parametrize('dependency',['historical_process','current_process_stale','historical_model','sample'])
def test_saved_snapshot_refuses_revoked_dependencies(db,client,actors,dependency):
    sid=sample(db,actors);pid=process(db,actors);modelid=model(db)
    mid=measurement(db,sid,process_id=pid,optical_model_id=modelid)
    insert(db,'measurement_points',measurement_id=mid,point_no=1,thickness_nm='1')
    r=client.post('/api/v1/analysis/save',headers=actors['operator']['headers'],json={
        'label':'snapshot','calculation':{'sources':[{'kind':'measurement','id':mid,'expected_row_version':1}]}})
    assert r.status_code==201,r.text
    rid=r.json()['data']['result_id']
    get(client,actors,f'/analysis/saved/{rid}')
    if dependency=='sample':
        db.execute(table('batches').update().where(table('batches').c.batch_id==batch(db,sid)).values(owner_user_id=actors['other']['user']['user_id']))
    elif dependency=='historical_model':
        # Old model still occurs in the snapshot after the current reference changes.
        db.execute(table('optical_models').update().where(table('optical_models').c.model_id==modelid).values(applicable_batch_id=batch(db,sample(db,actors,'other'))))
        db.execute(table('measurements').update().where(table('measurements').c.measurement_id==mid).values(optical_model_id=None))
    else:
        db.execute(table('processes').update().where(table('processes').c.process_id==pid).values(operator_user_id=actors['other']['user']['user_id']))
        db.execute(table('measurements').update().where(table('measurements').c.measurement_id==mid).values(
            **({'process_id':None} if dependency=='historical_process' else {'row_version':2})))
    get(client,actors,f'/analysis/saved/{rid}',status=404)
    get(client,actors,f'/analysis/saved/{rid}','admin')


@pytest.mark.parametrize('dependency', ['sample_id', 'process_id', 'optical_model_id',
                                         'pair_measurement_id', 'measurement_ids'])
def test_import_details_redacts_revoked_saved_context_without_changing_storage(db, client, actors, dependency):
    sid = sample(db, actors)
    pid = process(db, actors)
    modelid = model(db)
    baseline = measurement(db, sid)
    imported = measurement(db, sid)
    confirmation = {'sample_id': sid, 'process_id': pid, 'optical_model_id': modelid,
                    'pair_measurement_id': baseline, 'notes': 'saved context'}
    result = {'measurement_ids': [imported], 'warnings': ['saved context']}
    jobid = insert(db, 'import_jobs', owner_user_id=actors['operator']['user']['user_id'])
    iid = insert(db, 'import_items', job_id=jobid, filename='history.xlsx',
                 sha256='d'*64, storage_key='d'*64, parse_result={},
                 confirmation=confirmation, result=result)
    path = f'/imports/{jobid}'
    before = get(client, actors, path)['items'][0]
    assert before['confirmation'] == confirmation and before['result'] == result
    assert 'storage_key' not in before
    foreign_sid = sample(db, actors, 'other')
    foreign_uid = actors['other']['user']['user_id']
    if dependency == 'sample_id':
        db.execute(table('samples').update().where(table('samples').c.sample_id == sid)
                   .values(owner_user_id=foreign_uid))
    elif dependency == 'process_id':
        db.execute(table('processes').update().where(table('processes').c.process_id == pid)
                   .values(operator_user_id=foreign_uid))
    elif dependency == 'optical_model_id':
        db.execute(table('optical_models').update().where(table('optical_models').c.model_id == modelid)
                   .values(applicable_batch_id=batch(db, foreign_sid)))
    else:
        mid = baseline if dependency == 'pair_measurement_id' else imported
        db.execute(table('measurements').update().where(table('measurements').c.measurement_id == mid)
                   .values(sample_id=foreign_sid))
    item = get(client, actors, path)['items'][0]
    assert item['confirmation'] is None and item['result'] is None
    assert 'saved context' not in json.dumps(item)
    # The no-suggestions internal path must use the same projection.
    from app.imports import details
    assert details(db, jobid, actors['operator']['user'], False)['items'][0]['result'] is None
    get(client, actors, path, 'other', status=404)
    raw = db.execute(select(table('import_items')).where(table('import_items').c.item_id == iid)).mappings().one()
    assert raw['confirmation'] == confirmation and raw['result'] == result
    # Even for an admin the job stays personal; their own historical scientific refs remain global.
    db.execute(table('import_jobs').update().where(table('import_jobs').c.job_id == jobid)
               .values(owner_user_id=actors['admin']['user']['user_id']))
    admin = get(client, actors, path, 'admin')['items'][0]
    assert admin['confirmation'] == confirmation and admin['result'] == result


def test_ai_measurement_model_projection_on_detail_and_sample_context(db, actors):
    from app.ai_tools import execute_tool
    sid = sample(db, actors)
    foreign = sample(db, actors, 'other')
    ids = [model(db), model(db, batch(db, sid)), model(db, batch(db, foreign))]
    mids = [measurement(db, sid, optical_model_id=id) for id in ids]
    # Management accounts are denied research AI unless explicitly allowed (0013 policy).
    # An explicit policy cannot broaden a user's data scope; it only lifts the purpose gate.
    allowed = {'operator': dict(actors['operator']['user']),
               'admin': {**actors['admin']['user'], 'account_purpose': 'management'}}
    ai = table('ai_config')
    for role in ('operator', 'admin'):
        user = allowed[role]
        settings = {'user_policies': {str(user['user_id']): {'research_ai_allowed': True}}}
        db.execute(ai.update().values(settings=settings))
        for mid, modelid in zip(mids, ids):
            expected = None if role == 'operator' and modelid == ids[-1] else modelid
            detail = execute_tool(db, user, 'record_detail',
                                  {'kind': 'measurement', 'id': mid})
            assert detail['data']['record']['optical_model_id'] == expected
        context = execute_tool(db, user, 'record_detail',
                               {'kind': 'sample', 'id': sid})
        rows = {r['measurement_id']: r for r in context['data']['measurements']}
        assert rows[mids[-1]]['optical_model_id'] == (None if role == 'operator' else ids[-1])
    assert db.scalar(select(table('measurements').c.optical_model_id)
                     .where(table('measurements').c.measurement_id == mids[-1])) == ids[-1]


def test_admin_sample_hints_personal_but_scientific_reads_and_models_global(db, client, actors):
    from test_phase3_imports import test_suggestions_never_leak_foreign_samples_even_to_admin
    test_suggestions_never_leak_foreign_samples_even_to_admin(db, client, actors)
    own = sample(db, actors, 'admin')
    foreign = sample(db, actors)
    foreign_model = model(db, batch(db, foreign))
    samples = table('samples')
    own_code = db.scalar(select(samples.c.sample_code).where(samples.c.sample_id == own))
    assert own in {r['sample_id'] for r in suggestions(db, own_code, actors['admin']['user'])['samples']}
    # Batch ownership is required in addition to the sample's owner.
    db.execute(table('batches').update().where(table('batches').c.batch_id == batch(db, own))
               .values(owner_user_id=actors['operator']['user']['user_id']))
    hints = suggestions(db, own_code, actors['admin']['user'])
    assert own not in {r['sample_id'] for r in hints['samples']}
    assert foreign_model in {r['model_id'] for r in hints['optical_models']}
    assert get(client, actors, f'/samples/{foreign}', 'admin')['sample_id'] == foreign
