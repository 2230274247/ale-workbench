"""Versioned, conservative exports. No source-channel or temperature inference."""
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from decimal import Decimal
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from .common import envelope, audit
from .db import get_db
from .security import current_user
from .quick import selection, qt
from .quick_models import Model

router=APIRouter(prefix='/api/v1/quick/dataset',tags=['V2.2 Dataset'])
HEADERS='日期|实验ID|批次ID|样品ID|材料|设备/腔体|反应物A|反应物B|反应物C|温度/°C|压力/Pa|载气/sccm|A_Pulse/ms|A_ΔP/Pa|A_Purge/s|A_Wait/s|B_Pulse/ms|B_ΔP/Pa|B_Purge/s|B_Wait/s|C_Pulse/ms|C_ΔP/Pa|C_Purge/s|C_Wait/s|Cycle|膜厚前/nm|膜厚后/nm|EPC/(Å/cycle)|均匀性/%|结果标签|数据质量|用于建模|备注'.split('|')
# 旧版 28 列模板（无反应物C）：导入继续兼容，导出统一用 33 列。
HEADERS_28='日期|实验ID|批次ID|样品ID|材料|设备/腔体|反应物A|反应物B|温度/°C|压力/Pa|载气/sccm|A_Pulse/ms|A_ΔP/Pa|A_Purge/s|A_Wait/s|B_Pulse/ms|B_ΔP/Pa|B_Purge/s|B_Wait/s|Cycle|膜厚前/nm|膜厚后/nm|EPC/(Å/cycle)|均匀性/%|结果标签|数据质量|用于建模|备注'.split('|')
RECORD_HEADERS='RunID|实验ID(系统)|外部实验ID(原始标识)|批次ID|日期|当日第几次|状态|材料|工艺类型|设备/腔体|R1(°C)|R2(°C)|N₂(sccm)|腔体压力(Pa)|RF/ICP功率(W)|Bias功率(W)|薄膜属性|开始时间|结束时间|时区|备注|外层循环|前段RunID'.split('|')
RECORD_GROUPS=[(0,1,'实验定位'),(2,7,'基础信息'),(8,16,'工艺环境'),(17,22,'时间与结构')]
STEP_HEADERS='RunID|实验ID(系统)|组名|列序号|源(反应物)|Pulse(ms)|ΔP(Pa)|Purge(s)|Wait(s)|启用|ΔP下限|ΔP上限|组循环次数|主表映射'.split('|')
STEP_GROUPS=[(0,3,'列定位'),(4,8,'源与绑定参数'),(9,13,'附加')]
RESULT_HEADERS='RunID|实验ID(系统)|结果ID|样品标识|薄膜材料|膜厚前(nm)|膜厚后(nm)|本段有效循环|EPC(Å/cycle)|净减薄(nm)|均匀性(%)|均匀性定义|原报告EPC|前膜厚来源|后膜厚来源|数据性质|质量状态|结果标签|用于建模(人工覆盖)|文件来源|用于建模(输出)'.split('|')
RESULT_GROUPS=[(0,3,'结果定位'),(4,9,'量测与结果'),(10,20,'质量与来源')]
MAIN_GROUPS=[(0,3,'基础信息'),(4,8,'工艺参数'),(9,24,'核心工艺输入（模型 X）'),(25,26,'原始量测'),(27,28,'模型目标（y）'),(29,32,'质量控制')]
FEATURE_VERSION='ale.quick.features/2.2.2'
EXCEL_CELL_LIMIT=32767
FEATURE_UNITS={'X_before_measured_nm':'nm','X_effective_cycles':'cycle','X_r1_c':'°C','X_r2_c':'°C',
               'X_n2_sccm':'sccm','X_absolute_pressure_pa':'Pa','step.pulse_ms':'ms','step.purge_s':'s',
               'step.wait_s':'s','step.delta_p_pa':'Pa','y_loss_nm':'nm','y_epc_a_per_cycle':'Å/cycle',
               'y_uniformity_pct':'%'}
