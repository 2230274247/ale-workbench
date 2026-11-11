#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALE 实验工作台 · 共享数据模型生成器

从打包后的 OpenAPI 契约生成:
  - models/typescript/api.d.ts   前端 TypeScript 类型定义
  - models/python/schemas.py     后端 Pydantic 模型

关键类型映射（前后端一致）:
  数据库 DECIMAL (契约中为 string + x-db-type) → TS: string  | Python: Decimal
  数据库 TINYINT(1)                            → TS: boolean | Python: bool
  数据库 DATETIME                              → TS: string  | Python: datetime
  数据库 DATE                                  → TS: string  | Python: date
  数据库 JSON                                  → TS: Record<string, unknown> | Python: dict

**DECIMAL 一律映射为 string（TS）/ Decimal（Python）**，
不使用 number/float，避免精度损失——
数据库存的是 DECIMAL(14,6) 等定点类型，转 float 会失真。

用法: python gen_models.py
"""

import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
BUNDLED = BASE / "openapi" / "openapi.bundled.yaml"
TS_OUT = BASE / "models" / "typescript" / "api.d.ts"
PY_OUT = BASE / "models" / "python" / "schemas.py"


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def ref_name(ref):
    """#/components/schemas/Foo -> Foo"""
    return ref.split("/")[-1]


def is_decimal(schema):
    return "x-db-type" in schema and str(schema["x-db-type"]).startswith("decimal")


def ts_type(schema, schemas):
    """把 OpenAPI schema 映射为 TypeScript 类型。"""
    if not isinstance(schema, dict):
        return "unknown"
    if "const" in schema:
        return json.dumps(schema["const"])
    if "$ref" in schema:
        return ref_name(schema["$ref"])
    if "allOf" in schema:
        return " & ".join(ts_type(s, schemas) for s in schema["allOf"])
    if "oneOf" in schema:
        return " | ".join(ts_type(s, schemas) for s in schema["oneOf"])
    if "anyOf" in schema:
        return " | ".join(ts_type(s, schemas) for s in schema["anyOf"])

    t = schema.get("type")
    if isinstance(t, list):
        parts = [ts_type({**schema, "type": x}, schemas) for x in t]
        return " | ".join(dict.fromkeys(parts))

    if t == "null":
        return "null"
    if is_decimal(schema):
        return "string"
    if t == "string":
        if schema.get("enum"):
            return " | ".join(json.dumps(e, ensure_ascii=False) for e in schema["enum"])
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        if schema.get("enum"):
            return " | ".join(json.dumps(e) for e in schema["enum"])
        return "boolean"
    if t == "array":
        item = ts_type(schema.get("items", {}), schemas)
        if "|" in item and not item.startswith("("):
            item = f"({item})"
        return f"{item}[]"
    if t == "object" or "properties" in schema:
        if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
            return f"Record<string, {ts_type(schema['additionalProperties'], schemas)}>"
        if "properties" in schema:
            fields = "; ".join(
                f"{'readonly ' if v.get('readOnly') else ''}{json.dumps(k) if not k.isidentifier() else k}{'?' if k not in (schema.get('required') or []) else ''}: "
                f"{ts_type(v, schemas)}"
                for k, v in schema["properties"].items()
            )
            return "{ " + fields + " }"
        return "Record<string, unknown>"
    return "unknown"


