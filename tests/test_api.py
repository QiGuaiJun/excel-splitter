# -*- coding: utf-8 -*-
"""API 层测试：分类/数据源 CRUD + Excel/文件夹采集通道 + 预览。"""
import os
import sys
import io
import json
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import pandas as pd
from app import app
from db.dao import CategoryDAO, DataSourceDAO, CollectionLogDAO
from db.init_db import init_db

fail = 0
def check(name, cond, extra=""):
    global fail
    print(("[通过] " if cond else "[失败] ") + name + (f"  -> {extra}" if extra else ""))
    if not cond:
        fail += 1

# 确保表存在
init_db()

client = app.test_client()
P = "t_api_"

# 清理旧测试数据
for ds in DataSourceDAO.list_all()[0]:
    if ds["name"].startswith(P):
        DataSourceDAO.delete(ds["id"])
for c in CategoryDAO.list_all():
    if c["name"].startswith(P):
        CategoryDAO.delete(c["id"])


def _make_excel_bytes(rows, cols, sheet_name="明细"):
    """生成 Excel 文件的字节流。"""
    df = pd.DataFrame(rows, columns=cols)
    buf = io.BytesIO()
    df.to_excel(buf, sheet_name=sheet_name, index=False)
    buf.seek(0)
    return buf


# ========== 分类 API ==========
print("\n===== 分类 API =====")

# POST 创建
r = client.post("/api/categories", json={"name": f"{P}测试分类", "sort": 3})
data = r.get_json()
check("POST /categories 创建成功", r.status_code == 200 and data["ok"], str(data))
cid = data["data"]["id"] if data.get("ok") else None

# POST 重名
r2 = client.post("/api/categories", json={"name": f"{P}测试分类"})
check("POST 重名返回 400", r2.status_code == 400)

# GET 列表
r = client.get("/api/categories")
data = r.get_json()
check("GET /categories 包含新建分类", any(c["id"] == cid for c in data["data"]), f"共{len(data['data'])}个")
check("分类附带 source_count", "source_count" in data["data"][0])

# PUT 更新
r = client.put(f"/api/categories/{cid}", json={"name": f"{P}测试分类-改", "sort": 5})
data = r.get_json()
check("PUT /categories 更新成功", data["ok"] and data["data"]["name"] == f"{P}测试分类-改")

# DELETE（有数据源时不能删，先验证空分类可删）
r = client.delete(f"/api/categories/{cid}")
check("DELETE 空分类成功", r.get_json()["ok"])


# ========== 数据源 CRUD API ==========
print("\n===== 数据源 CRUD API =====")

# 先建一个分类
cat_id = CategoryDAO.create(f"{P}API分类", sort=1)["id"] if hasattr(CategoryDAO.create(f"{P}API分类"), '__getitem__') else None
# 上面写法有问题，重新来
for c in CategoryDAO.list_all():
    if c["name"] == f"{P}API分类":
        CategoryDAO.delete(c["id"])
cat_id = CategoryDAO.create(f"{P}API分类", sort=1)

# POST 创建数据源（登记）
r = client.post("/api/sources", json={
    "name": f"{P}登记数据源",
    "channel": "excel",
    "category_id": cat_id,
    "file_path": "/tmp/test.xlsx",
})
data = r.get_json()
check("POST /sources 登记成功", data["ok"], str(data))
sid = data["data"]["id"]

# GET 详情
r = client.get(f"/api/sources/{sid}")
data = r.get_json()
check("GET /sources/<id> 详情正确", data["ok"] and data["data"]["name"] == f"{P}登记数据源")

# GET 列表（带筛选和搜索）
r = client.get(f"/api/sources?category_id={cat_id}")
data = r.get_json()
check("GET /sources 按分类筛选", any(s["id"] == sid for s in data["data"]))
check("GET /sources 附带 stats", "total" in data["stats"] and "ready" in data["stats"])

r = client.get("/api/sources?keyword=登记数据源")
data = r.get_json()
check("GET /sources 关键词搜索", any(s["id"] == sid for s in data["data"]))

# PUT 更新
r = client.put(f"/api/sources/{sid}", json={"name": f"{P}登记数据源-改", "status": "ready"})
data = r.get_json()
check("PUT /sources 更新成功", data["ok"] and data["data"]["name"] == f"{P}登记数据源-改")

# DELETE
r = client.delete(f"/api/sources/{sid}")
check("DELETE /sources 成功", r.get_json()["ok"])
check("DELETE 后查不到", client.get(f"/api/sources/{sid}").status_code == 404)

