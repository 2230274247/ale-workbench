#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALE 实验工作台 · API 契约校验器

功能:
  1. 解析 openapi.yaml 及其全部外部 $ref（多文件拆分）
  2. 打包为单一自包含的 openapi.bundled.yaml
  3. 用 openapi-spec-validator 做 OpenAPI 3.1 规范校验
  4. 交叉核对契约与真实 MySQL 表结构的字段对应关系
  5. 统计接口覆盖情况

用法:
  python validate_contract.py            # 校验 + 打包 + 交叉核对
  python validate_contract.py --no-db    # 跳过数据库核对
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
SPEC_DIR = BASE / "openapi"
SPEC_FILE = SPEC_DIR / "openapi.yaml"
BUNDLED = SPEC_DIR / "openapi.bundled.yaml"


# ----------------------------------------------------------------------
# $ref 解析与打包
# ----------------------------------------------------------------------
def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_pointer(doc, pointer):
    """按 JSON Pointer 取值。pointer 形如 /components/schemas/Foo。"""
    if pointer in ("", "/"):
        return doc
    parts = pointer.lstrip("/").split("/")
    cur = doc
    for p in parts:
        # JSON Pointer 转义
        p = p.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    return cur


def bundle(spec_path):
    """把多文件 spec 打包为单一文档，就地替换外部 $ref。"""
    root = load_yaml(spec_path)
    root_dir = Path(spec_path).parent
    root_name = Path(spec_path).name
    cache = {}

    def load_file(rel):
        # paths/*.yaml 里用 ../openapi.yaml 回指根文件，需特殊处理
        if Path(rel).name == root_name:
            return root
        if rel not in cache:
            cache[rel] = load_yaml(root_dir / rel)
        return cache[rel]

    def walk(node, src=None):
        """src 为当前所在文件的路径；用于把文件内 #/X 引用重写为全局路径。"""
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref = node["$ref"]
                if ref.startswith("./") or ref.startswith("../"):
                    file_part, _, frag = ref.partition("#")
                    target_doc = load_file(file_part)
                    resolved = resolve_pointer(target_doc, frag) if frag else target_doc
                    # 被引入内容中的文件内引用，其基准是该文件自身
                    result = walk(resolved, src=file_part)
                    return {**result, **{k: walk(v, src) for k, v in node.items() if k != "$ref"}}
                if ref.startswith("#/") and src and src != root_name:
                    # 组件文件内的局部引用，重写为全局 components 路径
                    frag = ref[2:]
                    # 已含 components/ 前缀的不动
                    if not frag.startswith("components/"):
                        return {**node, "$ref": f"#/components/schemas/{frag}"}
                    return node
                return node
            return {k: walk(v, src) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, src) for v in node]
        return node

    bundled = walk(root, src=root_name)
    return bundled


def check_refs_resolvable(spec_path):
    """检查所有外部 $ref 是否可解析（打包前的独立校验）。"""
    root = load_yaml(spec_path)
    root_dir = Path(spec_path).parent
    cache = {}
    errors = []
    checked = 0

    def walk(node, path=""):
        nonlocal checked
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref = node["$ref"]
                if ref.startswith("./") or ref.startswith("../"):
                    checked += 1
                    file_part, _, frag = ref.partition("#")
                    try:
                        if file_part not in cache:
                            cache[file_part] = load_yaml(root_dir / file_part)
                        if frag:
                            resolve_pointer(cache[file_part], frag)
                    except Exception as e:
                        errors.append(f"{path}: {ref} -> {type(e).__name__}: {e}")
                return
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}/{i}")

    walk(root)
    return checked, errors


