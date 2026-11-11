from datetime import datetime, timezone, date
from decimal import Decimal
from collections.abc import Mapping
from fastapi import HTTPException, Request
from sqlalchemy import select, func

def now():
    return datetime.now(timezone.utc)
def dbnow():
    return now().replace(tzinfo=None)
def clean(value):
    if isinstance(value, Mapping):
        return {k:clean(v) for k,v in value.items() if k not in {'password_hash','token_version','code_hash','refresh_jti_hash'}}
    if isinstance(value,(list,tuple)):
        return [clean(v) for v in value]
    if isinstance(value,Decimal):
        return format(value,'f')
    if isinstance(value,datetime):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()
    if isinstance(value,date): return value.isoformat()
    return value

def envelope(request:Request, data=None, meta=None, code=0, message='ok'):
    result = dict(code=code,message=message,data=clean(data),request_id=request.state.request_id,timestamp=now().isoformat())
    if meta is not None:result['meta']=meta
    return result

def fail(status, message=None):
    raise HTTPException(status, message or {401:'Authentication required',403:'Permission denied',404:'Resource not found',409:'Operation conflicts with existing data',422:'Invalid request'}.get(status,'Request failed'))

def audit(db, uid, action, entity, entity_id):
    from .db import table
    # No raw request, changed values, passwords, tokens, or invitation codes are stored.
    db.execute(table('audit_log').insert().values(user_id=uid,action=action,entity_type=entity,entity_id=entity_id,occurred_at=dbnow()))

def page_result(db, query, page, size):
    total=db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows=[dict(x) for x in db.execute(query.offset((page-1)*size).limit(size)).mappings()]
    pages=(total+size-1)//size
    return rows,dict(page=page,size=size,total=total,total_pages=pages,has_next=page<pages,has_prev=page>1)