# 清理分类
CategoryDAO.delete(cat_id)


# ========== Excel 采集通道 API ==========
print("\n===== Excel 采集通道 API =====")

cols = ["市场", "健康顾问", "订单号", "金额", "手机号"]
rows = [
    ["义乌市场", "王顾问", "O1", 100, "13812345678"],
    ["义乌市场", "李顾问", "O2", 200, "13911112222"],
    ["金华市场", "赵顾问", "O3", 300, "13733334444"],
]
buf = _make_excel_bytes(rows, cols)

r = client.post(
    "/api/collect/excel",
    data={"file": (buf, "测试数据.xlsx"), "name": f"{P}Excel采集测试", "category_id": ""},
    content_type="multipart/form-data",
)
data = r.get_json()
check("POST /collect/excel 采集成功", r.status_code == 200 and data["ok"], str(data.get("msg", "")))
excel_sid = data["data"]["id"] if data.get("ok") else None

if excel_sid:
    ds = data["data"]
    check("采集后行数=3", ds["row_count"] == 3, str(ds["row_count"]))
    check("采集后列数=5", ds["col_count"] == 5, str(ds["col_count"]))
    check("采集后子表名正确", ds["sheet_names"] == ["明细"], str(ds["sheet_names"]))
    check("采集后 status=ready", ds["status"] == "ready")
    check("采集日志已记录", len(CollectionLogDAO.list_by_source(excel_sid)) >= 1)

    # 预览 API
    r = client.get(f"/api/sources/{excel_sid}/preview?limit=10")
    pv = r.get_json()
    check("GET /sources/<id>/preview 成功", pv["ok"], str(pv.get("msg", "")))
    if pv["ok"]:
        check("预览列名正确", pv["columns"] == cols, str(pv["columns"]))
        check("预览行数=3", len(pv["rows"]) == 3, str(len(pv["rows"])))
        check("预览首行市场=义乌市场", pv["rows"][0][0] == "义乌市场")

    # 重新采集
    r = client.post(f"/api/sources/{excel_sid}/collect")
    data = r.get_json()
    check("POST /sources/<id>/collect 重新采集成功", data["ok"], str(data.get("msg", "")))

    # 清理
    DataSourceDAO.delete(excel_sid)


# ========== 文件夹采集通道 API ==========
print("\n===== 文件夹采集通道 API =====")

tmpdir = tempfile.mkdtemp(prefix="t_api_folder_")
# 创建 2 个测试 Excel
for i, name in enumerate(["文件A.xlsx", "文件B.xlsx"]):
    df = pd.DataFrame([[f"市场{i}", f"顾问{i}", f"O{i}", 100 + i, f"138{i:08d}"]], columns=cols)
    df.to_excel(os.path.join(tmpdir, name), sheet_name="明细", index=False)

r = client.post("/api/collect/folder", json={"folder_path": tmpdir, "recursive": False})
data = r.get_json()
check("POST /collect/folder 批量导入成功", data["ok"], str(data.get("msg", "")))
if data["ok"]:
    check("导入总数=2", data["total"] == 2, str(data["total"]))
    check("成功数=2", data["success"] == 2, str(data["success"]))
    check("失败数=0", data["failed"] == 0)
    # 清理导入的数据源
    for res in data["results"]:
        if res.get("id"):
            DataSourceDAO.delete(res["id"])

# 无效文件夹
r = client.post("/api/collect/folder", json={"folder_path": "/nonexistent/path"})
check("无效文件夹返回 400", r.status_code == 400)

# 清理临时目录
import shutil
shutil.rmtree(tmpdir, ignore_errors=True)


# ========== 占位通道测试 ==========
print("\n===== 占位通道（数据库/爬虫）=====")

db_sid = DataSourceDAO.create(name=f"{P}数据库占位", channel="database", status="pending")
r = client.post(f"/api/sources/{db_sid}/collect")
check("数据库通道采集返回 400（待接入）", r.status_code == 400)
DataSourceDAO.delete(db_sid)

cr_sid = DataSourceDAO.create(name=f"{P}爬虫占位", channel="crawler", status="pending")
r = client.post(f"/api/sources/{cr_sid}/collect")
check("爬虫通道采集返回 400（待接入）", r.status_code == 400)
DataSourceDAO.delete(cr_sid)


# ========== 总结 ==========
print("\n" + "=" * 50)
if fail:
    print(f"存在 {fail} 项未通过")
    sys.exit(1)
print("API 层全部测试通过 ✓")