def py_type(schema, schemas, for_optional=False):
    """把 OpenAPI schema 映射为 Python/Pydantic 类型注解。"""
    if not isinstance(schema, dict):
        return "Any"
    if "const" in schema:
        return "Literal[" + repr(schema["const"]) + "]"
    if schema.get("x-python-type"):
        return schema["x-python-type"]
    if "$ref" in schema:
        name = ref_name(schema["$ref"])
        target = schemas.get(name, {})
        if target.get("type") in ("string", "integer", "number") and not target.get("enum"):
            return py_item_type(target, schemas)
        return name
    if "allOf" in schema:
        raise ValueError("Inline allOf must be promoted to a named model before generation")
    if "oneOf" in schema or "anyOf" in schema:
        key = "oneOf" if "oneOf" in schema else "anyOf"
        return " | ".join(py_type(s, schemas) for s in schema[key])

    t = schema.get("type")
    if isinstance(t, list):
        parts = [py_type({**schema, "type": x}, schemas) for x in t]
        return " | ".join(dict.fromkeys(parts))

    if t == "null":
        return "None"
    if is_decimal(schema):
        if schema.get('pattern'):
            return f"Annotated[Decimal, BeforeValidator(_decimal_input({schema['pattern']!r}))]"
        return "Decimal"
    if t == "string":
        if schema.get("enum"):
            return "Literal[" + ", ".join(repr(e) for e in schema["enum"]) + "]"
        if schema.get("format") == "uuid":
            return "uuid.UUID"
        if schema.get("format") == "date-time":
            return "datetime"
        if schema.get("format") == "date":
            return "date"
        return "str"
    if t == "integer":
        return "Annotated[int, Field(strict=True)]" if schema.get("x-python-strict") else "int"
    if t == "number":
        return "float"
    if t == "boolean":
        if schema.get("enum"):
            return "Literal[" + ", ".join(repr(e) for e in schema["enum"]) + "]"
        return "bool"
    if t == "array":
        return f"list[{py_item_type(schema.get('items', {}), schemas)}]"
    if t == "object" or "properties" in schema:
        if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
            return f"dict[str, {py_type(schema['additionalProperties'], schemas)}]"
        if "properties" in schema:
            return "dict[str, Any]"
        return "dict[str, Any]"
    return "Any"


def py_item_type(schema, schemas):
    value = py_type(schema, schemas)
    constraints = {target: schema[source] for source, target in
                   (("minLength", "min_length"), ("maxLength", "max_length"),
                    ("minimum", "ge"), ("maximum", "le"), ("exclusiveMinimum", "gt"),
                    ("exclusiveMaximum", "lt"), ("pattern", "pattern")) if source in schema}
    if constraints:
        return "Annotated[" + value + ", Field(" + ", ".join(f"{k}={v!r}" for k,v in constraints.items()) + ")]"
    return value


def flatten_object(schema, schemas):
    """Combine object allOf members, including referenced and inline extensions."""
    if "$ref" in schema:
        return flatten_object(schemas[ref_name(schema["$ref"])], schemas)
    merged = {k: v for k, v in schema.items() if k != "allOf"}
    props = {}
    required = []
    for member in schema.get("allOf", []):
        obj = flatten_object(member, schemas)
        props.update(obj.get("properties", {}))
        required.extend(obj.get("required", []))
    props.update(schema.get("properties", {}))
    required.extend(schema.get("required", []))
    merged.update(type="object", properties=props, required=list(dict.fromkeys(required)))
    return merged