FIELD_LABELS={'X_material':'薄膜材料','X_equipment':'设备/腔体','X_before_measured_nm':'实验前实测膜厚 (nm)',
              'X_effective_cycles':'本段有效循环次数','X_r1_c':'R1 (°C)','X_r2_c':'R2 (°C)',
              'X_n2_sccm':'N₂ (sccm)','X_absolute_pressure_pa':'腔体绝对压力 (Pa)',
              'y_loss_nm':'表观净减薄量 (nm)','y_epc_a_per_cycle':'EPC (Å/cycle)','y_uniformity_pct':'膜厚均匀性 (%)'}
REASON_LABELS={'draft':'尚为草稿','material_missing':'薄膜材料未确认','not_confirmed_real':'尚未确认为真实实验',
               'not_approved':'尚未通过质量审核','target_missing_or_zero_cycles':'膜厚结果缺失或有效循环为零/未知',
               'equipment_unknown':'设备/腔体未记录','reference_before_requires_review':'前膜厚为承接参考，尚需核查',
               'unsupported_recipe_unconfirmed_channel_mapping':'源通道的物理含义尚未确认',
               'uniformity_definition_unknown':'均匀性计算定义未记录','reported_epc_discrepancy':'原报告EPC与重算值不一致',
               'cycle_definition_mismatch':'程序循环与结果有效循环口径不一致',
               'measurement_unit_unconfirmed':'量测来源单位未确认或不是nm，未自动换算',
               'active_recipe_missing':'尚未记录已启用的工艺步骤','step_source_missing':'已启用步骤的源名称缺失',
               'carried_reference_stale':'承接的上一段膜厚已变更，需要重新核查'}
REASON_LABELS['recipe_requires_normalized_rows']='工艺快照超过宽表单格上限，需先读取完整附加步骤并规范化'

def excel_units(value):
    return len(value.encode('utf-16-le'))//2

