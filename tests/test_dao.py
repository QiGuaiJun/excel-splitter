# -*- coding: utf-8 -*-
"""categories / data_sources / collection_logs 全量 CRUD 单测。

依赖：MySQL 测试库（端口 3307）。DB 不可达时整个文件被 module-level skip，
不会污染其他测试，也不会在 setup 阶段抛 ERROR。
"""
import pytest

# 模块级 skip：必须放在所有用到 DAO 的 import 之前（pytest 文档推荐做法）
from tests.conftest import mysql_reachable_from_config

if not mysql_reachable_from_config():
    pytest.skip("MySQL 测试库不可达（端口 3307 未开放或配置缺失），跳过整个文件", allow_module_level=True)

from db.dao import CategoryDAO, DataSourceDAO, CollectionLogDAO  # noqa: E402
from db.init_db import init_db  # noqa: E402


# 会话级只跑一次 init_db（应在 skip 之后再调用）
init_db()

P = "t_dao_"


@pytest.fixture(autouse=True)
def _cleanup():
    """每个用例前后清理 t_dao_ 前缀的残留数据。"""
    for ds in DataSourceDAO.list_all()[0]:
        if ds["name"].startswith(P):
            DataSourceDAO.delete(ds["id"])
    for c in CategoryDAO.list_all():
        if c["name"].startswith(P):
            CategoryDAO.delete(c["id"])
    yield
    for ds in DataSourceDAO.list_all()[0]:
        if ds["name"].startswith(P):
            DataSourceDAO.delete(ds["id"])
    for c in CategoryDAO.list_all():
        if c["name"].startswith(P):
            CategoryDAO.delete(c["id"])


# ============================================================================
# CategoryDAO
# ============================================================================
@pytest.mark.db
class TestCategoryDAO:
    def test_create_returns_id(self):
        cid = CategoryDAO.create(f"{P}订单表", sort=2)
        assert cid > 0
        c = CategoryDAO.get_by_id(cid)
        assert c["name"] == f"{P}订单表"
        assert c["sort"] == 2

    def test_get_by_name_hit(self):
        cid = CategoryDAO.create(f"{P}by_name")
        found = CategoryDAO.get_by_name(f"{P}by_name")
        assert found is not None
        assert found["id"] == cid

    def test_list_all_contains_created(self):
        cid = CategoryDAO.create(f"{P}list_all")
        cats = CategoryDAO.list_all()
        assert any(c["id"] == cid for c in cats)

    def test_update_name_and_sort(self):
        cid = CategoryDAO.create(f"{P}update", sort=1)
        ok = CategoryDAO.update(cid, name=f"{P}update-ed", sort=5)
        assert ok is True
        c = CategoryDAO.get_by_id(cid)
        assert c["name"] == f"{P}update-ed"
        assert c["sort"] == 5

    def test_count_sources_empty(self):
        cid = CategoryDAO.create(f"{P}count_empty")
        assert CategoryDAO.count_sources(cid) == 0

    def test_delete_empty_category_succeeds(self):
        cid = CategoryDAO.create(f"{P}delete_empty")
        assert CategoryDAO.delete(cid) is True
        assert CategoryDAO.get_by_id(cid) is None


# ============================================================================
# DataSourceDAO
# ============================================================================
@pytest.mark.db
class TestDataSourceDAO:
    def test_create_get_by_id_round_trip(self):
        cat_id = CategoryDAO.create(f"{P}ds_cat", sort=1)
        sid = DataSourceDAO.create(
            name=f"{P}ds",
            channel="excel",
            category_id=cat_id,
            file_path="/data/test.xlsx",
            config={"sheet": "明细"},
            status="pending",
        )
        ds = DataSourceDAO.get_by_id(sid)
        assert ds["name"] == f"{P}ds"
        assert ds["channel"] == "excel"
        assert ds["category_name"] == f"{P}ds_cat"
        assert ds["config"] == {"sheet": "明细"}
        assert ds["status"] == "pending"

    def test_list_all_category_filter(self):
        cat_id = CategoryDAO.create(f"{P}ds_cat_filter", sort=1)
        sid = DataSourceDAO.create(name=f"{P}ds_filter", channel="excel", category_id=cat_id)
        rows, _ = DataSourceDAO.list_all(category_id=cat_id)
        assert any(r["id"] == sid for r in rows)

    def test_list_all_keyword_search(self):
        cat_id = CategoryDAO.create(f"{P}ds_cat_kw", sort=1)
        sid = DataSourceDAO.create(name=f"{P}kw_marker", channel="excel", category_id=cat_id)
        rows, _ = DataSourceDAO.list_all(keyword="kw_marker")
        assert any(r["id"] == sid for r in rows)

    def test_update(self):
        sid = DataSourceDAO.create(name=f"{P}ds_update", channel="excel")
        ok = DataSourceDAO.update(sid, name=f"{P}ds_update-ed", status="ready")
        assert ok is True
        ds = DataSourceDAO.get_by_id(sid)
        assert ds["name"] == f"{P}ds_update-ed"
        assert ds["status"] == "ready"

    def test_update_collect_result(self):
        sid = DataSourceDAO.create(name=f"{P}ds_collect", channel="excel")
        ok = DataSourceDAO.update_collect_result(
            sid, row_count=5286, col_count=12,
            sheet_names=["明细", "说明"], status="ready",
        )
        assert ok is True
        ds = DataSourceDAO.get_by_id(sid)
        assert ds["row_count"] == 5286
        assert ds["col_count"] == 12
        assert ds["sheet_names"] == ["明细", "说明"]
        assert ds["last_collected_at"] is not None

    def test_count_all_and_count_by_status(self):
        assert DataSourceDAO.count_all() >= 1
        assert DataSourceDAO.count_by_status("ready") >= 1

    def test_delete_with_source_blocks_category(self):
        cat_id = CategoryDAO.create(f"{P}ds_cat_block", sort=1)
        sid = DataSourceDAO.create(name=f"{P}ds_in_block", channel="excel", category_id=cat_id)
        # 分类下有数据源 -> delete 返回 False
        assert CategoryDAO.delete(cat_id) is False
        # 删掉数据源后 -> 可以删除
        assert DataSourceDAO.delete(sid) is True
        assert CategoryDAO.delete(cat_id) is True


