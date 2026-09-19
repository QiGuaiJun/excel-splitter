// 数据清洗模块
(function(){
  const CL = { view:"list", sources:[], selectedSource:null, rules:{format:{trim:true}, null:{action:"none"}, dedup:{enabled:false,columns:[]}}, previewData:null };

  function $(id){ return document.getElementById(id); }
  function esc(s){ if(s==null) return ""; const d=document.createElement("div"); d.textContent=s; return d.innerHTML; }
  function toast(msg, type){ const t=document.createElement("div"); t.className="toast "+(type||"ok"); t.textContent=msg; document.body.appendChild(t); setTimeout(()=>t.remove(),2500); }

  // 加载数据源列表（用于选择）
  async function loadSources(){
    try{
      const r = await fetch("/api/sources?page_size=200");
      const j = await r.json();
      if(j.ok) CL.sources = j.data;
    }catch(e){ console.error("加载数据源失败", e); }
  }

  // 加载清洗任务列表
  async function loadTasks(){
    try{
      const r = await fetch("/api/clean/tasks");
      const j = await r.json();
      if(j.ok){
        renderTasks(j.data);
      }
    }catch(e){ toast("加载清洗任务失败", "err"); }
  }

  // 渲染任务列表
  function renderTasks(tasks){
    const el = $("cleanTaskList");
    if(!el) return;
    if(tasks.length === 0){
      el.innerHTML = `<div style="text-align:center;padding:40px;color:#7a8a86">
        <div style="font-size:40px;margin-bottom:12px">🧹</div>
        <div>暂无清洗任务</div>
        <div style="font-size:12.5px;margin-top:6px">点击右上角"新建清洗任务"开始</div>
      </div>`;
      return;
    }
    el.innerHTML = tasks.map(t => {
      const stats = t.clean_stats || {};
      const rowDiff = (stats.rows_before || 0) - (stats.rows_after || 0);
      return `
        <div class="clean-task-card">
          <div class="ctc-head">
            <div class="ctc-name">${esc(t.name)}</div>
            <div class="ctc-status"><span class="status-ok">已完成</span></div>
          </div>
          <div class="ctc-body">
            <div class="ctc-meta">
              <span>原始数据源：${esc(t.original_source_name || "-")}</span>
              <span>清洗前：${stats.rows_before || 0} 行</span>
              <span>清洗后：${stats.rows_after || 0} 行</span>
              ${rowDiff > 0 ? `<span style="color:#e74c3c">删除：${rowDiff} 行</span>` : ""}
            </div>
            <div class="ctc-rules">${esc(t.rules_summary || "无变更")}</div>
            <div class="ctc-time">${esc(t.updated_at || t.created_at || "")}</div>
          </div>
        </div>`;
    }).join("");
  }

  // 打开新建清洗面板
  window.CL_openNew = async function(){
    if(CL.sources.length === 0) await loadSources();
    CL.view = "new";
    CL.selectedSource = null;
    CL.rules = {format:{trim:true}, null:{action:"none"}, dedup:{enabled:false,columns:[]}};
    CL.previewData = null;
    renderNewPanel();
    $("cleanListPanel").style.display = "none";
    $("cleanNewPanel").style.display = "block";
  };

  // 返回列表
  window.CL_backToList = function(){
    CL.view = "list";
    $("cleanNewPanel").style.display = "none";
    $("cleanListPanel").style.display = "block";
    loadTasks();
  };

  // 渲染新建面板
  function renderNewPanel(){
    const sourceOpts = CL.sources.map(s => `<option value="${s.id}">${esc(s.name)} (${s.row_count||0}行/${s.col_count||0}列)</option>`).join("");
    $("cleanNewPanel").innerHTML = `
      <div class="page-head">
        <div>
          <h2>新建清洗任务</h2>
          <p class="page-sub">选择数据源，配置清洗规则，预览后执行生成新数据源</p>
        </div>
        <button class="btn btn-ghost" onclick="CL_backToList()">← 返回列表</button>
      </div>
      <div class="clean-workspace">
        <div class="clean-config-panel">
          <div class="config-section">
            <div class="config-title">📊 选择数据源</div>
            <select id="cleanSourceSel" onchange="CL_onSourceChange()" style="width:100%">
              <option value="">请选择数据源</option>
              ${sourceOpts}
            </select>
          </div>
          <div class="config-section" id="cleanRulesSection" style="display:none">
            <div class="config-title">⚙️ 清洗规则</div>
            <div class="rule-group">
              <div class="rule-label">格式统一</div>
              <label class="rule-check"><input type="checkbox" id="ruleTrim" checked onchange="CL_updateRules()"> 去除首尾空格</label>
              <label class="rule-check"><input type="checkbox" id="ruleUpper" onchange="CL_updateRules()"> 统一大写</label>
              <label class="rule-check"><input type="checkbox" id="ruleLower" onchange="CL_updateRules()"> 统一小写</label>
            </div>
            <div class="rule-group">
              <div class="rule-label">空值处理</div>
              <label class="rule-check"><input type="radio" name="nullAction" value="none" checked onchange="CL_updateRules()"> 不处理</label>
              <label class="rule-check"><input type="radio" name="nullAction" value="drop" onchange="CL_updateRules()"> 删除空值行</label>
              <label class="rule-check"><input type="radio" name="nullAction" value="fill" onchange="CL_updateRules()"> 填充为
                <input type="text" id="nullFillValue" placeholder="填充值" style="width:80px;margin-left:6px;padding:2px 6px;border:1px solid #cfdcd9;border-radius:4px;font-size:12px" onchange="CL_updateRules()">
              </label>
            </div>
            <div class="rule-group">
              <div class="rule-label">去重</div>
              <label class="rule-check"><input type="checkbox" id="ruleDedup" onchange="CL_updateRules()"> 启用去重</label>
              <div id="dedupFieldsWrap" style="display:none;margin-top:8px">
                <div style="font-size:12px;color:#7a8a86;margin-bottom:6px">选择去重字段（不选则按全部字段）</div>
                <div class="dedup-field-grid" id="dedupFieldGrid"></div>
              </div>
            </div>
          </div>
          <div class="config-section" id="cleanActionSection" style="display:none">
            <button class="btn btn-primary" style="width:100%" onclick="CL_preview()">🔍 预览清洗结果</button>
          </div>
        </div>
        <div class="clean-preview-panel" id="cleanPreviewPanel">
          <div style="text-align:center;padding:60px;color:#7a8a86">
            <div style="font-size:40px;margin-bottom:12px">👁️</div>
            <div>选择数据源并配置规则后，点击"预览清洗结果"</div>
          </div>
        </div>
      </div>`;
  }

  // 数据源选择变化
  window.CL_onSourceChange = function(){
    const sid = parseInt($("cleanSourceSel").value);
    if(!sid){
      $("cleanRulesSection").style.display = "none";
      $("cleanActionSection").style.display = "none";
      return;
    }
    CL.selectedSource = CL.sources.find(s => s.id === sid);
    $("cleanRulesSection").style.display = "block";
    $("cleanActionSection").style.display = "block";
    // 渲染去重字段
    const cols = (CL.selectedSource.config && CL.selectedSource.config.columns) || [];
    if(cols.length === 0 && CL.selectedSource.sheet_names){
      // 尝试从预览获取字段
    }
    const grid = $("dedupFieldGrid");
    if(grid){
      grid.innerHTML = cols.map(c => `<label class="dedup-field-item"><input type="checkbox" value="${esc(c)}" onchange="CL_updateRules()"> ${esc(c)}</label>`).join("");
    }
  };

  // 更新规则
  window.CL_updateRules = function(){
    CL.rules = {
      format: {
        trim: $("ruleTrim")?.checked || false,
        uppercase: $("ruleUpper")?.checked || false,
        lowercase: $("ruleLower")?.checked || false,
      },
      null: {
        action: document.querySelector('input[name="nullAction"]:checked')?.value || "none",
        fill_value: $("nullFillValue")?.value || "",
      },
      dedup: {
        enabled: $("ruleDedup")?.checked || false,
        columns: Array.from(document.querySelectorAll("#dedupFieldGrid input:checked")).map(i => i.value),
      },
    };
    // 显示/隐藏去重字段
    const wrap = $("dedupFieldsWrap");
    if(wrap) wrap.style.display = CL.rules.dedup.enabled ? "block" : "none";
  };

  // 预览
  window.CL_preview = async function(){
    if(!CL.selectedSource){ toast("请选择数据源", "err"); return; }
    const panel = $("cleanPreviewPanel");
    panel.innerHTML = `<div style="text-align:center;padding:40px"><span class="spinner"></span><div style="margin-top:12px;color:#7a8a86">正在预览...</div></div>`;
    try{
      const r = await fetch("/api/clean/preview", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({source_id: CL.selectedSource.id, rules: CL.rules}),
      });
      const j = await r.json();
      if(j.ok){
        CL.previewData = j.data;
        renderPreview(j.data);
      } else {
        panel.innerHTML = `<div style="text-align:center;padding:40px;color:#e74c3c">预览失败：${esc(j.msg)}</div>`;
      }
    }catch(e){
      panel.innerHTML = `<div style="text-align:center;padding:40px;color:#e74c3c">预览失败：${esc(e.message)}</div>`;
    }
  };

  // 渲染预览
  function renderPreview(data){
    const stats = data.stats;
    const changes = stats.changes || [];
    const panel = $("cleanPreviewPanel");
    panel.innerHTML = `
      <div class="preview-stats">
        <div class="ps-item"><div class="ps-num">${stats.rows_before}</div><div class="ps-label">清洗前</div></div>
        <div class="ps-arrow">→</div>
        <div class="ps-item"><div class="ps-num">${stats.rows_after}</div><div class="ps-label">清洗后</div></div>
        <div class="ps-item"><div class="ps-num" style="color:${stats.rows_before-stats.rows_after>0?'#e74c3c':'#0f9d8f'}">${stats.rows_before-stats.rows_after}</div><div class="ps-label">变更行数</div></div>
      </div>
      <div class="preview-changes">
        <div style="font-weight:600;margin-bottom:6px">应用的规则：</div>
        ${changes.length > 0 ? changes.map(c => `<span class="change-tag">${esc(c)}</span>`).join("") : '<span style="color:#7a8a86">无变更</span>'}
      </div>
      <div class="preview-compare">
        <div class="compare-col">
          <div class="compare-title">清洗前（前20行）</div>
          <div class="compare-table-wrap">
            <table class="compare-table"><thead><tr>${data.columns.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead>
            <tbody>${data.before.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>
          </div>
        </div>
        <div class="compare-col">
          <div class="compare-title">清洗后（前20行）</div>
          <div class="compare-table-wrap">
            <table class="compare-table"><thead><tr>${data.columns.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead>
            <tbody>${data.after.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>
          </div>
        </div>
      </div>
      <div class="preview-action">
        <input type="text" id="cleanResultName" placeholder="结果数据源名称，留空自动命名" style="flex:1;padding:8px 12px;border:1px solid #cfdcd9;border-radius:8px;font-size:13px;font-family:inherit" value="${esc(CL.selectedSource.name)}_清洗后">
        <button class="btn btn-primary" onclick="CL_execute()">✅ 执行清洗并保存</button>
      </div>`;
  }

  // 执行清洗
  window.CL_execute = async function(){
    if(!CL.selectedSource){ toast("请选择数据源", "err"); return; }
    const resultName = $("cleanResultName")?.value.trim() || "";
    try{
      const r = await fetch("/api/clean/execute", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({source_id: CL.selectedSource.id, result_name: resultName, rules: CL.rules}),
      });
      const j = await r.json();
      if(j.ok){
        toast(`清洗完成！${j.data.row_count}行/${j.data.col_count}列`, "ok");
        CL_backToList();
      } else {
        toast(j.msg || "执行失败", "err");
      }
    }catch(e){
      toast("执行失败: " + e.message, "err");
    }
  };

  // 页面初始化
  window.CL_init = function(){
    loadTasks();
  };
})();
