# -*- coding: utf-8 -*-
"""端到端测试：真实 HTTP 请求，验证数据源管理中心全链路。"""
import io
import json
import urllib.request
import pandas as pd

BASE = "http://127.0.0.1:18765"

def http_get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

def http_post_json(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))

def http_post_multipart(path, fields, files):
    """简单的 multipart/form-data 上传。"""
    boundary = "----TestBoundary123456"
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    for k, (filename, content, ctype) in files.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode("utf-8")
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

fail = 0
def check(name, cond, extra=""):
    global fail
    print(("[通过] " if cond else "[失败] ") + name + (f" -> {extra}" if extra else ""))
    if not cond: fail += 1

# 1. 创建分类
print("\n=== 1. 创建分类 ===")
try:
    r = http_post_json("/api/categories", {"name": "E2E测试分类"})
    check("创建分类成功", r["ok"], str(r))
    cat_id = r["data"]["id"] if r["ok"] else None
except Exception as e:
    check("创建分类成功", False, str(e))
    cat_id = None

# 2. 上传 Excel
print("\n=== 2. 上传 Excel ===")
df = pd.DataFrame([
    ["义乌市场", "王顾问", "O001", 100, "13812345678"],
    ["金华市场", "李顾问", "O002", 200, "13911112222"],
], columns=["市场", "健康顾问", "订单号", "金额", "手机号"])
buf = io.BytesIO()
df.to_excel(buf, sheet_name="明细", index=False)
excel_bytes = buf.getvalue()

try:
    r = http_post_multipart("/api/collect/excel",
        {"name": "E2E测试数据源", "category_id": str(cat_id) if cat_id else ""},
        {"file": ("test_e2e.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    check("Excel 采集成功", r["ok"], str(r.get("msg", "")))
    src_id = r["data"]["id"] if r["ok"] else None
    if r["ok"]:
        check("采集后行数=2", r["data"]["row_count"] == 2, str(r["data"]["row_count"]))
        check("采集后列数=5", r["data"]["col_count"] == 5, str(r["data"]["col_count"]))
        check("子表名=明细", r["data"]["sheet_names"] == ["明细"], str(r["data"]["sheet_names"]))
except Exception as e:
    check("Excel 采集成功", False, str(e))
    src_id = None

# 3. 查询数据源列表
print("\n=== 3. 查询数据源列表 ===")
try:
    r = http_get("/api/sources")
    check("列表查询成功", r["ok"])
    check("列表包含新建数据源", any(s["id"] == src_id for s in r["data"]), f"共{len(r['data'])}个")
    check("统计 total>=1", r["stats"]["total"] >= 1, str(r["stats"]))
except Exception as e:
    check("列表查询成功", False, str(e))

# 4. 按分类筛选
print("\n=== 4. 按分类筛选 ===")
if cat_id:
    try:
        r = http_get(f"/api/sources?category_id={cat_id}")
        check("按分类筛选命中", any(s["id"] == src_id for s in r["data"]), f"命中{len(r['data'])}个")
    except Exception as e:
        check("按分类筛选", False, str(e))

# 5. 数据预览
print("\n=== 5. 数据预览 ===")
if src_id:
    try:
        r = http_get(f"/api/sources/{src_id}/preview?limit=10")
        check("预览成功", r["ok"], str(r.get("msg", "")))
        if r["ok"]:
            check("预览列名正确", r["columns"] == ["市场", "健康顾问", "订单号", "金额", "手机号"], str(r["columns"]))
            check("预览行数=2", len(r["rows"]) == 2, str(len(r["rows"])))
    except Exception as e:
        check("预览成功", False, str(e))

# 6. 重新采集
print("\n=== 6. 重新采集 ===")
if src_id:
    try:
        r = http_post_json(f"/api/sources/{src_id}/collect", {})
        check("重新采集成功", r["ok"], str(r.get("msg", "")))
    except Exception as e:
        check("重新采集成功", False, str(e))

# 7. 清理测试数据
print("\n=== 7. 清理测试数据 ===")
if src_id:
    try:
        req = urllib.request.Request(BASE + f"/api/sources/{src_id}", method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
            check("删除数据源成功", j["ok"])
    except Exception as e:
        check("删除数据源成功", False, str(e))
if cat_id:
    try:
        req = urllib.request.Request(BASE + f"/api/categories/{cat_id}", method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
            check("删除分类成功", j["ok"])
    except Exception as e:
        check("删除分类成功", False, str(e))

print("\n" + "=" * 50)
if fail:
    print(f"存在 {fail} 项未通过")
    exit(1)
print("端到端测试全部通过 ✓")
