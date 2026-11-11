"""FINAL void integration on real MySQL; production fingerprints, rollback only."""
import re
import pytest
from sqlalchemy import event
from app.db import metadata
from test_phase5_sample_void import fresh, void, call, code
from test_phase5_backend import run, plan
from test_phase5_closeout_deletion import unchanged_production, all_rows
from test_phase3_imports import originals, preview, confirm, choice

@pytest.mark.parametrize('route',['single','batch','create'])
def test_void_rejects_every_binding_route_atomically(client,actors,db,route):
    active=fresh(client,actors);dead=void(client,actors,fresh(client,actors))
    proc=run(client,actors);pid=proc['process_id']
    before=all_rows(db)
    if route=='single':call(client,actors,'post',f'/processes/{pid}/samples',{'sample_id':dead['sample_id']},status=409)
    elif route=='batch':call(client,actors,'post',f'/processes/{pid}/samples/batch',{'sample_ids':[dead['sample_id'],active['sample_id']]},status=409)
    else:call(client,actors,'post','/processes',{'process_code':code(),'process_mode':'other','steps':[{'step_index':1,'step_kind':'other'}],'samples':[{'sample_id':dead['sample_id']},{'sample_id':active['sample_id']}]},status=409)
    assert all_rows(db)==before
    call(client,actors,'post',f'/processes/{pid}/samples',{'sample_id':active['sample_id']},status=201)
    call(client,actors,'post',f"/samples/{active['sample_id']}/void",{'expected_row_version':1,'reason':'used'},status=409)

@pytest.mark.parametrize('action',['import','original_only'])
def test_void_import_association_rejected_before_any_science_write(client,actors,db,originals,action):
    active=fresh(client,actors);dead=void(client,actors,fresh(client,actors))
    job=preview(client,actors,files=None)
    before=all_rows(db)
    confirm(client,actors,job,[choice(job['items'][0],dead['sample_id'],action=action,sample_id=dead['sample_id'],confirm_associations=True)],status=409)
    assert all_rows(db)==before
    options=call(client,actors,'get',f"/imports/options/samples?keyword={dead['sample_code']}")
    assert options==[]
    call(client,actors,'get',f"/imports/options/samples/{dead['sample_id']}",status=409)
    confirm(client,actors,job,[choice(job['items'][0],active['sample_id'])])

@pytest.mark.parametrize('route',['batch','create','import'])
def test_guards_keep_plan_process_then_sorted_sample_locks(client,actors,db,originals,route):
    samples=[fresh(client,actors),fresh(client,actors)]
    p=plan(client,actors);r=run(client,actors,plan_id=p['plan_id'])
    job=preview(client,actors) if route=='import' else None
    seen=[]
    def track(conn,cursor,statement,params,context,many):
        if 'FOR UPDATE' not in statement:return
        for name,key in [('experiment_plans','plan_id'),('processes','process_id'),('samples','sample_id')]:
            if re.search(rf'FROM {name}\s+WHERE {name}\.{key} =',statement):
                bound=next((v for k,v in params.items() if k.startswith(key+'_')),None)
                seen.append((name,bound))
    event.listen(db,'before_cursor_execute',track)
    try:
        if route=='batch':call(client,actors,'post',f"/processes/{r['process_id']}/samples/batch",{'sample_ids':[s['sample_id'] for s in reversed(samples)]},status=201)
        elif route=='create':run(client,actors,plan_id=p['plan_id'],samples=[{'sample_id':s['sample_id']} for s in reversed(samples)])
        else:
            call(client,actors,'post',f"/processes/{r['process_id']}/samples",{'sample_id':samples[0]['sample_id']},status=201)
            seen.clear()
            confirm(client,actors,job,[choice(job['items'][0],samples[0]['sample_id'],process_id=r['process_id'])])
    finally:event.remove(db,'before_cursor_execute',track)
    # SQLAlchemy suffixes bound parameter names; prove actual table order too.
    assert seen, 'No locking SELECT captured'
    ranks={'experiment_plans':0,'processes':1,'samples':2}
    first_sample=next(i for i,x in enumerate(seen) if x[0]=='samples')
    assert any(x[0]=='experiment_plans' for x in seen[:first_sample])
    assert any(x[0]=='processes' for x in seen[:first_sample])
    locked=[x[1] for x in seen if x[0]=='samples']
    assert locked==sorted(locked)
    print('LOCK ORDER',route,seen)