# ----------------------------------------------------------------------
# TypeScript 生成
# ----------------------------------------------------------------------
def gen_typescript(schemas):
    L = []
    L.append("// =====================================================================")
    L.append("// ALE 实验工作台 · API 类型定义")
    L.append("// 由 tools/gen_models.py 从 openapi.bundled.yaml 自动生成，请勿手工修改")
    L.append("// ---------------------------------------------------------------------")
    L.append("// 类型约定:")
    L.append("//   数据库 DECIMAL 字段映射为 string（不是 number）——")
    L.append("//   数据库存的是 DECIMAL(14,6) 等定点类型，转 JS number 会精度失真。")
    L.append("//   数据库 DATETIME 映射为 string（ISO 8601 含时区）。")
    L.append("//   数据库 DATE 映射为 string（YYYY-MM-DD）。")
    L.append("// =====================================================================")
    L.append("")
    L.append("/** 统一响应包络。JSON 接口（含错误）返回此结构；204 无 body，原件下载成功为二进制。 */")
    L.append("export interface ApiEnvelope<T = unknown> {")
    L.append("  /** 业务状态码。0 表示成功。前端以此为准，而非 HTTP 状态码 */")
    L.append("  code: number;")
    L.append("  /** 提示信息（中文）。成功时为 'ok' */")
    L.append("  message: string;")
    L.append("  /** 业务数据。错误时为 null 或 ErrorDetail */")
    L.append("  data: T | null;")
    L.append("  /** 请求追踪 ID，排障时用于定位日志 */")
    L.append("  request_id: string;")
    L.append("  /** 服务端响应时间（ISO 8601） */")
    L.append("  timestamp: string;")
    L.append("}")
    L.append("")
    L.append("/** 分页元信息 */")
    L.append("export interface PageMeta {")
    L.append("  page: number;")
    L.append("  size: number;")
    L.append("  total: number;")
    L.append("  total_pages: number;")
    L.append("  has_next: boolean;")
    L.append("  has_prev: boolean;")
    L.append("}")
    L.append("")
    L.append("/** 分页响应 */")
    L.append("export interface PagedData<T> extends ApiEnvelope<T[]> {")
    L.append("  data: T[];")
    L.append("  meta: PageMeta;")
    L.append("}")
    L.append("")
    L.append("/** 字段级校验错误 */")
    L.append("export interface FieldError {")
    L.append("  field: string;")
    L.append("  message: string;")
    L.append("  rejected_value?: unknown;")
    L.append("}")
    L.append("")
    L.append("/** 错误详情（兼容 RFC 9457 Problem Details） */")
    L.append("export interface ErrorDetail {")
    L.append("  type: string;")
    L.append("  title: string;")
    L.append("  status: number;")
    L.append("  code: number;")
    L.append("  detail?: string;")
    L.append("  instance?: string;")
    L.append("  errors?: FieldError[];")
    L.append("}")
    L.append("")
    L.append("// ---------------------------------------------------------------------")
    L.append("// 契约模型包含 planned 结构；类型存在不表示对应接口已实现。")
    L.append("// 业务实体")
    L.append("// ---------------------------------------------------------------------")

    skip = {"ApiEnvelope", "PageMeta", "ErrorDetail", "FieldError"}
    for name in sorted(schemas, key=lambda n: (not bool(schemas[n].get("enum")), n)):
        if name in skip:
            continue
        s = schemas[name]
        if not isinstance(s, dict):
            continue

        desc = (s.get("description") or "").strip().split("\n")[0]
        L.append("")
        if desc:
            L.append(f"/** {desc} */")
        if s.get("enum"):
            vals = " | ".join(json.dumps(e, ensure_ascii=False) for e in s["enum"])
            L.append(f"export type {name} = {vals};")
            continue
        if s.get("type") in ("string", "integer", "number", "boolean"):
            L.append(f"export type {name} = {ts_type(s, schemas)};")
            continue
        if "allOf" in s:
            base = " & ".join(ts_type(x, schemas) for x in s["allOf"])
            L.append(f"export type {name} = {base};")
            continue

        props = s.get("properties")
        if not props:
            L.append(f"export type {name} = {ts_type(s, schemas)};")
            continue
        required = set(s.get("required") or [])
        L.append(f"export interface {name} {{")
        for k, v in props.items():
            pdesc = (v.get("description") or "").strip().split("\n")[0]
            if pdesc:
                L.append(f"  /** {pdesc} */")
            opt = "" if k in required else "?"
            L.append(f"  {'readonly ' if v.get('readOnly') else ''}{json.dumps(k) if not k.isidentifier() else k}{opt}: {ts_type(v, schemas)};")
        L.append("}")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------
