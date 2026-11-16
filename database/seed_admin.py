#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预设管理员种子脚本（幂等）。

在全新安装、数据库中还没有任何管理员账户时，创建一个预设管理员账户，
使工作站首次打开即可直接登录，无需 setup-code 初始化流程。

- 幂等：仅当 users 表不存在任何 role='admin' 的账户时才创建；已存在则跳过，绝不覆盖。
- 不重建数据库、不修改结构、不动任何实验数据。
- 预设密码由部署脚本通过环境变量 ALE_ADMIN_PASSWORD 提供（不硬编码在本文件、
  不进入版本控制、不打印）。哈希后仅写入 users.password_hash。

用法（deploy-mysql.ps1 在 migrate 之后调用）：
    $env:ALE_ADMIN_PASSWORD = '<预设密码>'
    python seed_admin.py
"""

import os
import sys
from pathlib import Path

try:
    import pymysql
except ImportError:
    print("缺少依赖: pymysql", file=sys.stderr)
    sys.exit(1)

try:
    from argon2 import PasswordHasher
except ImportError:
    print("缺少依赖: argon2-cffi", file=sys.stderr)
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
APPCREDS_FILE = BASE_DIR / ".appcreds"

ADMIN_USERNAME = "admin"
ADMIN_DISPLAY_NAME = "管理员"


def load_app_creds():
    """读取 .appcreds 中 ale_app 账户的 host/port/database/user/password。

    兼容 apply_schema.py 写入的扁平 key=value 格式（含 ale_app / ale_ro 两段）。
    """
    if not APPCREDS_FILE.exists():
        raise RuntimeError(f"未找到 {APPCREDS_FILE}")
    text = APPCREDS_FILE.read_text(encoding="utf-8-sig")
    common = {}
    account = {}
    accounts = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "user" and "user" in account:
            accounts.append({**common, **account})
            account = {}
        if key in ("host", "port", "database"):
            common[key] = value
        else:
            account[key] = value
    if account:
        accounts.append({**common, **account})
    for a in accounts:
        if a.get("user") == "ale_app":
            return a
    raise RuntimeError(".appcreds 中缺少 ale_app 账户")


def main():
    admin_password = os.environ.get("ALE_ADMIN_PASSWORD", "").strip()
    if not admin_password:
        print("未提供 ALE_ADMIN_PASSWORD，跳过预设管理员（保留 setup-code 流程）。")
        return 0

    creds = load_app_creds()
    host = os.environ.get("ALE_DB_HOST", creds.get("host", "127.0.0.1"))
    port = int(os.environ.get("ALE_DB_PORT", creds.get("port", "3307")))
    database = os.environ.get("ALE_DB_NAME", creds.get("database", "ale_workbench"))

    conn = pymysql.connect(
        host=host, port=port, user=creds["user"], password=creds.get("password", ""),
        database=database, charset="utf8mb4", autocommit=True, connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE role='admin' LIMIT 1")
            if cur.fetchone():
                print("已存在管理员账户，跳过预设（不覆盖）。")
                return 0

            ph = PasswordHasher()
            pw_hash = ph.hash(admin_password)
            cur.execute(
                "INSERT INTO users "
                "(username, display_name, password_hash, role, status, account_purpose, token_version) "
                "VALUES (%s, %s, %s, 'admin', 'active', 'management', 1)",
                (ADMIN_USERNAME, ADMIN_DISPLAY_NAME, pw_hash),
            )
        print(f"已创建预设管理员账户 {ADMIN_USERNAME}（role=admin）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
