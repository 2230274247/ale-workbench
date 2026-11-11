#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALE 实验工作台 · ER 图生成器

从 information_schema 读取真实表结构，生成:
  - er_diagram.svg   矢量 ER 图（分层布局，含外键连线）
  - er_diagram.mmd   Mermaid 源码（可在支持 Mermaid 的编辑器中打开）
  - er_diagram.html  自包含 HTML（浏览器直接打开，Mermaid CDN 渲染）

用法: python gen_erd.py
输出: H:\\ALE_AI\\reports\\er_diagram.*
"""

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_schema import load_admin_creds, connect  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "reports"

# 分层定义：决定 ER 图的列布局
LAYERS = [
    ("权限与元数据", ["users", "tools", "recipes"]),
    ("批次与样品",   ["batches", "samples", "experiment_plans"]),
    ("工艺执行",     ["processes", "process_steps", "process_samples", "sample_transitions"]),
    ("测量与模型",   ["optical_models", "measurements", "measurement_points"]),
    ("溯源与派生",   ["source_files", "derived_results"]),
    ("台账",         ["findings", "issues", "issues_links"]),
    ("仪器扩展",     ["instrument_datasets", "instrument_channels", "instrument_datapoints"]),
    ("辅助",         ["attachments", "audit_log"]),
]

# 每张表在图上展示的关键字段
KEY_COLS = {
    "users":            ["user_id", "username", "role"],
    "tools":            ["tool_id", "tool_code", "tool_type"],
    "recipes":          ["recipe_id", "recipe_code", "recipe_kind"],
    "batches":          ["batch_id", "batch_code", "nominal_thickness_nm", "anomaly_flag"],
    "samples":          ["sample_id", "sample_code", "batch_id", "parent_sample_id",
                         "exclude_from_analysis", "status"],
    "experiment_plans": ["plan_id", "plan_code", "status"],
    "processes":        ["process_id", "process_code", "process_mode",
                         "o3_pre_cycles", "hf_tma_repeats", "co_etch_group"],
    "process_steps":    ["step_id", "process_id", "step_kind", "o3_delta_p_kpa"],
    "process_samples":  ["process_sample_id", "process_id", "sample_id", "is_control"],
    "sample_transitions": ["transition_id", "sample_id", "event_type", "to_status"],
    "optical_models":   ["model_id", "model_code", "n_setting", "k_setting"],
    "measurements":     ["measurement_id", "measurement_code", "sample_id",
                         "optical_model_id", "stage", "supersedes_measurement_id",
                         "is_current", "thickness_mean_nm"],
    "measurement_points": ["point_id", "measurement_id", "x_mm", "y_mm",
                           "thickness_nm", "mse"],
    "source_files":     ["file_id", "file_sha256", "file_role", "is_readonly"],
    "derived_results":  ["result_id", "result_code", "result_kind", "value_nm",
                         "model_consistent", "evidence_level"],
    "findings":         ["finding_id", "finding_code", "evidence_level"],
    "issues":           ["issue_id", "issue_code", "severity", "avoid"],
    "issues_links":     ["link_id", "issue_id", "entity_type", "entity_id"],
    "instrument_datasets": ["dataset_id", "dataset_code", "instrument_type",
                            "sample_mapping_status"],
    "instrument_channels": ["channel_id", "dataset_id", "channel_code", "element"],
    "instrument_datapoints": ["datapoint_id", "channel_id", "x_value", "y_value"],
    "attachments":      ["attachment_id", "file_name", "attachment_type"],
    "audit_log":        ["audit_id", "user_id", "action", "entity_type"],
}

# 层配色
LAYER_COLORS = {
    "权限与元数据": "#5B7C99", "批次与样品": "#2E6B4F", "工艺执行": "#8A5A2B",
    "测量与模型": "#7B4B8A", "溯源与派生": "#9B3D3D", "台账": "#4A6B8A",
    "仪器扩展": "#3D7A7A", "辅助": "#6B6B6B",
}

BOX_W, BOX_H = 300, 0
ROW_GAP, COL_GAP = 26, 90
MARGIN = 60
LINE_H = 17
PAD_TOP = 30
PAD_BOT = 14


def fetch_schema():
    user, pw = load_admin_creds()
    conn = connect(user, pw, "ale_workbench")
    tables = {}
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA='ale_workbench' AND TABLE_TYPE='BASE TABLE'")
        for t, c in cur.fetchall():
            tables[t] = {"comment": c, "cols": []}
        for t in tables:
            cur.execute("SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_KEY FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA='ale_workbench' AND TABLE_NAME=%s "
                        "ORDER BY ORDINAL_POSITION", (t,))
            tables[t]["cols"] = cur.fetchall()
        cur.execute("""
            SELECT kcu.TABLE_NAME, kcu.COLUMN_NAME, kcu.REFERENCED_TABLE_NAME
            FROM information_schema.KEY_COLUMN_USAGE kcu
            WHERE kcu.CONSTRAINT_SCHEMA='ale_workbench' AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY kcu.TABLE_NAME""")
        fks = cur.fetchall()
    conn.close()
    return tables, fks


def box_height(table, tables):
    n = len(KEY_COLS.get(table, []))
    return PAD_TOP + n * LINE_H + PAD_BOT


def generate_svg(tables, fks):
    # 计算布局
    layout = {}
    col_x = MARGIN
    max_y = 0
    for layer_name, tbls in LAYERS:
        y = MARGIN + 26
        w = BOX_W
        for t in tbls:
            if t not in tables:
                continue
            h = box_height(t, tables)
            layout[t] = (col_x, y, w, h, layer_name)
            y += h + ROW_GAP
        max_y = max(max_y, y)
        col_x += w + COL_GAP
    width = col_x - COL_GAP + MARGIN
    height = max_y + MARGIN + 30

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Microsoft YaHei, sans-serif">',
        '<defs>',
        '<marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" '
        'orient="auto" markerUnits="strokeWidth">',
        '<path d="M0,0 L10,4 L0,8 z" fill="#888"/></marker>',
        '</defs>',
        f'<rect width="{width}" height="{height}" fill="#FCFCFA"/>',
        f'<text x="{MARGIN}" y="30" font-size="21" font-weight="600" fill="#222">'
        f'ALE 实验工作台 · 数据库 ER 图</text>',
        f'<text x="{MARGIN}" y="50" font-size="12" fill="#777">'
        f'数据库 ale_workbench · MySQL 8.4.11 · 23 张表 · 49 个外键 · 由 information_schema 实际结构生成</text>',
    ]

    # 层标题
    for layer_name, tbls in LAYERS:
        xs = [layout[t][0] for t in tbls if t in layout]
        if not xs:
            continue
        c = LAYER_COLORS[layer_name]
        parts.append(
            f'<rect x="{xs[0]-8}" y="{MARGIN+2}" width="{BOX_W+16}" height="20" rx="4" '
            f'fill="{c}" opacity="0.13"/>')
        parts.append(
            f'<text x="{xs[0]}" y="{MARGIN+17}" font-size="12.5" font-weight="600" '
            f'fill="{c}">{html.escape(layer_name)}</text>')

    # 外键连线（先画，置于框下）
    for t, col, rt in fks:
        if t not in layout or rt not in layout:
            continue
        x1, y1, w1, h1, _ = layout[t]
        x2, y2, w2, h2, _ = layout[rt]
        if x1 == x2:
            continue  # 同列自引用暂不画线
        # 从左侧框右边缘到右侧框左边缘
        if x1 < x2:
            sx, sy = x1 + w1, y1 + h1 / 2
            ex, ey = x2, y2 + h2 / 2
        else:
            sx, sy = x1, y1 + h1 / 2
            ex, ey = x2 + w2, y2 + h2 / 2
        mx = (sx + ex) / 2
        parts.append(
            f'<path d="M{sx:.0f},{sy:.0f} C{mx:.0f},{sy:.0f} {mx:.0f},{ey:.0f} {ex:.0f},{ey:.0f}" '
            f'fill="none" stroke="#999" stroke-width="1.1" opacity="0.5" marker-end="url(#arrow)"/>')

    # 表框
    for t, (x, y, w, h, layer) in layout.items():
        c = LAYER_COLORS[layer]
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" '
                     f'fill="#FFFFFF" stroke="{c}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="26" rx="7" fill="{c}"/>')
        parts.append(f'<rect x="{x}" y="{y+19}" width="{w}" height="7" fill="{c}"/>')
        parts.append(f'<text x="{x+11}" y="{y+18}" font-size="13" font-weight="700" '
                     f'fill="#FFFFFF">{html.escape(t)}</text>')
        cy = y + PAD_TOP + 3
        for colname in KEY_COLS.get(t, []):
            info = next((c2 for c2 in tables[t]["cols"] if c2[0] == colname), None)
            key = info[2] if info else ""
            badge = ""
            if key == "PRI":
                badge, bcolor = "PK", "#B8860B"
            elif key == "UNI":
                badge, bcolor = "UK", "#2E6B4F"
            elif key == "MUL":
                badge, bcolor = "FK", "#7B4B8A"
            if badge:
                parts.append(f'<rect x="{x+11}" y="{cy-9}" width="21" height="12" rx="2.5" '
                             f'fill="{bcolor}" opacity="0.16"/>')
                parts.append(f'<text x="{x+13}" y="{cy}" font-size="8.5" font-weight="700" '
                             f'fill="{bcolor}">{badge}</text>')
            parts.append(f'<text x="{x+38}" y="{cy}" font-size="11" fill="#333">'
                         f'{html.escape(colname)}</text>')
            cy += LINE_H

    # 图例
    ly = height - 26
    parts.append(f'<text x="{MARGIN}" y="{ly}" font-size="10.5" fill="#666">'
                 f'PK=主键  UK=唯一键  FK=外键　|　箭头指向被引用表　|　'
                 f'连线仅表示外键关系，不代表数据流向</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def generate_mermaid(tables, fks):
    rels = set()
    for t, col, rt in fks:
        rels.add((t, rt))
    lines = ["erDiagram"]
    for t, rt in sorted(rels):
        if t == rt:
            lines.append(f'    {t} ||--o{{ {t} : "自引用"')
        else:
            lines.append(f'    {rt} ||--o{{ {t} : ""')
    for t in sorted(tables):
        lines.append(f"    {t} {{")
        for colname in KEY_COLS.get(t, [])[:6]:
            info = next((c for c in tables[t]["cols"] if c[0] == colname), None)
            ctype = info[1] if info else "varchar"
            ctype = ctype.replace(" ", "_").replace("(", "_").replace(")", "")
            lines.append(f"        {ctype} {colname}")
        lines.append("    }")
    return "\n".join(lines)


def generate_html(mermaid_src):
    esc = html.escape(mermaid_src)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>ALE 实验工作台 · ER 图</title>
<style>
 :root{{color-scheme:light}}
 body{{margin:0;padding:24px;background:#FCFCFA;
   font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#222}}
 h1{{font-size:19px;margin:0 0 4px}}
 p.sub{{color:#777;font-size:12.5px;margin:0 0 20px}}
 #wrap{{background:#fff;border:1px solid #E3E3E0;border-radius:10px;padding:20px;overflow:auto}}
 .hint{{margin-top:14px;font-size:12px;color:#888}}
</style></head><body>
<h1>ALE 实验工作台 · 数据库 ER 图</h1>
<p class="sub">数据库 ale_workbench · MySQL 8.4.11 · 23 张表 · 49 个外键</p>
<div id="wrap"><pre class="mermaid">{esc}</pre></div>
<p class="hint">此文件需联网加载 Mermaid 渲染库。若离线打开显示为源码，请改用同目录的 er_diagram.svg。</p>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
 mermaid.initialize({{startOnLoad:true,securityLevel:"strict",
   er:{{layoutDirection:"TB",useMaxWidth:true}}}});
</script>
</body></html>"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tables, fks = fetch_schema()
    print(f"读取到 {len(tables)} 张表, {len(fks)} 个外键")

    svg = generate_svg(tables, fks)
    (OUT_DIR / "er_diagram.svg").write_text(svg, encoding="utf-8")
    print(f"✓ {OUT_DIR / 'er_diagram.svg'}  ({len(svg)//1024} KB)")

    mmd = generate_mermaid(tables, fks)
    (OUT_DIR / "er_diagram.mmd").write_text(mmd, encoding="utf-8")
    print(f"✓ {OUT_DIR / 'er_diagram.mmd'}")

    (OUT_DIR / "er_diagram.html").write_text(generate_html(mmd), encoding="utf-8")
    print(f"✓ {OUT_DIR / 'er_diagram.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
