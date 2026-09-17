# -*- coding: utf-8 -*-
"""数据层 DAO 测试：categories / data_sources / collection_logs 全量 CRUD。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

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

# 用唯一前缀避免测试数据残留冲突
P = "t_dao_"

# ========== CategoryDAO ==========
print("\n===== CategoryDAO =====")

# 清理旧测试数据
for c in CategoryDAO.list_all():
    if c["name"].startswith(P):
        CategoryDAO.delete(c["id"])

# create + get_by_id
cid = CategoryDAO.create(f"{P}订单表", sort=2)
check("create 返回有效 ID", cid > 0, str(cid))
c = CategoryDAO.get_by_id(cid)
check("get_by_id 名称正确", c["name"] == f"{P}订单表", str(c))
check("get_by_id sort 正确", c["sort"] == 2, str(c["sort"]))

# get_by_name
c2 = CategoryDAO.get_by_name(f"{P}订单表")
check("get_by_name 命中", c2 is not None and c2["id"] == cid)

# list_all
all_cats = CategoryDAO.list_all()
check("list_all 包含新建分类", any(x["id"] == cid for x in all_cats), f"共{len(all_cats)}个")

# update
ok = CategoryDAO.update(cid, name=f"{P}订单表-改", sort=5)
check("update 成功", ok)
c3 = CategoryDAO.get_by_id(cid)
check("update 后名称正确", c3["name"] == f"{P}订单表-改", str(c3["name"]))
check("update 后 sort 正确", c3["sort"] == 5, str(c3["sort"]))

# count_sources（此时无数据源）
check("count_sources 空分类=0", CategoryDAO.count_sources(cid) == 0)

# delete 空分类成功
ok = CategoryDAO.delete(cid)
check("delete 空分类成功", ok)
check("delete 后查不到", CategoryDAO.get_by_id(cid) is None)

# ========== DataSourceDAO ==========
print("\n===== DataSourceDAO =====")

# 清理旧测试数据
for ds in DataSourceDAO.list_all():
    if ds["name"].startswith(P):
        DataSourceDAO.delete(ds["id"])
for c in CategoryDAO.list_all():
    if c["name"].startswith(P):
        CategoryDAO.delete(c["id"])

# 建一个分类用于关联
cat_id = CategoryDAO.create(f"{P}测试分类", sort=1)

# create
sid = DataSourceDAO.create(
    name=f"{P}测试数据源",
    channel="excel",
    category_id=cat_id,
    file_path="/data/test.xlsx",
    config={"sheet": "明细"},
    status="pending",
)
check("create 返回有效 ID", sid > 0, str(sid))

# get_by_id
ds = DataSourceDAO.get_by_id(sid)
check("get_by_id 名称正确", ds["name"] == f"{P}测试数据源", str(ds["name"]))
check("get_by_id channel 正确", ds["channel"] == "excel")
check("get_by_id category_name 关联正确", ds["category_name"] == f"{P}测试分类", str(ds.get("category_name")))
check("get_by_id config JSON 反序列化正确", ds["config"] == {"sheet": "明细"}, str(ds["config"]))
check("get_by_id 默认 status=pending", ds["status"] == "pending")

# list_all 全量
all_ds = DataSourceDAO.list_all()
check("list_all 包含新建数据源", any(x["id"] == sid for x in all_ds), f"共{len(all_ds)}个")

# list_all 按分类筛选
by_cat = DataSourceDAO.list_all(category_id=cat_id)
check("list_all 按分类筛选命中", len(by_cat) >= 1 and any(x["id"] == sid for x in by_cat), f"命中{len(by_cat)}个")

# list_all 关键词搜索
by_kw = DataSourceDAO.list_all(keyword="测试数据源")
check("list_all 关键词搜索命中", any(x["id"] == sid for x in by_kw), f"命中{len(by_kw)}个")

# update
ok = DataSourceDAO.update(sid, name=f"{P}测试数据源-改", status="ready")
check("update 成功", ok)
ds2 = DataSourceDAO.get_by_id(sid)
check("update 后名称正确", ds2["name"] == f"{P}测试数据源-改")
check("update 后 status 正确", ds2["status"] == "ready")

# update_collect_result
ok = DataSourceDAO.update_collect_result(sid, row_count=5286, col_count=12,
                                            sheet_names=["明细", "说明"], status="ready")
check("update_collect_result 成功", ok)
ds3 = DataSourceDAO.get_by_id(sid)
check("采集后 row_count=5286", ds3["row_count"] == 5286, str(ds3["row_count"]))
check("采集后 col_count=12", ds3["col_count"] == 12)
check("采集后 sheet_names 反序列化正确", ds3["sheet_names"] == ["明细", "说明"], str(ds3["sheet_names"]))
check("采集后 last_collected_at 非空", ds3["last_collected_at"] is not None)

# count_all / count_by_status
check("count_all >= 1", DataSourceDAO.count_all() >= 1)
check("count_by_status ready >= 1", DataSourceDAO.count_by_status("ready") >= 1)

# 分类有数据源时不能删除
check("有数据源的分类 delete 返回 False", CategoryDAO.delete(cat_id) is False)

# ========== CollectionLogDAO ==========
print("\n===== CollectionLogDAO =====")

# create
lid = CollectionLogDAO.create(source_id=sid, status="success", row_count=5286, duration_ms=1234)
check("create 日志返回有效 ID", lid > 0, str(lid))

# get_by_id
log = CollectionLogDAO.get_by_id(lid)
check("get_by_id 状态正确", log["status"] == "success")
check("get_by_id row_count 正确", log["row_count"] == 5286)
check("get_by_id duration_ms 正确", log["duration_ms"] == 1234)

# 失败日志
lid2 = CollectionLogDAO.create(source_id=sid, status="failed", row_count=0,
                                 error_msg="文件损坏，无法解析", duration_ms=50)
check("create 失败日志成功", lid2 > 0)

# list_by_source
logs = CollectionLogDAO.list_by_source(sid)
check("list_by_source 返回 2 条", len(logs) == 2, f"返回{len(logs)}条")
check("list_by_source 按时间倒序（最新在前）", logs[0]["id"] > logs[1]["id"])

# ========== 级联删除验证 ==========
print("\n===== 级联删除 =====")

# 删除数据源，collection_logs 应级联删除
ok = DataSourceDAO.delete(sid)
check("delete 数据源成功", ok)
check("delete 后查不到数据源", DataSourceDAO.get_by_id(sid) is None)
logs_after = CollectionLogDAO.list_by_source(sid)
check("级联删除后日志为空", len(logs_after) == 0, f"剩余{len(logs_after)}条")

# 现在分类无数据源，可以删除
ok = CategoryDAO.delete(cat_id)
check("数据源删除后分类可删除", ok)

# ========== 总结 ==========
print("\n" + "=" * 50)
if fail:
    print(f"存在 {fail} 项未通过")
    sys.exit(1)
print("数据层 DAO 全部测试通过 ✓")
