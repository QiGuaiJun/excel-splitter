# -*- coding: utf-8 -*-
"""脱敏引擎。

来源背景：原本定义在 api/distribute.py（约 90 行）。本批把脱敏逻辑搬到
services 层，让分发路由层只做路由 + IO，业务规则可独立测试。

URL：
- phone      手机号：前 3 后 4（如 138****5678）
- idcard     身份证：前 4 后 4（如 3307**********1234）
- address    地址：保留到区/县级市
- name       姓名：保留姓，其余 *
- bankcard   银行卡：保留后 4 位（************1234）
- email      邮箱：保留前 2 位（ab***@qq.com）
- keep_ab    自定义前后各 a/b 位
- replace    整列统一替换
- regex      按正则找出文内片段再部分打星（如"张三13812345678"只动号码，姓名保留）
"""
import re

import pandas as pd

# 「正则表达式」规则的默认匹配式：中国大陆 11 位手机号。
# 用 lookaround 卡住前后边界，避免从 18 位身份证等长数字串里截出"手机号"
# （如 330782199001011234 中间一段会被裸正则误命中）。
DEFAULT_TEXT_PATTERN = r"(?<!\d)1[3-9]\d{9}(?!\d)"


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


def mask_bankcard(v):
    """银行卡号：保留后 4 位，其余用 *（16 位 => ************1234）

    只处理数字部分；空格、连字符等分隔符会被丢掉，保证打码后的位数可核对。
    位数不足 4 位时全部打星，不暴露任何数字。
    """
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    d = _digits(s)
    if len(d) <= 4:
        return "*" * len(d)
    return "*" * (len(d) - 4) + d[-4:]


def mask_email(v):
    """邮箱：保留前 2 位，中间固定 ***，域名原样（ab***@qq.com）

    不含 @ 的文本不当邮箱处理，原样返回（避免把普通说明文字整段替换）。
    """
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    if "@" not in s:
        return s
    local, at, domain = s.partition("@")
    keep = local[:2]
    return keep + "***" + at + domain


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


def compile_pattern(pattern):
    """编译用户填的正则；为空则用内置手机号匹配式。非法返回 None。"""
    try:
        return re.compile(pattern or DEFAULT_TEXT_PATTERN)
    except re.error:
        return None


def _mask_fragment(text, a, b):
    """对正则命中的片段保留前 a 后 b 个字符，中间打星。"""
    n = len(text)
    if n <= a + b:
        return "*" * n
    return text[:a] + "*" * (n - a - b) + (text[-b:] if b else "")


def _regex_apply(v, rx, a, b):
    if v is None:
        return v
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v)
    if s.strip() == "":
        return ""
    return rx.sub(lambda m: _mask_fragment(m.group(0), a, b), s)


def mask_regex(v, pattern=None, a=3, b=4):
    """在文本中按正则定位片段并部分打星，未命中的文字（如客户姓名）原样保留。

    mask_regex("张三 13812345678") -> "张三 138****5678"
    """
    rx = compile_pattern(pattern)
    if rx is None:
        # 非法正则不阻断整列，原样返回（API 层会提前校验并给出明确报错）
        return v if v is None else str(v)
    a = 3 if a is None else int(a)
    b = 4 if b is None else int(b)
    return _regex_apply(v, rx, a, b)


# 规则注册表（type -> ("显示名称", 函数)）
RULES = {
    "phone":    ("手机号(前3后4)", mask_phone),
    "idcard":   ("身份证(前4后4)", mask_idcard),
    "address":  ("详细地址(保留到区县)", mask_address),
    "name":     ("姓名(留姓)", mask_name),
    "bankcard": ("银行卡号(保留后4位)", mask_bankcard),
    "email":    ("邮箱(保留前2位)", mask_email),
}


def apply_mask(series: pd.Series, rule: dict) -> pd.Series:
    """对 Series 应用脱敏规则。

    rule 支持 type:
    - phone / idcard / address / name: 用 RULES 注册的函数
    - keep_ab: 自定义前后保留 a/b 位
    - replace: 整列替换为 text (默认 "***")
    - regex:   按 pattern 在文本内定位片段，保留前 a 后 b 位（默认手机号 + 3/4）
    - 其它 / type 为空: 走 mask_replace 兜底
    """
    t = rule.get("type")
    if t == "keep_ab":
        return series.map(lambda x: mask_keep_ab(x, rule.get("a", 0), rule.get("b", 0)))
    if t == "replace":
        return series.map(lambda x: mask_replace(x, rule.get("text", "***")))
    if t == "regex":
        rx = compile_pattern(rule.get("pattern"))
        if rx is None:
            return series
        a = 3 if rule.get("a") is None else int(rule.get("a"))
        b = 4 if rule.get("b") is None else int(rule.get("b"))
        return series.map(lambda x: _regex_apply(x, rx, a, b))
    fn = RULES.get(t, (None, mask_replace))[1]
    return series.map(fn)
