"""Batch import of the 28-column ALE workbook. The payload stays authoritative.

Preview is stateless: the reviewed rows are returned to the browser and posted back
with a SHA-256 fingerprint. Confirmation revalidates every row and writes all runs
in the request transaction, so a single failure rolls back the whole batch.
"""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from openpyxl import Workbook, load_workbook
from pydantic import Field
from .common import envelope, fail, audit
from .db import get_db
from .security import current_user, writer
from .quick import qt, owned, store
from .quick_models import Model, Run

router=APIRouter(prefix='/api/v1/quick/batch',tags=['V2.2 Batch import'])
MAX_ROWS=200
QUALITY={'有效':'approved','待复核':'unreviewed','排除':'excluded',
         'approved':'approved','unreviewed':'unreviewed','excluded':'excluded'}

class Confirm(Model):
    rows:list[dict]=Field(max_length=MAX_ROWS)
    expected_sha256:str=Field(min_length=64,max_length=64)
    confirm:bool

def _text(value):
    return None if value is None or str(value).strip()=='' else str(value).strip()

_SUBSTITUTIONS=(('（','('),('）',')'),('℃','°C'),('°c','°C'),('°Ｃ','°C'),
                ('▲','Δ'),('Δp','ΔP'),('／','/'),('：',':'),('₂','2'),
                ('\u00a0',''),('\u3000',''),(' ',''),('\n',''),('\r',''),('\t',''))
_ALIASES={}
def _norm(value):
    if value is None:return ''
    text=str(value)
    for old,new in _SUBSTITUTIONS:text=text.replace(old,new)
    return text.strip().upper()

def _header_map():
    """Canonical header name -> set of accepted normalized spellings."""
    from .quick_dataset import HEADERS
    canon={_norm(h):h for h in HEADERS}
    alias={'腔体压力/PA':'压力/PA','腔体绝对压力/PA':'压力/PA','腔体压力(PA)':'压力/PA',
           '载气流量/SCCM':'载气/SCCM','N2(SCCM)':'载气/SCCM','N2流量/SCCM':'载气/SCCM',
           '循环次数':'CYCLE','循环/CYCLE':'CYCLE','CYCLE数':'CYCLE',
           '前膜厚/NM':'膜厚前/NM','膜厚前':'膜厚前/NM','后膜厚/NM':'膜厚后/NM','膜厚后':'膜厚后/NM',
           '均匀性':'均匀性/%','均匀性(%)':'均匀性/%','EPC(Å/CYCLE)':'EPC/(Å/CYCLE)',
           '质量':'数据质量','质量状态':'数据质量'}
    out={}
    for key,name in canon.items():
        out.setdefault(key,[]).append(name)
    for key,name in alias.items():
        if _norm(name) in canon:out.setdefault(key,[]).append(canon[_norm(name)])
    return out

def _locate(workbook):
    """Find the header row on any plausible sheet; return (ws, row, {canonical: column})."""
    accepted=_header_map()
    order=(['实验记录'] if '实验记录' in workbook.sheetnames else [])+[n for n in workbook.sheetnames if n!='实验记录']
    for name in order:
        ws=workbook[name]
        for row in range(1,min(10,ws.max_row)+1):
            matched={}
            for col in range(1,ws.max_column+1):
                for canonical in accepted.get(_norm(ws.cell(row,col).value),()):
                    matched.setdefault(canonical,col)
            if '日期' in matched and '材料' in matched and len(matched)>=15:
                return ws,row,matched
    fail(422,'未找到可识别的表头：需要一张含「日期 / 材料 / 反应物A / A_Pulse/ms」等列的表，'
             '且与你的记录表或标准模板一致（列顺序、空格、全角符号不影响识别）')

def _number(value,label):
    text=_text(value)
    if text is None:return None
    try:Decimal(text)
    except InvalidOperation:raise ValueError(f'{label} 不是有效数字：{text}')
    return text

