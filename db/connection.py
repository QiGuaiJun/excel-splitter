# -*- coding: utf-8 -*-
"""数据库连接管理：从 config/database.json 读取配置，返回 pymysql 连接。"""
import json
import os
import pymysql
from pymysql.cursors import DictCursor

# 项目根目录（db/connection.py 的上两级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "database.json")


def load_config():
    """读取数据库连接配置。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_connection(use_dict=True):
    """获取一个数据库连接。

    Args:
        use_dict: 是否使用 DictCursor（返回字典而非元组）。

    Returns:
        pymysql.connections.Connection
    """
    cfg = load_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg.get("password", ""),
        database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
        cursorclass=DictCursor if use_dict else pymysql.cursors.Cursor,
        autocommit=False,
    )
