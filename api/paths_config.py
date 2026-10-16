# -*- coding: utf-8 -*-
"""项目路径常量集中管理。

背景：原本路径分散在两处：
- app.py 顶层定义 UPLOAD_DIR / CONFIG_DIR 模块级常量
- api/*.py 通过 db.connection.BASE_DIR 推断出 data/sources/

本批次统一：所有路径常量集中在本模块。
"""
import os

from db.connection import BASE_DIR

# 分发流程的临时文件目录（inspect 上传的 Excel 临时落地这里）
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 拆分配置模板目录
CONFIG_DIR = os.path.join(BASE_DIR, "configs")
os.makedirs(CONFIG_DIR, exist_ok=True)

# 数据采集 / 清洗 / 计算 模块的源文件落地目录
SOURCES_DIR = os.path.join(BASE_DIR, "data", "sources")
os.makedirs(SOURCES_DIR, exist_ok=True)
