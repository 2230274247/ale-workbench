"""Reusable generic step definitions. Records store copies, never template references.

Integration: register router; migrate step_parameter_templates before first use.
The snapshot models are also exported for plan/actual step schema reuse.
"""
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, true
from .db import table, get_db
from .common import audit, envelope, fail, page_result
from .security import current_user, writer

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

Name = Annotated[str, Field(min_length=1, max_length=128)]
Unit = Annotated[str, Field(max_length=32)]
Value = Annotated[str, Field(max_length=2000)]

class ParameterField(Input):
    name: Name
    value: Value | None = None
    unit: Unit | None = None

class ParameterGroup(Input):
    name: Name
    fields: Annotated[list[ParameterField], Field(max_length=64)] = Field(default_factory=list)

    @field_validator('fields')
    @classmethod
    def unique_fields(cls, fields):
        if len({f.name for f in fields}) != len(fields):
            raise ValueError('Field names must be unique within a group')
        return fields

class Temperature(Input):
    value: Value | None = None
    unit: Annotated[str, Field(min_length=1, max_length=32)] = '°C'

class ParameterSnapshot(Input):
    step_type: Name
    temperature: Temperature = Field(default_factory=Temperature)
    groups: Annotated[list[ParameterGroup], Field(max_length=32)] = Field(default_factory=list)

    @model_validator(mode='after')
    def bounded_payload(self):
        if sum(len(g.fields) for g in self.groups) > 256:
            raise ValueError('A snapshot supports at most 256 parameter cells')
        if len(self.model_dump_json().encode('utf-8')) > 65536:
            raise ValueError('A snapshot supports at most 64 KiB')
        return self

    @field_validator('groups')
    @classmethod
    def unique_groups(cls, groups):
        if len({g.name for g in groups}) != len(groups):
            raise ValueError('Group names must be unique')
        return groups

class TemplateCreate(Input):
    template_name: Name
    definition: ParameterSnapshot

class TemplateUpdate(Input):
    expected_row_version: Annotated[int, Field(strict=True, ge=1)]
    template_name: Name | None = None
    definition: ParameterSnapshot | None = None

    @field_validator('template_name', 'definition')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('Explicit null is not allowed')
        return value

router = APIRouter(prefix='/api/v1', tags=['Step parameter templates'])

def scope(user):
    t = table('step_parameter_templates')
    return true() if user['role'] == 'admin' else t.c.owner_user_id == user['user_id']

def fetch(db, id, user, lock=False):
    t = table('step_parameter_templates')
    q = select(t).where(t.c.template_id == id, scope(user))
    row = db.execute(q.with_for_update() if lock else q).mappings().first()
    if row is None:
        fail(404)
    return dict(row)

def version(row, expected):
    if row['row_version'] != expected:
        fail(409, 'Template was changed; reload and retry')

@router.get('/step-parameter-templates')
def list_templates(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), keyword: str = Query('', max_length=128), user=Depends(current_user), db=Depends(get_db)):
    t = table('step_parameter_templates')
    q = select(t).where(scope(user))
    if keyword:
        q = q.where(t.c.template_name.contains(keyword, autoescape=True))
    rows, meta = page_result(db, q.order_by(t.c.template_name, t.c.template_id), page, size)
    return envelope(request, rows, meta)

@router.post('/step-parameter-templates', status_code=201)
def create_template(body: TemplateCreate, request: Request, user=Depends(writer), db=Depends(get_db)):
    t = table('step_parameter_templates')
    id = db.execute(t.insert().values(**body.model_dump(mode='json'), owner_user_id=user['user_id'], row_version=1)).inserted_primary_key[0]
    audit(db, user['user_id'], 'insert', 'step_parameter_template', id)
    return envelope(request, fetch(db, id, user))

@router.get('/step-parameter-templates/{id}')
def get_template(id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    return envelope(request, fetch(db, id, user))

@router.patch('/step-parameter-templates/{id}')
def update_template(id: int, body: TemplateUpdate, request: Request, user=Depends(writer), db=Depends(get_db)):
    row = fetch(db, id, user, True)
    version(row, body.expected_row_version)
    values = body.model_dump(exclude_unset=True, mode='json')
    values.pop('expected_row_version')
    if not values:
        return envelope(request, row)
    t = table('step_parameter_templates')
    result = db.execute(t.update().where(t.c.template_id == id, t.c.row_version == row['row_version']).values(**values, row_version=row['row_version'] + 1))
    if result.rowcount != 1:
        fail(409, 'Template was changed; reload and retry')
    audit(db, user['user_id'], 'update', 'step_parameter_template', id)
    return envelope(request, fetch(db, id, user))

@router.delete('/step-parameter-templates/{id}', status_code=204)
def delete_template(id: int, expected_row_version: int = Query(..., ge=1), user=Depends(writer), db=Depends(get_db)):
    row = fetch(db, id, user, True)
    version(row, expected_row_version)
    t = table('step_parameter_templates')
    result = db.execute(t.delete().where(t.c.template_id == id, t.c.row_version == expected_row_version))
    if result.rowcount != 1:
        fail(409, 'Template was changed; reload and retry')
    audit(db, user['user_id'], 'delete', 'step_parameter_template', id)
    return Response(status_code=204)