# Python / Pydantic 生成
# ----------------------------------------------------------------------
def gen_python(schemas):
    L = []
    L.append('"""')
    L.append("ALE 实验工作台 · Pydantic 数据模型")
    L.append("")
    L.append("由 tools/gen_models.py 从 openapi.bundled.yaml 自动生成，请勿手工修改。")
    L.append("")
    L.append("类型约定:")
    L.append("  数据库 DECIMAL 字段映射为 Decimal（不是 float）——")
    L.append("  数据库存的是 DECIMAL(14,6) 等定点类型，转 float 会精度失真。")
    L.append("  数据库 DATETIME 映射为 datetime，DATE 映射为 date。")
    L.append("契约包含 planned 模型；模型存在不代表路由或科研写入已经实现。")
    L.append('"""')
    L.append("")
    L.append("from __future__ import annotations")
    L.append("")
    L.append("from datetime import date, datetime")
    L.append("from decimal import Decimal")
    L.append("from typing import Any, Literal, Generic, TypeVar, Annotated")
    L.append("import re")
    L.append("import uuid")
    L.append("")
    L.append("from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, model_validator, field_validator, SecretStr")
    L.extend(["", "def validate_endpoint(value):", "    from urllib.parse import urlsplit", "    import ipaddress", "    try:", "        p = urlsplit(value)", "        if (p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment", "                or p.port not in (None, 443) or '\\\\' in value or '%' in p.netloc", "                or not re.fullmatch(r'[A-Za-z0-9.:-]+|\\[[A-Fa-f0-9:]+\\]', p.netloc)", "                or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/*', p.path)):", "            raise ValueError()", "        host = p.hostname.lower()", "        if host == 'localhost' or '.' not in host and ':' not in host: raise ValueError()", "        try:", "            if not ipaddress.ip_address(host).is_global: raise ValueError()", "        except ValueError:", "            if ':' in host or re.fullmatch(r'[0-9.]+', host): raise ValueError()", "        return value.rstrip('/')", "    except (ValueError, TypeError):", "        raise ValueError('A public HTTPS provider endpoint is required') from None", ""])
    L.append("")
    L.append("def _decimal_input(pattern):")
    L.append("    def check(value):")
    L.append("        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:")
    L.append("            raise ValueError('Decimal must be a plain decimal string within precision and scale')")
    L.append("        return Decimal(value)")
    L.append("    return check")
    L.append("")
    L.append("")
    L.append("class ApiBaseModel(BaseModel):")
    L.append('    """所有模型基类。允许从 ORM 对象构造，忽略未声明字段。"""')
    L.append("")
    L.append("    model_config = ConfigDict(")
    L.append("        from_attributes=True,")
    L.append("        extra='ignore',")
    L.append("        populate_by_name=True,")
    L.append("    )")
    L.append("")
    L.append("")
    L.append("class PageMeta(ApiBaseModel):")
    L.append('    """分页元信息。"""')
    L.append("    page: int")
    L.append("    size: int")
    L.append("    total: int")
    L.append("    total_pages: int")
    L.append("    has_next: bool")
    L.append("    has_prev: bool")
    L.append("")
    L.append("T = TypeVar('T')")
    L.append("class ApiEnvelope(ApiBaseModel, Generic[T]):")
    L.append("    code: int")
    L.append("    message: str")
    L.append("    data: T | None = None")
    L.append("    request_id: str")
    L.append("    timestamp: datetime")
    L.append("")
    L.append("class PagedData(ApiEnvelope[list[T]], Generic[T]):")
    L.append("    data: list[T]")
    L.append("    meta: PageMeta")
    L.append("")
    L.append("class FieldError(ApiBaseModel):")
    L.append('    """字段级校验错误。"""')
    L.append("    field: str")
    L.append("    message: str")
    L.append("    rejected_value: Any | None = None")
    L.append("")
    L.append("")
    L.append("class ErrorDetail(ApiBaseModel):")
    L.append('    """错误详情（兼容 RFC 9457 Problem Details）。"""')
    L.append("    type: str")
    L.append("    title: str")
    L.append("    status: int")
    L.append("    code: int")
    L.append("    detail: str | None = None")
    L.append("    instance: str | None = None")
    L.append("    errors: list[FieldError] | None = None")
    L.append("")
    L.append("")

    skip = {"ApiEnvelope", "PageMeta", "ErrorDetail", "FieldError"}
    for name in sorted(schemas, key=lambda n: (not bool(schemas[n].get("enum")), n)):
        if name in skip:
            continue
        s = schemas[name]
        if not isinstance(s, dict):
            continue

        if s.get("x-python-definition"):
            L.extend(["", re.sub(r"default_factory=([A-Z]\w*)", r"default_factory=lambda: \1()", s["x-python-definition"])])
            continue
        desc = (s.get("description") or "").strip().split("\n")[0].replace('"""', "'''")
        L.append("")
        if s.get("enum"):
            vals = ", ".join(repr(e) for e in s["enum"])
            L.append(f"{name} = Literal[{vals}]")
            continue
        if "allOf" in s:
            s = flatten_object(s, schemas)
        props = s.get("properties")
        if not props:
            t = py_type(s, schemas)
            if t in ("str", "int", "float", "bool", "Decimal"):
                L.append(f"{name} = {t}")
            else:
                L.append(f"{name} = Any")
            continue

        L.append(f"class {name}(ApiBaseModel):")
        if desc:
            L.append(f'    """{desc}"""')
        config = []
        if s.get("additionalProperties") is False:
            config.append("extra='forbid'")
        if s.get("x-python-validate-default"):
            config.append("validate_default=True")
        if s.get('x-python-strict'):
            config.append('strict=True')
        if s.get('x-python-strip-whitespace'):
            config.append('str_strip_whitespace=True')
        if config:
            L.append("    model_config = ConfigDict(" + ", ".join(config) + ")")
        required = set(s.get("required") or [])
        for k, v in props.items():
            t = py_type(v, schemas)
            constraints = {}
            bounds = v
            if 'anyOf' in v:
                variants = [x for x in v['anyOf'] if x.get('type') != 'null']
                if len(variants) == 1:
                    bounds = {**variants[0], **v}
            if v.get('x-python-type') == 'SecretStr | None':
                bounds = {}  # SecretStr validation is enforced by the backend-matching key validator.
            field_name = re.sub(r'\W', '_', k).strip('_')
            if field_name != k:
                constraints['alias'] = k
            for source, target in (("minLength", "min_length"), ("maxLength", "max_length"),
                                   ("minimum", "ge"), ("maximum", "le"), ("pattern", "pattern"),
                                   ("exclusiveMinimum", "gt"), ("exclusiveMaximum", "lt"),
                                   ("minItems", "min_length"), ("maxItems", "max_length")):
                if source in bounds and not (source == 'pattern' and is_decimal(bounds)):
                    constraints[target] = bounds[source]
            if v.get('x-python-exclude'):
                constraints['exclude'] = True
                constraints['repr'] = False
            if v.get('x-python-strict'):
                constraints['strict'] = True
            if '$ref' in v and 'default' in v:
                constraints['validate_default'] = True
            if "description" in v:
                constraints["description"] = v["description"].strip()
            default = "..." if k in required else repr(v.get("default"))
            if constraints:
                args = ", ".join(f"{key}={value!r}" for key, value in constraints.items())
                L.append(f"    {field_name}: {t} = Field({default}, {args})")
            else:
                L.append(f"    {field_name}: {t}" + ("" if k in required else f" = {default}"))
        L.extend(s.get("x-python-methods", []))
        if s.get('x-unique-item-key'):
            key = s['x-unique-item-key']
            L.extend(["", "    @model_validator(mode='after')", "    def unique_items(self):",
                      f"        if len({{getattr(item, {key!r}) for item in self.items}}) != len(self.items):",
                      f"            raise ValueError('Duplicate {key}')", "        return self"])
        if s.get('x-at-least-one-fields'):
            fields = set(s['x-at-least-one-fields'])
            L.extend(["", "    @model_validator(mode='after')", "    def has_change(self):",
                      f"        if not self.model_fields_set.intersection({fields!r}):",
                      "            raise ValueError('Supply at least one update field')", "        return self"])
        unique = s.get('x-unique-list-key')
        if unique:
            field, key = unique['field'], unique['key']
            L.extend(["", f"    @field_validator({field!r})", "    @classmethod",
                      f"    def unique_{field}(cls, values):",
                      f"        if len({{getattr(item, {key!r}) for item in values}}) != len(values):",
                      f"            raise ValueError('Duplicate {key}')", "        return values"])
        for field in s.get('x-nonblank-fields', []):
            L.extend(["", f"    @field_validator({field!r})", "    @classmethod",
                      f"    def nonblank_{field}(cls, value):", "        if not value.strip():",
                      "            raise ValueError('Nonblank value required')", "        return value.strip()"])

    L.append("")
    for name, schema in schemas.items():
        if "oneOf" in schema or "anyOf" in schema:
            L.append(f"{name} = {py_type(schema, schemas)}")
    L.append("# Resolve forward annotations only after every model has been defined.")
    L.append("for _model in list(globals().values()):")
    L.append("    if isinstance(_model, type) and _model is not BaseModel and issubclass(_model, BaseModel):")
    L.append("        _model.model_rebuild(_types_namespace=globals())")
    return "\n".join(L) + "\n"


def main():
    if not BUNDLED.exists():
        print(f"[×] 未找到 {BUNDLED}，请先运行 validate_contract.py", file=sys.stderr)
        return 1
    with open(BUNDLED, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    schemas = spec["components"]["schemas"]

    TS_OUT.parent.mkdir(parents=True, exist_ok=True)
    PY_OUT.parent.mkdir(parents=True, exist_ok=True)

    ts = gen_typescript(schemas)
    TS_OUT.write_text(ts, encoding="utf-8")
    print(f"✓ {TS_OUT}  ({len(ts.splitlines())} 行)")

    py = gen_python(schemas)
    PY_OUT.write_text(py, encoding="utf-8")
    print(f"✓ {PY_OUT}  ({len(py.splitlines())} 行)")

    print(f"\n共 {len(schemas)} 个 Schema 定义")
    return 0


if __name__ == "__main__":
    sys.exit(main())