def _range(value,label):
    text=_text(value)
    if text is None:return None,None,None
    match=re.fullmatch(r'([-+]?\d+(?:\.\d+)?)\s*[-–~]\s*([-+]?\d+(?:\.\d+)?)',text)
    if match:
        low,high=match.group(1),match.group(2)
        if Decimal(low)>Decimal(high):raise ValueError(f'{label} 区间下限大于上限：{text}')
        return None,low,high
    return _number(text,label),None,None

def _date(value,label):
    text=_text(value)
    if text is None:raise ValueError(f'{label} 不能为空')
    if isinstance(value,date):return value.isoformat()
    try:return date.fromisoformat(text[:10]).isoformat()
    except ValueError:raise ValueError(f'{label} 不是 YYYY-MM-DD：{text}')

def build_row(record,line,materials):
    """One spreadsheet row -> one independent Run; no inference of scientific facts."""
    name=_text(record.get('材料'))
    if not name:raise ValueError('材料不能为空')
    if name not in materials:raise ValueError(f'材料「{name}」不在你的材料目录中，请先在快录页创建')
    steps=[]
    for prefix in ('A','B','C'):
        source=_text(record.get(f'反应物{prefix}'))
        pulse=_number(record.get(f'{prefix}_Pulse/ms'),f'{prefix}_Pulse/ms')
        delta,low,high=_range(record.get(f'{prefix}_ΔP/Pa'),f'{prefix}_ΔP/Pa')
        purge=_number(record.get(f'{prefix}_Purge/s'),f'{prefix}_Purge/s')
        wait=_number(record.get(f'{prefix}_Wait/s'),f'{prefix}_Wait/s')
        if any(v is not None for v in (source,pulse,delta,low,purge,wait)):
            steps.append({'source_label':source or '', 'pulse_ms':pulse,'purge_s':purge,'wait_s':wait,
                          'delta_p_pa':delta,'delta_p_pa_min':low,'delta_p_pa_max':high,'enabled':True})
    quality=_text(record.get('数据质量'))
    if quality and quality not in QUALITY:raise ValueError(f'数据质量应为 有效/待复核/排除，收到：{quality}')
    flag=_text(record.get('用于建模'))
    override=True if flag in ('是','True','true') else False if flag in ('否','False','false') else None
    cycle=_number(record.get('Cycle'),'Cycle')
    return {'experiment_date':_date(record.get('日期'),'日期'),
            'external_experiment_id':_text(record.get('实验ID')),
            'external_batch_id':_text(record.get('批次ID')),
            'note':_text(record.get('备注')) or '',
            'state':'recorded','timezone':'Asia/Hong_Kong',
            'material_id':materials[name],
            'program':{'outer_cycles':None,'groups':[{'code':'A','repeat_count':None,'steps':steps}]},
            'environment':{'r1_temperature_c':_number(record.get('温度/°C'),'温度/°C'),
                           'r2_temperature_c':None,
                           'n2_flow_sccm':_number(record.get('载气/sccm'),'载气/sccm'),
                           'chamber_pressure_pa':_number(record.get('压力/Pa'),'压力/Pa'),
                           'equipment':_text(record.get('设备/腔体')),
                           'film_context':None,'process_type':None,
                           'rf_icp_power_w':None,'bias_power_w':None},
            'results':[{'alias':_text(record.get('样品ID')) or '样品1',
                        'material_id':None,
                        'effective_cycles':cycle,
                        'thickness_before_nm':_number(record.get('膜厚前/nm'),'膜厚前/nm'),
                        'thickness_after_nm':_number(record.get('膜厚后/nm'),'膜厚后/nm'),
                        'uniformity_pct':_number(record.get('均匀性/%'),'均匀性/%'),
                        'uniformity_definition':None,'reported_epc':None,
                        'result_label':_text(record.get('结果标签')),
                        'quality_status':QUALITY.get(quality,'unreviewed'),
                        'use_for_model_override':override,
                        'data_nature':'real_experiment','before_origin':'unknown','after_origin':'manual',
                        'source':None}],
            '_line':line}

