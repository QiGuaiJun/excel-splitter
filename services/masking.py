# -*- coding: utf-8 -*-
"""脱敏引擎。

来源背景：原本定义在 api/distribute.py（约 90 行）。本批把脱敏逻辑搬到
services 层，让分发路由层只做路由 + IO，业务规则可独立测试。

URL：
- phone      手机号：前 3 后 4（如 138****5678）
- idcard     身份证：前 4 后 4（如 3307**********1234）
- address    地址：保留到区/县级市
- name       姓名：保留姓，其余 *
- keep_ab    自定义前后各 a/b 位
- replace    整列统一替换
"""
import re

import pandas as pd


def _digits(s: str) -> str:
    return re.sub(r"\D", "", str(s))


def mask_phone(v):
    """手机号：保留前3后4，其余位用 *（标准11位 => 138****5678）"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    d = _digits(s)
    if len(d) >= 7:
        return d[:3] + "*" * (len(d) - 7) + d[-4:]
    return "*" * len(s)


def mask_idcard(v):
    """身份证：保留前4后4，其余用 *（18位 => 3307**********1234）"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    if len(s) >= 8:
        return s[:4] + "*" * (len(s) - 8) + s[-4:]
    return "*" * len(s)


def mask_name(v):
    """姓名：保留姓（第一个字符），其余用 *"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    if len(s) == 1:
        return s
    return s[0] + "*" * (len(s) - 1)


def mask_address(v):
    """详细地址：保留到区/县(县级市)，其后统一打 ****"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    # 先定位省级
    prov = re.search(r"^.*?(省|自治区|特别行政区|市)", s)
    start = prov.end() if prov else 0
    rest = s[start:]
    head = None
    m = re.search(r"^.*?[区县旗]", rest)
    if m:
        head = s[: start + len(m.group(0))]
    else:
        # 没有区/县：按"市"判断取到县级市
        city_idx = [i for i, c in enumerate(rest) if c == "市"]
        if len(city_idx) >= 2:
            head = s[: start + city_idx[1] + 1]
        elif len(city_idx) == 1:
            head = s[: start + city_idx[0] + 1]
    if not head:
        head = s[: min(6, len(s))]
    if len(head) >= len(s):
        return s
    return head + "****"


def mask_keep_ab(v, a=0, b=0):
    """通用：保留前 a 位、后 b 位，其余用 *"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    a, b = int(a or 0), int(b or 0)
    if len(s) <= a + b:
        return "*" * len(s)
    return s[:a] + "*" * (len(s) - a - b) + (s[-b:] if b else "")


def mask_replace(v, text="***"):
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    return text or "***"


# 规则注册表（type -> ("显示名称", 函数)）
RULES = {
    "phone":   ("手机号(前3后4)", mask_phone),
    "idcard":  ("身份证(前4后4)", mask_idcard),
    "address": ("详细地址(保留到区县)", mask_address),
    "name":    ("姓名(留姓)", mask_name),
}


def apply_mask(series: pd.Series, rule: dict) -> pd.Series:
    """对 Series 应用脱敏规则。

    rule 支持 type:
    - phone / idcard / address / name: 用 RULES 注册的函数
    - keep_ab: 自定义前后保留 a/b 位
    - replace: 整列替换为 text (默认 "***")
    - 其它 / type 为空: 走 mask_replace 兜底
    """
    t = rule.get("type")
    if t == "keep_ab":
        return series.map(lambda x: mask_keep_ab(x, rule.get("a", 0), rule.get("b", 0)))
    if t == "replace":
        return series.map(lambda x: mask_replace(x, rule.get("text", "***")))
    fn = RULES.get(t, (None, mask_replace))[1]
    return series.map(fn)
