import logging
import os
import copy
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse,FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
import yaml
from .config import ROOT,jwt_secret
from .db import engine, MigrationRequired
from .common import envelope
from . import auth,users,records,dashboard,experiments,transitions,imports,measurement_management,chemistry,step_templates,ai,scientificanalysis,lifecycle,workflow,quick,quick_dataset,quick_batch

logger=logging.getLogger('ale.requests')

app=FastAPI(title='ALE Workbench 1.8.0',version='1.8.0',docs_url='/docs',redoc_url=None,openapi_url='/openapi.json')
app.add_middleware(CORSMiddleware,allow_origin_regex=r'https?://(localhost|127\.0\.0\.1|172\.16\.10\.3)(:\d+)?',allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Authorization','Content-Type'])

@app.middleware('http')
async def request_context(request,call_next):
    request.state.request_id=str(uuid.uuid4())
    try:
        response=await call_next(request)
    except Exception:
        # Keep the same request ID/headers even for unhandled failures; never log
        # exception text, request bodies, authorization or SQL parameters.
        response=error(request,500,'Internal server error')
    response.headers['X-Request-ID']=request.state.request_id
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

def error(request,status,message,errors=None):
    logger.warning('request_error request_id=%s method=%s path=%s status=%s',
                   request.state.request_id, request.method, request.url.path.replace('\r','').replace('\n',''), status)
    code={401:2001,403:2003,404:4004,409:4009,422:1001,429:2029,503:5003}.get(status,5000)
    detail=dict(type=f'urn:ale:error:{status}',title=message,status=status,code=code,detail=message,instance=request.url.path)
    if errors is not None:detail['errors']=errors
    return JSONResponse(envelope(request,detail,code=code,message=message),status_code=status)

@app.exception_handler(HTTPException)
async def http_error(request,exc):return error(request,exc.status_code,str(exc.detail))
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    # Omit rejected inputs, validator context, and free-form messages which may contain secrets.
    return error(request,422,'Invalid request',[{'field':'.'.join(str(p) for p in e['loc'] if p not in ('body','query','path')),'message':'Invalid field value'} for e in exc.errors()])
@app.exception_handler(IntegrityError)
async def conflict(request,exc):return error(request,409,'Operation conflicts with existing data')
@app.exception_handler(MigrationRequired)
async def migration_error(request,exc):return error(request,503,'Application database migration is required')
@app.exception_handler(SQLAlchemyError)
async def database_error(request,exc):return error(request,503,'Database is temporarily unavailable')
@app.exception_handler(Exception)
async def unexpected(request,exc):return error(request,500,'Internal server error')

for router in (auth.router,users.router,records.router,dashboard.router,experiments.router,transitions.router,imports.router,measurement_management.router,chemistry.router,step_templates.router,ai.router,scientificanalysis.router,lifecycle.router,workflow.router,quick.router,quick_dataset.router,quick_batch.router):app.include_router(router)

@app.get('/health')
def health(request:Request):
    with engine().connect() as db:db.execute(text('SELECT 1'))
    return envelope(request,{'status':'ok','database':'ok'})

_contract=None
def canonical_contract():
    global _contract
    if _contract is None:
        _contract=yaml.safe_load((ROOT/'api/openapi/openapi.bundled.yaml').read_text(encoding='utf-8'))
    return _contract

@app.get('/api-contract',include_in_schema=False)
def api_contract():return canonical_contract()

def implemented_openapi():
    if app.openapi_schema:return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    generated=get_openapi(title=app.title,version=app.version,routes=app.routes)
    # Use actual schemas for phase-one extensions and validation, retaining canonical operations where present.
    canonical=canonical_contract()
    # The shared handler accepts exactly these two parent kinds. Publish concrete
    # paths so runtime Swagger, the canonical contract and readiness agree.
    grid=generated['paths'].pop('/api/v1/{kind}/{id}/process-grid',None)
    if grid:
        for kind in ('plans','processes'):
            concrete=copy.deepcopy(grid)
            for operation in concrete.values():
                operation['parameters']=[p for p in operation.get('parameters',[]) if p.get('name')!='kind']
                operation['operationId']=('savePlanGrid' if kind=='plans' else 'saveProcessGrid')
            generated['paths'][f'/api/v1/{kind}/{{id}}/process-grid']=concrete
    generated['x-canonical-contract']='/api-contract'
    for name, schema in canonical.get('components',{}).get('schemas',{}).items():
        generated['components']['schemas'].setdefault(name,copy.deepcopy(schema))
    for path,methods in generated['paths'].items():
        for method,operation in list(methods.items()):
            canonical_op=canonical.get('paths',{}).get(path,{}).get(method)
            round7_path=(path.startswith('/api/v1/analysis/') or path.endswith('/process-grid')
                         or path in ('/api/v1/workflow/plans', '/api/v1/workflow/processes'))
            if canonical_op and (round7_path or not any(token in path for token in ('/samples','/batches','/tools','/step-parameter-templates','/plans','/plan-steps','/processes','/process-steps','/process-samples','/transitions','/imports','/measurements','/source-files','/instrument-datasets','/analysis'))):
                methods[method]=copy.deepcopy(canonical_op)
                methods[method]['x-implementation-status']='implemented'
    app.openapi_schema=generated
    return generated
app.openapi=implemented_openapi

@app.get('/{path:path}',include_in_schema=False)
def spa(path:str,request:Request):
    from .common import fail
    if path=='api' or path.startswith(('api/','api-contract/','openapi.json/','health/')):fail(404)
    # Explicit isolated acceptance builds never replace the installed production assets.
    test_dist=os.getenv('ALE_TEST_FRONTEND_DIST') if os.getenv('ALE_ENVIRONMENT')=='testing' else None
    dist=Path(test_dist).resolve() if test_dist else (ROOT/'frontend/dist').resolve();candidate=(dist/path).resolve()
    if not candidate.is_relative_to(dist):fail(404)
    if candidate.is_file():return FileResponse(candidate)
    if '.' in Path(path).name:fail(404)
    index=dist/'index.html'
    if not index.is_file():fail(404)
    return FileResponse(index)