def feature_recipe(run):
    recipe={'outer_cycles':run['program']['outer_cycles'],'groups':[
        {'code':g['code'],'repeat_count':g['repeat_count'],'steps':[
            {k:v for k,v in s.items() if k!='step_id'} for s in g['steps']]} for g in run['program']['groups']]}
    return json.dumps(recipe,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def eligibility(run,result):
    reasons=[]
    if run['state']!='recorded':reasons.append('draft')
    if not result['material_name']:reasons.append('material_missing')
    if result['data_nature']!='real_experiment':reasons.append('not_confirmed_real')
    if result['quality_status']!='approved':reasons.append('not_approved')
    if result['epc_a_per_cycle'] is None:reasons.append('target_missing_or_zero_cycles')
    if not run['environment']['equipment']:reasons.append('equipment_unknown')
    if result.get('source') and result['source'].get('units')!='nm':reasons.append('measurement_unit_unconfirmed')
    if result['before_origin']=='carried_forward':reasons.append('reference_before_requires_review')
    # There is no confirmed physical mapping in this release. Keep full recipes for review.
    reasons.append('unsupported_recipe_unconfirmed_channel_mapping')
    if result['uniformity_pct'] is not None and not result['uniformity_definition']:reasons.append('uniformity_definition_unknown')
    if result['reported_epc_difference'] is not None and Decimal(result['reported_epc_difference'])!=0:reasons.append('reported_epc_discrepancy')
    if run['warnings']:reasons.append('cycle_definition_mismatch')
    return reasons

def wide(runs):
    rows=[]
    for run in runs:
        recipe=feature_recipe(run);oversized=excel_units(recipe)>EXCEL_CELL_LIMIT
        for result in run['results']:
            reasons=eligibility(run,result)
            if oversized:reasons.append('recipe_requires_normalized_rows')
            rows.append({'meta_run_id':run['run_id'],'meta_result_id':result['result_id'],
                'meta_leak_group':run['sequence_id'],'meta_experiment_date':run['experiment_date'],
                'meta_daily_no':run['daily_no'],'meta_result_alias':result['alias'],'meta_feature_schema_version':FEATURE_VERSION,
                'meta_data_nature':result['data_nature'],'meta_quality_status':result['quality_status'],
                'meta_training_eligible':not reasons,'meta_exclusion_reasons':';'.join(reasons),
                'meta_recipe_reference':f"run:{run['run_id']}:program",'meta_recipe_json_export_status':'normalized_rows' if oversized else 'inline_json',
                'meta_recipe_sha256':hashlib.sha256(recipe.encode()).hexdigest(),
                'X_material':result['material_name'],'X_equipment':run['environment']['equipment'],
                'X_before_measured_nm':result['thickness_before_nm'] if result['before_origin']=='measured' else None,
                'X_effective_cycles':result['effective_cycles'],
                'X_r1_c':run['environment']['r1_temperature_c'],'X_r2_c':run['environment']['r2_temperature_c'],
                'X_n2_sccm':run['environment']['n2_flow_sccm'],'X_absolute_pressure_pa':run['environment']['chamber_pressure_pa'],
                'X_recipe_json':None if oversized else recipe,
                'y_loss_nm':result['thickness_loss_nm'],'y_epc_a_per_cycle':result['epc_a_per_cycle'],
                'y_uniformity_pct':result['uniformity_pct'],'meta_uniformity_definition':result['uniformity_definition']})
    numeric_fields=('X_before_measured_nm','X_r1_c','X_r2_c','X_n2_sccm','X_absolute_pressure_pa','y_loss_nm','y_epc_a_per_cycle','y_uniformity_pct')
    for row in rows:
        for key in numeric_fields:
            if row[key] is not None:row[key]=float(row[key])
        bucket=int(hashlib.sha256(row['meta_leak_group'].encode()).hexdigest()[:8],16)%10
        row['meta_suggested_group_split']='test' if bucket==9 else 'validation' if bucket==8 else 'train'
    return rows

def manifest(runs,filters):
    warnings=['源与反应物的映射由用户确认：网页第 1 列 → 反应物A，第 2 列 → 反应物B，第 3 列 → 反应物C；第 4 列及以后在「源步骤明细」逐行保留。空白源不推断、不补值。',
              '温度/°C 只写入 R1；R2 保留在「记录明细」，网页端非必填；当日序号不是物理批次。',
              '数据质量按 待复核/有效/排除 输出；用于建模默认由资格审查计算，人工覆盖在「结果明细」留痕。',
              '主表按参照表扩展为 33 列（含反应物C 与 C_Pulse/C_ΔP/C_Purge/C_Wait）；网页其余字段在「记录明细」「源步骤明细」「结果明细」及完整附加字段中保留。']
    for run in runs:
        if excel_units(feature_recipe(run))>EXCEL_CELL_LIMIT:
            warnings.append(f"{run['experiment_date']} 第{run['daily_no']}次：工艺快照超过宽表单格上限，宽表改用规范化引用；完整有序步骤保留在完整附加字段及JSON，不截断。")
    return {'schema_version':'ale.quick/2.2.1','feature_schema_version':FEATURE_VERSION,'mapping_version':'competition33/user-confirmed-4',
        'generated_at':datetime.now(timezone.utc).isoformat(),'filters':filters,'run_count':len(runs),
        'result_count':sum(len(r['results']) for r in runs),'versions':{str(r['run_id']):r['version'] for r in runs},
        'source_hashes':sorted({r['source']['sha256'] for run in runs for r in run['results'] if r.get('source')}),
        'warnings':warnings,
        'training_policy':'real_experiment + approved + complete comparable X/y; split by sequence_id (includes same-run results); no outcome in X'}

def group_audit(rows):
    assignments={}
    for row in rows:assignments.setdefault(row['meta_leak_group'],set()).add(row['meta_suggested_group_split'])
    shared=sorted(group for group,splits in assignments.items() if len(splits)>1)
    return {'status':'FAIL' if shared else 'PASS' if rows else 'NOT_RUN',
            'method':'sha256(sequence_id), 80/10/10 group buckets; suggested only, no model fitted',
            'checked_rows':len(rows),'checked_groups':len(assignments),'shared_groups_across_splits':shared,
            'split_counts':dict(Counter(r['meta_suggested_group_split'] for r in rows))}

def readiness(runs,filters):
    rows=wide(runs);reasons=Counter(reason for r in rows for reason in r['meta_exclusion_reasons'].split(';') if reason)
    materials=Counter(r['X_material'] or '未知材料' for r in rows)
    groups=Counter(r['meta_leak_group'] for r in rows)
    signatures=Counter(hashlib.sha256(json.dumps({**{k:v for k,v in r.items() if k.startswith(('X_','y_'))},'_full_recipe_sha256':r['meta_recipe_sha256']},sort_keys=True).encode()).hexdigest() for r in rows)
    fields=['X_material','X_equipment','X_before_measured_nm','X_effective_cycles','X_r1_c','X_r2_c','X_n2_sccm','X_absolute_pressure_pa','y_loss_nm','y_epc_a_per_cycle','y_uniformity_pct']
    missing=Counter({field:sum(r[field] is None or r[field]=='' for r in rows) for field in fields})
    by_material={};by_equipment={};by_sequence={}
    for row in rows:
        for summary,key in [(by_material,row['X_material'] or '未知材料'),(by_equipment,row['X_equipment'] or '未知设备'),(by_sequence,row['meta_leak_group'])]:
            bucket=summary.setdefault(key,{'row_count':0,'eligible_count':0,'missing_fields':{field:0 for field in fields},'exclusion_counts':{}})
            bucket['row_count']+=1;bucket['eligible_count']+=int(row['meta_training_eligible'])
            for field in fields:bucket['missing_fields'][field]+=int(row[field] is None or row[field]=='')
            for reason in row['meta_exclusion_reasons'].split(';'):
                if reason:bucket['exclusion_counts'][reason]=bucket['exclusion_counts'].get(reason,0)+1
    issues=[]
    for run in runs:
        active=[(g,s) for g in run['program']['groups'] for s in g['steps'] if s.get('enabled')]
        for result in run['results']:
            source=result.get('source');row_issues=[]
            if source and source.get('units')!='nm':row_issues.append('measurement_unit_unconfirmed')
            if not active:row_issues.append('active_recipe_missing')
            if any(not s.get('source_label','').strip() for _,s in active):row_issues.append('step_source_missing')
            if result.get('reported_epc_difference') is not None and Decimal(result['reported_epc_difference'])!=0:row_issues.append('reported_epc_discrepancy')
            if result.get('reference_needs_review'):row_issues.append('carried_reference_stale')
            if result['uniformity_pct'] is not None and not result['uniformity_definition']:row_issues.append('uniformity_definition_unknown')
            if row_issues:issues.append({'run_id':run['run_id'],'result_id':result['result_id'],'issues':row_issues})
    unit_anomalies=sum('measurement_unit_unconfirmed' in row['issues'] for row in issues)
    return {**manifest(runs,filters),'training_status':'数据不足/不适合训练','eligible_count':sum(r['meta_training_eligible'] for r in rows),
        'materials':dict(materials),'equipment':dict(Counter(r['X_equipment'] or '未知' for r in rows)),
        'data_nature':dict(Counter(r['meta_data_nature'] for r in rows)),
        'quality_status':dict(Counter(r['meta_quality_status'] for r in rows)),
        'field_labels':FIELD_LABELS,'reason_labels':REASON_LABELS,
        'missing_fields':dict(missing),'by_material':by_material,'by_equipment':by_equipment,'by_sequence':by_sequence,
        'row_issues':issues,'unit_audit':{'status':'FAIL' if unit_anomalies else 'PASS' if rows else 'NOT_RUN',
            'checked_result_rows':len(rows),'anomaly_count':unit_anomalies,'canonical_units':FEATURE_UNITS,
            'policy':'Numeric fields retain schema units; unconfirmed source units are flagged, never converted or guessed.'},
        'exclusion_counts':dict(reasons),'leak_groups':dict(groups),'group_split_required':True,
        'duplicate_feature_target_rows':sum(n-1 for n in signatures.values() if n>1),
        'split_contract':{'group_key':'sequence_id','same_run_results_share_group':True,'random_row_split_allowed':False},
        'group_split_audit':group_audit(rows),
        'recommendations':['确认源通道物理映射与有效周期口径。','补全材料、设备及实验前已知条件，审核真实数据。','按材料/设备/工艺筛选并以连续序列分组后再训练；此版本没有训练或预测指标。'],
        'rows':rows}

@router.get('/preview')
def preview(request:Request,db=Depends(get_db),user=Depends(current_user)):
    filters=dict(request.query_params);runs=selection(db,user,filters)
    return envelope(request,manifest(runs,filters))

@router.get('/readiness')
def check(request:Request,db=Depends(get_db),user=Depends(current_user)):
    filters=dict(request.query_params);return envelope(request,readiness(selection(db,user,filters),filters))

def safe(value):
    if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False)
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r')):return "'"+value
    return value

