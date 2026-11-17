# -*- coding: utf-8 -*-
"""敏感片段识别 + 文内脱敏替换。

业务背景
--------
「全表脱敏」需要在一张 Excel 的多个子表里自动找出敏感信息，不需要用户逐列勾选。
用户明确要求：**不要只靠列名判断**——像「买家姓名」「买家昵称」这种字段，
里面可能整列都是手机号，也可能某一格混着手机号，都要扫出来打码。

三层判断（从强到弱）
1. 列名命中关键词（强信号）：列名里有「手机/电话/身份证/银行卡/邮箱/地址」等词，
   这一整列直接按该类型处理，哪怕内容是空的、脏的。
2. 逐格片段扫描（兜底，解决"字段不智能"）：不管列名是什么，只要单元格内容里
   出现手机号 / 身份证 / 银行卡 / 邮箱，就把那一格纳入处理。
3. 姓名不再特殊对待：普通姓名（"张三"）不会被任何规则命中，自然保留；
   姓名列里冒出手机号，就只把号码打星。

地址是例外：只按列名启用。整段替换会误伤"适用于浙江省的产品"这类描述文字，
所以地址不做全字段片段扫描。

关键防误伤
----------
- 每格只取一个类型，优先级 idcard > bankcard > phone > email，
  避免 18 位身份证被当成银行卡再打一遍。
- 身份证必须通过 GB 11643 校验位，银行卡必须通过 Luhn，订单号不会被误打；
  列名命中的列走 strict=False（列名本身可信，假号、测试数据照样打码）。

性能
----
- 采样只读前 300 行、每列前 60 个非空值。
- 每个值先做廉价预筛（没有数字也没有 @ 直接跳过，不跑正则）；
  有数字才依次试 idcard/bankcard/phone，短列表因此只付一次字符串遍历。
- 执行阶段只遍历"命中的列"，每列一趟、多类型串行，不扫全表。
"""
import re

from services.masking import (
    mask_address,
    mask_bankcard,
    mask_email,
    mask_idcard,
    mask_phone,
)

# 采样上限：每列只看前 60 个非空值。
MAX_SAMPLE = 60

# 同一格命中多个类型时的处理优先级（越靠前越具体）
KIND_ORDER = ("idcard", "bankcard", "phone", "email", "address")

# 手机号：11 位，1 开头、第二位 3-9，前后不能紧贴数字。
PHONE_BARE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 11-13 位连续数字串：12/13 位常见于"序号 + 手机号"粘在一格里（昵称、备注），
# 长串（>=14 位）交给身份证 / 银行卡逻辑，避免把订单号、卡号打坏。
_DIGIT_RUN_RE = re.compile(r"\d{11,13}")
# 身份证：17 位数字 + 数字/X 校验位。
IDCARD_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
# 银行卡：16-19 位连续数字。
BANKCARD_RE = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
# 邮箱
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 地址行政区划词（只在列名命中地址时整段处理）
ADDR_RE = re.compile(r"[省市区县旗镇街道路号]")
# 整格只由号码 + 常见分隔符组成（用于判断"要不要整段替换"）
_PHONE_ONLY_RE = re.compile(r"^[+\d\-()（） ]+$")

