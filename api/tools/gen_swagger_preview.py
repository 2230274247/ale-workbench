#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALE 实验工作台 · Swagger 预览生成器

生成 Swagger UI 页面；内嵌版只内嵌契约，UI 资源仍需联网。

输出:
  api/openapi/swagger.html      在线版（CDN 加载 Swagger UI）
  api/openapi/swagger-embedded.html  内嵌版（UI 仍需 CDN）

用法: python gen_swagger_preview.py
"""

import html
import json
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
BUNDLED = BASE / "openapi" / "openapi.bundled.yaml"
OUT_ONLINE = BASE / "openapi" / "swagger.html"
OUT_EMBED = BASE / "openapi" / "swagger-embedded.html"


def main():
    if not BUNDLED.exists():
        print(f"[×] 未找到 {BUNDLED}，请先运行 validate_contract.py", file=sys.stderr)
        return 1

    with open(BUNDLED, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    n_paths = len(spec.get("paths", {}))
    n_ops = sum(1 for p in spec["paths"].values() for m in p
                if m in ("get", "post", "put", "patch", "delete"))

    n_implemented = sum(op.get("x-implementation-status") == "implemented"
                        for item in spec["paths"].values()
                        for method, op in item.items()
                        if method in ("get", "post", "put", "patch", "delete"))
    status_note = (f"版本 {spec['info']['version']} · 已实现 {n_implemented} 操作 · "
                   f"planned {n_ops - n_implemented} 操作；planned 为规划，模型存在不表示功能已实现")

    # 在线版：指向同目录的契约文件
    online = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ALE 实验工作台 API · Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    :root {{ color-scheme: light }}
    body {{ margin: 0; background: #fafafa;
           font-family: "Segoe UI","Microsoft YaHei",sans-serif }}
    .topbar {{ display: none }}
    .banner {{ padding: 14px 20px; background: #1f4e5f; color: #fff }}
    .banner h1 {{ margin: 0 0 4px; font-size: 17px; font-weight: 600 }}
    .banner p {{ margin: 0; font-size: 12.5px; opacity: .85 }}
    .note {{ padding: 10px 20px; background: #fff8e1; color: #7a5c00;
             font-size: 12.5px; border-bottom: 1px solid #f0e0b0 }}
  </style>
</head>
<body>
<div class="banner">
  <h1>ALE 实验工作台 API</h1>
  <p>OpenAPI 3.1 · {n_paths} 个路径 · {n_ops} 个端点 · 基础路径 /api/v1</p>
</div>
<div class="note">
  {status_note}<br>需联网加载 Swagger UI 资源。内嵌契约版：<code>swagger-embedded.html</code>。
  接口契约源文件：<code>openapi.bundled.yaml</code>
</div>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.onload = () => {{
  window.ui = SwaggerUIBundle({{
    url: './openapi.bundled.yaml',
    dom_id: '#swagger-ui',
    deepLinking: true,
    docExpansion: 'list',
    defaultModelsExpandDepth: 1,
    tryItOutEnabled: true,
    displayRequestDuration: true,
    filter: true,
    persistAuthorization: true,
    presets: [SwaggerUIBundle.presets.apis],
    layout: 'BaseLayout',
  }});
}};
</script>
</body>
</html>"""
    OUT_ONLINE.write_text(online, encoding="utf-8")
    print(f"✓ {OUT_ONLINE}")

    # 内嵌版：契约以 JSON 内嵌，无需额外文件
    spec_json = json.dumps(spec, ensure_ascii=False)
    embedded = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ALE 实验工作台 API · Swagger UI（内嵌契约）</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    :root {{ color-scheme: light }}
    body {{ margin: 0; background: #fafafa;
           font-family: "Segoe UI","Microsoft YaHei",sans-serif }}
    .topbar {{ display: none }}
    .banner {{ padding: 14px 20px; background: #1f4e5f; color: #fff }}
    .banner h1 {{ margin: 0 0 4px; font-size: 17px; font-weight: 600 }}
    .banner p {{ margin: 0; font-size: 12.5px; opacity: .85 }}
    .note {{ padding: 10px 20px; background: #fff8e1; color: #7a5c00;
             font-size: 12.5px; border-bottom: 1px solid #f0e0b0 }}
  </style>
</head>
<body>
<div class="banner">
  <h1>ALE 实验工作台 API</h1>
  <p>OpenAPI 3.1 · {n_paths} 个路径 · {n_ops} 个端点 · 契约已内嵌</p>
</div>
<div class="note">
  {status_note}<br>契约已内嵌在本文件中，无需额外文件。Swagger UI 资源仍需联网加载。
</div>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
const SPEC = {spec_json};
window.onload = () => {{
  window.ui = SwaggerUIBundle({{
    spec: SPEC,
    dom_id: '#swagger-ui',
    deepLinking: true,
    docExpansion: 'list',
    defaultModelsExpandDepth: 1,
    tryItOutEnabled: true,
    displayRequestDuration: true,
    filter: true,
    persistAuthorization: true,
    presets: [SwaggerUIBundle.presets.apis],
    layout: 'BaseLayout',
  }});
}};
</script>
</body>
</html>"""
    OUT_EMBED.write_text(embedded, encoding="utf-8")
    print(f"✓ {OUT_EMBED}  ({len(embedded)//1024} KB)")

    # 统计
    print(f"\n契约规模: {n_paths} 路径 / {n_ops} 端点 / "
          f"{len(spec['components']['schemas'])} schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