def numeric(value):
    return float(value) if value is not None else None

QUALITY_LABELS={'unreviewed':'待复核','approved':'有效','excluded':'排除'}
GROUP_FILLS=['5B9BD5','70AD47','ED7D31','A5A5A5','8064A2','4472C4']

def reactant(step):
    if not step:return None
    return (step.get('source_label') or '').strip() or None

def step_number(step,key):
    return numeric(step.get(key)) if step else None

def delta_p(step):
    """Single value or a user-confirmed fluctuation range, never inferred."""
    if not step:return None
    low,high=step.get('delta_p_pa_min'),step.get('delta_p_pa_max')
    if low is not None and high is not None:
        return str(low) if str(low)==str(high) else f'{low}–{high}'
    return numeric(step.get('delta_p_pa'))

def leading_steps(run,count=3):
    """Column 1 -> reactant A, 2 -> B, 3 -> C; no group or channel inference."""
    groups=run['program']['groups']
    steps=groups[0]['steps'] if groups else []
    return [steps[i] if i<len(steps) else None for i in range(count)]

def model_flag(run,result):
    override=result.get('use_for_model_override')
    if override is True:return '是'
    if override is False:return '否'
    return '否' if eligibility(run,result) else '是'

def readiness_html(report):
    h=lambda value:html.escape(str(value))
    def grid(headers,rows,label):
        return '<div class="scroll" tabindex="0" role="region" aria-label="'+h(label)+'"><table><thead><tr>'+''.join('<th scope="col">'+h(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+h(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    missing=[[FIELD_LABELS.get(key,key),report['result_count']-count,count] for key,count in report['missing_fields'].items()]
    materials=[[name,value['row_count'],value['eligible_count']] for name,value in report['by_material'].items()]
    measurements=[]
    for row in report['rows']:
        reasons='；'.join(REASON_LABELS.get(reason,reason) for reason in row['meta_exclusion_reasons'].split(';') if reason)
        measurements.append([row['meta_experiment_date'],row['meta_result_alias'],row['X_material'] or '未确认',row['y_epc_a_per_cycle'] if row['y_epc_a_per_cycle'] is not None else '—','可训练' if row['meta_training_eligible'] else '暂不可训练',reasons])
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>数据集质量与训练就绪度</title>'
            '<style>body{max-width:1160px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui;color:#203a4b;background:#eef3f6}h1,h2{color:#15384a}table{border-collapse:collapse;width:100%;min-width:600px;background:#f8fafc}td,th{padding:12px;text-align:left;vertical-align:top;border:1px solid #a4b6c3}th{background:#dfecef}pre{white-space:pre-wrap;overflow-wrap:anywhere}.scroll{overflow:auto;max-width:100%}:focus-visible{outline:3px solid #087f8c;outline-offset:2px}details{margin-top:24px}summary{cursor:pointer;min-height:44px}</style>'
            '<h1>数据集质量与训练就绪度</h1><p>'+h(report['training_status'])+'。本次扫描 '+h(report['run_count'])+' 次运行、'+h(report['result_count'])+' 条测量，可训练 '+h(report['eligible_count'])+' 条。</p>'
            '<p>本报告没有训练模型或生成性能指标。零值计为已记录；未知值、承接参考与来源单位疑问分别保留。</p>'
            '<h2>材料覆盖</h2>'+grid(['薄膜材料','测量条数','可训练条数'],materials,'材料覆盖')+
            '<h2>字段完整性</h2>'+grid(['字段','已记录','缺失'],missing,'字段缺失统计')+
            '<h2>逐条测量审核</h2>'+grid(['实验日期','样品标识','薄膜材料','EPC (Å/cycle)','审核结果','具体原因'],measurements,'测量审核结果')+
            '<h2>单位与分组检查</h2><p>来源单位异常 '+h(report['unit_audit']['anomaly_count'])+' 条；跨训练/测试的共享组 '+h(len(report['group_split_audit']['shared_groups_across_splits']))+' 个。建议分组只是数据合同的一部分，不表示已经训练或获得有效评估。</p>'
            '<h2>补充建议</h2><ul>'+''.join('<li>'+h(item)+'</li>' for item in report['recommendations'])+'</ul>'
            '<details><summary>查看完整机器可读数据与版本依据</summary><pre>'+h(json.dumps(report,ensure_ascii=False,indent=2))+'</pre></details></html>')

def sheet(w,name,headers,rows,group=False):
    s=w.create_sheet(name)
    if group:s.append(['实验身份与条件']+['']*18+['周期与结果']+['']*8)
    s.append(headers)
    for row in rows:
        values=[safe(v) for v in row]
        for value in values:
            if isinstance(value,str) and excel_units(value)>EXCEL_CELL_LIMIT:
                from .common import fail
                fail(422,'某项文本超过Excel单元格上限；请使用完整JSON导出保留原值。未截断任何数据。')
            if isinstance(value,str) and re.search(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]',value):
                from .common import fail
                fail(422,'文本包含XLSX不支持的控制字符；请使用完整JSON导出保留原值。未改写任何数据。')
        s.append(values)
    header_row=2 if group else 1
    for cell in s[header_row]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='102438');cell.alignment=Alignment(wrap_text=True)
    from openpyxl.utils import get_column_letter
    for i in range(1,len(headers)+1):s.column_dimensions[get_column_letter(i)].width=21
    s.freeze_panes='A'+str(header_row+1);s.auto_filter.ref=s.dimensions
    return s

def styled_sheet(w,name,headers,rows,groups,widths=None,freeze='A3'):
    """Two-row grouped header matching the reference workbook's measured style."""
    from openpyxl.utils import get_column_letter
    s=w.create_sheet(name)
    first=['']*len(headers)
    for start,end,label in groups:first[start]=label
    s.append(first)
    for start,end,label in groups:
        s.merge_cells(start_row=1,start_column=start+1,end_row=1,end_column=end+1)
    s.append(headers)
    for row in rows:
        values=[safe(v) for v in row]
        for value in values:
            if isinstance(value,str) and excel_units(value)>EXCEL_CELL_LIMIT:
                from .common import fail
                fail(422,'某项文本超过Excel单元格上限；请使用完整JSON导出保留原值。未截断任何数据。')
            if isinstance(value,str) and re.search(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]',value):
                from .common import fail
                fail(422,'文本包含XLSX不支持的控制字符；请使用完整JSON导出保留原值。未改写任何数据。')
        s.append(values)
    thin=Side(style='thin',color='B4B2A9')
    border=Border(left=thin,right=thin,top=thin,bottom=thin)
    for index,(start,end,label) in enumerate(groups):
        color=GROUP_FILLS[index%len(GROUP_FILLS)]
        for col in range(start+1,end+2):
            s.cell(1,col).fill=PatternFill('solid',fgColor=color)
    for row_index in (1,2):
        for cell in s[row_index]:
            cell.font=Font(name='Carlito',size=11 if row_index==1 else 10,bold=True,color='FFFFFF')
            cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=row_index==2)
            if row_index==2:cell.fill=PatternFill('solid',fgColor='1F4E78')
            cell.border=border
    for row in s.iter_rows(min_row=3,max_row=s.max_row,max_col=len(headers)):
        for cell in row:
            cell.font=Font(name='Carlito',size=11);cell.border=border
    s.row_dimensions[1].height=24;s.row_dimensions[2].height=42
    s.freeze_panes=freeze
    for i in range(1,len(headers)+1):
        s.column_dimensions[get_column_letter(i)].width=(widths or {}).get(i,18)
    return s

