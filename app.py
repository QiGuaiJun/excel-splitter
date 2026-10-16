# -*- coding: utf-8 -*-
"""Excel 智能分表脱敏工作台（本地网页版）· 入口。

数据全程只在本机处理，不上传外网。

本文件仅做应用启动与蓝图注册。所有业务逻辑在各 api/*.py 子模块中：
- api/distribute.py   数据分发（拆分/汇总/模板/Excel 上传解析）
- api/sources.py      分类与数据源 CRUD
- api/collect.py      多通道采集（Excel / 文件夹 / 代码爬取）
- api/clean.py        数据清洗
- api/calc.py         数据计算（SQL / 表关联）
- api/logs.py         运行历史

历史：本文件原本 897 行，分发逻辑 600 行写在模块顶层；批次 4 把这些搬到了
api/distribute.py。本文件只用 `from api.distribute import *` 重导出
分发层会用到的纯函数（mask_* 等），保留根目录测试脚本 `from app import xxx`
的兼容性（批次 5 再清理）。
"""
import socket
import threading

from flask import Flask, render_template

from api.calc import bp as calc_bp
from api.clean import bp as clean_bp
from api.collect import bp as collect_bp
from api.distribute import bp as distribute_bp  # noqa: F401
from api.logs import bp as logs_bp
from api.sources import bp as sources_bp


app = Flask(__name__)

# 注册蓝图
app.register_blueprint(sources_bp, url_prefix="/api")
app.register_blueprint(collect_bp, url_prefix="/api")
app.register_blueprint(logs_bp, url_prefix="/api")
app.register_blueprint(clean_bp, url_prefix="/api")
app.register_blueprint(calc_bp, url_prefix="/api")
app.register_blueprint(distribute_bp, url_prefix="/api")

app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 最大 512MB


# ---------------------------------------------------------------------------
# 重新导出分发层纯函数，保留 `from app import mask_xxx / build_summary` 等
# 兼容性用法（根目录的 test_workbench.py / test_summary.py / test_four.py 等
# 直接 `import app` 然后 `A.mask_phone(...)`）。批次 5 把这些测试迁到
# tests/ 下后，会同步把 import 改成 `from api.distribute import ...`。
# ---------------------------------------------------------------------------
from api.distribute import (  # noqa: E402, F401
    RULES,
    _autofit_ws,
    _col_meta,
    _digits,
    _excel_row_number,
    _is_multi_value,
    _safe_filename,
    _sheet_to_df,
    _to_num,
    apply_mask,
    build_summary,
    mask_address,
    mask_idcard,
    mask_keep_ab,
    mask_name,
    mask_phone,
    mask_replace,
)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
def _find_free_port(preferred=18765):
    for p in [preferred] + list(range(preferred + 1, preferred + 30)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            s.close()
            continue
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


if __name__ == "__main__":
    import webbrowser

    port = _find_free_port(18765)
    url = f"http://127.0.0.1:{port}"
    print(f"工作台已启动：{url}")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # 本机访问，不开公网
    app.run(host="127.0.0.1", port=port, debug=False)
