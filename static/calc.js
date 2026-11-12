// 数据计算模块
(function(){
  const CA = { view:"list", tab:"sql", sources:[], selectedSource:null, sqlResult:null, mergeResult:null };

  function $(id){ return document.getElementById(id); }
  function esc(s){ if(s==null) return ""; const d=document.createElement("div"); d.textContent=s; return d.innerHTML; }
  function toast(msg, type){ const t=document.createElement("div"); t.className="toast "+(type||"ok"); t.textContent=msg; document.body.appendChild(t); setTimeout(()=>t.remove(),2500); }

  async function loadSources(){
    try{
      const r = await fetch("/api/sources?page_size=200");
      const j = await r.json();
      if(j.ok) CA.sources = j.data;
    }catch(e){ console.error("加载数据源失败", e); }
  }

  async function loadTasks(){
    try{
      const r = await fetch("/api/calc/tasks");
      const j = await r.json();
      if(j.ok) renderTasks(j.data);
      else renderLoadError(j.msg || "接口返回异常");
    }catch(e){
      renderLoadError("后端返回异常（通常是数据库未就绪）");
    }
  }

  // 列表加载失败时的可见提示（避免整块区域留白）
  function renderLoadError(msg){
    const el = $("calcTaskList");
    if(!el) return;
    el.innerHTML = `<div class="empty-state"><div class="big">⚠️</div>
      <div>计算任务列表读取失败</div>
      <div style="font-size:12.5px;margin-top:8px;color:#c0392b">${esc(msg)}</div>
      <div style="font-size:12px;margin-top:6px">请确认后端服务与数据库连接正常后重试</div>
      <button class="btn btn-ghost" type="button" style="margin-top:14px" onclick="CA_refresh()">重试</button>
    </div>`;
  }

  function renderTasks(tasks){
    const el = $("calcTaskList");
    if(!el) return;
    if(tasks.length === 0){
      el.innerHTML = `<div class="empty-state"><div class="big">🧮</div>
        <div>暂无计算任务</div>
        <div style="font-size:12.5px;margin-top:6px">点击右上角「新建计算任务」开始</div>
      </div>`;
      return;
    }
    el.innerHTML = tasks.map(t => {
      const typeIcon = t.calc_type === "sql" ? "📝" : "🔗";
      return `
        <div class="calc-task-card">
          <div class="ctc-head">
            <div class="ctc-name">${esc(t.name)}</div>
            <div class="ctc-type"><span class="type-tag">${typeIcon} ${esc(t.calc_type_text || t.calc_type)}</span></div>
          </div>
          <div class="ctc-body">
            <div class="ctc-meta">
              <span>原始数据源：${esc(t.original_source_name || "-")}</span>
              <span>${t.row_count || 0} 行 / ${t.col_count || 0} 列</span>
            </div>
            <div class="ctc-time">${esc(t.updated_at || t.created_at || "")}</div>
          </div>
        </div>`;
    }).join("");
  }

  window.CA_openNew = async function(){
    if(CA.sources.length === 0) await loadSources();
    CA.view = "new";
    CA.tab = "sql";
    CA.sqlResult = null;
    CA.mergeResult = null;
    renderNewPanel();
    $("calcListPanel").style.display = "none";
    $("calcNewPanel").style.display = "block";
  };

  window.CA_backToList = function(){
    CA.view = "list";
    $("calcNewPanel").style.display = "none";
    $("calcListPanel").style.display = "block";
    loadTasks();
  };

  window.CA_switchTab = function(tab){
    CA.tab = tab;
    document.querySelectorAll(".calc-tab").forEach(t => t.classList.remove("active"));
    document.querySelector(`.calc-tab[data-tab="${tab}"]`)?.classList.add("active");
    $("calcSqlPanel").style.display = tab === "sql" ? "block" : "none";
    $("calcMergePanel").style.display = tab === "merge" ? "block" : "none";
  };

  function renderNewPanel(){
    const sourceOpts = CA.sources.map(s => `<option value="${s.id}">${esc(s.name)} (${s.row_count||0}行/${s.col_count||0}列)</option>`).join("");
    $("calcNewPanel").innerHTML = `
      <div class="page-head">
        <div>
          <h2>新建计算任务</h2>
          <p class="page-sub">通过 SQL 查询或表关联，从已有数据源生成新的衍生数据源</p>
        </div>
        <button class="btn btn-ghost" onclick="CA_backToList()">← 返回列表</button>
      </div>
      <div class="calc-tabs">
        <div class="calc-tab active" data-tab="sql" onclick="CA_switchTab('sql')">📝 SQL 计算</div>
        <div class="calc-tab" data-tab="merge" onclick="CA_switchTab('merge')">🔗 表关联</div>
      </div>
      <div id="calcSqlPanel">
        <div class="calc-workspace">
          <div class="calc-config-panel">
            <div class="config-section">
              <div class="config-title">📊 选择数据源</div>
              <select id="calcSqlSource" onchange="CA_onSqlSourceChange()" style="width:100%">
                <option value="">请选择数据源</option>
                ${sourceOpts}
              </select>
              <div style="margin-top:8px;font-size:12px;color:#7a8a86">
                表名：<code id="calcSqlTableName" style="background:#f0f4f3;padding:2px 6px;border-radius:4px">data</code>
              </div>
            </div>
            <div class="config-section">
              <div class="config-title">📝 SQL 语句</div>
              <textarea id="calcSqlInput" class="sql-editor" placeholder="SELECT * FROM data WHERE ..." spellcheck="false">SELECT * FROM data</textarea>
              <div style="font-size:11.5px;color:#9aada8;margin-top:6px">使用表名 "data" 引用所选数据源，支持标准 SQLite 语法</div>
            </div>
            <div class="config-section">
              <button class="btn btn-primary" style="width:100%" onclick="CA_sqlPreview()">▶️ 运行预览</button>
            </div>
          </div>
          <div class="calc-preview-panel" id="calcSqlPreview">
            <div style="text-align:center;padding:60px;color:#7a8a86">
              <div style="font-size:40px;margin-bottom:12px">👁️</div>
              <div>选择数据源并输入 SQL，点击"运行预览"</div>
            </div>
          </div>
        </div>
      </div>
      <div id="calcMergePanel" style="display:none">
        <div class="calc-workspace">
          <div class="calc-config-panel">
            <div class="config-section">
              <div class="config-title">📊 主表（左表）</div>
              <select id="calcMergeLeft" onchange="CA_onMergeSourceChange('left')" style="width:100%">
                <option value="">请选择主表</option>
                ${sourceOpts}
              </select>
            </div>
            <div class="config-section">
              <div class="config-title">🔗 关联表（右表）</div>
              <select id="calcMergeRight" onchange="CA_onMergeSourceChange('right')" style="width:100%">
                <option value="">请选择关联表</option>
                ${sourceOpts}
              </select>
            </div>
            <div class="config-section">
              <div class="config-title">⚙️ 关联配置</div>
              <div style="margin-bottom:10px">
                <label style="font-size:12.5px;color:#5a6a66;display:block;margin-bottom:4px">主表关联字段</label>
                <select id="calcMergeLeftOn" style="width:100%"><option value="">请先选择主表</option></select>
              </div>
              <div style="margin-bottom:10px">
                <label style="font-size:12.5px;color:#5a6a66;display:block;margin-bottom:4px">关联表字段</label>
                <select id="calcMergeRightOn" style="width:100%"><option value="">请先选择关联表</option></select>
              </div>
              <div>
                <label style="font-size:12.5px;color:#5a6a66;display:block;margin-bottom:4px">关联类型</label>
                <select id="calcMergeHow" style="width:100%">
                  <option value="left">LEFT JOIN（保留主表全部）</option>
                  <option value="right">RIGHT JOIN（保留关联表全部）</option>
                  <option value="inner">INNER JOIN（只保留匹配）</option>
                  <option value="outer">OUTER JOIN（全部保留）</option>
                </select>
              </div>
            </div>
            <div class="config-section">
              <button class="btn btn-primary" style="width:100%" onclick="CA_mergePreview()">🔍 预览关联结果</button>
            </div>
          </div>
          <div class="calc-preview-panel" id="calcMergePreview">
            <div style="text-align:center;padding:60px;color:#7a8a86">
              <div style="font-size:40px;margin-bottom:12px">👁️</div>
              <div>选择主表和关联表，配置关联字段，点击"预览关联结果"</div>
            </div>
          </div>
        </div>
      </div>`;
  }

  window.CA_onSqlSourceChange = function(){
    const sid = parseInt($("calcSqlSource").value);
    if(!sid) return;
    CA.selectedSource = CA.sources.find(s => s.id === sid);
  };

  window.CA_onMergeSourceChange = function(side){
    const sid = parseInt($(side === "left" ? "calcMergeLeft" : "calcMergeRight").value);
    if(!sid) return;
    const src = CA.sources.find(s => s.id === sid);
    const cols = (src.config && src.config.columns) || [];
    const sel = $(side === "left" ? "calcMergeLeftOn" : "calcMergeRightOn");
    if(sel && cols.length > 0){
      sel.innerHTML = cols.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    }
  };

  window.CA_sqlPreview = async function(){
    const sid = parseInt($("calcSqlSource").value);
    const sql = $("calcSqlInput").value.trim();
    if(!sid){ toast("请选择数据源", "err"); return; }
    if(!sql){ toast("请输入 SQL 语句", "err"); return; }
    const panel = $("calcSqlPreview");
    panel.innerHTML = `<div style="text-align:center;padding:40px"><span class="spinner"></span><div style="margin-top:12px;color:#7a8a86">正在执行...</div></div>`;
    try{
      const r = await fetch("/api/calc/sql-preview", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({source_id: sid, sql: sql, table_name: "data"}),
      });
      const j = await r.json();
      if(j.ok){
        CA.sqlResult = j.data;
        renderSqlPreview(j.data);
      } else {
        panel.innerHTML = `<div style="text-align:center;padding:40px;color:#e74c3c">执行失败：${esc(j.msg)}</div>`;
      }
    }catch(e){
      panel.innerHTML = `<div style="text-align:center;padding:40px;color:#e74c3c">执行失败：${esc(e.message)}</div>`;
    }
  };

  function renderSqlPreview(data){
    const panel = $("calcSqlPreview");
    panel.innerHTML = `
      <div class="preview-stats">
        <div class="ps-item"><div class="ps-num">${data.total_rows}</div><div class="ps-label">结果行数</div></div>
        <div class="ps-item"><div class="ps-num">${data.total_cols}</div><div class="ps-label">结果列数</div></div>
      </div>
      <div class="compare-table-wrap" style="max-height:400px;overflow:auto;border:1px solid #e2e8e6;border-radius:8px">
        <table class="compare-table"><thead><tr>${data.columns.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${data.rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>
      </div>
      <div class="preview-action">
        <input type="text" id="calcSqlResultName" placeholder="结果数据源名称，留空自动命名" style="flex:1;padding:8px 12px;border:1px solid #cfdcd9;border-radius:8px;font-size:13px;font-family:inherit">
        <button class="btn btn-primary" onclick="CA_sqlExecute()">💾 保存为新数据源</button>
      </div>`;
  }

  window.CA_sqlExecute = async function(){
    const sid = parseInt($("calcSqlSource").value);
    const sql = $("calcSqlInput").value.trim();
    const resultName = $("calcSqlResultName")?.value.trim() || "";
    try{
      const r = await fetch("/api/calc/sql-execute", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({source_id: sid, sql: sql, table_name: "data", result_name: resultName}),
      });
      const j = await r.json();
      if(j.ok){
        toast(`计算完成！${j.data.row_count}行/${j.data.col_count}列`, "ok");
        CA_backToList();
      } else {
        toast(j.msg || "执行失败", "err");
      }
    }catch(e){
      toast("执行失败: " + e.message, "err");
    }
  };

  window.CA_mergePreview = async function(){
    const leftId = parseInt($("calcMergeLeft").value);
    const rightId = parseInt($("calcMergeRight").value);
    const leftOn = $("calcMergeLeftOn").value;
    const rightOn = $("calcMergeRightOn").value;
    const how = $("calcMergeHow").value;
    if(!leftId || !rightId){ toast("请选择主表和关联表", "err"); return; }
    if(!leftOn || !rightOn){ toast("请选择关联字段", "err"); return; }
    const panel = $("calcMergePreview");
    panel.innerHTML = `<div style="text-align:center;padding:40px"><span class="spinner"></span><div style="margin-top:12px;color:#7a8a86">正在关联...</div></div>`;
    try{
      const r = await fetch("/api/calc/merge-preview", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({left_source_id: leftId, right_source_id: rightId, left_on: leftOn, right_on: rightOn, how: how}),
      });
      const j = await r.json();
      if(j.ok){
        CA.mergeResult = j.data;
        renderMergePreview(j.data);
      } else {
        panel.innerHTML = `<div style="text-align:center;padding:40px;color:#e74c3c">关联失败：${esc(j.msg)}</div>`;
      }
    }catch(e){
      panel.innerHTML = `<div style="text-align:center;padding:40px;color:#e74c3c">关联失败：${esc(e.message)}</div>`;
    }
  };

  function renderMergePreview(data){
    const panel = $("calcMergePreview");
    panel.innerHTML = `
      <div class="preview-stats">
        <div class="ps-item"><div class="ps-num">${data.left_rows}</div><div class="ps-label">主表行数</div></div>
        <div class="ps-arrow">+</div>
        <div class="ps-item"><div class="ps-num">${data.right_rows}</div><div class="ps-label">关联表行数</div></div>
        <div class="ps-arrow">=</div>
        <div class="ps-item"><div class="ps-num" style="color:#0f9d8f">${data.total_rows}</div><div class="ps-label">结果行数</div></div>
        <div class="ps-item"><div class="ps-num">${data.total_cols}</div><div class="ps-label">结果列数</div></div>
      </div>
      <div class="compare-table-wrap" style="max-height:400px;overflow:auto;border:1px solid #e2e8e6;border-radius:8px">
        <table class="compare-table"><thead><tr>${data.columns.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${data.rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>
      </div>
      <div class="preview-action">
        <input type="text" id="calcMergeResultName" placeholder="结果数据源名称，留空自动命名" style="flex:1;padding:8px 12px;border:1px solid #cfdcd9;border-radius:8px;font-size:13px;font-family:inherit">
        <button class="btn btn-primary" onclick="CA_mergeExecute()">💾 保存为新数据源</button>
      </div>`;
  }

  window.CA_mergeExecute = async function(){
    const leftId = parseInt($("calcMergeLeft").value);
    const rightId = parseInt($("calcMergeRight").value);
    const leftOn = $("calcMergeLeftOn").value;
    const rightOn = $("calcMergeRightOn").value;
    const how = $("calcMergeHow").value;
    const resultName = $("calcMergeResultName")?.value.trim() || "";
    try{
      const r = await fetch("/api/calc/merge-execute", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({left_source_id: leftId, right_source_id: rightId, left_on: leftOn, right_on: rightOn, how: how, result_name: resultName}),
      });
      const j = await r.json();
      if(j.ok){
        toast(`关联完成！${j.data.row_count}行/${j.data.col_count}列`, "ok");
        CA_backToList();
      } else {
        toast(j.msg || "执行失败", "err");
      }
    }catch(e){
      toast("执行失败: " + e.message, "err");
    }
  };

  window.CA_init = function(){ loadTasks(); };

  // 重新拉取任务列表
  window.CA_refresh = function(){ loadTasks(); };
})();
