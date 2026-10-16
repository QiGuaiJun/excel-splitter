# -*- coding: utf-8 -*-
"""API 层测试：分类 / 数据源 CRUD + Excel/文件夹采集 + 预览。

依赖：MySQL 测试库（端口 3307）+ Flask test_client。DB 不可达时整个文件 skip。
"""
import io
import os
import tempfile

import pandas as pd
import pytest

from tests.conftest import mysql_reachable_from_config

if not mysql_reachable_from_config():
    pytest.skip("MySQL 测试库不可达，跳过整个文件", allow_module_level=True)

from app import app  # noqa: E402
from db.dao import CategoryDAO, DataSourceDAO, CollectionLogDAO  # noqa: E402
from db.init_db import init_db  # noqa: E402


init_db()

client = app.test_client()
P = "t_api_"


@pytest.fixture(autouse=True)
def _cleanup():
    """前后清理 t_api_ 前缀的测试数据。"""
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


def _make_excel_bytes(rows, cols, sheet_name="明细"):
    df = pd.DataFrame(rows, columns=cols)
    buf = io.BytesIO()
    df.to_excel(buf, sheet_name=sheet_name, index=False)
    buf.seek(0)
    return buf


# ============================================================================
# 分类 API
# ============================================================================
@pytest.mark.integration
class TestCategoriesAPI:
    def test_post_creates(self):
        r = client.post("/api/categories", json={"name": f"{P}测试分类", "sort": 3})
        data = r.get_json()
        assert r.status_code == 200 and data["ok"], data
        assert "id" in data["data"]

    def test_post_duplicate_returns_400(self):
        client.post("/api/categories", json={"name": f"{P}dup"})
        r2 = client.post("/api/categories", json={"name": f"{P}dup"})
        assert r2.status_code == 400

    def test_get_list_contains_source_count(self):
        r = client.get("/api/categories")
        data = r.get_json()
        assert data["ok"]
        assert any("source_count" in c for c in data["data"])

    def test_put_updates(self):
        cid = client.post("/api/categories", json={"name": f"{P}put_target"}).get_json()["data"]["id"]
        r = client.put(f"/api/categories/{cid}", json={"name": f"{P}put_target-ed", "sort": 5})
        data = r.get_json()
        assert data["ok"] and data["data"]["name"] == f"{P}put_target-ed"

    def test_delete_empty_succeeds(self):
        cid = client.post("/api/categories", json={"name": f"{P}del_target"}).get_json()["data"]["id"]
        r = client.delete(f"/api/categories/{cid}")
        assert r.get_json()["ok"] is True


# ============================================================================
# 数据源 CRUD API
# ============================================================================
@pytest.mark.integration
class TestSourcesCRUDAPI:
    def test_post_register(self):
        cid = CategoryDAO.create(f"{P}API分类", sort=1)
        try:
            r = client.post("/api/sources", json={
                "name": f"{P}登记数据源",
                "channel": "excel",
                "category_id": cid,
                "file_path": "/tmp/test.xlsx",
            })
            data = r.get_json()
            assert data["ok"], data
            sid = data["data"]["id"]
            assert sid > 0
        finally:
            CategoryDAO.delete(cid)

    def test_get_detail(self):
        sid = DataSourceDAO.create(name=f"{P}detail", channel="excel")
        r = client.get(f"/api/sources/{sid}")
        data = r.get_json()
        assert data["ok"] and data["data"]["name"] == f"{P}detail"

    def test_get_list_with_filters(self):
        cid = CategoryDAO.create(f"{P}list_cat", sort=1)
        sid = DataSourceDAO.create(name=f"{P}list_target", channel="excel", category_id=cid)
        try:
            r = client.get(f"/api/sources?category_id={cid}")
            data = r.get_json()
            assert any(s["id"] == sid for s in data["data"])
            assert "total" in data["stats"]
        finally:
            CategoryDAO.delete(cid)

    def test_put_update(self):
        sid = DataSourceDAO.create(name=f"{P}put_src", channel="excel")
        r = client.put(f"/api/sources/{sid}", json={"name": f"{P}put_src-ed", "status": "ready"})
        data = r.get_json()
        assert data["ok"] and data["data"]["name"] == f"{P}put_src-ed"

    def test_delete_then_404(self):
        sid = DataSourceDAO.create(name=f"{P}del_src", channel="excel")
        r = client.delete(f"/api/sources/{sid}")
        assert r.get_json()["ok"] is True
        assert client.get(f"/api/sources/{sid}").status_code == 404


