#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALE 实验工作台 · 数据库建库执行器

功能:
  1. 从 H:\\ALE_AI\\database\\.dbcreds 读取管理员凭据(不硬编码密码)
  2. 按序执行 sql/ 下的 DDL 脚本
  3. 为 ale_app / ale_ro 生成随机强密码并注入 07_app_accounts.sql
     生成的密码写入 H:\\ALE_AI\\database\\.appcreds，不进入报告与版本控制
  4. 执行后校验表/视图/外键/账号是否齐备
  5. 幂等性测试: 再跑一遍全部脚本，确认不报错

用法:
  python apply_schema.py            # 建库 + 建账号 + 校验
  python apply_schema.py --verify   # 只校验，不执行 DDL
  python apply_schema.py --dry-run  # 只打印将执行的语句，不连库

安全:
  - 密码仅存在于内存与本地 .appcreds 文件
  - 不打印密码到标准输出
"""

import argparse
import os
import re
import secrets
import string
import sys
from pathlib import Path

try:
    import pymysql
except ImportError:
    print("缺少依赖: pip install pymysql --break-system-packages", file=sys.stderr)
    sys.exit(1)

# ----------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
SQL_DIR = BASE_DIR / "sql"
CREDS_FILE = BASE_DIR / ".dbcreds"
APPCREDS_FILE = BASE_DIR / ".appcreds"

DB_HOST = os.environ.get("ALE_DB_HOST", "172.16.10.254")
DB_PORT = int(os.environ.get("ALE_DB_PORT", "3307"))
DB_NAME = "ale_workbench"

# 执行顺序（文件名前缀即顺序）
SQL_FILES = [
    "00_create_database.sql",
    "01_core_schema.sql",
    "02_execution_schema.sql",
    "03_measurement_schema.sql",
    "04_provenance_schema.sql",
    "05_findings_and_ext.sql",
    "06_constraints_and_views.sql",
    "07_app_accounts.sql",
]

EXPECTED_TABLES = [
    "users", "tools", "recipes", "batches", "samples", "experiment_plans",
    "optical_models", "processes", "process_steps", "process_samples",
    "sample_transitions", "measurements", "measurement_points",
    "source_files", "derived_results", "findings", "issues", "issues_links",
    "instrument_datasets", "instrument_channels", "instrument_datapoints",
    "attachments", "audit_log",
]

EXPECTED_VIEWS = [
    "v_sample_overview", "v_measurement_current", "v_derived_removal",
    "v_process_detail", "v_issue_dashboard", "v_sample_evidence",
]


# ----------------------------------------------------------------------
# 凭据读取
# ----------------------------------------------------------------------
def load_admin_creds():
    """从 .dbcreds 读取管理员凭据。支持 user= / password= 或 JSON。"""
    if not CREDS_FILE.exists():
        print(f"[×] 未找到凭据文件: {CREDS_FILE}", file=sys.stderr)
        print("    请创建该文件，内容格式:", file=sys.stderr)
        print("      user=root", file=sys.stderr)
        print("      password=你的密码", file=sys.stderr)
        sys.exit(2)

    text = CREDS_FILE.read_text(encoding="utf-8")
    user = password = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip().lower()
            v = v.strip().strip('"').strip("'")
            if k in ("user", "username"):
                user = v
            elif k in ("password", "passwd", "pwd"):
                password = v
    if not user or password is None:
        print(f"[×] 凭据文件格式不正确: {CREDS_FILE}", file=sys.stderr)
        sys.exit(2)
    return user, password


def connect(user, password, database=None):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=user, password=password,
        database=database, charset="utf8mb4", autocommit=True,
        connect_timeout=10,
    )


# ----------------------------------------------------------------------
# SQL 执行
# ----------------------------------------------------------------------
def _is_comment_only(stmt):
    """判断语句是否只含注释与空白（无实际 SQL）。"""
    for line in stmt.split("\n"):
        s = line.strip()
        if s and not s.startswith("--") and not s.startswith("#"):
            return False
    return True


def split_statements(sql_text):
    """按分号切分 SQL，尊重 DELIMITER 变更与字符串/注释。"""
    statements = []
    delimiter = ";"
    buf = []
    i = 0
    n = len(sql_text)
    while i < n:
        line_end = sql_text.find("\n", i)
        if line_end == -1:
            line_end = n
        line = sql_text[i:line_end]

        # DELIMITER 指令
        m = re.match(r"^\s*DELIMITER\s+(\S+)\s*$", line, re.IGNORECASE)
        if m:
            delimiter = m.group(1)
            i = line_end + 1
            continue

        # 行注释 / 空行
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("#") or not stripped:
            buf.append(line)
            i = line_end + 1
            continue

        buf.append(line)
        current = "\n".join(buf)
        if current.rstrip().endswith(delimiter):
            stmt = current.rstrip()[: -len(delimiter)].strip()
            if stmt and not _is_comment_only(stmt):
                statements.append(stmt)
            buf = []
        i = line_end + 1

    tail = "\n".join(buf).strip()
    if tail and not _is_comment_only(tail):
        statements.append(tail)
    return statements


def run_sql_file(conn, path, substitutions=None, verbose=True):
    text = path.read_text(encoding="utf-8")
    if substitutions:
        for k, v in substitutions.items():
            text = text.replace(k, v)
    stmts = split_statements(text)
    ok = 0
    with conn.cursor() as cur:
        for stmt in stmts:
            head = stmt.strip().split("\n")[0][:80]
            try:
                cur.execute(stmt)
                ok += 1
            except pymysql.err.MySQLError as e:
                code = e.args[0] if e.args else "?"
                # 幂等容错: 已存在的对象
                if code in (1007, 1008, 1050, 1060, 1061, 1091, 1396, 1826):
                    if verbose:
                        print(f"    ~ 已存在，跳过: {head}")
                    continue
                print(f"    [×] {code}: {e}", file=sys.stderr)
                print(f"        语句: {head}", file=sys.stderr)
                raise
    if verbose:
        print(f"    ✓ {path.name}: {ok} 条语句")
    return ok


# ----------------------------------------------------------------------
# 校验
# ----------------------------------------------------------------------
def verify(conn):
    print("\n" + "=" * 68)
    print("结构校验")
    print("=" * 68)
    problems = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME", (DB_NAME,))
        rows = cur.fetchall()
        tables = {r[0] for r in rows if r[1] == "BASE TABLE"}
        views = {r[0] for r in rows if r[1] == "VIEW"}

        print(f"\n基础表 {len(tables)} 张:")
        for t in sorted(tables):
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (DB_NAME, t))
            ncol = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME<>'PRIMARY'",
                (DB_NAME, t))
            nidx = cur.fetchone()[0]
            cur.execute(
                "SELECT TABLE_COMMENT FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (DB_NAME, t))
            cmt = (cur.fetchone()[0] or "")[:34]
            print(f"  {t:26s} {ncol:3d} 字段  {nidx:2d} 索引  {cmt}")

        print(f"\n视图 {len(views)} 个: {', '.join(sorted(views))}")

        missing_t = [t for t in EXPECTED_TABLES if t not in tables]
        missing_v = [v for v in EXPECTED_VIEWS if v not in views]
        if missing_t:
            problems.append(f"缺失表: {missing_t}")
        if missing_v:
            problems.append(f"缺失视图: {missing_v}")

        # 外键
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA=%s AND CONSTRAINT_TYPE='FOREIGN KEY'", (DB_NAME,))
        nfk = cur.fetchone()[0]
        print(f"\n外键约束: {nfk} 个")

        # CHECK 约束
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA=%s AND CONSTRAINT_TYPE='CHECK'", (DB_NAME,))
        nck = cur.fetchone()[0]
        print(f"CHECK 约束: {nck} 个")

        # 账号
        cur.execute("SELECT User, Host FROM mysql.user WHERE User IN ('ale_app','ale_ro') ORDER BY User, Host")
        accts = cur.fetchall()
        print(f"\n应用账号: {len(accts)} 条授权记录")
        for u, h in accts:
            print(f"  {u}@{h}")
        if len(accts) < 4:
            problems.append("应用账号不完整(期望 ale_app/ale_ro 各 2 个 host)")

        # 权限抽查
        cur.execute("SHOW GRANTS FOR 'ale_ro'@'localhost'")
        for (g,) in cur.fetchall():
            print(f"  GRANT: {g}")

        # 字符集
        cur.execute(
            "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
            "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (DB_NAME,))
        cs, coll = cur.fetchone()
        print(f"\n库字符集: {cs} / {coll}")

        # 既有库未受影响
        cur.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME NOT IN ('mysql','performance_schema','sys','information_schema')")
        others = [r[0] for r in cur.fetchall()]
        print(f"实例内全部用户库: {others}")

    return problems


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="只校验")
    ap.add_argument("--dry-run", action="store_true", help="不连库")
    ap.add_argument("--idempotency-test", action="store_true",
                    help="全部脚本再跑一遍，验证幂等")
    args = ap.parse_args()

    if args.dry_run:
        for f in SQL_FILES:
            p = SQL_DIR / f
            print(f"--- {p.name} ---")
            for s in split_statements(p.read_text(encoding="utf-8")):
                print("  " + s.strip().split("\n")[0][:100])
        return 0

    admin_user, admin_pw = load_admin_creds()
    print(f"连接 {DB_HOST}:{DB_PORT}  (用户 {admin_user})")

    # 生成应用账号密码
    alphabet = string.ascii_letters + string.digits + "!@#%^*_-+="
    def gen_pw(n=28):
        while True:
            pw = "".join(secrets.choice(alphabet) for _ in range(n))
            if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                    and any(c.isdigit() for c in pw) and any(c in "!@#%^*_-+=" for c in pw)):
                return pw
    app_pw = gen_pw()
    ro_pw = gen_pw()
    subs = {"__ALE_APP_PASSWORD__": app_pw, "__ALE_RO_PASSWORD__": ro_pw}

    conn = connect(admin_user, admin_pw)
    try:
        if not args.verify:
            print("\n" + "=" * 68)
            print("执行 DDL")
            print("=" * 68)
            for f in SQL_FILES:
                p = SQL_DIR / f
                if not p.exists():
                    print(f"    [!] 跳过缺失文件 {f}")
                    continue
                use_subs = subs if f == "07_app_accounts.sql" else None
                run_sql_file(conn, p, use_subs)

            APPCREDS_FILE.write_text(
                "# ALE 工作台应用账号凭据（请勿提交到版本控制）\n"
                f"# 生成时间: {__import__('datetime').datetime.now().isoformat(timespec='seconds')}\n"
                f"host={DB_HOST}\nport={DB_PORT}\ndatabase={DB_NAME}\n\n"
                f"# 应用读写账号 (FastAPI 后端)\n"
                f"user=ale_app\npassword={app_pw}\n\n"
                f"# 只读账号 (图表/导出/AI 分析)\n"
                f"user=ale_ro\npassword={ro_pw}\n",
                encoding="utf-8")
            print(f"\n应用账号凭据已写入: {APPCREDS_FILE}")

        conn.select_db(DB_NAME)
        problems = verify(conn)

        if args.idempotency_test:
            print("\n" + "=" * 68)
            print("幂等性测试：重新执行全部脚本")
            print("=" * 68)
            for f in SQL_FILES:
                p = SQL_DIR / f
                if p.exists():
                    run_sql_file(conn, p, subs if f == "07_app_accounts.sql" else None,
                                 verbose=False)
            print("    ✓ 全部脚本重复执行无错误")

        print("\n" + "=" * 68)
        if problems:
            print("校验未通过:")
            for p in problems:
                print(f"  [×] {p}")
            return 1
        print("✓ 校验通过")
        print("=" * 68)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
