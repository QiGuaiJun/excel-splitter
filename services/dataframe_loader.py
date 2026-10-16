# -*- coding: utf-8 -*-
"""统一 DataFrame 加载器。

来源背景：api/clean.py / api/calc.py 原本各自定义了完全相同的
`_load_dataframe(source_id)`（24 行，按 ID 读 Excel/CSV/JSON）。
本模块把这一逻辑收敛一份，供清洗/计算/分发等模块共享。
"""
import json
import os
from typing import Tuple

import pandas as pd


def load_dataframe_by_source_id(source_id: int, file_path: str) -> Tuple[pd.DataFrame, str]:
    """根据数据源登记的 file_path 加载 DataFrame。

    Returns:
        (df, error_msg)：成功时 error_msg 为 None，失败时 df 为空 df + 错误信息。

    支持扩展名：.xlsx / .xls / .csv / .json
    """
    if not file_path or not os.path.exists(file_path):
        return pd.DataFrame(), "源文件不存在"
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, dtype=str)
        elif ext == ".csv":
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
        elif ext == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            df = pd.DataFrame(data)
        else:
            return pd.DataFrame(), f"不支持的文件格式: {ext}"
    except Exception as e:
        return pd.DataFrame(), f"读取文件失败: {e}"
    return df, None


def parse_config_json(cfg) -> dict:
    """安全地反序列化 MySQL JSON 列。

    重复出现于 api/clean.py / api/calc.py：每次拿到 cfg 都得防御一次
    字符串/字典两种情况。本工具把防御性解析收口到一处。
    """
    if not cfg:
        return {}
    if isinstance(cfg, str):
        try:
            return json.loads(cfg) or {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return cfg
