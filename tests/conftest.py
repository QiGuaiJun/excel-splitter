# -*- coding: utf-8 -*-
"""pytest 共享夹具。

约定：
- unit 测试：纯函数，不需要任何外部依赖。
- db 标记：需要 MySQL（config/database.json 中描述的端口 3307 实例）。
- integration 标记：依赖文件系统 / Flask test_client，可能需要也可能不需要 DB。

设计原则：单元测试不应因为 DB 不可用而失败；DB 不可用时，db/integration 用例 skip。

注意：pytest 9.1 在 conftest 的 autouse fixture 解析顺序上有差异，
不能稳定保证 conftest 的 skip 在测试文件的其他 autouse fixture 之前执行，
所以本 conftest **改用 module-level pytest.importorskip + fixtures
显式声明 mysql_available 依赖** 的双保险策略。
"""
import os
import socket
import sys

import pytest

# 把项目根加入 sys.path，让 `import app / api.xxx / db.xxx` 直接可用
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _mysql_reachable(host: str, port: int, timeout: float = 0.4) -> bool:
    """快速探测 MySQL TCP 端口是否可达。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def mysql_reachable_from_config(timeout: float = 0.4) -> bool:
    """读取 config/database.json 并探测 MySQL TCP 是否可达。

    用于模块顶层 pytest.importorskip / pytest.skip：
    把"DB 不可达"在收集阶段就消化掉，不进入 setup 阶段抛 ERROR。
    """
    cfg_path = os.path.join(BASE_DIR, "config", "database.json")
    if not os.path.exists(cfg_path):
        return False
    try:
        import json

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return False
    return _mysql_reachable(
        cfg.get("host", "127.0.0.1"),
        int(cfg.get("port", 3307)),
        timeout=timeout,
    )


@pytest.fixture(scope="session")
def mysql_available() -> bool:
    """整个测试会话探测一次 MySQL 可达性。DAO/API/integration 用例按需 skip。"""
    cfg_path = os.path.join(BASE_DIR, "config", "database.json")
    if not os.path.exists(cfg_path):
        return False
    try:
        import json

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return False
    return _mysql_reachable(cfg.get("host", "127.0.0.1"), int(cfg.get("port", 3307)))