@router.get('/template')
def template(request:Request,user=Depends(current_user)):
    from .quick_dataset import HEADERS, MAIN_GROUPS, styled_sheet
    w=Workbook();w.remove(w.active)
    styled_sheet(w,'实验记录',HEADERS,[],MAIN_GROUPS,widths={33:191.2},freeze='E7')
    buffer=BytesIO();w.save(buffer);content=buffer.getvalue()
    sha=hashlib.sha256(content).hexdigest()
    return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':"attachment; filename*=UTF-8''ale-33col-template.xlsx",'X-Content-SHA256':sha})

@router.post('/preview')
async def preview(request:Request,file:UploadFile=File(...),db=Depends(get_db),user=Depends(writer)):
    content=await file.read(25*1024*1024+1)
    if len(content)>25*1024*1024:fail(422,'文件超过 25 MiB 上限')
    if not (file.filename or '').lower().endswith(('.xlsx','.xlsm')):fail(422,'请上传 .xlsx 文件（.xls 请先在 Excel 中另存为 xlsx）')
    try:workbook=load_workbook(BytesIO(content),data_only=True)
    except Exception:fail(422,'无法读取 xlsx；请确认文件未加密、未损坏')
    ws,header_row,mapping=_locate(workbook)
    t=qt('materials')
    materials={m['canonical_name']:m['material_id'] for m in db.execute(select(t).where(owned(t,user))).mappings()}
    rows,errors,skipped=[],[],[]
    for i in range(header_row+1,ws.max_row+1):
        record={name:ws.cell(i,col).value for name,col in mapping.items()}
        if all(v is None or str(v).strip()=='' for v in record.values()):continue
        if not _text(record.get('日期')) and not _text(record.get('材料')):
            skipped.append(f'第 {i} 行：无日期与材料，按汇总/说明行跳过');continue
        if len(rows)>=MAX_ROWS:
            errors.append(f'超过 {MAX_ROWS} 行上限，后续行未读取');break
        try:rows.append(build_row(record,i,materials))
        except ValueError as exc:errors.append(f'第 {i} 行：{exc}')
    digest=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return envelope(request,{'filename':file.filename,'sha256':hashlib.sha256(content).hexdigest(),
                             'sheet':ws.title,'header_row':header_row,'matched_columns':len(mapping),
                             'rows':rows,'errors':errors,'skipped':skipped,
                             'expected_sha256':digest,'row_count':len(rows)})

@router.post('/confirm',status_code=201)
def confirm(body:Confirm,request:Request,db=Depends(get_db),user=Depends(writer)):
    if not body.confirm:fail(422,'请确认逐行核对后再入库')
    if not body.rows:fail(422,'没有可导入的数据行')
    digest=hashlib.sha256(json.dumps(body.rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if digest!=body.expected_sha256:fail(422,'预览数据已变化，请重新上传并核对')
    identifiers=[r.get('external_experiment_id') for r in body.rows if r.get('external_experiment_id')]
    if len(identifiers)!=len(set(identifiers)):fail(409,'文件内实验ID重复；请在 Excel 中修改后重试，系统不会自动改写')
    t=qt('runs')
    existing=db.execute(select(t.c.experiment_date,t.c.daily_no).where(owned(t,user))).mappings().all()
    used={(str(x['experiment_date']),x['daily_no']) for x in existing}
    if 'external_experiment_id' in t.c:
        saved={x[0] for x in db.execute(select(t.c.external_experiment_id).where(owned(t,user),t.c.external_experiment_id.is_not(None)))}
        repeated=[i for i in identifiers if i in saved]
        if repeated:fail(409,'实验ID 已存在：'+', '.join(repeated[:5])+'；请在 Excel 中修改后重试')
    next_no={}
    ids=[]
    for row in body.rows:
        payload={k:v for k,v in row.items() if not k.startswith('_')}
        day=payload['experiment_date'];n=next_no.get(day,1)
        while (day,n) in used:n+=1
        used.add((day,n));next_no[day]=n+1
        payload.update(daily_no=n,idempotency_key=str(uuid4()),expected_version=None)
        ids.append(store(db,Run.model_validate(payload),user))
    audit(db,user['user_id'],'insert','process',None)
    return envelope(request,{'run_ids':ids,'count':len(ids)})
