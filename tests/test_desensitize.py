# -*- coding: utf-8 -*-
"""全表脱敏测试。

覆盖：
- 新增脱敏规则 bankcard / email
- 识别引擎：列名命中、内容命中、阈值、订单号防误伤、姓名不脱敏
- 片段替换：姓名+手机号同格只打号码
- 工作簿执行：多子表、跳过无敏感子表、格式（列宽/底色/合并单元格）保留
- 两个接口：/api/desensitize/scan、/api/desensitize/run

依赖：Flask test_client + openpyxl，不需要 MySQL。
"""
import io
import os
import shutil
import tempfile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from app import app
from services.detect import (
    _ID_C,
    _ID_W,
    cell_kinds,
    detect_column,
    detect_sheet,
    idcard_ok,
    luhn_ok,
    mask_text,
)
from services.desensitize import run_desensitize, scan_workbook
from services.masking import mask_bankcard, mask_email


# ----------------------------------------------------------------------------
# 辅助：造出真实能过校验的身份证 / 银行卡
# ----------------------------------------------------------------------------
def gen_idcard(base17: str) -> str:
    """按 GB 11643 算校验位。"""
    total = sum(int(base17[i]) * _ID_W[i] for i in range(17))
    return base17 + _ID_C[total % 11]


def gen_bankcard(base15: str) -> str:
    """补足 16 位并算 Luhn 校验位。"""
    body = base15 + "0"
    for chk in "0123456789":
        cand = body[:-1] + chk
        total = 0
        for i, c in enumerate(reversed(cand)):
            n = int(c)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        if total % 10 == 0:
            return cand
    return body


