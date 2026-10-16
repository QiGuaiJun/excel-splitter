# -*- coding: utf-8 -*-
"""路径 / 配置工具纯函数单测。"""
import os

import pytest

from app import _safe_filename  # 复用，避免重复定义


def test_safe_filename_handles_chinese():
    # 中文字段保留，空白折叠
    assert _safe_filename(" 义乌市场  ") == "义乌市场"


def test_safe_filename_replaces_windows_reserved_chars():
    # <>:"/\|?* 等应被替换
    s = _safe_filename("a<b>c:d/e\\f|g?h*i")
    assert "<" not in s and ">" not in s and ":" not in s
    assert "/" not in s and "\\" not in s and "|" not in s
    assert "?" not in s and "*" not in s
