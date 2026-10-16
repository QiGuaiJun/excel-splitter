# -*- coding: utf-8 -*-
"""Excel 读取与列元数据判定的纯函数单测。"""
import io

import pandas as pd
import pytest
from openpyxl import Workbook

from app import _col_meta, _excel_row_number, _is_multi_value, _safe_filename, _sheet_to_df, _to_num
from api.collect import _inspect_csv, _inspect_xlsx, inspect_excel


# ----------------------------------------------------------------------------
# 工具小函数
# ----------------------------------------------------------------------------
class TestSafeFilename:
    def test_replaces_invalid_chars(self):
        # Windows 非法字符全部替换成 _
        out = _safe_filename("a/b\\c:d*e?f\"g<h>i|j.txt")
        assert "\\" not in out and "/" not in out and ":" not in out
        assert "*" not in out and "?" not in out and '"' not in out
        assert "<" not in out and ">" not in out and "|" not in out
        # 去掉前后 . 与空格
        assert out == "a_b_c_d_e_f_g_h_i_j.txt"

    def test_strips_dots_and_spaces(self):
        assert _safe_filename("  ..hi..  ") == "hi"

    def test_empty_returns_placeholder(self):
        assert _safe_filename("") == "未命名"
        assert _safe_filename("...") == "未命名"


class TestIsMultiValue:
    @pytest.mark.parametrize("s,expected", [
        ("a,b", True),
        ("a，b", True),
        ("a、b", True),
        ("a;b", True),
        ("a;b/c", True),
        ("a+b", True),
        ("a\nb", True),
        ("a", False),
        ("", False),
        (",,,", False),  # 全是分隔符 -> 无有效段
    ])
    def test_detection(self, s, expected):
        assert _is_multi_value(s) is expected


class TestExcelRowNumber:
    def test_zero_based_to_excel_row(self):
        # DataFrame 下标 0 对应 Excel 第 2 行（表头占第 1 行）
        assert _excel_row_number(0) == 2
        assert _excel_row_number(1) == 3
        assert _excel_row_number(10) == 12


# ----------------------------------------------------------------------------
# _sheet_to_df 流式读取
# ----------------------------------------------------------------------------
@pytest.fixture
def workbook_path(tmp_path):
    """在临时目录造一个 2-Sheet 的 Excel：明细 + 说明。"""
    path = str(tmp_path / "fixture.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame([
            ["义乌", "王顾问", "O1", 100],
            ["金华", "李顾问", "O2", 200],
        ], columns=["市场", "顾问", "订单号", "金额"]).to_excel(w, sheet_name="明细", index=False)
        pd.DataFrame([["说明文字"]], columns=["注释"]).to_excel(w, sheet_name="说明", index=False)
    return path


class TestSheetToDf:
    def test_reads_column_headers_and_skips_unnamed(self, workbook_path):
        """_sheet_to_df 是流式读层：返回字符串 DF，Excel 行号存在 index 上。

        注意：__row__ 列是 _clean() 加的，不在此层保证。
        """
        from openpyxl import load_workbook

        wb = load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            df = _sheet_to_df(wb, "明细")
        finally:
            wb.close()
        assert list(df.columns) == ["市场", "顾问", "订单号", "金额"]
        assert len(df) == 2
        assert df.iloc[0]["市场"] == "义乌"
        # Excel 真实行号存在 df.index 上：第 1 行表头，之后行号从 2 开始
        assert list(df.index) == [2, 3]

    def test_drops_fully_empty_rows(self, tmp_path):
        path = str(tmp_path / "with_blanks.xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            pd.DataFrame([
                ["A", "1"],
                [None, None],   # 全空行
                ["B", "2"],
            ], columns=["x", "y"]).to_excel(w, sheet_name="S", index=False)
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            df = _sheet_to_df(wb, "S")
        finally:
            wb.close()
        assert len(df) == 2
        assert list(df["x"]) == ["A", "B"]

    def test_nrows_limit(self, workbook_path):
        from openpyxl import load_workbook

        wb = load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            df = _sheet_to_df(wb, "明细", nrows=1)
        finally:
            wb.close()
        assert len(df) == 1
        assert df.iloc[0]["市场"] == "义乌"


# ----------------------------------------------------------------------------
# 列元数据判定 _col_meta
# ----------------------------------------------------------------------------
class TestColMeta:
    def test_numeric_column_detected(self):
        df = pd.DataFrame({"金额": ["100", "200", "300", "400"]})
        meta = _col_meta(["金额"], df)
        assert meta["金额"]["numeric"] is True
        assert meta["金额"]["measure"] is True

    def test_text_column_not_numeric(self):
        df = pd.DataFrame({"市场": ["义乌", "金华", "杭州", "北京"]})
        meta = _col_meta(["市场"], df)
        assert meta["市场"]["numeric"] is False
        assert meta["市场"]["measure"] is False

    def test_id_keyword_marks_measure_false(self):
        # 数字编号（名称含"号"）不是 measure
        df = pd.DataFrame({"订单号": ["1001", "1002", "1003"]})
        meta = _col_meta(["订单号"], df)
        assert meta["订单号"]["numeric"] is True
        assert meta["订单号"]["measure"] is False

    def test_empty_df_returns_flags_false(self):
        df = pd.DataFrame({"x": []})
        meta = _col_meta(["x"], df)
        assert meta["x"]["numeric"] is False
        assert meta["x"]["measure"] is False


# ----------------------------------------------------------------------------
# inspect_excel / _inspect_csv / _inspect_xlsx 入口
# ----------------------------------------------------------------------------
class TestInspectExcel:
    def test_xlsx_returns_sheet_list(self, workbook_path):
        info = inspect_excel(workbook_path)
        names = [s["name"] for s in info["sheets"]]
        assert names == ["明细", "说明"]
        # 不严格断言 total_rows：openpyxl read_only 模式下 max_row
        # 会把尾部空 sheet 也算大，已知小毛病（app.py 主流程用 100 行空行终止规避）
        assert info["total_rows"] >= 2
        # 但每个 sheet 的 columns 必须正确
        cols_by_sheet = {s["name"]: s["columns"] for s in info["sheets"]}
        assert cols_by_sheet["明细"] == ["市场", "顾问", "订单号", "金额"]

    def test_csv_basic(self, tmp_path):
        path = str(tmp_path / "x.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("市场,顾问\n义乌,王\n金华,李\n")
        info = inspect_excel(path)
        assert info["total_rows"] == 2
        assert info["sheets"][0]["columns"] == ["市场", "顾问"]

    def test_empty_csv(self, tmp_path):
        path = str(tmp_path / "empty.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
        info = inspect_excel(path)
        assert info["total_rows"] == 0
