# -*- coding: utf-8 -*-
"""端到端测试：真实 HTTP 请求，验证数据源管理中心全链路。

依赖：
- MySQL 测试库（端口 3307）
- 运行中的 Flask app（python app.py 启动后默认 18765）

DB 不可达时整个文件 skip；服务未启动时用例 marker-skip（标记为 integration，
需要在 conftest 或本文件探测服务）。

原始 e2e 测试用的是 urllib + 硬编码 BASE URL，行为等价。
"""
import io
import json
import socket
import urllib.request

import pandas as pd
import pytest

from tests.conftest import mysql_reachable_from_config

if not mysql_reachable_from_config():
    pytest.skip("MySQL 测试库不可达，跳过整个文件", allow_module_level=True)


BASE = "http://127.0.0.1:18765"


def _server_up(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


if not _server_up("127.0.0.1", 18765):
    pytest.skip("Flask app 未运行（端口 18765 不可达），跳过整个文件", allow_module_level=True)


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


# ============================================================================
# 全链路端到端
# ============================================================================
@pytest.mark.integration
class TestFullLifecycle:
    def test_create_category(self):
        r = http_post_json("/api/categories", {"name": "E2E测试分类"})
        assert r["ok"], r
        self.cat_id = r["data"]["id"]

    def test_upload_excel(self):
        df = pd.DataFrame([
            ["义乌市场", "王顾问", "O001", 100, "13812345678"],
            ["金华市场", "李顾问", "O002", 200, "13911112222"],
        ], columns=["市场", "健康顾问", "订单号", "金额", "手机号"])
        buf = io.BytesIO()
        df.to_excel(buf, sheet_name="明细", index=False)
        excel_bytes = buf.getvalue()
        r = http_post_multipart(
            "/api/collect/excel",
            {"name": "E2E测试数据源", "category_id": str(getattr(self, "cat_id", ""))},
            {"file": ("test_e2e.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r["ok"], r.get("msg", "")
        assert r["data"]["row_count"] == 2
        assert r["data"]["col_count"] == 5
        assert r["data"]["sheet_names"] == ["明细"]
        self.src_id = r["data"]["id"]

    def test_list_sources_contains_created(self):
        r = http_get("/api/sources")
        assert r["ok"]
        assert any(s["id"] == getattr(self, "src_id", -1) for s in r["data"])
        assert r["stats"]["total"] >= 1

    def test_filter_by_category(self):
        cat_id = getattr(self, "cat_id", None)
        if not cat_id:
            pytest.skip("前置分类未创建")
        r = http_get(f"/api/sources?category_id={cat_id}")
        assert any(s["id"] == getattr(self, "src_id", -1) for s in r["data"])

    def test_preview(self):
        src_id = getattr(self, "src_id", None)
        if not src_id:
            pytest.skip("前置数据源未创建")
        r = http_get(f"/api/sources/{src_id}/preview?limit=10")
        assert r["ok"], r.get("msg", "")
        assert r["columns"] == ["市场", "健康顾问", "订单号", "金额", "手机号"]
        assert len(r["rows"]) == 2

    def test_recollect(self):
        src_id = getattr(self, "src_id", None)
        if not src_id:
            pytest.skip("前置数据源未创建")
        r = http_post_json(f"/api/sources/{src_id}/collect", {})
        assert r["ok"], r.get("msg", "")

    def test_cleanup(self):
        src_id = getattr(self, "src_id", None)
        cat_id = getattr(self, "cat_id", None)
        if src_id:
            req = urllib.request.Request(BASE + f"/api/sources/{src_id}", method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as r:
                assert json.loads(r.read().decode("utf-8"))["ok"]
        if cat_id:
            req = urllib.request.Request(BASE + f"/api/categories/{cat_id}", method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as r:
                assert json.loads(r.read().decode("utf-8"))["ok"]


# ============================================================================
# 注意：pytest 的默认顺序按字典序执行类内方法；如果想强制顺序，加 pytest-order
# 或把全链路用例合并到一个 test 方法里。当前 setup/teardown 用 self.xxx 传递数据。
# ============================================================================
