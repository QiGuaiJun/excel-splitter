# -*- coding: utf-8 -*-
"""脱敏函数单元测试。

覆盖：
- 手机号 / 身份证 / 地址 / 姓名 / 通用前后保留 / 整体替换 / 正则识别 七种规则
- apply_mask 对 Series 的封装
- 边界：None、空串、NaN、过短号码、含非数字字符
"""
import math

import pandas as pd
import pytest

from app import (
    apply_mask,
    compile_pattern,
    mask_address,
    mask_idcard,
    mask_keep_ab,
    mask_name,
    mask_phone,
    mask_regex,
    mask_replace,
)


# ----------------------------------------------------------------------------
# mask_phone
# ----------------------------------------------------------------------------
class TestMaskPhone:
    def test_standard_11_digits(self):
        assert mask_phone("13812345678") == "138****5678"

    def test_strips_non_digits_then_masks(self):
        # "+86 138 1234 5678" 去非数字后是 13 位，按 13 位规则切片
        # 这是 _digits() 的设计：把国家码区号也算进有效数字
        result = mask_phone("+86 138 1234 5678")
        # 数字部分: 8613812345678 (13 位) -> 前 3 + 6* + 后 4
        assert result == "861" + "*" * 6 + "5678"

    def test_with_dash(self):
        assert mask_phone("138-1234-5678") == "138****5678"

    def test_short_invalid_returns_all_masked(self):
        # 不足 7 位无法稳定切片 -> 整体打星（按字符数）
        assert mask_phone("12345") == "*" * len("12345")

    def test_empty_returns_empty(self):
        assert mask_phone("") == ""

    def test_none_returns_none(self):
        assert mask_phone(None) is None

    def test_nan_string_returns_empty(self):
        assert mask_phone("nan") == ""

    def test_thirteen_digits(self):
        assert mask_phone("1381234567890") == "138" + "*" * 6 + "7890"


# ----------------------------------------------------------------------------
# mask_idcard
# ----------------------------------------------------------------------------
class TestMaskIdcard:
    def test_standard_18(self):
        assert mask_idcard("330782199001011234") == "3307" + "*" * 10 + "1234"

    def test_short_returns_full_mask(self):
        # 不足 8 位 -> 整段打星
        s = "1234567"
        assert mask_idcard(s) == "*" * len(s)

    def test_empty_returns_empty(self):
        assert mask_idcard("") == ""

    def test_none_returns_none(self):
        assert mask_idcard(None) is None

    def test_nan_returns_empty(self):
        assert mask_idcard("nan") == ""


# ----------------------------------------------------------------------------
# mask_name
# ----------------------------------------------------------------------------
class TestMaskName:
    def test_double_char(self):
        assert mask_name("张伟") == "张*"

    def test_single_char_unchanged(self):
        assert mask_name("欧") == "欧"

    def test_long_name(self):
        assert mask_name("欧阳娜娜") == "欧***"

    def test_empty_returns_empty(self):
        assert mask_name("") == ""

    def test_none_returns_none(self):
        assert mask_name(None) is None


# ----------------------------------------------------------------------------
# mask_address
# ----------------------------------------------------------------------------
class TestMaskAddress:
    def test_county_level_city(self):
        assert mask_address("浙江省金华市义乌市稠城街道城中北路123号") == "浙江省金华市义乌市****"

    def test_main_city_district(self):
        assert mask_address("浙江省杭州市西湖区文三路100号") == "浙江省杭州市西湖区****"

    def test_municipality(self):
        assert mask_address("北京市朝阳区建国路88号") == "北京市朝阳区****"

    def test_autonomous_region(self):
        assert mask_address("广西壮族自治区南宁市兴宁区民生路1号") == "广西壮族自治区南宁市兴宁区****"

    def test_no_district_short_circuit(self):
        # 没有"区县旗"：省 + 一个"市"（普通地级市），保留到地级市
        s = "江苏省南京市新街口路1号"
        assert mask_address(s) == "江苏省南京市****"

    def test_empty_returns_empty(self):
        assert mask_address("") == ""

    def test_short_address_truncated_to_six(self):
        # 没有省市区县 -> 兜底保留前 6 字
        assert mask_address("新街口路1号") == "新街口路1号"

    def test_none_returns_none(self):
        assert mask_address(None) is None


# ----------------------------------------------------------------------------
# mask_keep_ab / mask_replace
# ----------------------------------------------------------------------------
class TestKeepAbReplace:
    def test_keep_3_4(self):
        assert mask_keep_ab("13812345678", 3, 4) == "138****5678"

    def test_keep_only_front(self):
        assert mask_keep_ab("abcdef", 2, 0) == "ab****"

    def test_keep_only_back(self):
        assert mask_keep_ab("abcdef", 0, 2) == "****ef"

    def test_keep_too_much_returns_all_masked(self):
        # 3+4=7 已超过 6 长 -> 整段打星
        assert mask_keep_ab("abcdef", 3, 4) == "*" * 6

    def test_string_args_coerced(self):
        # 传入字符串数字也应该工作
        assert mask_keep_ab("abcdef", "3", "4") == "*" * 6

    def test_replace(self):
        assert mask_replace("张三") == "***"
        assert mask_replace("张三", "保密") == "保密"

    def test_replace_empty(self):
        assert mask_replace("") == ""
        assert mask_replace(None) is None