ID_OK = gen_idcard("33070219900101123")
CARD_OK = gen_bankcard("622202123456789")


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def work_dir():
    d = tempfile.mkdtemp(prefix="des_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def build_sample(path):
    """造一个三子表工作簿：客户明细（敏感）/ 订单流水（干净）/ 活动名单（混合）。

    客户明细特意带上「买家姓名」「买家昵称」两列：前者整列是手机号，后者姓名+手机号，
    用来复现"列名不可信、靠正则扫内容"的场景。
    """
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "客户明细"
    ws1.append(["客户名称", "手机号", "身份证号", "银行卡号", "邮箱", "详细地址", "订单号", "买家姓名", "买家昵称"])
    ws1.append(["张三", "13812345678", ID_OK, CARD_OK, "zhangsan@qq.com", "浙江省金华市义乌市稠城街道1号", "202401011234567890", "13812345678", "小红13912345678"])
    ws1.append(["李四", "13912345678", ID_OK, CARD_OK, "lisi@163.com", "浙江省杭州市西湖区文一路2号", "202401011234567891", "13612345678", "阿强"])
    ws1.column_dimensions["A"].width = 18
    ws1.row_dimensions[1].height = 26
    ws1["A1"].fill = PatternFill("solid", fgColor="FFC7CE")
    ws1["A1"].font = Font(bold=True, size=12)

    ws2 = wb.create_sheet("订单流水")
    ws2.append(["订单号", "金额"])
    ws2.append(["202401011234567890", 199.5])

    ws3 = wb.create_sheet("活动名单")
    ws3.append(["姓名", "客户信息"])
    ws3.append(["王五", "王五13812345678"])
    ws3.append(["赵六", "赵六13912345678"])
    ws3.merge_cells("A4:B4")

    wb.save(path)
    return path


# ----------------------------------------------------------------------------
# 规则：银行卡 / 邮箱
# ----------------------------------------------------------------------------
class TestMaskBankcard:
    def test_keeps_last_four(self):
        assert mask_bankcard("6222021234567890123") == "*" * 15 + "0123"

    def test_short_number_all_stars(self):
        assert mask_bankcard("1234") == "****"

    def test_ignores_separators(self):
        assert mask_bankcard("6222 0212 3456 7890") == "*" * 12 + "7890"

    def test_empty(self):
        assert mask_bankcard("") == ""
        assert mask_bankcard(None) is None


class TestMaskEmail:
    def test_keeps_first_two_of_local(self):
        assert mask_email("zhangsan@qq.com") == "zh***@qq.com"

    def test_single_char_local(self):
        assert mask_email("a@qq.com") == "a***@qq.com"

    def test_text_without_at_returns_raw(self):
        assert mask_email("没有邮箱") == "没有邮箱"

    def test_empty(self):
        assert mask_email("") == ""


# ----------------------------------------------------------------------------
# 识别：列名命中
# ----------------------------------------------------------------------------
class TestDetectByName:
    def test_phone_column(self):
        info = detect_column("联系电话", ["13812345678"])
        assert info["kinds"][0] == {"kind": "phone", "by": "name"}

    def test_idcard_column(self):
        info = detect_column("身份证号", ["33070219900101123X"])
        assert info["kinds"][0] == {"kind": "idcard", "by": "name"}

    def test_bankcard_column(self):
        assert detect_column("银行卡号", ["6222"])["kinds"][0]["kind"] == "bankcard"

    def test_email_column(self):
        assert detect_column("电子邮箱", ["a@b.com"])["kinds"][0]["kind"] == "email"

    def test_address_column(self):
        assert detect_column("详细地址", ["浙江省金华市"])["kinds"][0]["kind"] == "address"

    def test_plain_name_column_not_in_list(self):
        # 纯姓名列：没有任何号码片段，不进脱敏清单（姓名要保留）
        assert detect_column("姓名", ["张三", "李四"]) is None
        hits = detect_sheet(["姓名", "手机号"], [["张三", "13812345678"]])
        assert [h["col"] for h in hits] == ["手机号"]
        assert hits[0]["kinds"][0] == {"kind": "phone", "by": "name"}


# ----------------------------------------------------------------------------
# 识别：内容命中 / 防误伤
# ----------------------------------------------------------------------------
class TestDetectByContent:
    def test_note_column_high_hit_ratio(self):
        values = ["13812345678", "13912345678", "13712345678", "13612345678", "无号码"]
        assert detect_column("备注", values)["kinds"][0]["kind"] == "phone"

    def test_single_phone_in_note_column_still_caught(self):
        # 防漏优先：只要有一格出现手机号就处理，不再要求整列 80% 命中
        values = ["13812345678", "正常文字", "另一条备注", "随便写"]
        info = detect_column("备注", values)
        assert info["kinds"][0]["kind"] == "phone"
        assert info["kinds"][0]["by"] == "content"

    def test_order_number_not_mistaken_as_idcard(self):
        assert detect_column("订单号", ["202401011234567890", "202401011234567891"]) is None

    def test_name_plus_phone_column_uses_content_kind(self):
        info = detect_column("客户信息", ["王五13812345678", "赵六13912345678"])
        assert info["kinds"][0] == {"kind": "phone", "by": "content"}

    def test_empty_column_ignored(self):
        assert detect_column("备注", ["", "", None]) is None

    def test_duplicate_header_columns_both_indexed(self):
        # 两个同名列各自独立定位，执行时两列都会被处理，不会漏掉第二列
        hits = detect_sheet(["手机号", "手机号"], [["13812345678", "13912345678"]])
        assert [h["index"] for h in hits] == [0, 1]


# ----------------------------------------------------------------------------
# 字段名不可信：姓名 / 昵称里出现号码也要打码
# ----------------------------------------------------------------------------
class TestFieldNameAgnostic:
    def test_name_column_full_of_phones_is_masked(self):
        info = detect_column("买家姓名", ["13812345678", "13912345678"])
        assert info["kinds"][0] == {"kind": "phone", "by": "content"}

    def test_name_column_with_one_phone_still_caught(self):
        info = detect_column("买家姓名", ["张三", "13812345678", "李四"])
        assert info["kinds"][0] == {"kind": "phone", "by": "content"}

    def test_nickname_embedded_phone_masked(self):
        assert mask_text("phone", "小红13912345678") == "小红139****5678"

    def test_plain_names_never_touched(self):
        assert cell_kinds("张三") == []
        assert cell_kinds("已付款") == []
        assert detect_column("买家昵称", ["小明", "阿强"]) is None


# ----------------------------------------------------------------------------
# 片段替换
# ----------------------------------------------------------------------------
class TestMaskText:
    def test_mixed_cell_keeps_name(self):
        assert mask_text("phone", "张三13812345678") == "张三138****5678"

    def test_phone_glued_after_digits(self):
        # 昵称里"序号+号码"被拼成一串 12/13 位数字，尾部 11 位照样打码
        assert mask_text("phone", "昵称013800000000") == "昵称0138****0000"
        assert mask_text("phone", "昵称1213800000012") == "昵称12138****0012"

    def test_twelve_digit_number_not_phone(self):
        # 普通 12 位编号不能被当成粘连号码
        assert cell_kinds("202401011234") == []

    def test_whole_cell_with_86_prefix(self):
        assert mask_text("phone", "+86 138 1234 5678") == "138****5678"

    def test_idcard_strict_skips_invalid(self):
        # 校验位不对的 18 位数字，内容判定场景下不动（防订单号）
        assert mask_text("idcard", "202401011234567890", strict=True) == "202401011234567890"

    def test_idcard_loose_masks_by_column_name(self):
        assert mask_text("idcard", "202401011234567890", strict=False) == "2024**********7890"

    def test_bankcard_strict_requires_luhn(self):
        assert mask_text("bankcard", "6222021234567890123", strict=True) == "6222021234567890123"
        assert mask_text("bankcard", CARD_OK, strict=True) == "*" * 12 + CARD_OK[-4:]

    def test_email_in_sentence(self):
        assert mask_text("email", "联系 zhangsan@qq.com 即可") == "联系 zh***@qq.com 即可"


# ----------------------------------------------------------------------------
# 工作簿：扫描 + 执行
# ----------------------------------------------------------------------------
class TestWorkbookFlow:
    def test_scan_marks_hit_and_clean_sheets(self, work_dir):
        src = build_sample(os.path.join(work_dir, "源表.xlsx"))
        plan = scan_workbook(src)
        names = {s["name"]: s for s in plan["sheets"]}
        assert set(names) == {"客户明细", "订单流水", "活动名单"}
        assert [h["col"] for h in names["客户明细"]["hits"]] == [
            "手机号", "身份证号", "银行卡号", "邮箱", "详细地址",
            "买家姓名", "买家昵称",
        ]
        # 买家姓名两列都是"内容识别"出来的（列名不含任何号码关键词）
        by_col = {h["col"]: h["kinds"][0]["by"] for h in names["客户明细"]["hits"]}
        assert by_col["买家姓名"] == "content"
        assert by_col["买家昵称"] == "content"
        assert names["订单流水"]["hits"] == []
        assert plan["hit_sheets"] == 2

    def test_run_outputs_one_file_multi_sheet_and_skips_clean(self, work_dir):
        src = build_sample(os.path.join(work_dir, "源表.xlsx"))
        out = os.path.join(work_dir, "源表_已脱敏.xlsx")
        plan = scan_workbook(src)
        report = run_desensitize(src, out, plan)

        assert report["ok"] is True
        assert report["out_sheets"] == 2
        assert [s["name"] for s in report["skipped"]] == ["订单流水"]
        assert os.path.exists(out)

        wb = load_workbook(out)
        assert wb.sheetnames == ["客户明细", "活动名单"]
        ws = wb["客户明细"]
        assert ws["A2"].value == "张三"                     # 姓名保留
        assert ws["B2"].value == "138****5678"
        assert ws["C2"].value == "3307**********" + ID_OK[-4:]
        assert ws["D2"].value == "*" * 12 + CARD_OK[-4:]
        assert ws["E2"].value == "zh***@qq.com"
        assert ws["F2"].value == "浙江省金华市义乌市****"    # 保留到区县
        assert ws["G2"].value == "202401011234567890"      # 订单号不动
        # 列名不可信的两列：姓名列整列号码打码，昵称列只打号码
        assert ws["H2"].value == "138****5678"
        assert ws["I2"].value == "小红139****5678"
        assert ws["I3"].value == "阿强"                     # 纯昵称不动
        # 混合单元格：姓名保留，号码打星
        ws3 = wb["活动名单"]
        assert ws3["B2"].value == "王五138****5678"
        wb.close()

    def test_format_preserved(self, work_dir):
        src = build_sample(os.path.join(work_dir, "源表.xlsx"))
        out = os.path.join(work_dir, "out.xlsx")
        run_desensitize(src, out, scan_workbook(src))

        wb = load_workbook(out)
        ws = wb["客户明细"]
        assert ws.column_dimensions["A"].width == 18          # 列宽
        assert ws.row_dimensions[1].height == 26              # 行高
        assert ws["A1"].fill.fgColor.rgb.endswith("FFC7CE")   # 底色
        assert ws["A1"].font.bold is True                     # 字体
        assert ws["A1"].font.sz == 12
        assert "A4:B4" in {str(r) for r in wb["活动名单"].merged_cells.ranges}  # 合并单元格
        wb.close()

    def test_all_clean_creates_no_file(self, work_dir):
        src = os.path.join(work_dir, "干净表.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "流水"
        ws.append(["订单号", "金额"])
        ws.append(["202401011234567890", 10])
        wb.save(src)

        out = os.path.join(work_dir, "干净表_已脱敏.xlsx")
        report = run_desensitize(src, out, scan_workbook(src))
        assert report["ok"] is False
        assert not os.path.exists(out)


# ----------------------------------------------------------------------------
# 接口
# ----------------------------------------------------------------------------
class TestApi:
    def test_scan_endpoint(self, client, work_dir):
        src = build_sample(os.path.join(work_dir, "源表.xlsx"))
        with open(src, "rb") as f:
            data = {"file": (io.BytesIO(f.read()), "源表.xlsx")}
        resp = client.post("/api/desensitize/scan", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        j = resp.get_json()
        assert j["ok"] is True
        assert j["total_sheets"] == 3
        assert j["hit_sheets"] == 2
        assert j["file_id"]

    def test_run_endpoint(self, client, work_dir):
        src = build_sample(os.path.join(work_dir, "源表.xlsx"))
        with open(src, "rb") as f:
            data = {"file": (io.BytesIO(f.read()), "源表.xlsx")}
        file_id = client.post(
            "/api/desensitize/scan", data=data, content_type="multipart/form-data"
        ).get_json()["file_id"]

        out_dir = os.path.join(work_dir, "out")
        os.makedirs(out_dir, exist_ok=True)
        resp = client.post(
            "/api/desensitize/run",
            json={"file_id": file_id, "filename": "源表.xlsx", "output_dir": out_dir},
        )
        j = resp.get_json()
        assert j["ok"] is True
        assert j["out_sheets"] == 2
        assert os.path.exists(j["out_path"])

    def test_xls_rejected(self, client):
        resp = client.post(
            "/api/desensitize/scan",
            data={"file": (io.BytesIO(b"x"), "old.xls")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "xlsx" in resp.get_json()["msg"]

    def test_missing_dir_rejected(self, client):
        resp = client.post(
            "/api/desensitize/run",
            json={"file_id": "0" * 32 + ".xlsx", "output_dir": ""},
        )
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False
