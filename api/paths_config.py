# -*- coding: utf-8 -*-
"""项目路径常量集中管理。

历史背景：app.py 原本定义 UPLOAD_DIR / CONFIG_DIR 模块级常量，
其他模块通过 db.connection.BASE_DIR 推断路径，存在两套家底
（app.py 的 uploads/ 与 api/*.py 的 data/sources/）。

本批次仅新增本模块，让分发等模块按需引用，避免引入大型路径重构（批次 9
再做集中统一）。后续批次会把所有模块路径都改成从这里导入。
"""
import os

from db.connection import BASE_DIR

# 分发流程的临时文件目录（inspect 上传的 Excel 临时落地这里）
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 拆分配置模板目录
CONFIG_DIR = os.path.join(BASE_DIR, "configs")
os.makedirs(CONFIG_DIR, exist_ok=True)