# ----------------------------------------------------------------------
# 数据库交叉核对
# ----------------------------------------------------------------------
# 契约字段名 -> 数据库 (表, 列) 映射。用于验证接口字段真实存在。
FIELD_MAP = {
    # 通用
    "code": None, "message": None, "request_id": None, "timestamp": None,
    # users
    "user_id": ("users", "user_id"),
    "username": ("users", "username"),
    "display_name": ("users", "display_name"),
    "email": ("users", "email"),
    "role": ("users", "role"),
    "status": None,          # 多表共用
    "notes": None,           # 多表共用
    # batches
    "batch_id": ("batches", "batch_id"),
    "batch_code": ("batches", "batch_code"),
    "batch_name": ("batches", "batch_name"),
    "material": ("batches", "material"),
    "wafer_size": ("batches", "wafer_size"),
    "nominal_thickness_nm": ("batches", "nominal_thickness_nm"),
    "deposit_recipe_id": ("batches", "deposit_recipe_id"),
    "deposit_date": ("batches", "deposit_date"),
    "deposit_set_temp_c": ("batches", "deposit_set_temp_c"),
    "deposit_actual_temp_c": ("batches", "deposit_actual_temp_c"),
    "deposit_gas_flows": ("batches", "deposit_gas_flows"),
    "source_zip": ("batches", "source_zip"),
    "source_zip_sha256": ("batches", "source_zip_sha256"),
    "anomaly_flag": ("batches", "anomaly_flag"),
    "anomaly_note": ("batches", "anomaly_note"),
    "owner_user_id": ("batches", "owner_user_id"),
    # samples
    "sample_id": ("samples", "sample_id"),
    "sample_code": ("samples", "sample_code"),
    "parent_sample_id": ("samples", "parent_sample_id"),
    "sample_type": ("samples", "sample_type"),
    "display_label": ("samples", "display_label"),
    "size_desc": ("samples", "size_desc"),
    "cut_position": ("samples", "cut_position"),
    "surface_state": ("samples", "surface_state"),
    "pre_treatment": ("samples", "pre_treatment"),
    "exclude_from_analysis": ("samples", "exclude_from_analysis"),
    "exclude_reason": ("samples", "exclude_reason"),
    # Phase 2: row_version exists on several parents; expected is request-only.
    "row_version": None, "expected_row_version": None,
    "plan_step_id": ("process_steps", "plan_step_id"),
    "planned_parameters": ("experiment_plan_steps", "planned_parameters"),
    # plans
    "plan_id": ("experiment_plans", "plan_id"),
    "plan_code": ("experiment_plans", "plan_code"),
    "title": ("experiment_plans", "title"),
    "objective": ("experiment_plans", "objective"),
    "hypothesis": ("experiment_plans", "hypothesis"),
    "design_note": ("experiment_plans", "design_note"),
    "planned_start": ("experiment_plans", "planned_start"),
    "planned_end": ("experiment_plans", "planned_end"),
    "priority": ("experiment_plans", "priority"),
    # processes
    "process_id": ("processes", "process_id"),
    "process_code": ("processes", "process_code"),
    "plan_id_fk": ("processes", "plan_id"),
    "process_mode": ("processes", "process_mode"),
    "r1_temp_c": ("processes", "r1_temp_c"),
    "r2_temp_c": ("processes", "r2_temp_c"),
    "n2_flow_sccm": ("processes", "n2_flow_sccm"),
    "o3_pre_cycles": ("processes", "o3_pre_cycles"),
    "o3_pre_duration_s": ("processes", "o3_pre_duration_s"),
    "full_ale_cycles": ("processes", "full_ale_cycles"),
    "hf_tma_repeats": ("processes", "hf_tma_repeats"),
    "started_at": ("processes", "started_at"),
    "ended_at": ("processes", "ended_at"),
    "co_etch_group": ("processes", "co_etch_group"),
    "is_independent_run": ("processes", "is_independent_run"),
    "log_status": ("processes", "log_status"),
    # steps
    "step_id": ("process_steps", "step_id"),
    "step_index": ("process_steps", "step_index"),
    "step_kind": ("process_steps", "step_kind"),
    "chemistry": ("process_steps", "chemistry"),
    "cycles": ("process_steps", "cycles"),
    "cumulative_cycles": ("process_steps", "cumulative_cycles"),
    "duration_s": ("process_steps", "duration_s"),
    "pulse_s": ("process_steps", "pulse_s"),
    "purge_s": ("process_steps", "purge_s"),
    "wait_s": ("process_steps", "wait_s"),
    "actual_temp_c": ("process_steps", "actual_temp_c"),
    "delta_p": ("process_steps", "delta_p"),
    "delta_p_unit": ("process_steps", "delta_p_unit"),
    "o3_delta_p_kpa": ("process_steps", "o3_delta_p_kpa"),
    "hf_delta_p_pa": ("process_steps", "hf_delta_p_pa"),
    "tma_delta_p_pa": ("process_steps", "tma_delta_p_pa"),
    "o3_generator_o2_flow_set_sccm": ("process_steps", "o3_generator_o2_flow_set_sccm"),
    "o3_generator_o2_flow_measured_sccm": ("process_steps", "o3_generator_o2_flow_measured_sccm"),
    "o3_concentration": ("process_steps", "o3_concentration"),
    "o2_plasma_w": ("process_steps", "o2_plasma_w"),
    "o2_plasma_sccm": ("process_steps", "o2_plasma_sccm"),
    "o2_plasma_pa": ("process_steps", "o2_plasma_pa"),
    "step_note": ("process_steps", "step_note"),
    # process_samples
    "process_sample_id": ("process_samples", "process_sample_id"),
    "chamber_position": ("process_samples", "chamber_position"),
    "is_control": ("process_samples", "is_control"),
    "sample_role_note": ("process_samples", "sample_role_note"),
    # transitions
    "transition_id": ("sample_transitions", "transition_id"),
    "from_status": ("sample_transitions", "from_status"),
    "to_status": ("sample_transitions", "to_status"),
    "event_type": ("sample_transitions", "event_type"),
    "event_at": ("sample_transitions", "event_at"),
    "location": ("sample_transitions", "location"),
    "note": ("sample_transitions", "note"),
    # optical_models
    "model_id": ("optical_models", "model_id"),
    "model_code": ("optical_models", "model_code"),
    "model_name": ("optical_models", "model_name"),
    "rcp_name": ("optical_models", "rcp_name"),
    "spl_name": ("optical_models", "spl_name"),
    "n_setting": ("optical_models", "n_setting"),
    "k_setting": ("optical_models", "k_setting"),
    "layer_structure": ("optical_models", "layer_structure"),
    "aoi_deg": ("optical_models", "aoi_deg"),
    "valid_range_nm": ("optical_models", "valid_range_nm"),
    "applicable_batch_id": ("optical_models", "applicable_batch_id"),
    "quality_note": ("optical_models", "quality_note"),
    # measurements
    "measurement_id": ("measurements", "measurement_id"),
    "measurement_code": ("measurements", "measurement_code"),
    "optical_model_id": ("measurements", "optical_model_id"),
    "stage": ("measurements", "stage"),
    "stage_seq": ("measurements", "stage_seq"),
    "measured_at": ("measurements", "measured_at"),
    "operator_user_id": ("measurements", "operator_user_id"),
    "point_count": ("measurements", "point_count"),
    "thickness_mean_nm": ("measurements", "thickness_mean_nm"),
    "thickness_sd_nm": ("measurements", "thickness_sd_nm"),
    "thickness_min_nm": ("measurements", "thickness_min_nm"),
    "thickness_max_nm": ("measurements", "thickness_max_nm"),
    "mse_mean": ("measurements", "mse_mean"),
    "mse_max": ("measurements", "mse_max"),
    "gof_mean": ("measurements", "gof_mean"),
    "grid_desc": ("measurements", "grid_desc"),
    "supersedes_measurement_id": ("measurements", "supersedes_measurement_id"),
    "is_current": ("measurements", "is_current"),
    "supersede_reason": ("measurements", "supersede_reason"),
    "quality_flag": ("measurements", "quality_flag"),
    # points
    "point_id": ("measurement_points", "point_id"),
    "point_no": ("measurement_points", "point_no"),
    "x_mm": ("measurement_points", "x_mm"),
    "y_mm": ("measurement_points", "y_mm"),
    "thickness_nm": ("measurement_points", "thickness_nm"),
    "intensity": ("measurement_points", "intensity"),
    "height_mm": ("measurement_points", "height_mm"),
    "mse": ("measurement_points", "mse"),
    "gof": ("measurement_points", "gof"),
    "fit_iter": ("measurement_points", "fit_iter"),
    "lbh": ("measurement_points", "lbh"),
    "fit_time_ms": ("measurement_points", "fit_time_ms"),
    "dispersion_params": ("measurement_points", "dispersion_params"),
    "source_file_id": ("measurement_points", "source_file_id"),
    "source_sheet": ("measurement_points", "source_sheet"),
    "source_row": ("measurement_points", "source_row"),
    "source_cell": ("measurement_points", "source_cell"),
    "is_outlier": ("measurement_points", "is_outlier"),
    "outlier_note": ("measurement_points", "outlier_note"),
    # derived
    "result_id": ("derived_results", "result_id"),
    "result_code": ("derived_results", "result_code"),
    "result_kind": ("derived_results", "result_kind"),
    "before_measurement_id": ("derived_results", "before_measurement_id"),
    "after_measurement_id": ("derived_results", "after_measurement_id"),
    "value_nm": ("derived_results", "value_nm"),
    "value_unit": ("derived_results", "value_unit"),
    "value_sd_nm": ("derived_results", "value_sd_nm"),
    "cycles_basis": ("derived_results", "cycles_basis"),
    "pairing_method": ("derived_results", "pairing_method"),
    "paired_point_count": ("derived_results", "paired_point_count"),
    "model_consistent": ("derived_results", "model_consistent"),
    "is_valid": ("derived_results", "is_valid"),
    "evidence_level": ("derived_results", "evidence_level"),
    "computation_note": ("derived_results", "computation_note"),
    "computed_at": ("derived_results", "computed_at"),
    "computed_by": ("derived_results", "computed_by"),
    # source_files
    "file_id": ("source_files", "file_id"),
    "file_sha256": ("source_files", "file_sha256"),
    "file_name": ("source_files", "file_name"),
    "rel_path": ("source_files", "rel_path"),
    "file_role": ("source_files", "file_role"),
    "file_ext": ("source_files", "file_ext"),
    "size_bytes": ("source_files", "size_bytes"),
    "mtime_epoch": ("source_files", "mtime_epoch"),
    "is_readonly": ("source_files", "is_readonly"),
    "is_duplicate_of": ("source_files", "is_duplicate_of"),
    "parse_status": ("source_files", "parse_status"),
    "parse_note": ("source_files", "parse_note"),
    # findings / issues
    "finding_id": ("findings", "finding_id"),
    "finding_code": ("findings", "finding_code"),
    "statement": ("findings", "statement"),
    "support_sample_count": ("findings", "support_sample_count"),
    "is_confirmed": ("findings", "is_confirmed"),
    "scope_note": ("findings", "scope_note"),
    "created_by": ("findings", "created_by"),
    "issue_id": ("issues", "issue_id"),
    "issue_code": ("issues", "issue_code"),
    "severity": ("issues", "severity"),
    "observed": ("issues", "observed"),
    "effect": ("issues", "effect"),
    "action": ("issues", "action"),
    "avoid": ("issues", "avoid"),
    "opened_at": ("issues", "opened_at"),
    "closed_at": ("issues", "closed_at"),
    "link_id": ("issues_links", "link_id"),
    "entity_type": ("issues_links", "entity_type"),
    "entity_id": ("issues_links", "entity_id"),
    "relation": ("issues_links", "relation"),
    # instrument
    "dataset_id": ("instrument_datasets", "dataset_id"),
    "dataset_code": ("instrument_datasets", "dataset_code"),
    "instrument_type": ("instrument_datasets", "instrument_type"),
    "tool_id": ("instrument_datasets", "tool_id"),
    "external_ref": ("instrument_datasets", "external_ref"),
    "acquired_at": ("instrument_datasets", "acquired_at"),
    "acquisition_params": ("instrument_datasets", "acquisition_params"),
    "sample_mapping_status": ("instrument_datasets", "sample_mapping_status"),
    "mapping_note": ("instrument_datasets", "mapping_note"),
    "channel_id": ("instrument_channels", "channel_id"),
    "channel_code": ("instrument_channels", "channel_code"),
    "channel_label": ("instrument_channels", "channel_label"),
    "channel_type": ("instrument_channels", "channel_type"),
    "element": ("instrument_channels", "element"),
    "transition": ("instrument_channels", "transition"),
    "mass_charge": ("instrument_channels", "mass_charge"),
    "x_unit": ("instrument_channels", "x_unit"),
    "y_unit": ("instrument_channels", "y_unit"),
    "peak_center": ("instrument_channels", "peak_center"),
    "peak_height": ("instrument_channels", "peak_height"),
    "fwhm": ("instrument_channels", "fwhm"),
    "peak_area": ("instrument_channels", "peak_area"),
    "extra_json": ("instrument_channels", "extra_json"),
    "datapoint_id": ("instrument_datapoints", "datapoint_id"),
    "x_value": ("instrument_datapoints", "x_value"),
    "y_value": ("instrument_datapoints", "y_value"),
    # attachments / tools / recipes
    "attachment_id": ("attachments", "attachment_id"),
    "attachment_type": ("attachments", "attachment_type"),
    "mime_type": ("attachments", "mime_type"),
    "description": ("attachments", "description"),
    "uploaded_by": ("attachments", "uploaded_by"),
    "tool_code": ("tools", "tool_code"),
    "tool_name": ("tools", "tool_name"),
    "tool_type": ("tools", "tool_type"),
    "vendor": ("tools", "vendor"),
    "model": ("tools", "model"),
    "recipe_id": ("recipes", "recipe_id"),
    "recipe_code": ("recipes", "recipe_code"),
    "recipe_name": ("recipes", "recipe_name"),
    "recipe_kind": ("recipes", "recipe_kind"),
    "nominal_temp_c": ("recipes", "nominal_temp_c"),
    "nominal_pressure": ("recipes", "nominal_pressure"),
    "pressure_unit": ("recipes", "pressure_unit"),
    "nominal_gas_flows": ("recipes", "nominal_gas_flows"),
    "version": ("recipes", "version"),
    "created_at": ("users", "created_at"),
    "updated_at": ("users", "updated_at"),
}


