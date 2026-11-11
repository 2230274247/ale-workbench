"""General chemistry systems, their species and reusable step templates.

Visibility mirrors the rest of the workbench: admins see everything, every
other role sees rows it owns. Unowned systems (owner_user_id NULL, e.g. rows
whose owner was removed) stay admin-only. Writers create and edit; only
administrators delete, and a system referenced by any run cannot be deleted.
"""
from fastapi import APIRouter,Depends,Query,Request,Response
from sqlalchemy import select,or_,true
from .db import table,get_db
from .common import fail,envelope,audit,page_result
from .security import current_user,writer,admin
from .records import ordered
from . import schemas as S

router=APIRouter(prefix='/api/v1',tags=['Chemistry'])
KINDS={'systems':('chemistry_systems','system_id','chemistry_system','system_code'),
       'species':('chemistry_species','species_id','chemistry_species','species_code'),
       'templates':('chemistry_step_templates','template_id','chemistry_step_template','template_code')}

def visible(user):
    if user['role']=='admin':return true()
    return table('chemistry_systems').c.owner_user_id==user['user_id']

def fetch(db,kind,id,user,lock=False):
    name,pk,_,_=KINDS[kind];t=table(name)
    q=select(t).where(t.c[pk]==id)
    if kind=='systems':q=q.where(visible(user))
    else:q=q.where(t.c.system_id.in_(select(table('chemistry_systems').c.system_id).where(visible(user))))
    row=db.execute(q.with_for_update() if lock else q).mappings().first()
    if row is None:fail(404)
    return dict(row)

def child(db,kind,id,user):
    """Discover, lock the parent system, then lock the child and recheck the link.

    Parent-before-child ordering matches every other hierarchy writer, so a
    concurrent cascade delete of the system cannot deadlock against this edit.
    """
    name,pk,_,_=KINDS[kind];t=table(name)
    initial=db.execute(select(t).where(t.c[pk]==id)).mappings().first()
    if initial is None:fail(404)
    fetch(db,'systems',initial['system_id'],user,True)
    row=db.execute(select(t).where(t.c[pk]==id).with_for_update()).mappings().first()
    if row is None:fail(404)
    if row['system_id']!=initial['system_id']:fail(409,'Record was changed; reload and retry')
    return dict(row)

def check_version(row,expected):
    if expected is not None and row['row_version']!=expected:fail(409,'Record was changed; reload and retry')

def nonnull(t,values):
    if any(v is None and not t.c[k].nullable for k,v in values.items()):fail(422)

def detail(db,id,user):
    row=fetch(db,'systems',id,user)
    s=table('chemistry_species');t=table('chemistry_step_templates')
    row['species']=[dict(r) for r in db.execute(select(s).where(s.c.system_id==id).order_by(s.c.species_code)).mappings()]
    row['templates']=[dict(r) for r in db.execute(select(t).where(t.c.system_id==id).order_by(t.c.template_code)).mappings()]
    u=table('users')
    row['owner']=dict(db.execute(select(u.c.user_id,u.c.username,u.c.display_name).where(u.c.user_id==row['owner_user_id'])).mappings().one()) if row['owner_user_id'] else None
    return row

@router.get('/chemistry-systems')
def list_systems(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),sort:str|None=None,keyword:str=Query('',max_length=128),status:S.SystemStatus|None=None,user=Depends(current_user),db=Depends(get_db)):
    t=table('chemistry_systems');q=select(t).where(visible(user))
    if keyword:q=q.where(or_(t.c.system_code.contains(keyword,autoescape=True),t.c.system_name.contains(keyword,autoescape=True)))
    if status is not None:q=q.where(t.c.status==status)
    q=ordered(q,t,sort,'-created_at',{'system_id','system_code','system_name','status','created_at','updated_at'})
    rows,meta=page_result(db,q,page,size)
    return envelope(request,rows,meta)