def main_table_rows(runs):
    """33-column worksheet; columns 1/2/3 map to reactant A/B/C only."""
    rows=[]
    for run in runs:
        first,second,third=leading_steps(run)
        e=run['environment']
        for r in run['results']:
            rows.append([run['experiment_date'],run['process_code'],run.get('external_batch_id'),r['alias'],r['material_name'],e.get('equipment'),reactant(first),reactant(second),reactant(third),numeric(e.get('r1_temperature_c')),numeric(e.get('chamber_pressure_pa')),numeric(e.get('n2_flow_sccm')),step_number(first,'pulse_ms'),delta_p(first),step_number(first,'purge_s'),step_number(first,'wait_s'),step_number(second,'pulse_ms'),delta_p(second),step_number(second,'purge_s'),step_number(second,'wait_s'),step_number(third,'pulse_ms'),delta_p(third),step_number(third,'purge_s'),step_number(third,'wait_s'),r['effective_cycles'],numeric(r['thickness_before_nm']),numeric(r['thickness_after_nm']),numeric(r['epc_a_per_cycle']),numeric(r['uniformity_pct']),r.get('result_label'),QUALITY_LABELS.get(r['quality_status']),model_flag(run,r),run['note']])
    return rows

def detail_tables(runs):
    """Flat details for every web field, including column 3+ and the second temperature zone."""
    run_rows,step_rows,result_rows=[],[],[]
    for run in runs:
        e=run['environment'];prog=run['program']
        run_rows.append([run['run_id'],run['process_code'],run.get('external_experiment_id'),run.get('external_batch_id'),run['experiment_date'],run['daily_no'],run['state'],run['material_name'],e.get('process_type'),e.get('equipment'),numeric(e.get('r1_temperature_c')),numeric(e.get('r2_temperature_c')),numeric(e.get('n2_flow_sccm')),numeric(e.get('chamber_pressure_pa')),numeric(e.get('rf_icp_power_w')),numeric(e.get('bias_power_w')),e.get('film_context'),run.get('started_at'),run.get('ended_at'),run.get('timezone'),run['note'],prog.get('outer_cycles'),run.get('previous_run_id')])
        for group in prog['groups']:
            for index,step in enumerate(group['steps']):
                low,high=step.get('delta_p_pa_min'),step.get('delta_p_pa_max')
                step_rows.append([run['run_id'],run['process_code'],group['code'],index+1,reactant(step),numeric(step.get('pulse_ms')),delta_p(step),numeric(step.get('purge_s')),numeric(step.get('wait_s')),bool(step.get('enabled')),numeric(low) if low is not None else None,numeric(high) if high is not None else None,group.get('repeat_count'),{0:'A',1:'B',2:'C'}.get(index,'D 及以后（明细表）')])
        for r in run['results']:
            result_rows.append([run['run_id'],run['process_code'],r['result_id'],r['alias'],r['material_name'],numeric(r['thickness_before_nm']),numeric(r['thickness_after_nm']),r['effective_cycles'],numeric(r['epc_a_per_cycle']),numeric(r.get('thickness_loss_nm')),numeric(r['uniformity_pct']),r.get('uniformity_definition'),numeric(r['reported_epc']),r['before_origin'],r['after_origin'],r['data_nature'],r['quality_status'],r.get('result_label'),r.get('use_for_model_override'),'有' if r.get('source') else '无',model_flag(run,r)])
    return run_rows,step_rows,result_rows