def fetch_db_columns():
    sys.path.insert(0, str(BASE.parent / "database"))
    from apply_schema import load_admin_creds, connect  # noqa
    user, pw = load_admin_creds()
    conn = connect(user, pw, "ale_workbench")
    cols = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA='ale_workbench'")
        for t, c in cur.fetchall():
            cols.setdefault(t, set()).add(c)
    conn.close()
    return cols


def fetch_db_enums():
    """读取数据库 CHECK 约束中的枚举值集合。返回 {(表, 列): set(允许值)}。"""
    sys.path.insert(0, str(BASE.parent / "database"))
    from apply_schema import load_admin_creds, connect  # noqa
    user, pw = load_admin_creds()
    conn = connect(user, pw, "ale_workbench")
    out = {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE, tc.TABLE_NAME
            FROM information_schema.CHECK_CONSTRAINTS cc
            JOIN information_schema.TABLE_CONSTRAINTS tc
              ON tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME
             AND tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA
            WHERE cc.CONSTRAINT_SCHEMA='ale_workbench'
              AND tc.CONSTRAINT_TYPE='CHECK'""")
        for cname, clause, table in cur.fetchall():
            if not clause or " in (" not in clause.lower():
                continue
            # CHECK 约束的列名需从子句本身解析：`col` in ('a','b',...)
            m = re.match(r"\s*`?(\w+)`?\s+in\s*\(", clause, re.IGNORECASE)
            if not m:
                # 处理 (col is null) or (col in (...)) 形式
                m2 = re.search(r"`?(\w+)`?\s+in\s*\(", clause, re.IGNORECASE)
                if not m2:
                    continue
                col = m2.group(1)
            else:
                col = m.group(1)
            # Compound constraints (e.g. role+account_purpose) are not a pure
            # enumeration of one column; including them would attribute values
            # of a sibling column to this one. Only single-column clauses count.
            columns = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", clause))
            if columns - {col}:
                continue
            # MySQL 在 CHECK 子句里把单引号转义为 \' ，需先还原再提取
            normalized = clause.replace("\\'", "'")
            vals = set(re.findall(r"'([^']*)'", normalized))
            if vals:
                out.setdefault((table, col), set()).update(vals)
    conn.close()
    return out


def check_enum_consistency(bundled):
    """核对契约枚举值与数据库 CHECK 约束是否一致。

    重点检查 entity_type 这类在多个表中语义相同、约束却可能不同的字段。
    """
    db_enums = fetch_db_enums()
    problems = []
    checked = 0

    # 契约中枚举 Schema 名 -> 数据库 (表, 列) 列表
    ENUM_TARGETS = {
        "AIRequestStatus": [("ai_requests", "status")],
        "EntityType": [("issues_links", "entity_type")],
        "SampleStatus": [("samples", "status")],
        "SampleType": [("samples", "sample_type")],
        "ProcessMode": [("processes", "process_mode")],
        "MeasurementStage": [("measurements", "stage")],
        "MeasurementQualityFlag": [("measurements", "quality_flag")],
        "ImportJobStatus": [("import_jobs", "status")],
        "ImportItemStatus": [("import_items", "status")],
        "ResultKind": [("derived_results", "result_kind")],
        "EvidenceLevel": [("derived_results", "evidence_level"),
                          ("findings", "evidence_level")],
        "FileRole": [("source_files", "file_role")],
        "ParseStatus": [("source_files", "parse_status")],
        "BatchStatus": [("batches", "status")],
        "PlanStatus": [("experiment_plans", "status")],
        "PlanPriority": [("experiment_plans", "priority")],
        "UserRole": [("users", "role")],
        "UserStatus": [("users", "status")],
        "InstrumentType": [("instrument_datasets", "instrument_type")],
        "SampleMappingStatus": [("instrument_datasets", "sample_mapping_status")],
        "ChannelType": [("instrument_channels", "channel_type")],
        "AttachmentType": [("attachments", "attachment_type")],
        "ToolType": [("tools", "tool_type")],
        "ToolStatus": [("tools", "status")],
        "RecipeKind": [("recipes", "recipe_kind")],
        "RecipeStatus": [("recipes", "status")],
        "OpticalModelStatus": [("optical_models", "status")],
        "IssueSeverity": [("issues", "severity")],
        "IssueStatus": [("issues", "status")],
        "ProcessLogStatus": [("processes", "log_status")],
        "ProcessStepKind": [("process_steps", "step_kind")],
        "TransitionEventType": [("sample_transitions", "event_type")],
    }

    schemas = bundled["components"]["schemas"]
    for sname, targets in ENUM_TARGETS.items():
        s = schemas.get(sname)
        if not s or not s.get("enum"):
            continue
        contract_vals = set(s["enum"])
        for table, col in targets:
            db_vals = db_enums.get((table, col))
            if not db_vals:
                if (table, col) == ('tools', 'tool_type'):
                    print('  · ToolType: VARCHAR 无枚举 CHECK；由 API 验证允许值，不计入数据库枚举比较')
                    continue
                problems.append(f"{sname}: 数据库 {table}.{col} 缺少可核对的 CHECK 枚举约束")
                continue
            checked += 1
            extra = contract_vals - db_vals
            missing = db_vals - contract_vals
            if extra or missing:
                problems.append(
                    f"{sname}: 契约允许 {sorted(extra)}，"
                    f"但数据库 {table}.{col} 的 CHECK 约束不允许；数据库额外值 {sorted(missing)}")
    return checked, problems


def cross_check(bundled):
    """核对契约中的业务字段是否在数据库中存在。"""
    db = fetch_db_columns()
    problems = []
    verified = 0
    skipped = set()

    schemas = bundled["components"]["schemas"]
    for sname, schema in schemas.items():
        props = (schema or {}).get("properties") or {}
        for pname, prop in props.items():
            # Explicit per-schema mappings avoid ambiguous job/status/result/source fields.
            target = prop.get('x-db-column')
            if target is False:
                skipped.add(f'{sname}.{pname}')
                continue
            if target:
                table, column = target.split('.', 1)
                if table in db and column in db[table]:
                    verified += 1
                else:
                    problems.append(f"{sname}.{pname} -> 数据库中不存在 {target}")
                continue
            if pname in ("data", "meta", "token", "user", "permissions",
                         "data_scope", "access_token", "refresh_token",
                         "token_type", "expires_in", "refresh_expires_in",
                         "old_password", "new_password", "invite_code",
                         "password", "errors", "instance", "detail",
                         "rejected_value", "total_pages", "has_next",
                         "has_prev", "page", "size", "total", "points",
                         "steps", "samples", "channels", "datapoints",
                         "batch", "parent_sample", "child_samples", "process",
                         "tool", "plan", "owner", "supersedes", "superseded_by",
                         "before_measurement", "after_measurement", "links",
                         "series", "groups", "items", "warnings",
                         "unmatched_before", "unmatched_after", "mean_before_nm",
                         "mean_after_nm", "mean_delta_nm", "mean_r_nm",
                         "sd_delta_nm", "model_warning", "linked_entity_count",
                         "recent_samples", "recent_processes", "recent_measurements",
                         "n_measurements", "n_derived_results",
                         "n_instrument_datasets", "n_linked_issues",
                         "linked_issues", "measurement_count", "point_count_total",
                         "first_measured_at", "last_measured_at",
                         "inserted_count", "recomputed_count", "results",
                         "invalidated_derived_results", "replacement_measurement_id",
                         "recomputed", "measurement", "sample_count", "step_count",
                         "channel_count", "process_count", "matched", "unknown",
                         "files", "points_count", "metric", "value", "x_range",
                         "y_range", "value_range", "group_key", "group_label",
                         "exceeds_threshold", "batch_nominal_nm",
                         "sample_status", "model_id", "generated_at",
                         "total_count", "template_code", "chart_type",
                         "data_source", "required_params", "name",
                         "format", "params", "sample_ids", "result_ids",
                         "process_ids", "metric_name", "point_count",
                         "rejected", "detail_msg", "exclude_duplicates"):
                skipped.add(pname)
                continue
            if pname in FIELD_MAP:
                target = FIELD_MAP[pname]
                if target is None:
                    skipped.add(pname)
                    continue
                t, c = target
                if t in db and c in db[t]:
                    verified += 1
                else:
                    problems.append(f"{sname}.{pname} -> 数据库中不存在 {t}.{c}")
            else:
                skipped.add(pname)
    return verified, problems, sorted(skipped)


def check_phase1_contract(spec):
    """Enforce conventions that permissive OpenAPI validation alone cannot catch."""
    problems = []
    def walk(node, path=""):
        if isinstance(node, dict):
            if "nullable" in node:
                problems.append(f"{path}: OpenAPI 3.1 must use type/anyOf null")
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")
    walk(spec)
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                if op.get("x-implementation-status") not in ("implemented", "planned"):
                    problems.append(f"{method} {path}: missing implementation status")
    ids = [op.get('operationId') for item in spec.get('paths', {}).values() for method, op in item.items() if method in ('get','post','put','patch','delete')]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        problems.append('operationId must be present and unique')
    # Phase 2 requests must stay separate from server-owned response entities.
    schemas = spec.get('components', {}).get('schemas', {})
    requests = ('PlanCreate', 'PlanUpdate', 'PlanStepCreate', 'PlanStepUpdate',
                'ProcessCreate', 'ProcessUpdate', 'ProcessStepCreate', 'ProcessStepUpdate',
                'ProcessSampleCreate', 'ProcessSampleUpdate', 'TransitionCreate')
    for name in requests:
        schema = schemas.get(name, {})
        if schema.get('additionalProperties') is not False:
            problems.append(f'{name}: request must reject undeclared fields')
        for field in ('row_version', 'created_at', 'updated_at', 'operator_user_id', 'owner_user_id'):
            if field in schema.get('properties', {}):
                problems.append(f'{name}: server-owned field {field} in request')
    if 'expected_row_version' not in schemas.get('TransitionCreate', {}).get('required', []):
        problems.append('TransitionCreate: expected_row_version must be required')
    for name in ('PlanStepCreate', 'ProcessStepCreate'):
        if not {'step_index', 'step_kind'} <= set(schemas.get(name, {}).get('required', [])):
            problems.append(f'{name}: client step_index/step_kind must be required')
    # Read actual registered APIRouter decorators; never execute backend or DB writes.
    backend = BASE.parent / 'backend' / 'app'
    if backend.is_dir():
        routes = set()
        main_tree = ast.parse((backend / 'main.py').read_text(encoding='utf-8'))
        registered = set()
        for node in ast.walk(main_tree):
            if isinstance(node, ast.Attribute) and node.attr == 'router' and isinstance(node.value, ast.Name):
                registered.add(node.value.id)
        for module in sorted(registered):
            source = backend / f'{module}.py'
            if not source.exists():
                continue
            tree = ast.parse(source.read_text(encoding='utf-8'))
            prefix = ''
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'APIRouter':
                    prefix = next((ast.literal_eval(k.value) for k in node.keywords if k.arg == 'prefix'), '')
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for deco in node.decorator_list:
                    if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                            and isinstance(deco.func.value, ast.Name) and deco.func.value.id == 'router'
                            and deco.func.attr in ('get', 'post', 'put', 'patch', 'delete')):
                        route = prefix + ast.literal_eval(deco.args[0])
                        if route == '/api/v1/{kind}/{id}/process-grid':
                            routes.update((route.replace('{kind}', kind), deco.func.attr) for kind in ('plans','processes'))
                        else:
                            routes.add((route, deco.func.attr))
        documented = {(path, method): op for path, item in spec.get('paths', {}).items()
                      for method, op in item.items() if method in ('get','post','put','patch','delete')}
        for route in routes:
            if documented.get(route, {}).get('x-implementation-status') != 'implemented':
                problems.append(f'{route}: actual registered route must be documented implemented')
        for route, op in documented.items():
            if op.get('x-implementation-status') == 'implemented' and route not in routes:
                problems.append(f'{route}: implemented marker has no registered route')
    expected_requests = ('ImportPreviewRequest', 'ImportChoice', 'ImportConfirmation',
                         'MeasurementUpdate', 'MeasurementSupersedeRequest')
    for name in expected_requests:
        if schemas.get(name, {}).get('additionalProperties') is not False:
            problems.append(f'{name}: request must reject undeclared fields')
    quality = schemas.get('MeasurementUpdate', {})
    if set(quality.get('properties', {})) != {'expected_row_version', 'quality_flag', 'quality_note'}:
        problems.append('MeasurementUpdate: quality-only fields required')
    if 'expected_row_version' not in quality.get('required', []):
        problems.append('MeasurementUpdate: expected_row_version required')
    supersede = schemas.get('MeasurementSupersedeRequest', {})
    if set(supersede.get('required', [])) != {'replacement_measurement_id', 'expected_row_version',
                                            'expected_replacement_row_version', 'reason'}:
        problems.append('Supersede: replacement, both versions and reason required')
    for path, method in [('/api/v1/source-files/verify','post'),('/api/v1/source-files','post'),
                         ('/api/v1/source-files/{id}','patch'),('/api/v1/measurements','post'),
                         ('/api/v1/instrument-datasets','post')]:
        if spec.get('paths', {}).get(path, {}).get(method, {}).get('x-implementation-status') != 'planned':
            problems.append(f'{method} {path}: unimplemented route must stay planned')
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args()

    print("=" * 68)
    print("ALE 工作台 API 契约校验")
    print("=" * 68)

    # 1. $ref 可解析性
    checked, errors = check_refs_resolvable(SPEC_FILE)
    print(f"\n[1] 外部 $ref 解析: 检查 {checked} 个")
    if errors:
        print("  [×] 存在无法解析的引用:")
        for e in errors[:20]:
            print(f"      {e}")
        return 1
    print("  ✓ 全部外部 $ref 可解析")

    # 2. 打包
    bundled = bundle(SPEC_FILE)
    with open(BUNDLED, "w", encoding="utf-8") as f:
        yaml.safe_dump(bundled, f, allow_unicode=True, sort_keys=False, width=1000)
    print(f"\n[2] 打包为单文件: {BUNDLED.name} ({BUNDLED.stat().st_size // 1024} KB)")

    convention_errors = check_phase1_contract(bundled)
    if convention_errors:
        for error in convention_errors:
            print(f"  [×] {error}")
        return 1

    # 3. OpenAPI 3.1 规范校验
    print("\n[3] OpenAPI 3.1 规范校验:")
    try:
        from openapi_spec_validator import validate
        validate(bundled)
        print("  ✓ 通过 OpenAPI 3.1 规范校验")
    except Exception as e:
        msg = str(e)
        print(f"  [×] 校验失败: {type(e).__name__}")
        print(f"      {msg[:600]}")
        return 1

    # 4. 统计
    paths = bundled.get("paths", {})
    n_ops = sum(1 for p in paths.values() for m in p
                if m in ("get", "post", "put", "patch", "delete"))
    schemas = bundled.get("components", {}).get("schemas", {})
    print(f"\n[4] 契约规模:")
    print(f"  路径          {len(paths)}")
    print(f"  操作(端点)    {n_ops}")
    print(f"  Schema 定义   {len(schemas)}")
    print(f"  Tag 分组      {len(bundled.get('tags', []))}")
    print(f"  错误响应组件  {len(bundled.get('components', {}).get('responses', {}))}")

    # 按模块统计
    print("\n  按模块:")
    tag_count = {}
    for p, item in paths.items():
        for m, op in item.items():
            if m not in ("get", "post", "put", "patch", "delete"):
                continue
            for t in op.get("tags", []):
                tag_count[t] = tag_count.get(t, 0) + 1
    for t, n in sorted(tag_count.items(), key=lambda x: -x[1]):
        print(f"    {t:12s} {n:2d} 个端点")

    # 5. 数据库交叉核对
    if not args.no_db:
        print("\n[5] 与数据库字段交叉核对:")
        try:
            verified, problems, skipped = cross_check(bundled)
            print(f"  ✓ 已验证对应字段: {verified} 个")
            print(f"  · 非数据库字段(计算/包装字段): {len(skipped)} 个")
            if problems:
                print(f"  [×] 存在 {len(problems)} 处不匹配:")
                for p in problems[:20]:
                    print(f"      {p}")
                return 1
            print("  ✓ 契约字段全部与数据库对应")
        except Exception as e:
            print(f"  [×] 数据库核对失败: {type(e).__name__}: {e}")
            return 1

        print("\n[6] 枚举值与数据库 CHECK 约束一致性:")
        try:
            n_enum, enum_problems = check_enum_consistency(bundled)
            print(f"  · 已核对枚举字段: {n_enum} 处")
            if enum_problems:
                print(f"  [!] 发现 {len(enum_problems)} 处不一致"
                      f"（接口允许的值会被数据库拒绝）:")
                for p in enum_problems:
                    print(f"      {p}")
                print("  [×] 枚举不匹配；数据库迁移或契约修订完成后重试。")
                return 1
            else:
                print("  ✓ 枚举值全部一致")
        except Exception as e:
            print(f"  [×] 枚举核对失败: {type(e).__name__}: {e}")
            return 1

    print("\n" + "=" * 68)
    print("✓ 契约校验通过" + ("（--no-db：未核对数据库）" if args.no_db else ""))
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