@router.post('/chemistry-systems',status_code=201)
def create_system(body:S.ChemistrySystemCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    t=table('chemistry_systems');values=body.model_dump();values['owner_user_id']=user['user_id']
    if db.execute(select(t.c.system_id).where(t.c.system_code==values['system_code']).limit(1)).first():fail(409,'System code already exists')
    id=db.execute(t.insert().values(**values)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','chemistry_system',id)
    return envelope(request,detail(db,id,user))

@router.get('/chemistry-systems/{id}')
def get_system(id:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    return envelope(request,detail(db,id,user))

@router.patch('/chemistry-systems/{id}')
def patch_system(id:int,body:S.ChemistrySystemUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    row=fetch(db,'systems',id,user,True);check_version(row,body.expected_row_version)
    values=body.model_dump(exclude_unset=True);values.pop('expected_row_version',None)
    t=table('chemistry_systems');nonnull(t,values)
    changed=db.execute(t.update().where(t.c.system_id==id,t.c.row_version==row['row_version']).values(**values,row_version=row['row_version']+1))
    if changed.rowcount!=1:fail(409,'Record was changed; reload and retry')
    audit(db,user['user_id'],'update','chemistry_system',id)
    return envelope(request,detail(db,id,user))

@router.delete('/chemistry-systems/{id}')
def delete_system(id:int,user=Depends(admin),db=Depends(get_db)):
    fetch(db,'systems',id,user,True)
    r=table('processes')
    if db.execute(select(r.c.process_id).where(r.c.chemistry_system_id==id).limit(1)).first():fail(409,'Scientific dependencies prevent deletion')
    t=table('chemistry_systems');db.execute(t.delete().where(t.c.system_id==id))
    audit(db,user['user_id'],'delete','chemistry_system',id)
    return Response(status_code=204)

@router.post('/chemistry-systems/{id}/species',status_code=201)
def create_species(id:int,body:S.SpeciesCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    fetch(db,'systems',id,user,True)
    t=table('chemistry_species');values=body.model_dump()
    if db.execute(select(t.c.species_id).where(t.c.system_id==id,t.c.species_code==values['species_code']).limit(1)).first():fail(409,'Species code already exists in this system')
    sid=db.execute(t.insert().values(**values,system_id=id)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','chemistry_species',sid)
    return envelope(request,dict(db.execute(select(t).where(t.c.species_id==sid)).mappings().one()))

@router.patch('/species/{id}')
def patch_species(id:int,body:S.SpeciesUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    child(db,'species',id,user)
    values=body.model_dump(exclude_unset=True);values.pop('expected_row_version',None)
    t=table('chemistry_species');nonnull(t,values)
    db.execute(t.update().where(t.c.species_id==id).values(**values))
    audit(db,user['user_id'],'update','chemistry_species',id)
    return envelope(request,dict(db.execute(select(t).where(t.c.species_id==id)).mappings().one()))

@router.delete('/species/{id}',status_code=204)
def delete_species(id:int,user=Depends(admin),db=Depends(get_db)):
    child(db,'species',id,user)
    t=table('chemistry_species');db.execute(t.delete().where(t.c.species_id==id))
    audit(db,user['user_id'],'delete','chemistry_species',id)
    return Response(status_code=204)

@router.post('/chemistry-systems/{id}/step-templates',status_code=201)
def create_template(id:int,body:S.TemplateCreate,request:Request,user=Depends(writer),db=Depends(get_db)):
    fetch(db,'systems',id,user,True)
    t=table('chemistry_step_templates')
    if db.execute(select(t.c.template_id).where(t.c.system_id==id,t.c.template_code==body.template_code).limit(1)).first():fail(409,'Template code already exists in this system')
    values=body.model_dump(mode='json')
    tid=db.execute(t.insert().values(**values,system_id=id)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','chemistry_step_template',tid)
    return envelope(request,dict(db.execute(select(t).where(t.c.template_id==tid)).mappings().one()))

@router.patch('/step-templates/{id}')
def patch_template(id:int,body:S.TemplateUpdate,request:Request,user=Depends(writer),db=Depends(get_db)):
    child(db,'templates',id,user)
    values=body.model_dump(exclude_unset=True,mode='json');values.pop('expected_row_version',None)
    t=table('chemistry_step_templates');nonnull(t,values)
    db.execute(t.update().where(t.c.template_id==id).values(**values))
    audit(db,user['user_id'],'update','chemistry_step_template',id)
    return envelope(request,dict(db.execute(select(t).where(t.c.template_id==id)).mappings().one()))

@router.delete('/step-templates/{id}',status_code=204)
def delete_template(id:int,user=Depends(admin),db=Depends(get_db)):
    child(db,'templates',id,user)
    t=table('chemistry_step_templates');db.execute(t.delete().where(t.c.template_id==id))
    audit(db,user['user_id'],'delete','chemistry_step_template',id)
    return Response(status_code=204)