# ============================================================================
# Excel 采集通道 API
# ============================================================================
@pytest.mark.integration
class TestExcelCollectAPI:
    def test_collect_excel(self):
        cols = ["市场", "健康顾问", "订单号", "金额", "手机号"]
        rows = [
            ["义乌市场", "王顾问", "O1", 100, "13812345678"],
            ["义乌市场", "李顾问", "O2", 200, "13911112222"],
            ["金华市场", "赵顾问", "O3", 300, "13733334444"],
        ]
        buf = _make_excel_bytes(rows, cols)
        r = client.post(
            "/api/collect/excel",
            data={"file": (buf, "测试数据.xlsx"), "name": f"{P}Excel采集测试"},
            content_type="multipart/form-data",
        )
        data = r.get_json()
        assert r.status_code == 200 and data["ok"], data.get("msg", "")
        sid = data["data"]["id"]
        ds = data["data"]
        assert ds["row_count"] == 3
        assert ds["col_count"] == 5
        assert ds["sheet_names"] == ["明细"]
        assert ds["status"] == "ready"
        assert len(CollectionLogDAO.list_by_source(sid)) >= 1

        # 预览
        pv = client.get(f"/api/sources/{sid}/preview?limit=10").get_json()
        assert pv["ok"]
        assert pv["columns"] == cols
        assert len(pv["rows"]) == 3
        assert pv["rows"][0][0] == "义乌市场"

        # 重新采集
        rr = client.post(f"/api/sources/{sid}/collect").get_json()
        assert rr["ok"]

        # 清理
        DataSourceDAO.delete(sid)


# ============================================================================
# 文件夹采集通道 API
# ============================================================================
@pytest.mark.integration
class TestFolderCollectAPI:
    def test_collect_folder(self, tmp_path):
        cols = ["市场", "健康顾问", "订单号", "金额", "手机号"]
        for i, name in enumerate(["文件A.xlsx", "文件B.xlsx"]):
            df = pd.DataFrame(
                [[f"市场{i}", f"顾问{i}", f"O{i}", 100 + i, f"138{i:08d}"]],
                columns=cols,
            )
            df.to_excel(str(tmp_path / name), sheet_name="明细", index=False)
        r = client.post("/api/collect/folder", json={"folder_path": str(tmp_path), "recursive": False})
        data = r.get_json()
        assert data["ok"], data.get("msg", "")
        assert data["total"] == 2
        assert data["success"] == 2
        assert data["failed"] == 0
        # 清理
        for res in data["results"]:
            if res.get("id"):
                DataSourceDAO.delete(res["id"])

    def test_collect_nonexistent_folder_returns_400(self):
        r = client.post("/api/collect/folder", json={"folder_path": "/nonexistent/path"})
        assert r.status_code == 400


# ============================================================================
# 占位通道（数据库/爬虫）应返回 400 告知未接入
# ============================================================================
@pytest.mark.integration
class TestPlaceholderChannels:
    def test_database_channel_returns_400(self):
        sid = DataSourceDAO.create(name=f"{P}数据库占位", channel="database", status="pending")
        try:
            r = client.post(f"/api/sources/{sid}/collect")
            assert r.status_code == 400
        finally:
            DataSourceDAO.delete(sid)

    def test_crawler_channel_returns_400(self):
        sid = DataSourceDAO.create(name=f"{P}爬虫占位", channel="crawler", status="pending")
        try:
            r = client.post(f"/api/sources/{sid}/collect")
            assert r.status_code == 400
        finally:
            DataSourceDAO.delete(sid)
