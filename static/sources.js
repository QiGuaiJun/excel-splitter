// -*- coding: utf-8 -*-
/* 数据源管理中心 · 前端逻辑 */
(function(){
  "use strict";

  const SRC = {
    categories: [],
    sources: [],
    stats: {total:0, ready:0, pending:0, error:0},
    curCat: null,
    keyword: "",
    addChannel: "excel",
    view: "overview",
  };

  const $ = id => document.getElementById(id);
  const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

  /* ---------- toast ---------- */
  function toast(msg, type){
    const t = document.createElement("div");
    t.className = "toast " + (type||"");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(()=>{ t.style.opacity="0"; t.style.transition="opacity .3s"; }, 2200);
    setTimeout(()=>t.remove(), 2600);
  }

  /* ---------- 弹窗 ---------- */
  function showModal(id){ $(id).classList.add("show"); }
  function hideModal(id){ $(id).classList.remove("show"); }
  function closeModalOnMask(e){ if(e.target.classList.contains("modal-mask")) e.target.classList.remove("show"); }

  /* ---------- 模块切换（匹配原型导航架构） ---------- */
  window.goModule = function(mod){
    if(typeof currentModule !== "undefined") currentModule = mod;
    document.querySelectorAll(".panel").forEach(p=>p.classList.remove("show"));
    if(mod === "sources"){
      const panel = document.querySelector('[data-module="sources"]');
      if(panel) panel.classList.add("show");
      const crumb = $("crumb"), title = $("title");
      if(crumb) crumb.textContent = "数据采集";
      if(title) title.textContent = "数据源管理中心";
      const prev = $("btnPrev"), next = $("btnNext");
      if(prev) prev.style.visibility = "hidden";
      if(next) next.style.display = "none";
      loadAll();
    }
    document.querySelectorAll(".nav-item").forEach(el=>el.classList.remove("active"));
    if(mod === "sources") $("navSources")?.classList.add("active");
    if(mod === "distribute") $("navDistribute")?.classList.add("active");
    // 配置模板栏仅分发模块显示
    const tplbar = $("tplbar");
    if(tplbar) tplbar.style.display = (mod === "distribute") ? "flex" : "none";
  };
  window.goSources = function(){ goModule("sources"); };

  /* 分发模块展开/折叠 */
  window.toggleDistribute = function(){
    const sub = $("distSubSteps"), arrow = $("distArrow"), item = $("navDistribute");
    if(sub.classList.contains("collapsed")){
      sub.classList.remove("collapsed"); item.classList.remove("collapsed");
      if(arrow) arrow.textContent = "▾";
    } else {
      sub.classList.add("collapsed"); item.classList.add("collapsed");
      if(arrow) arrow.textContent = "▸";
    }
    if(typeof currentModule !== "undefined" && currentModule !== "distribute" && typeof goStep === "function"){
      goStep(1);
    }
  };

  /* ---------- 加载 ---------- */
  async function loadAll(){
    await Promise.all([loadCategories(), loadSources()]);
  }

  async function loadCategories(){
    try{
      const r = await fetch("/api/categories");
      const j = await r.json();
      if(j.ok) SRC.categories = j.data;
    }catch(e){ console.error("加载分类失败", e); }
    renderCats();
  }

  async function loadSources(){
    const params = new URLSearchParams();
    if(SRC.curCat) params.set("category_id", SRC.curCat);
    if(SRC.keyword) params.set("keyword", SRC.keyword);
    try{
      const r = await fetch("/api/sources?" + params.toString());
      const j = await r.json();
      if(j.ok){
        SRC.sources = j.data;
        SRC.stats = j.stats || SRC.stats;
      }
    }catch(e){ console.error("加载数据源失败", e); }
    renderStats();
    if(SRC.view === "overview"){ renderCategoryOverview(); }
    else { renderSources(); updateDetailHeader(); }
  }

  /* ---------- 渲染统计 ---------- */
  function renderStats(){
    const el = $("srcStats");
    if(!el) return;
    el.innerHTML = `
      <div class="src-stat"><div class="num">${SRC.stats.total||0}</div><div class="lab">数据源总数</div></div>
      <div class="src-stat"><div class="num">${SRC.stats.ready||0}</div><div class="lab">已就绪</div></div>
      <div class="src-stat warn"><div class="num">${SRC.stats.pending||0}</div><div class="lab">待采集</div></div>
      <div class="src-stat err"><div class="num">${SRC.stats.error||0}</div><div class="lab">异常</div></div>
    `;
  }

  /* ---------- 第一层：分类汇总 ---------- */
  function renderCategoryOverview(){
    const el = $("catGrid");
    if(!el) return;
    const catMap = {};
    SRC.sources.forEach(ds=>{
      const cid = ds.category_id || "none";
      if(!catMap[cid]) catMap[cid] = {name: ds.category_name || "未分类", total:0, ready:0, pending:0, error:0};
      catMap[cid].total++;
      if(catMap[cid][ds.status] !== undefined) catMap[cid][ds.status]++;
    });
    SRC.categories.forEach(c=>{
      if(!catMap[c.id]) catMap[c.id] = {name: c.name, total:0, ready:0, pending:0, error:0};
    });
    if(!catMap["none"]) catMap["none"] = {name: "未分类", total:0, ready:0, pending:0, error:0};
    const cats = Object.entries(catMap).map(([id, data])=>({id, ...data}));
    if(!cats.length){
      el.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="big">📂</div>暂无分类，点击「管理分类」创建</div>`;
      return;
    }
    el.innerHTML = cats.map(c=>`
      <div class="cat-card" onclick="SRC_goCategory('${c.id}')">
        <div class="cc-head">
          <div class="cc-icon">📁</div>
          <div class="cc-name">${esc(c.name)}</div>
          <span class="cc-count">${c.total} 个</span>
        </div>
        <div class="cc-stats">
          <div class="cc-stat ready"><div class="n">${c.ready||0}</div><div class="l">已就绪</div></div>
          <div class="cc-stat pending"><div class="n">${c.pending||0}</div><div class="l">待采集</div></div>
          <div class="cc-stat error"><div class="n">${c.error||0}</div><div class="l">异常</div></div>
        </div>
        <div class="cc-arrow">→</div>
      </div>`).join("");
  }

  function updateDetailHeader(){
    const nameEl = $("catDetailName"), countEl = $("catDetailCount");
    if(!nameEl) return;
    let catName = "未分类";
    if(SRC.curCat){
      const cat = SRC.categories.find(c=>c.id===SRC.curCat);
      if(cat) catName = cat.name;
    }
    nameEl.textContent = catName;
    if(countEl) countEl.textContent = `${SRC.sources.length} 个数据源`;
  }

  window.SRC_goCategory = function(catId){
    SRC.view = "detail";
    SRC.curCat = (catId === "none" || catId === "") ? null : parseInt(catId);
    SRC.keyword = "";
    const si = $("srcSearchDetail");
    if(si) si.value = "";
    $("catOverview").style.display = "none";
    $("catDetail").style.display = "block";
    loadSources();
  };

  window.SRC_backToOverview = function(){
    SRC.view = "overview";
    SRC.curCat = null;
    SRC.keyword = "";
    $("catOverview").style.display = "block";
    $("catDetail").style.display = "none";
    loadSources();
  };

  /* ---------- 渲染分类标签 ---------- */
  function renderCats(){
    const el = $("srcCats");
    if(!el) return;
    let html = `<div class="src-cat ${SRC.curCat===null?'on':''}" onclick="SRC_setCat(null)">全部<span class="cnt">${SRC.stats.total||SRC.sources.length||0}</span></div>`;
    SRC.categories.forEach(c=>{
      html += `<div class="src-cat ${SRC.curCat===c.id?'on':''}" onclick="SRC_setCat(${c.id})">${esc(c.name)}<span class="cnt">${c.source_count||0}</span></div>`;
    });
    el.innerHTML = html;
  }
  window.SRC_setCat = function(id){ SRC.curCat = id; renderCats(); loadSources(); };
  window.SRC_search = function(v){ SRC.keyword = v; clearTimeout(SRC._st); SRC._st=setTimeout(loadSources, 250); };

  /* ---------- 渲染数据源卡片 ---------- */
  const CHANNEL_LABEL = {excel:"Excel", folder:"文件夹", database:"数据库", crawler:"爬虫"};
  const CHANNEL_ICON = {
    excel:'<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><rect x="4" y="3" width="16" height="18" rx="2" fill="#e7f6f4" stroke="#0f9d8f" stroke-width="1.5"/><path d="M8 8h8M8 12h8M8 16h5" stroke="#0b7d72" stroke-width="1.5" stroke-linecap="round"/></svg>',
    folder:'<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" fill="#eef4ff" stroke="#2b6cb0" stroke-width="1.5"/></svg>',
    database:'<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><ellipse cx="12" cy="5" rx="8" ry="3" fill="#fff3df" stroke="#b07a1a" stroke-width="1.5"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" stroke="#b07a1a" stroke-width="1.5" fill="none"/></svg>',
    crawler:'<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" fill="#fdecec" stroke="#c0392b" stroke-width="1.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" stroke="#c0392b" stroke-width="1.5" stroke-linecap="round"/></svg>',
  };

  function fmtTime(s){
    if(!s) return "-";
    const d = new Date(s);
    if(isNaN(d.getTime())) return s;
    const pad = n=>String(n).padStart(2,"0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function renderSources(){
    const el = $("srcList");
    if(!el) return;
    if(!SRC.sources.length){
      el.innerHTML = `<div class="empty-state"><div class="big">📂</div>暂无数据源，点击右上角「新增数据源」开始采集</div>`;
      return;
    }
    el.innerHTML = SRC.sources.map(ds=>{
      const sheets = (ds.sheet_names||[]).slice(0,4).map(s=>`<span class="sheet-chip">${esc(s)}</span>`).join("");
      const more = (ds.sheet_names||[]).length > 4 ? `<span class="sheet-chip">+${(ds.sheet_names||[]).length-4}</span>` : "";
      return `
      <div class="src-card" onclick="SRC_preview(${ds.id})">
        <div class="sc-head">
          <div class="sc-icon">${CHANNEL_ICON[ds.channel]||CHANNEL_ICON.excel}</div>
          <div class="sc-name">${esc(ds.name)}</div>
          <span class="sc-channel ${ds.channel}">${CHANNEL_LABEL[ds.channel]||ds.channel}</span>
        </div>
        <div class="sc-meta">
          <span>行数 <b>${ds.row_count||0}</b></span>
          <span>列数 <b>${ds.col_count||0}</b></span>
          <span>更新 <b>${fmtTime(ds.updated_at)}</b></span>
          <span class="status-tag ${ds.status}">${ds.status==='ready'?'已就绪':ds.status==='pending'?'待采集':'异常'}</span>
        </div>
        ${sheets?`<div class="sc-sheets">${sheets}${more}</div>`:""}
        <div class="sc-actions" onclick="event.stopPropagation()">
          <button class="btn btn-ghost" onclick="SRC_preview(${ds.id})">预览</button>
          <button class="btn btn-ghost cat-btn" onclick="SRC_changeCategory(${ds.id})">改分类</button>
          <button class="btn btn-ghost" onclick="SRC_recollect(${ds.id})">重新采集</button>
          <button class="btn btn-ghost" onclick="SRC_delete(${ds.id})" style="color:#e03131">删除</button>
        </div>
      </div>`;
    }).join("");
  }

  /* ---------- 新增数据源 ---------- */
  window.SRC_toggleAddMenu = function(){
    const menuId = SRC.view === "detail" ? "addMenuDetail" : "addMenu";
    const m = $(menuId);
    if(m) m.style.display = m.style.display==="none" ? "block" : "none";
  };
  document.addEventListener("click", e=>{
    if(!e.target.closest("#addMenu") && !e.target.closest("#addMenuDetail") && !e.target.closest("[onclick*='SRC_toggleAddMenu']")){
      const m1=$("addMenu"); if(m1) m1.style.display="none";
      const m2=$("addMenuDetail"); if(m2) m2.style.display="none";
    }
  });

  window.SRC_openAdd = function(channel){
    SRC.addChannel = channel;
    const m1=$("addMenu"); if(m1) m1.style.display="none";
    const m2=$("addMenuDetail"); if(m2) m2.style.display="none";
    // 渲染通道选择
    const channels = [
      {k:"excel", label:"Excel 文件", desc:"上传 .xlsx/.csv 自动解析", icon:"📊"},
      {k:"folder", label:"文件夹导入", desc:"批量导入目录下所有 Excel", icon:"📁"},
      {k:"database", label:"数据库连接", desc:"待接入接口", icon:"🗄️", disabled:true},
      {k:"crawler", label:"代码爬取", desc:"待接入接口", icon:"🕷️", disabled:true},
    ];
    $("addChannelPicker").innerHTML = channels.map(c=>`
      <div class="channel-opt ${SRC.addChannel===c.k?'sel':''} ${c.disabled?'disabled':''}" ${c.disabled?'':`onclick="SRC_pickChannel('${c.k}')"`}>
        <div class="ci">${c.icon}</div>
        <div class="ct">${c.label}</div>
        <div class="cd">${c.desc}</div>
      </div>`).join("");
    SRC_renderAddForm();
    if(SRC.view === "detail" && SRC.curCat){
      setTimeout(()=>{ const sel=document.getElementById("addCat"); if(sel) sel.value=SRC.curCat; }, 0);
    }
    showModal("addModal");
  };

  window.SRC_pickChannel = function(ch){ SRC.addChannel = ch; SRC_openAdd(ch); };

  function SRC_renderAddForm(){
    const body = $("addFormBody");
    if(SRC.addChannel === "excel"){
      body.innerHTML = `
        <div class="form-row">
          <label>选择 Excel 文件 <span class="hint">.xlsx / .xls / .csv</span></label>
          <div class="upload-zone" onclick="$('excelFile').click()">
            <div class="big" id="excelFileName">点击选择文件或拖拽到此处</div>
            <div class="small">支持最大 512MB，大文件自动流式解析</div>
          </div>
          <input type="file" id="excelFile" accept=".xlsx,.xls,.csv" style="display:none" onchange="SRC_onFilePick(this)">
        </div>
        <div class="form-row">
          <label>数据源名称 <span class="hint">留空则用文件名</span></label>
          <input type="text" id="addName" placeholder="例如：8月企微好友添加进度">
        </div>
        <div class="form-row">
          <label>所属分类</label>
          <select id="addCat">${SRC_catOptions()}</select>
        </div>`;
    } else if(SRC.addChannel === "folder"){
      body.innerHTML = `
        <div class="form-row">
          <label>文件夹路径 <span class="hint">本地绝对路径</span></label>
          <input type="text" id="folderPath" placeholder="例如：D:\\数据\\8月报表">
        </div>
        <div class="form-row">
          <label>
            <input type="checkbox" id="folderRecursive" style="width:auto;margin-right:6px"> 递归导入子文件夹
          </label>
        </div>
        <div class="form-row">
          <label>统一分类 <span class="hint">导入的所有文件归到此分类</span></label>
          <select id="addCat">${SRC_catOptions()}</select>
        </div>`;
    } else {
      body.innerHTML = `<div style="text-align:center;padding:30px;color:var(--faint)">该通道待接入接口，暂不可用</div>`;
    }
  }

  function SRC_catOptions(){
    let opts = `<option value="">未分类</option>`;
    SRC.categories.forEach(c=>{ opts += `<option value="${c.id}">${esc(c.name)}</option>`; });
    return opts;
  }

  window.SRC_onFilePick = function(input){
    if(input.files[0]) $("excelFileName").textContent = input.files[0].name;
  };

  window.SRC_submitAdd = async function(){
    if(SRC.addChannel === "excel"){
      const fileInput = $("excelFile");
      if(!fileInput.files[0]){ toast("请先选择文件", "err"); return; }
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      const name = $("addName").value.trim();
      if(name) fd.append("name", name);
      const cat = $("addCat").value;
      if(cat) fd.append("category_id", cat);
      $("addSubmitBtn").disabled = true;
      $("addSubmitBtn").innerHTML = '<span class="spinner"></span> 采集中...';
      try{
        const r = await fetch("/api/collect/excel", {method:"POST", body:fd});
        const j = await r.json();
        if(j.ok){
          toast(`采集成功：${j.data.row_count} 行 / ${j.data.col_count} 列`, "ok");
          hideModal("addModal");
          loadAll();
        } else {
          toast(j.msg || "采集失败", "err");
        }
      }catch(e){ toast("网络错误："+e.message, "err"); }
      finally{
        $("addSubmitBtn").disabled = false;
        $("addSubmitBtn").textContent = "开始采集";
      }
    } else if(SRC.addChannel === "folder"){
      const path = $("folderPath").value.trim();
      if(!path){ toast("请输入文件夹路径", "err"); return; }
      const cat = $("addCat").value;
      const recursive = $("folderRecursive").checked;
      $("addSubmitBtn").disabled = true;
      $("addSubmitBtn").innerHTML = '<span class="spinner"></span> 导入中...';
      try{
        const r = await fetch("/api/collect/folder", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({folder_path:path, category_id: cat?parseInt(cat):null, recursive})
        });
        const j = await r.json();
        if(j.ok){
          toast(`导入完成：成功 ${j.success} / 共 ${j.total}`, "ok");
          hideModal("addModal");
          loadAll();
        } else {
          toast(j.msg || "导入失败", "err");
        }
      }catch(e){ toast("网络错误："+e.message, "err"); }
      finally{
        $("addSubmitBtn").disabled = false;
        $("addSubmitBtn").textContent = "开始导入";
      }
    }
  };

  /* ---------- 预览 ---------- */
  window.SRC_preview = async function(id){
    const ds = SRC.sources.find(s=>s.id===id);
    if(!ds) return;
    $("previewTitle").textContent = ds.name;
    $("previewSheetSel").innerHTML = (ds.sheet_names||["Sheet1"]).map((s,i)=>`<option value="${esc(s)}">${esc(s)}</option>`).join("");
    $("previewSheetSel").onchange = ()=>SRC_loadPreview(id);
    $("previewBody").innerHTML = `<div style="text-align:center;padding:30px"><span class="spinner"></span> 加载中...</div>`;
    showModal("previewModal");
    SRC_loadPreview(id);
  };

  async function SRC_loadPreview(id){
    const sheet = $("previewSheetSel").value;
    try{
      const r = await fetch(`/api/sources/${id}/preview?sheet=${encodeURIComponent(sheet)}&limit=100`);
      const j = await r.json();
      if(j.ok){
        const cols = j.columns||[], rows = j.rows||[];
        $("previewMeta").innerHTML = `<span>子表：<b>${esc(j.sheet||sheet)}</b></span><span>预览行数：<b>${rows.length}</b></span><span>列数：<b>${cols.length}</b></span>`;
        if(!cols.length){
          $("previewBody").innerHTML = `<div class="empty-state">无子表数据</div>`;
          return;
        }
        let html = `<div class="preview-table-wrap"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>`;
        rows.forEach(row=>{
          html += `<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`;
        });
        html += `</tbody></table></div>`;
        if(rows.length >= 100) html += `<div style="font-size:11.5px;color:var(--faint);margin-top:8px">仅预览前 100 行</div>`;
        $("previewBody").innerHTML = html;
      } else {
        $("previewBody").innerHTML = `<div class="empty-state">预览失败：${esc(j.msg)}</div>`;
      }
    }catch(e){
      $("previewBody").innerHTML = `<div class="empty-state">网络错误</div>`;
    }
  }

  /* ---------- 重新采集 ---------- */
  window.SRC_recollect = async function(id){
    if(!confirm("确定重新采集此数据源？将重新解析文件并更新元数据。")) return;
    try{
      const r = await fetch(`/api/sources/${id}/collect`, {method:"POST"});
      const j = await r.json();
      if(j.ok){ toast("重新采集成功", "ok"); loadAll(); }
      else toast(j.msg||"重新采集失败", "err");
    }catch(e){ toast("网络错误", "err"); }
  };

  /* ---------- 删除 ---------- */
  window.SRC_delete = async function(id){
    const ds = SRC.sources.find(s=>s.id===id);
    if(!ds) return;
    if(!confirm(`确定删除数据源「${ds.name}」？采集日志将一并删除（源文件不会被删除）。`)) return;
    try{
      const r = await fetch(`/api/sources/${id}`, {method:"DELETE"});
      const j = await r.json();
      if(j.ok){ toast("已删除", "ok"); loadAll(); }
      else toast(j.msg||"删除失败", "err");
    }catch(e){ toast("网络错误", "err"); }
  };

  /* ---------- 修改数据源分类 ---------- */
  window.SRC_changeCategory = function(id){
    const ds = SRC.sources.find(s=>s.id===id);
    if(!ds) return;
    SRC._changeCatId = id;
    // 设置数据源名称
    $("changeCatSrcName").textContent = ds.name;
    // 填充分类下拉框
    const sel = $("changeCatSelect");
    sel.innerHTML = `<option value="">未分类</option>` + SRC.categories.map(c=>
      `<option value="${c.id}" ${c.id===ds.category_id?'selected':''}>${esc(c.name)}</option>`
    ).join("");
    showModal("changeCatModal");
  };

  window.SRC_confirmChangeCategory = async function(){
    const id = SRC._changeCatId;
    if(!id) return;
    const val = $("changeCatSelect").value;
    const newCatId = val ? parseInt(val) : null;
    try{
      const r = await fetch(`/api/sources/${id}`, {
        method:"PUT", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({category_id: newCatId})
      });
      const j = await r.json();
      if(j.ok){
        toast("分类已更新", "ok");
        hideModal("changeCatModal");
        loadSources();
      } else {
        toast(j.msg||"更新失败", "err");
      }
    }catch(e){ toast("网络错误", "err"); }
  };

  /* ---------- 分类管理 ---------- */
  window.SRC_openCatManager = function(){
    SRC_renderCatList();
    showModal("catModal");
  };

  function SRC_renderCatList(){
    const el = $("catList");
    if(!SRC.categories.length){
      el.innerHTML = `<div style="text-align:center;padding:20px;color:var(--faint)">暂无分类，在下方添加</div>`;
      return;
    }
    el.innerHTML = SRC.categories.map(c=>`
      <div class="cat-item">
        <span class="cn">${esc(c.name)}</span>
        <span class="cc">${c.source_count||0} 个数据源</span>
        <div class="actions">
          <button class="btn btn-ghost" onclick="SRC_renameCat(${c.id}, '${esc(c.name)}')">重命名</button>
          <button class="btn btn-ghost" style="color:#e03131" onclick="SRC_deleteCat(${c.id}, '${esc(c.name)}')">删除</button>
        </div>
      </div>`).join("");
  }

  window.SRC_addCat = async function(){
    const input = $("newCatName");
    const name = input.value.trim();
    if(!name){ toast("请输入分类名称", "err"); return; }
    try{
      const r = await fetch("/api/categories", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name})});
      const j = await r.json();
      if(j.ok){ toast("分类已添加", "ok"); input.value=""; loadCategories(); SRC_renderCatList(); }
      else toast(j.msg||"添加失败", "err");
    }catch(e){ toast("网络错误", "err"); }
  };

  window.SRC_renameCat = async function(id, oldName){
    const name = prompt("重命名分类：", oldName);
    if(!name || name.trim()===oldName) return;
    try{
      const r = await fetch(`/api/categories/${id}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name:name.trim()})});
      const j = await r.json();
      if(j.ok){ toast("已重命名", "ok"); loadCategories(); SRC_renderCatList(); }
      else toast(j.msg||"重命名失败", "err");
    }catch(e){ toast("网络错误", "err"); }
  };

  window.SRC_deleteCat = async function(id, name){
    if(!confirm(`确定删除分类「${name}」？该分类下有数据源时无法删除。`)) return;
    try{
      const r = await fetch(`/api/categories/${id}`, {method:"DELETE"});
      const j = await r.json();
      if(j.ok){ toast("分类已删除", "ok"); if(SRC.curCat===id) SRC.curCat=null; loadCategories(); SRC_renderCatList(); loadSources(); }
      else toast(j.msg||"删除失败", "err");
    }catch(e){ toast("网络错误", "err"); }
  };

  /* ---------- 分发模块：从数据源中心选择 ---------- */
  let PICKER_CACHE = [];

  window.openSourcePicker = async function(){
    showModal("sourcePickerModal");
    $("pickerSearch").value = "";
    $("pickerList").innerHTML = `<div class="empty-state"><span class="spinner"></span> 加载中...</div>`;
    try{
      const r = await fetch("/api/sources");
      const j = await r.json();
      if(j.ok){
        PICKER_CACHE = j.data.filter(s => s.channel === "excel" && s.status === "ready");
        renderSourcePicker();
      } else {
        $("pickerList").innerHTML = `<div class="empty-state">加载失败：${esc(j.msg)}</div>`;
      }
    }catch(e){
      $("pickerList").innerHTML = `<div class="empty-state">网络错误</div>`;
    }
  };

  window.renderSourcePicker = function(){
    const kw = ($("pickerSearch")?.value || "").trim().toLowerCase();
    const list = kw ? PICKER_CACHE.filter(s => s.name.toLowerCase().includes(kw)) : PICKER_CACHE;
    const el = $("pickerList");
    if(!list.length){
      el.innerHTML = `<div class="empty-state"><div class="big">📂</div>${kw ? "没有匹配的数据源" : "暂无已就绪的 Excel 数据源，请先到「数据采集」模块添加"}</div>`;
      return;
    }
    el.innerHTML = list.map(ds=>`
      <div class="src-card" onclick="pickSource(${ds.id})">
        <div class="sc-head">
          <div class="sc-icon">${CHANNEL_ICON[ds.channel]||CHANNEL_ICON.excel}</div>
          <div class="sc-name">${esc(ds.name)}</div>
          <span class="status-tag ready">已就绪</span>
        </div>
        <div class="sc-meta">
          <span>行数 <b>${ds.row_count||0}</b></span>
          <span>列数 <b>${ds.col_count||0}</b></span>
          <span>子表 <b>${(ds.sheet_names||[]).length}</b></span>
          <span>分类 <b>${esc(ds.category_name||"未分类")}</b></span>
        </div>
        <div style="font-size:12px;color:var(--primary-d);font-weight:600;margin-top:auto">点击选用 →</div>
      </div>`).join("");
  };

  window.pickSource = async function(id){
    const ds = PICKER_CACHE.find(s=>s.id===id);
    if(!ds) return;
    try{
      const r = await fetch(`/api/sources/${id}/inspect`);
      const j = await r.json();
      if(!j.ok) throw new Error(j.msg || "读取失败");
      // 复用分发模块的 upload 后续逻辑
      if(typeof S !== "undefined"){
        S.data = j;
        S.sheets = j.sheets[0] ? [j.sheets[0].name] : [];
        S.srcName = "来源";
        S.srcMap = {};
        S.includeDetail = true;
        if(typeof syncOutMode === "function") syncOutMode();
        if(typeof initCfg === "function") initCfg();
      }
      const dropBig = $("dropBig");
      if(dropBig) dropBig.textContent = "点击重新选择，或拖拽替换文件";
      const fileInfo = $("fileInfo");
      if(fileInfo){
        fileInfo.innerHTML = `<div class="file-pick"><div class="fi"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="4" y="3" width="16" height="18" rx="2" fill="#dff1ef"/><path d="M14 3v4h4" stroke="#0f9d8f" stroke-width="1.6"/></svg></div><div><div class="fn">${esc(j.filename)}</div><div class="fs">来自数据源中心 · ${j.sheets.length} 个子表 · 读取成功</div></div><button class="linkbtn" onclick="openSourcePicker()">重新选择</button></div>`;
      }
      const sheetWrap = $("sheetWrap");
      if(sheetWrap) sheetWrap.style.display = "block";
      if(typeof renderSheets === "function") renderSheets();
      hideModal("sourcePickerModal");
      toast(`已从数据源中心载入：${j.filename}`, "ok");
    }catch(e){
      toast("读取失败：" + e.message, "err");
    }
  };

  /* ---------- 初始化 ---------- */
  function initDragDrop(){
    const wrap = $("srcPanelWrap");
    if(!wrap) return;
    let dragCounter = 0;
    wrap.addEventListener("dragenter", e=>{
      e.preventDefault();
      dragCounter++;
      $("dropMask")?.classList.add("show");
    });
    wrap.addEventListener("dragover", e=>{ e.preventDefault(); });
    wrap.addEventListener("dragleave", e=>{
      e.preventDefault();
      dragCounter--;
      if(dragCounter<=0){ $("dropMask")?.classList.remove("show"); dragCounter=0; }
    });
    wrap.addEventListener("drop", e=>{
      e.preventDefault();
      dragCounter = 0;
      $("dropMask")?.classList.remove("show");
      const files = e.dataTransfer.files;
      if(files && files.length>0){
        const file = files[0];
        const ext = file.name.split(".").pop().toLowerCase();
        if(["xlsx","xls","csv"].includes(ext)){
          SRC_openAdd("excel");
          setTimeout(()=>{
            const fi = $("excelFile");
            if(fi){
              try{
                const dt = new DataTransfer();
                dt.items.add(file);
                fi.files = dt.files;
                $("excelFileName").textContent = file.name;
              }catch(e){ toast("请手动选择文件", "err"); }
            }
          }, 100);
        } else {
          toast("仅支持 .xlsx / .xls / .csv 文件", "err");
        }
      }
    });
  }

  function init(){
    const nav = $("nav");
    if(nav){
      nav.addEventListener("click", e=>{
        if(e.target.closest(".step")) $("navSources")?.classList.remove("active");
      });
    }
    document.querySelectorAll(".modal-mask").forEach(m=>m.addEventListener("click", closeModalOnMask));
    initDragDrop();
  }

  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // 暴露给全局
  window.SRC = SRC;
  window.showModal = showModal;
  window.hideModal = hideModal;
  window.toast = toast;
})();
