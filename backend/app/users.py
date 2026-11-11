import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, Request, Query, Response
from sqlalchemy import select, or_
from .db import table,get_db
from .common import fail,envelope,audit,dbnow,page_result
from .security import admin,hasher,revoke_all,digest
from . import schemas as S

router=APIRouter(prefix='/api/v1',tags=['Administration'])

@router.get('/users')
def users(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),keyword:str=Query('',max_length=128),role:S.Role|None=None,status:S.UserStatus|None=None,user=Depends(admin),db=Depends(get_db)):
    u=table('users');q=select(u)
    if keyword:q=q.where(or_(u.c.username.contains(keyword,autoescape=True),u.c.display_name.contains(keyword,autoescape=True)))
    if role:q=q.where(u.c.role==role)
    if status:q=q.where(u.c.status==status)
    rows,meta=page_result(db,q.order_by(u.c.user_id),page,size)
    return envelope(request,rows,meta)

@router.post('/users',status_code=201)
def create(body:S.UserCreate,request:Request,user=Depends(admin),db=Depends(get_db)):
    u=table('users');values=body.model_dump(exclude={'password'});values['email']=values['email'] or None
    values['password_hash']=hasher.hash(body.password)
    uid=db.execute(u.insert().values(**values)).inserted_primary_key[0]
    audit(db,user['user_id'],'insert','user',uid)
    return envelope(request,dict(db.execute(select(u).where(u.c.user_id==uid)).mappings().one()))

def get_user(db,id,lock=False):
    u=table('users');q=select(u).where(u.c.user_id==id)
    row=db.execute(q.with_for_update() if lock else q).mappings().first()
    if not row:fail(404)
    return dict(row)

@router.get('/users/{id}')
def get(id:int,request:Request,user=Depends(admin),db=Depends(get_db)):
    return envelope(request,get_user(db,id))

def modify(db,actor,id,values):
    u=table('users')
    # Lock all admins in a stable order, including inactive admins, before checking the last-active-admin invariant.
    admins=list(db.execute(select(u).where(u.c.role=='admin').order_by(u.c.user_id).with_for_update()).mappings())
    target=get_user(db,id,True)
    if any(values.get(k) is None for k in ('role','status','account_purpose') if k in values):fail(422)
    role=values.get('role',target['role']);status=values.get('status',target['status'])
    purpose=values.get('account_purpose',target['account_purpose'])
    losing=role!='admin' or status!='active'
    if actor['user_id']==id and (status!='active' or role!=target['role']):fail(409,'You cannot disable or change your own role')
    if not S.valid_account_purpose(role,purpose):fail(422,'Account purpose must match role')
    if target['role']=='admin' and target['status']=='active' and losing and sum(a['status']=='active' for a in admins)<=1:fail(409,'At least one active administrator is required')
    if 'email' in values:values['email']=values['email'] or None
    if values:db.execute(u.update().where(u.c.user_id==id).values(**values))
    if role!=target['role'] or status!=target['status'] or purpose!=target['account_purpose']:revoke_all(db,id)
    audit(db,actor['user_id'],'update','user',id)
    return get_user(db,id)

@router.patch('/users/{id}')
def update(id:int,body:S.UserUpdate,request:Request,user=Depends(admin),db=Depends(get_db)):
    return envelope(request,modify(db,user,id,body.model_dump(exclude_unset=True)))

@router.delete('/users/{id}')
def disable(id:int,request:Request,user=Depends(admin),db=Depends(get_db)):
    modify(db,user,id,{'status':'disabled'})
    return Response(status_code=204)

@router.put('/users/{id}/password')
def reset(id:int,body:S.ResetPassword,request:Request,user=Depends(admin),db=Depends(get_db)):
    get_user(db,id,True);u=table('users')
    db.execute(u.update().where(u.c.user_id==id).values(password_hash=hasher.hash(body.new_password)))
    revoke_all(db,id);audit(db,user['user_id'],'update','user',id)
    return envelope(request)

@router.get('/invitations')
def invitations(request:Request,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=200),user=Depends(admin),db=Depends(get_db)):
    i=table('invitations');rows,meta=page_result(db,select(i).order_by(i.c.invitation_id.desc()),page,size)
    return envelope(request,rows,meta)

@router.post('/invitations',status_code=201)
def invite(body:S.InvitationCreate,request:Request,user=Depends(admin),db=Depends(get_db)):
    code=secrets.token_urlsafe(32);i=table('invitations')
    id=db.execute(i.insert().values(code_hash=digest(code),role=body.role,account_purpose=body.account_purpose,created_by=user['user_id'],expires_at=dbnow()+timedelta(hours=body.expires_in_hours),created_at=dbnow())).inserted_primary_key[0]
    audit(db,user['user_id'],'update','user',user['user_id'])
    return envelope(request,{**dict(db.execute(select(i).where(i.c.invitation_id==id)).mappings().one()),'invite_code':code})

@router.delete('/invitations/{id}')
def revoke(id:int,request:Request,user=Depends(admin),db=Depends(get_db)):
    i=table('invitations');row=db.execute(select(i).where(i.c.invitation_id==id).with_for_update()).mappings().first()
    if not row:fail(404)
    db.execute(i.update().where(i.c.invitation_id==id).values(revoked_at=dbnow()))
    audit(db,user['user_id'],'update','user',user['user_id'])
    return Response(status_code=204)