# ----------------------------------------------------------------------------
# mask_regex / compile_pattern
# ----------------------------------------------------------------------------
class TestMaskRegex:
    """核心场景：一格里"客户姓名 + 手机号"混排，只动号码，姓名原样保留。"""

    def test_name_and_phone_keep_name(self):
        assert mask_regex("张三 13812345678") == "张三 138****5678"

    def test_no_separator(self):
        assert mask_regex("张三13812345678") == "张三138****5678"

    def test_name_after_phone(self):
        assert mask_regex("13812345678（张三）") == "138****5678（张三）"

    def test_multiple_phones_in_one_cell(self):
        assert mask_regex("张三 13812345678 / 李四 13998765432") == "张三 138****5678 / 李四 139****5432"

    def test_text_without_phone_untouched(self):
        assert mask_regex("张三 已加微信") == "张三 已加微信"

    def test_chinese_name_with_punct_and_spaces(self):
        assert mask_regex("客户：欧阳娜娜，联系方式 138-1234-5678") == "客户：欧阳娜娜，联系方式 138-1234-5678"

    def test_idcard_not_mistaken_as_phone(self):
        # 默认式带前后数字边界，18 位身份证里不会被截出"手机号"
        assert mask_regex("330782199001011234") == "330782199001011234"

    def test_idcard_beside_phone(self):
        assert mask_regex("张三 330782199001011234 13812345678") == "张三 330782199001011234 138****5678"

    def test_custom_pattern(self):
        assert mask_regex("订单 A123456789 已完成", pattern=r"A\d{9}", a=1, b=3) == "订单 A******789 已完成"

    def test_zero_keep_masks_whole_fragment(self):
        assert mask_regex("13812345678", a=0, b=0) == "*" * 11

    def test_invalid_pattern_keeps_original(self):
        assert mask_regex("张三 13812345678", pattern="1[3-9") == "张三 13812345678"

    def test_compile_pattern_returns_none_for_invalid(self):
        assert compile_pattern("1[3-9") is None
        assert compile_pattern("") is not None  # 空串走内置手机号式

    def test_none_nan_empty(self):
        assert mask_regex(None) is None
        assert mask_regex(float("nan")) == ""
        assert mask_regex("") == ""
        assert mask_regex("   ") == ""


# ----------------------------------------------------------------------------
# apply_mask + RULES 注册表
# ----------------------------------------------------------------------------
class TestApplyMask:
    def test_phone_rule(self):
        s = pd.Series(["13812345678", "13911112222"])
        out = apply_mask(s, {"type": "phone"})
        assert out.tolist() == ["138****5678", "139****2222"]

    def test_idcard_rule(self):
        s = pd.Series(["330782199001011234"])
        out = apply_mask(s, {"type": "idcard"})
        assert out.tolist() == ["3307" + "*" * 10 + "1234"]

    def test_keep_ab_rule(self):
        s = pd.Series(["abcdef", "ghijkl"])
        out = apply_mask(s, {"type": "keep_ab", "a": 2, "b": 2})
        assert out.tolist() == ["ab**ef", "gh**kl"]

    def test_replace_rule(self):
        s = pd.Series(["张三", "李四"])
        out = apply_mask(s, {"type": "replace", "text": "[已脱敏]"})
        assert out.tolist() == ["[已脱敏]", "[已脱敏]"]

    def test_unknown_type_falls_back_to_replace(self):
        s = pd.Series(["hello"])
        out = apply_mask(s, {"type": "totally_made_up_rule"})
        assert out.tolist() == ["***"]

    def test_no_op_passthrough_for_none(self):
        s = pd.Series(["abc"])
        out = apply_mask(s, {"type": None})  # 无规则 -> 走 default replace
        assert out.tolist() == ["***"]

    def test_regex_rule_default_phone(self):
        s = pd.Series(["张三 13812345678", "李四 已加微信"])
        out = apply_mask(s, {"type": "regex"})
        assert out.tolist() == ["张三 138****5678", "李四 已加微信"]

    def test_regex_rule_explicit_pattern(self):
        s = pd.Series(["张三 13812345678", "李四 13998765432"])
        out = apply_mask(s, {"type": "regex", "pattern": r"(?<!\d)1[3-9]\d{9}(?!\d)", "a": 3, "b": 4})
        assert out.tolist() == ["张三 138****5678", "李四 139****5432"]

    def test_regex_rule_invalid_pattern_is_passthrough(self):
        s = pd.Series(["张三 13812345678"])
        out = apply_mask(s, {"type": "regex", "pattern": "1[3-9"})
        assert out.tolist() == ["张三 13812345678"]
