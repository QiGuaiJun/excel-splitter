// -*- coding: utf-8 -*-
/* 全表脱敏 · 前端逻辑
   进入模块时由 goModule() 惰性调用 DES_init()（见 sources.js 的 MODULES）。 */
(function () {
  "use strict";

  const DES = {
    file_id: "",
    filename: "",
    sheets: [],
    hit: 0,
    total: 0,
    outdir: "",
    busy: false,
    bound: false,
  };

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]
  ));

  const KIND_LABEL = {
    phone: "手机号", idcard: "身份证", bankcard: "银行卡",
    email: "邮箱", address: "详细地址", name: "姓名",
  };
  const kindLabel = k => KIND_LABEL[k] || k;

  function toast(msg, type) {
    const t = document.createElement("div");
    t.className = "toast " + (type || "");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, 2200);
    setTimeout(() => t.remove(), 2600);
  }

  /* ---------- 初始化（幂等） ---------- */
  window.DES_init = function () {
    if (DES.bound) return;
    const drop = $("desDrop"), inp = $("desFile");
    if (!drop || !inp) return;

    drop.onclick = () => inp.click();
    // 阻止 input 的 click 冒泡回 drop，否则会递归触发两次选择框
    inp.addEventListener("click", e => e.stopPropagation());
    inp.onchange = () => { if (inp.files && inp.files[0]) scan(inp.files[0]); };

    drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = e => {
      e.preventDefault();
      drop.classList.remove("over");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) scan(e.dataTransfer.files[0]);
    };

    DES.bound = true;
  };

  window.DES_pickFile = function () {
    DES_init();
    const inp = $("desFile");
    if (inp) inp.click();
  };

  /* ---------- 扫描 ---------- */
  async function scan(file) {
    const main = $("desDropMain");
    if (main) main.innerHTML = '<span class="spinner" style="border-color:#bfe6e1;border-top-color:#0f9d8f"></span> 正在扫描所有子表…';
    $("desResult").innerHTML = "";

    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/desensitize/scan", { method: "POST", body: fd });
      const j = await r.json();
      if (!j.ok) throw new Error(j.msg || "扫描失败");

      DES.file_id = j.file_id;
      DES.filename = j.filename;
      DES.sheets = j.sheets || [];
      DES.hit = j.hit_sheets || 0;
      DES.total = j.total_sheets || 0;

      if (main) main.textContent = "点击重新选择，或拖拽替换文件";
      $("desScanWrap").style.display = "block";
      renderScan();
    } catch (e) {
      if (main) main.textContent = e.message + "（点击重试）";
      $("desScanWrap").style.display = "none";
    }
  }

  function renderScan() {
    const sheets = DES.sheets || [];
    const hitSheets = sheets.filter(s => (s.hits || []).length);
    const skipSheets = sheets.filter(s => !(s.hits || []).length);
    const colCount = hitSheets.reduce((a, s) => a + s.hits.length, 0);

    $("desFileBar").innerHTML =
      '<div class="ic">📘</div>' +
      '<div><div class="fn">' + esc(DES.filename) + '</div>' +
      '<div class="fs">' + DES.total + ' 个子表 · 扫描完成</div></div>' +
      '<span class="spacer"></span>' +
      '<button class="linkbtn" onclick="DES_pickFile()">重新选择</button>';

    $("desStats").innerHTML =
      '<div class="des-stat"><div class="n">' + DES.total + '</div><div class="l">子表总数</div></div>' +
      '<div class="des-stat hit"><div class="n">' + hitSheets.length + '</div><div class="l">含敏感信息</div></div>' +
      '<div class="des-stat skip"><div class="n">' + skipSheets.length + '</div><div class="l">无敏感信息（不输出）</div></div>' +
      '<div class="des-stat mask"><div class="n">' + colCount + '</div><div class="l">待脱敏列</div></div>';

    // 明细卡片不再展示（页面保持简约）；统计卡已给出子表数与待脱敏列数
    const list = $("desSheetList");
    if (list) list.innerHTML = "";

    const outdirInput = $("desOutdir");
    if (outdirInput && DES.outdir) outdirInput.value = DES.outdir;
    $("desRunBtn").disabled = hitSheets.length === 0;
  }

  /* ---------- 选输出文件夹（复用分发模块的系统对话框接口） ---------- */
  window.DES_chooseDir = async function () {
    try {
      const r = await fetch("/api/browse_folder", { method: "POST" });
      const j = await r.json();
      if (j.ok && j.path) {
        DES.outdir = j.path;
        $("desOutdir").value = j.path;
      } else if (j.msg) {
        toast(j.msg, "err");
      }
    } catch (e) {
      toast("无法打开选择窗口，请直接粘贴文件夹路径", "err");
    }
  };

  /* ---------- 执行 ---------- */
  window.DES_run = async function () {
    if (DES.busy) return;
    if (!DES.file_id) { toast("请先选择要脱敏的 Excel", "err"); return; }
    const out = ($("desOutdir").value || "").trim();
    if (!out) { toast("请先选择输出文件夹", "err"); return; }

    const btn = $("desRunBtn");
    DES.busy = true;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> 正在脱敏…';
    $("desResult").innerHTML = "";

    try {
      const r = await fetch("/api/desensitize/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_id: DES.file_id,
          filename: DES.filename,
          output_dir: out,
        }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.msg || "脱敏失败");
      renderResult(j);
      toast("脱敏完成：" + j.filename, "ok");
    } catch (e) {
      $("desResult").innerHTML = '<div class="alert err">' + esc(e.message) + '</div>';
    } finally {
      DES.busy = false;
      btn.disabled = false;
      btn.textContent = "开始脱敏";
    }
  };

  function renderResult(j) {
    const skipped = j.skipped || [];
    const skipHtml = skipped.length
      ? '<div class="des-out-sheets">' +
        '<div class="des-sheet-head" style="margin:14px 0 6px"><span class="des-dir-label">已跳过 ' +
        skipped.length + ' 个子表</span></div>' +
        skipped.map(s =>
          '<div class="des-sheet skip"><div class="des-sheet-head">' +
          '<span class="name">' + esc(s.name) + '</span>' +
          '<span class="rows">' + (s.rows || 0) + ' 行</span>' +
          '<span class="spacer"></span><span class="des-tag gray">无敏感信息 · 未输出</span>' +
          '</div></div>'
        ).join("") +
        '</div>'
      : "";

    $("desResult").innerHTML =
      '<div class="des-hero">' +
      '<div class="hic">✅</div>' +
      '<h3>脱敏完成</h3>' +
      '<p>' + esc(j.filename) + '</p>' +
      '<div class="path">' + esc(j.out_path) + '</div>' +
      '</div>' +
      '<div class="des-out-stats">' +
      '<div class="des-stat hit"><div class="n">' + j.out_sheets + '</div><div class="l">输出子表</div></div>' +
      '<div class="des-stat mask"><div class="n">' + j.total_masked + '</div><div class="l">脱敏单元格</div></div>' +
      '<div class="des-stat skip"><div class="n">' + skipped.length + '</div><div class="l">跳过子表</div></div>' +
      '</div>' +
      '<div class="des-out-sheets">' +
      (j.sheets || []).map(s =>
        '<div class="des-sheet">' +
        '<div class="des-sheet-head">' +
        '<span class="name">' + esc(s.name) + '</span>' +
        '<span class="rows">' + s.rows + ' 行 · ' + s.masked + ' 格已脱敏</span>' +
        '</div>' +
        '<div class="des-cols">' + (s.cols || []).map(c =>
          '<div class="des-col"><span class="cname">' + esc(c.col) + '</span>' +
          (c.kinds || []).map(k => '<span class="kind">' + kindLabel(k) + '</span>').join(" ") +
          '<div class="sample">' + c.count + ' 格</div></div>'
        ).join("") + '</div>' +
        '</div>'
      ).join("") +
      '</div>' + skipHtml;
  }
})();
