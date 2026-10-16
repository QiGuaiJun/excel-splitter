# -*- coding: utf-8 -*-
"""汇总构建器。

来源背景：原本在 api/distribute.py（build_summary，约 50 行）。
本批把业务规则搬到 services 层，分发路由只做调用。
"""
import pandas as pd


def _to_num(s: pd.Series) -> pd.Series:
    """把 '￥1,200.50元' 之类的文本安全转成数值，转不了的变 NaN。"""
    cleaned = (
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("，", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.replace("元", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def build_summary(sub: pd.DataFrame, scfg: dict):
    """聚合：计数(行数/去重)+求和，末行合计；支持分组列别名；无分组时整表一行总计。

    scfg 结构：
    {
      "groups":  [{"col": "健康顾问", "label": "顾问姓名"}],
      "sums":    [{"col": "金额", "label": "金额合计"}],
      "counts":  [{"col": "订单号", "label": "订单数", "distinct": true}],
      "sort_label": "金额合计",
      "sort_desc":  true,
    }
    """
    groups = scfg.get("groups") or []
    graw = [g for g in groups if g.get("col") in sub.columns]
    gcols = [g["col"] for g in graw]
    galias = {}
    for g in graw:
        al = str(g.get("label") or "").strip()
        galias[g["col"]] = al if al else g["col"]
    sums = [s for s in (scfg.get("sums") or []) if s.get("col") in sub.columns]
    counts = [c for c in (scfg.get("counts") or []) if c.get("col") in sub.columns]

    work = sub.copy()
    agg, label_order = {}, []
    for c in counts:
        lab = c.get("label") or (c["col"] + ("数" if c.get("distinct") else "行数"))
        agg[lab] = (c["col"], "nunique" if c.get("distinct") else "count")
        label_order.append(("count", lab))
    for idx, s in enumerate(sums):
        lab = s.get("label") or (s["col"] + "合计")
        key = f"__num_{idx}"
        work[key] = _to_num(work[s["col"]])
        agg[lab] = (key, "sum")
        label_order.append(("sum", lab))
    if not agg:
        return None

    metric_cols = [lab for _, lab in label_order]

    def _whole_row(frame):
        row = {}
        for kind, lab in label_order:
            col, how = agg[lab]
            if how == "sum":
                row[lab] = round(float(pd.to_numeric(frame[col], errors="coerce").sum()), 2)
            elif how == "nunique":
                row[lab] = int(frame[col].nunique())
            else:
                row[lab] = int(frame[col].count())
        return row

    if not gcols:
        # 无分组维度：整张表只输出一行总计
        return pd.DataFrame([_whole_row(work)])[metric_cols]

    res = work.groupby(gcols, dropna=False, sort=False).agg(**agg).reset_index()
    for kind, lab in label_order:
        if kind == "sum":
            res[lab] = pd.to_numeric(res[lab], errors="coerce").fillna(0).round(2)
        else:
            res[lab] = pd.to_numeric(res[lab], errors="coerce").fillna(0).astype(int)

    sort_label = scfg.get("sort_label") or ""
    sort_desc = bool(scfg.get("sort_desc", True))
    alias2col = {a: c for c, a in galias.items()}
    if sort_label in metric_cols:
        sort_key = sort_label
    elif sort_label in galias.values():
        sort_key = alias2col[sort_label]
    else:
        sort_key = None
    if sort_key is not None:
        res = res.sort_values(
            by=sort_key, ascending=not sort_desc, kind="mergesort"
        ).reset_index(drop=True)

    total = _whole_row(work)
    for _gi, g in enumerate(gcols):
        total[g] = "合计" if _gi == 0 else ""
    res = pd.concat([res, pd.DataFrame([total])], ignore_index=True)
    res = res[gcols + metric_cols].rename(columns=galias)
    return res