# 列名关键词（按优先级排序）。「身份证号」不能被「号码」抢成手机号，
# 「银行卡号」不能被「卡号」抢成地址，所以 idcard 放在最前。
COLUMN_HINTS = [
    ("idcard", ("身份证", "证件号", "证件号码", "idcard", "id_no", "idno")),
    ("bankcard", ("银行卡", "银行帐号", "银行账号", "卡号", "开户行", "bank", "card")),
    ("phone", ("手机", "电话", "联系方式", "联系电话", "tel", "mobile", "phone", "号码")),
    ("email", ("邮箱", "电子邮件", "email", "mail", "邮件")),
    ("address", ("地址", "住址", "收货", "详细地址", "所在地", "居住地")),
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


def phone_span(s):
    """在文本里找一个手机号，返回 (start, end)；没有返回 None。

    除了标准 "13812345678"，也覆盖 "昵称0 13800000000" 被拼成一串 12 位数字的情况
    （取尾部 11 位）。14 位以上的长数字串不参与，留给身份证 / 银行卡判定。
    """
    for m in _DIGIT_RUN_RE.finditer(s):
        d = m.group(0)
        if len(d) == 11:
            if re.fullmatch(r"1[3-9]\d{9}", d):
                return m.span()
        else:
            tail = d[-11:]
            if re.fullmatch(r"1[3-9]\d{9}", tail):
                return (m.start() + len(d) - 11, m.end())
    return None


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


def cell_kinds(text):
    """扫单个单元格，返回命中的类型（最多一个，按 KIND_ORDER 取最具体的）。

    纯文本（"张三"、"已付款"）会走最前面两次判断就返回，不跑正则。
    """
    s = str(text or "").strip()
    if len(s) < 6:
        return []

    has_digit = False
    for ch in s:
        if "0" <= ch <= "9":
            has_digit = True
            break
    has_at = "@" in s
    if not has_digit and not has_at:
        return []

    if has_digit:
        for m in IDCARD_RE.finditer(s):
            if idcard_ok(m.group(1)):
                return ["idcard"]
        for m in BANKCARD_RE.finditer(s):
            if luhn_ok(m.group(1)):
                return ["bankcard"]
        if phone_span(s) is not None:
            return ["phone"]

    if has_at and EMAIL_RE.search(s):
        return ["email"]

    return []


def kind_by_value(text):
    """单格判断，返回类型或 None（cell_kinds 的便捷包装，保留旧调用方式）。"""
    ks = cell_kinds(text)
    return ks[0] if ks else None


def detect_column(col_name, values):
    """判断一列里有哪些敏感类型，以及每个类型的来源。

    返回 dict 或 None：
    - {
        "col": 列名,
        "kinds": [{"kind": "phone", "by": "name|content"}, ...],
        "by": "name|content|mixed",
        "ratio": 内容命中率（有片段的样本占比）,
        "sample_in": 原始样例,
        "sample_out": 依次应用所有类型后的样例,
      }
    普通姓名列（"张三"）不会被任何规则命中，返回 None。
    """
    kinds = {}  # kind -> "name" | "content"

    by_name = kind_by_name(col_name)
    if by_name:
        kinds[by_name] = "name"

    pairs = [(str(v).strip(), v) for v in values if str(v).strip() != ""][:MAX_SAMPLE]
    hit = 0
    for t, _ in pairs:
        ks = cell_kinds(t)
        if ks:
            hit += 1
            for k in ks:
                kinds.setdefault(k, "content")

    if not kinds:
        return None

    ratio = round(hit / len(pairs), 3) if pairs else 0.0
    ordered = sorted(kinds, key=KIND_ORDER.index)
    by_set = {v for v in kinds.values()}
    by = "name" if by_set == {"name"} else ("content" if by_set == {"content"} else "mixed")

    sample_in = pairs[0][0] if pairs else ""
    sample_out = sample_in
    for k in ordered:
        sample_out = mask_text(k, sample_out, strict=(kinds[k] == "content"))

    return {
        "col": str(col_name),
        "kinds": [{"kind": k, "by": kinds[k]} for k in ordered],
        "by": by,
        "ratio": ratio,
        "sample_in": sample_in[:40],
        "sample_out": sample_out[:40],
    }


def detect_sheet(headers, rows):
    """扫一张子表，返回所有含敏感信息的列。

    headers: 表头文本列表
    rows:    数据行（list of list），只用于抽样判断
    """
    out = []
    for idx, h in enumerate(headers):
        values = []
        for r in rows:
            if idx < len(r):
                values.append(r[idx])
        info = detect_column(h, values)
        if not info:
            continue
        info["index"] = idx
        out.append(info)
    return out


def mask_text(kind, text, strict=True):
    """对单个单元格按类型脱敏，只动敏感片段，同格其他文字保留。

    "张三13812345678" -> "张三138****5678"

    strict=True 时（内容扫描出来的）要求身份证校验位、银行卡 Luhn 通过才打码，
    防止订单号误伤；strict=False 时（列名命中的列）不做校验，列名本身已足够可信。
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
            if len(d) == 11 and re.fullmatch(r"1[3-9]\d{9}", d):
                return mask_phone(d)
            if len(d) == 13 and d.startswith("86"):
                return mask_phone(d[2:])
        # 逐段替换：一格可能有多个号码，号码前也可能贴着序号（"昵称01380000000"）
        for _ in range(3):
            span = phone_span(s)
            if not span:
                break
            s = s[:span[0]] + mask_phone(s[span[0]:span[1]]) + s[span[1]:]
        return s

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
            "index": d.get("index"),
            "col": d["col"],
            "kinds": d["kinds"],
            "by": d["by"],
            "ratio": d["ratio"],
            "sample_in": d["sample_in"],
            "sample_out": d["sample_out"],
        }
        for d in detections
    ]