# ============================================================================
# CollectionLogDAO
# ============================================================================
@pytest.mark.db
class TestCollectionLogDAO:
    def test_create_and_get_by_id(self):
        sid = DataSourceDAO.create(name=f"{P}log_target", channel="excel")
        lid = CollectionLogDAO.create(source_id=sid, status="success", row_count=5286, duration_ms=1234)
        log = CollectionLogDAO.get_by_id(lid)
        assert log["status"] == "success"
        assert log["row_count"] == 5286
        assert log["duration_ms"] == 1234

    def test_create_failed_log(self):
        sid = DataSourceDAO.create(name=f"{P}log_target2", channel="excel")
        lid = CollectionLogDAO.create(
            source_id=sid, status="failed", row_count=0,
            error_msg="文件损坏，无法解析", duration_ms=50,
        )
        assert lid > 0

    def test_list_by_source_returns_in_desc_order(self):
        sid = DataSourceDAO.create(name=f"{P}log_target3", channel="excel")
        CollectionLogDAO.create(source_id=sid, status="success", row_count=1, duration_ms=10)
        CollectionLogDAO.create(source_id=sid, status="success", row_count=2, duration_ms=20)
        logs = CollectionLogDAO.list_by_source(sid)
        assert len(logs) == 2
        # 时间倒序：第二个 create 的 id 应更大
        assert logs[0]["id"] > logs[1]["id"]


# ============================================================================
# 级联删除
# ============================================================================
@pytest.mark.db
class TestCascadeDelete:
    def test_delete_source_cascades_logs(self):
        sid = DataSourceDAO.create(name=f"{P}cascade_target", channel="excel")
        CollectionLogDAO.create(source_id=sid, status="success", row_count=10, duration_ms=10)
        CollectionLogDAO.create(source_id=sid, status="failed", row_count=0, duration_ms=10)
        assert len(CollectionLogDAO.list_by_source(sid)) == 2
        DataSourceDAO.delete(sid)
        assert DataSourceDAO.get_by_id(sid) is None
        assert CollectionLogDAO.list_by_source(sid) == []


# ============================================================================
# Bug 回归：P0 — stats 接口 count_by_status("error") ⇒ 永远是 0（schema 注释定义的是 "failed"）
# ============================================================================
@pytest.mark.db
class TestStatusFilterRegression:
    """验证 batch 3 修过的 P0 bug 不再复发。"""

    def test_count_by_status_failed_works(self):
        sid = DataSourceDAO.create(name=f"{P}failed_target", channel="excel", status="pending")
        try:
            DataSourceDAO.update_collect_result(sid, row_count=10, col_count=5, status="failed")
            assert DataSourceDAO.count_by_status("failed") >= 1
        finally:
            DataSourceDAO.delete(sid)

    def test_sources_api_stats_uses_failed_key(self):
        # 这个对应 api/sources.py 的 stats 字段，bug 是写成 "error" 永远=0
        from app import app
        client = app.test_client()
        # 故意把一个数据源改成 failed，再调用 stats
        sid = DataSourceDAO.create(name=f"{P}failed_for_api", channel="excel", status="pending")
        try:
            DataSourceDAO.update_collect_result(sid, row_count=10, col_count=5, status="failed")
            r = client.get("/api/sources")
            data = r.get_json()
            assert data["ok"]
            # API 应该返回 failed 字段（旧 bug 是返回 error）
            assert "failed" in data["stats"]
            assert "error" not in data["stats"]
            assert data["stats"]["failed"] >= 1
        finally:
            DataSourceDAO.delete(sid)
