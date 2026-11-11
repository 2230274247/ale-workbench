#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALE 实验工作台 · 约束生效性测试执行器

逐条执行预期被拒的语句，捕获异常并判定约束是否真的生效。
所有操作在 SAVEPOINT 隔离下进行，最终 ROLLBACK，不留数据。

用法: python run_constraint_test.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_schema import load_admin_creds, connect  # noqa: E402

# (名称, SQL, 预期错误码集合)
TESTS = [
    ("CHECK samples.status",
     "UPDATE samples SET status='melted' WHERE sample_code='CT-SAMPLE'", {3819}),
    ("CHECK measurements.stage",
     "UPDATE measurements SET stage='before_after' WHERE measurement_code='CT-MSR'", {3819}),
    ("CHECK measurements.quality_flag",
     "UPDATE measurements SET quality_flag='weird' WHERE measurement_code='CT-MSR'", {3819}),
    ("CHECK instrument_datasets.instrument_type",
     "INSERT INTO instrument_datasets(dataset_code,instrument_type) VALUES('D-X','nmr')", {3819}),
    ("CHECK source_files.file_role",
     "INSERT INTO source_files(file_sha256,file_name,file_role) "
     "VALUES(REPEAT('c',64),'x.xlsx','bogus')", {3819}),
    ("CHECK issues_links.entity_type",
     "INSERT INTO issues_links(issue_id,entity_type,entity_id) VALUES(1,'spaceship',1)", {3819}),
    ("UNIQUE samples.sample_code",
     "INSERT INTO samples(sample_code,batch_id) "
     "SELECT sample_code,batch_id FROM samples WHERE sample_code='CT-SAMPLE'", {1062}),
    ("UNIQUE users.username",
     "INSERT INTO users(username) VALUES('ct_admin')", {1062}),
    ("UNIQUE measurements.measurement_code",
     "INSERT INTO measurements(measurement_code,sample_id,stage) "
     "SELECT measurement_code,sample_id,'final' FROM measurements WHERE measurement_code='CT-MSR'", {1062}),
    ("UNIQUE measurement_points(measurement_id,point_no)",
     "INSERT INTO measurement_points(measurement_id,point_no,x_mm,y_mm) "
     "SELECT measurement_id,1,0,0 FROM measurements WHERE measurement_code='CT-MSR'", {1062}),
    ("FK batches 被引用时禁止删除",
     "DELETE FROM batches WHERE batch_code='CT-BATCH'", {1451}),
    ("FK measurements.sample_id 必须存在",
     "INSERT INTO measurements(measurement_code,sample_id,stage) VALUES('M-BAD',999999,'initial')", {1452}),
]


def main():
    user, pw = load_admin_creds()
    conn = connect(user, pw, "ale_workbench")
    conn.autocommit(False)
    passed = failed = 0
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE username='ct_admin'")
            cur.execute("INSERT INTO users(username,role) VALUES('ct_admin','admin')")
            cur.execute("INSERT INTO batches(batch_code,batch_name) VALUES('CT-BATCH','constraint test batch')")
            cur.execute("INSERT INTO samples(sample_code,batch_id,status) "
                        "SELECT 'CT-SAMPLE',batch_id,'available' FROM batches WHERE batch_code='CT-BATCH'")
            cur.execute("INSERT INTO measurements(measurement_code,sample_id,stage) "
                        "SELECT 'CT-MSR',sample_id,'initial' FROM samples WHERE sample_code='CT-SAMPLE'")
            cur.execute("INSERT INTO measurement_points(measurement_id,point_no,x_mm,y_mm,thickness_nm) "
                        "SELECT measurement_id,1,0,0,30.0 FROM measurements WHERE measurement_code='CT-MSR'")
            cur.execute("SAVEPOINT base")

        print("约束生效性测试")
        print("=" * 66)
        for name, sql, expect in TESTS:
            blocked = False
            code = None
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
            except Exception as e:
                code = e.args[0] if e.args else None
                blocked = code in expect
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT base")
            if blocked:
                print(f"  [OK]   {name:52s} 拦截({code})")
                passed += 1
            else:
                print(f"  [FAIL] {name:52s} 未拦截(code={code})")
                failed += 1

        conn.rollback()
    finally:
        conn.close()

    print("=" * 66)
    print(f"通过 {passed} / {passed + failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
