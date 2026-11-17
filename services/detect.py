# -*- coding: utf-8 -*-
"""敏感列自动识别 + 文内脱敏片段替换。

业务背景
--------
「全表脱敏」需要在一张 Excel 的多个子表里自动找出敏感列，不需要用户逐列勾选。
判断依据按产品要求走**列名 + 内容双重判断**：

1. 列名命中关键词（强信号）：列名里有「手机/电话/身份证/银行卡/邮箱/地址」等词，
   即便内容是脏的、空的，也按该类型处理（列名是人工写的，可信度最高）。
2. 列名不明显时看内容（兜底）：抽样前 60 个非空单元格，命中率达到 50% 才认定，
   避免「备注」列里偶尔出现一个号码就把整列打星。

姓名有意**不脱敏**：业务上分发出去的名单必须能认出人。列名命中「姓名」时只标记
类型、不产出脱敏动作；「张三13812345678」这类姓名与手机号同格的，由手机号的正则
片段替换天然只打号码，姓名原样保留。

关键防误伤
----------
- 身份证：内容判定时必须通过 GB 11643 校验位，订单号、18 位流水号不会被当身份证。
- 银行卡：内容判定时必须通过 Luhn 校验，16-19 位订单号同理不会被误伤。
- 手机号：lookaround 卡死前后边界，不会从 18 位身份证中间截出「手机号」。
"""
import re

from services.masking import (
    mask_address,
    mask_bankcard,
    mask_email,
    mask_idcard,
    mask_phone,
)

# 抽样上限：只读前 60 个非空值。列有 5 万行也没必要全扫，前 60 个足够定性。
MAX_SAMPLE = 60
# 内容判定阈值：命中率 >= 80% 才认定这一列是敏感列。
# 定得比"半数"严，是因为「备注」这类自由文本列偶尔出现一个号码很正常，
# 整列打星会把备注里的正常文字一起毁掉。
MIN_RATIO = 0.8

# 手机号：11 位，1 开头、第二位 3-9，前后不能紧贴数字。
PHONE_BARE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 身份证：17 位数字 + 数字/X 校验位。
IDCARD_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
# 银行卡：16-19 位连续数字。
BANKCARD_RE = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
# 邮箱
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 中文姓名：2-5 个汉字（允许间隔点，如少数民族姓名）
NAME_RE = re.compile(r"^[\u4e00-\u9fa5·]{2,6}$")
# 地址：出现省/市/区/县/旗/镇/街道任意行政区划词，且长度够
ADDR_RE = re.compile(r"[省市区县旗镇街道路号]")
# 整格只由号码 + 常见分隔符组成（用于判断"要不要整段替换"）
_PHONE_ONLY_RE = re.compile(r"^[+\d\-()（） ]+$")

# 列名关键词（按优先级排序）。命中靠前的先归类：
# 「身份证号」不能被「号码」抢成手机号，「银行卡号」不能被「卡号」抢成地址。
COLUMN_HINTS = [
    ("idcard", ("身份证", "证件号", "证件号码", "idcard", "id_no", "idno")),
    ("bankcard", ("银行卡", "银行帐号", "银行账号", "卡号", "开户行", "bank", "card")),
    ("phone", ("手机", "电话", "联系方式", "联系电话", "tel", "mobile", "phone", "号码")),
    ("email", ("邮箱", "电子邮件", "email", "mail", "邮件")),
    ("address", ("地址", "住址", "收货", "详细地址", "所在地", "居住地")),
    ("name", ("姓名", "客户名", "联系人", "名字", "负责人", "业务员")),
]

# 身份证加权因子与校验码表（GB 11643-1999）
_ID_W = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_C = "10X98765432"


def digits(s) -> str:
    return re.sub(r"\D", "", str(s))


def idcard_ok(s) -> bool:
    """18 位身份证校验位验证。"""
    s = str(s).strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", s):
        return False
    total = sum(int(s[i]) * _ID_W[i] for i in range(17))
    return _ID_C[total % 11] == s[17]


