# -*- coding: utf-8 -*-
"""build_summary() 单元测试。

覆盖场景：
- 仅求和（无 counts）
- 仅计数（distinct=true 去重，distinct=false 计行数）
- 分组 + 求和 + 计数 组合
- 末行合计
- 按自定义指标排序（sort_label/sort_desc）
- 分组列别名
- 无分组维度时只输出一行总计
- 文本订单号去重计数（与 test_order_count.py 同样逻辑，但走纯函数入口）
"""
from decimal import Decimal

import pandas as pd
import pytest

from app import build_summary, _to_num


# ----------------------------------------------------------------------------
# 共享 fixture 数据：4 行明细
# ----------------------------------------------------------------------------
@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame([
        ["义乌", "王顾问", "O001", "100"],
        ["义乌", "王顾问", "O001", "50"],   # 同一订单号第二行
        ["义乌", "王顾问", "O002", "200"],
        ["义乌", "李顾问", "O003", "30"],
    ], columns=["市场", "健康顾问", "订单号", "金额"])


# ----------------------------------------------------------------------------
# _to_num 数字清洗
# ----------------------------------------------------------------------------
class TestToNum:
    def test_plain_int(self):
        s = pd.Series(["100", "200", ""])
        out = _to_num(s).tolist()
        assert out[0] == 100
        assert out[1] == 200
        assert pd.isna(out[2])

    def test_currency_symbols_stripped(self):
        s = pd.Series(["￥1,200.50", "¥3,000", "1,234.56元"])
        out = _to_num(s).tolist()
        assert float(out[0]) == 1200.50
        assert float(out[1]) == 3000.0
        assert float(out[2]) == 1234.56

    def test_unparseable_becomes_nan(self):
        s = pd.Series(["abc", ""])
        out = _to_num(s).tolist()
        assert pd.isna(out[0])
        assert pd.isna(out[1])


# ----------------------------------------------------------------------------
# build_summary
# ----------------------------------------------------------------------------
class TestBuildSummary:
    def test_group_count_distinct_and_sum(self, sample_df):
        sconf = {
            "groups": [{"col": "健康顾问"}],
            "sums":   [{"col": "金额", "label": "金额合计"}],
            "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
            "sort_label": "金额合计",
            "sort_desc": True,
        }
        res = build_summary(sample_df, sconf)
        assert res is not None
        # 按金额降序 -> 王在前
        assert res.iloc[0]["健康顾问"] == "王顾问"
        # 王顾问：去重订单 O001/O002 = 2 单；金额 100+50+200 = 350
        w = res[res["健康顾问"] == "王顾问"].iloc[0]
        assert int(w["订单数"]) == 2
        assert float(w["金额合计"]) == 350.0
        # 李顾问：1 单 30 元
        l = res[res["健康顾问"] == "李顾问"].iloc[0]
        assert int(l["订单数"]) == 1
        assert float(l["金额合计"]) == 30.0
        # 末行合计
        tot = res[res["健康顾问"] == "合计"].iloc[0]
        assert int(tot["订单数"]) == 3
        assert float(tot["金额合计"]) == 380.0

    def test_no_group_one_total_row(self, sample_df):
        """无分组时只输出一行总计（表头 + 一行）。"""
        sconf = {
            "groups": [],
            "sums":   [{"col": "金额", "label": "金额合计"}],
            "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
        }
        res = build_summary(sample_df, sconf)
        assert res is not None
        assert list(res.columns) == ["订单数", "金额合计"]
        # 仅一行总计：3 个不同订单；金额 380
        assert len(res) == 1
        assert int(res.iloc[0]["订单数"]) == 3
        assert float(res.iloc[0]["金额合计"]) == 380.0

    def test_text_order_id_distinct_count(self, sample_df):
        """文本型订单号也必须能正确去重计数。"""
        sconf = {
            "groups": [{"col": "健康顾问"}],
            "counts": [{"col": "订单号", "label": "记录数", "distinct": True}],
        }
        res = build_summary(sample_df, sconf)
        w = res[res["健康顾问"] == "王顾问"].iloc[0]
        # 王顾问 3 行 -> 2 个不同订单号（O001 / O002）
        assert int(w["记录数"]) == 2

    def test_count_row_level(self, sample_df):
        """distinct=False 时按行数计（不去重）。"""
        sconf = {
            "groups": [{"col": "健康顾问"}],
            "counts": [{"col": "订单号", "label": "记录数", "distinct": False}],
        }
        res = build_summary(sample_df, sconf)
        w = res[res["健康顾问"] == "王顾问"].iloc[0]
        assert int(w["记录数"]) == 3
        l = res[res["健康顾问"] == "李顾问"].iloc[0]
        assert int(l["记录数"]) == 1

    def test_group_alias(self, sample_df):
        sconf = {
            "groups": [{"col": "健康顾问", "label": "顾问姓名"}],
            "sums":   [{"col": "金额", "label": "金额合计"}],
        }
        res = build_summary(sample_df, sconf)
        assert "顾问姓名" in res.columns
        assert "健康顾问" not in res.columns

    def test_no_metrics_returns_none(self, sample_df):
        """没有 sums/counts 时不应生成汇总表。"""
        res = build_summary(sample_df, {"groups": [{"col": "健康顾问"}]})
        assert res is None

    def test_sum_desc_default(self, sample_df):
        sconf = {
            "groups": [{"col": "健康顾问"}],
            "sums":   [{"col": "金额", "label": "金额合计"}],
            "sort_label": "金额合计",
            "sort_desc": True,
        }
        res = build_summary(sample_df, sconf)
        # 把合计行去掉
        body = res[res["健康顾问"] != "合计"]
        first_sum = float(body.iloc[0]["金额合计"])
        last_sum = float(body.iloc[-1]["金额合计"])
        assert first_sum >= last_sum