@router.get('/download')
def download(request:Request,format:str='json',db=Depends(get_db),user=Depends(current_user)):
    filters={k:v for k,v in request.query_params.items() if k!='format'}
    runs=selection(db,user,filters);meta=manifest(runs,filters);eid=str(uuid4());meta['export_id']=eid
    if format in ('readiness_json','readiness_html'):
        report=readiness(runs,filters)
        content=json.dumps(report,ensure_ascii=False,indent=2).encode()
        mime='application/json';ext='json'
        if format=='readiness_html':
            content=readiness_html(report).encode();mime='text/html';ext='html'
    elif format=='json':
        # Full revision snapshots are included, preserving changes and original reported values.
        from sqlalchemy import select
        rev=qt('revisions')
        revisions=[dict(r) for r in db.execute(select(rev).where(rev.c.process_id.in_([r['run_id'] for r in runs]))).mappings()]
        catalog=qt('materials')
        owner_ids={r['owner_user_id'] for r in db.execute(select(qt('runs')).where(qt('runs').c.process_id.in_([r['run_id'] for r in runs]))).mappings()}
        materials=[dict(m) for m in db.execute(select(catalog).where(catalog.c.owner_user_id.in_(owner_ids))).mappings()]
        imports=qt('imports')
        import_history=[dict(i) for i in db.execute(select(imports).where(imports.c.process_id.in_([r['run_id'] for r in runs]),imports.c.owner_user_id==user['user_id'])).mappings()]
        content=json.dumps({'manifest':meta,'runs':runs,'materials':materials,'revisions':revisions,'imports':import_history},ensure_ascii=False,indent=2,default=str).encode();mime='application/json';ext='json'
    elif format in ('xlsx','wide'):
        w=Workbook();w.remove(w.active)
        if format=='xlsx':
            styled_sheet(w,'实验记录',HEADERS,main_table_rows(runs),MAIN_GROUPS,widths={33:191.2},freeze='E7')
            run_rows,step_rows,result_rows=detail_tables(runs)
            styled_sheet(w,'记录明细',RECORD_HEADERS,run_rows,RECORD_GROUPS,widths={18:30,19:30,21:40})
            styled_sheet(w,'源步骤明细',STEP_HEADERS,step_rows,STEP_GROUPS)
            styled_sheet(w,'结果明细',RESULT_HEADERS,result_rows,RESULT_GROUPS,widths={12:30})
        else:
            data=wide(runs);keys=list(data[0]) if data else ['meta_feature_schema_version','meta_exclusion_reasons']
            sheet(w,'建模宽表',keys,[[r.get(k) for k in keys] for r in data])
        sheet(w,'映射说明',['项目','内容'],[[k,v] for k,v in meta.items()])
        # One cell per group/step avoids Excel's 32767-character cell truncation.
        extras=[]
        def extra(run_id,kind,value):
            encoded=json.dumps(value,ensure_ascii=False)
            if excel_units(encoded)<=EXCEL_CELL_LIMIT:extras.append([run_id,kind,value]);return
            chunks=[encoded[i:i+8000] for i in range(0,len(encoded),8000)]
            for i,chunk in enumerate(chunks):extras.append([run_id,kind+'_fragment',{'fragment':i+1,'fragments':len(chunks),'encoding':'JSON text','text':chunk}])
        for run in runs:
            extra(run['run_id'],'environment',run['environment']);extra(run['run_id'],'sequence',{'sequence_id':run['sequence_id'],'previous_run_id':run['previous_run_id']})
            extra(run['run_id'],'program',{'outer_cycles':run['program']['outer_cycles'],'group_order':[g['group_id'] for g in run['program']['groups']]})
            for group in run['program']['groups']:
                extra(run['run_id'],'group',{**{k:v for k,v in group.items() if k!='steps'},'step_order':[s['step_id'] for s in group['steps']]})
                for step in group['steps']:extra(run['run_id'],'step',{'group_id':group['group_id'],**step})
            for r in run['results']:extra(run['run_id'],'result',r)
        sheet(w,'完整附加字段',['Run','类别','JSON'],extras)
        buffer=BytesIO();w.save(buffer);content=buffer.getvalue();mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';ext='xlsx'
    else:
        from .common import fail
        fail(422,'不支持的导出格式')
    sha=hashlib.sha256(content).hexdigest()
    db.execute(qt('exports').insert().values(export_id=eid,owner_user_id=user['user_id'],manifest=meta,sha256=sha))
    audit(db,user['user_id'],'export','process',None)
    filename=f'ale-{format}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}.{ext}'
    return Response(content,media_type=mime,headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}",'X-Content-SHA256':sha})