def luhn_ok(s) -> bool:
    """银行卡 Luhn 校验（16-19 位）。"""
    d = digits(s)
    if not (16 <= len(d) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def kind_by_name(col_name: str):
    """按列名判断敏感类型；不是敏感列返回 None。"""
    name = str(col_name or "").strip().lower().replace(" ", "")
    if not name:
        return None
    for kind, words in COLUMN_HINTS:
        for w in words:
            if w in name:
                return kind
    return None


def kind_by_value(text: str):
    """判断单个单元格属于哪种敏感类型；不属于返回 None。

    严格校验（身份证校验位、银行卡 Luhn），只用于「列名不明显时看内容」。
    """
    s = str(text or "").strip()
    if not s:
        return None
    if IDCARD_RE.fullmatch(s) and idcard_ok(s):
        return "idcard"
    if any(idcard_ok(m.group(1)) for m in IDCARD_RE.finditer(s)):
        return "idcard"
    if EMAIL_RE.search(s):
        return "email"
    if any(luhn_ok(m.group(1)) for m in BANKCARD_RE.finditer(s)):
        return "bankcard"
    if PHONE_BARE_RE.search(s):
        return "phone"
    if len(s) >= 8 and ADDR_RE.search(s) and ("省" in s or "市" in s or "区" in s or "县" in s):
        return "address"
    return None


def detect_column(col_name, values):
    """判断一列是否敏感列。

    返回 dict 或 None：
    - {"col": 列名, "kind": "phone|idcard|bankcard|email|address", "by": "name|content",
       "ratio": 内容命中率, "sample_in": 原始样例, "sample_out": 脱敏后样例}
    姓名列返回 {"col":..., "kind": "name", "by": "name", ...}，由调用方跳过不脱敏。
    """
    by_name = kind_by_name(col_name)
    pairs = [(str(v).strip(), v) for v in values if str(v).strip() != ""][:MAX_SAMPLE]
    ratio = 0.0
    by_content = None
    if pairs:
        hits = [kind_by_value(t) for t, _ in pairs]
        hits = [h for h in hits if h]
        ratio = len(hits) / len(pairs)
        if ratio >= MIN_RATIO and hits:
            by_content = max(set(hits), key=hits.count)

    # 列名是强信号：命中即处理。但列名是「姓名」而内容明显是手机号/邮箱时，
    # 按内容类型处理（业务上这类混合列真正敏感的是号码，姓名要留着）。
    if by_name:
        if by_name == "name" and by_content and by_content != "name":
            return _build(col_name, by_content, "content", ratio, pairs)
        return _build(col_name, by_name, "name", ratio, pairs)

    if by_content:
        return _build(col_name, by_content, "content", ratio, pairs)
    return None


def _build(col_name, kind, by, ratio, pairs):
    sample_in = pairs[0][0] if pairs else ""
    sample_out = mask_text(kind, sample_in, strict=(by == "content")) if sample_in else ""
    return {
        "col": str(col_name),
        "kind": kind,
        "by": by,
        "ratio": round(ratio, 3),
        "sample_in": sample_in[:40],
        "sample_out": sample_out[:40],
    }


def detect_sheet(headers, rows):
    """扫一张子表，返回其中所有敏感列。

    headers: 表头文本列表
    rows:    数据行（list of list），只用于抽样判断
    返回:    [detect_column 的返回结果, ...]（不含姓名列）
    """
    out = []
    ncol = len(headers)
    for idx, h in enumerate(headers):
        values = []
        for r in rows:
            if idx < len(r):
                values.append(r[idx])
        info = detect_column(h, values)
        if not info:
            continue
        info["index"] = idx
        if info["kind"] == "name":
            # 姓名不脱敏：只记录、不产出脱敏动作
            continue
        out.append(info)
    return out


def mask_text(kind, text, strict=True):
    """对单个单元格按类型脱敏，只动敏感片段，同格其他文字保留。

    "张三13812345678" -> "张三138****5678"

    strict=True 时（内容判定出来的列）要求身份证校验位、银行卡 Luhn 通过才打码，
    防止订单号误伤；strict=False 时（列名命中的列）不做校验，列名本身已足够可信，
    假号码、测试数据也照样打掉。
    """
    if text is None:
        return text
    s = str(text)
    if s.strip() == "":
        return s

    if kind == "phone":
        # 整格就是号码（允许 +86、空格、横线、括号）时按整体打码；
        # 含汉字/字母（"张三13812345678"）时只替换号码片段，姓名保留。
        d = digits(s)
        if _PHONE_ONLY_RE.fullmatch(s):
            if len(d) == 11 and PHONE_BARE_RE.fullmatch(d):
                return mask_phone(d)
            if len(d) == 13 and d.startswith("86"):
                return mask_phone(d[2:])
        return PHONE_BARE_RE.sub(lambda m: mask_phone(m.group(0)), s)

    if kind == "idcard":
        if not strict:
            return IDCARD_RE.sub(lambda m: mask_idcard(m.group(1)), s)
        return IDCARD_RE.sub(
            lambda m: mask_idcard(m.group(1)) if idcard_ok(m.group(1)) else m.group(0), s
        )

    if kind == "bankcard":
        if not strict:
            return BANKCARD_RE.sub(lambda m: mask_bankcard(m.group(1)), s)
        return BANKCARD_RE.sub(
            lambda m: mask_bankcard(m.group(1)) if luhn_ok(m.group(1)) else m.group(0), s
        )

    if kind == "email":
        return EMAIL_RE.sub(lambda m: mask_email(m.group(0)), s)

    if kind == "address":
        return mask_address(s)

    return s


def summarize(detections):
    """把识别结果转成前端/接口用的精简结构。"""
    return [
        {
            "col": d["col"],
            "kind": d["kind"],
            "by": d["by"],
            "ratio": d["ratio"],
            "sample_in": d["sample_in"],
            "sample_out": d["sample_out"],
        }
        for d in detections
    ]
