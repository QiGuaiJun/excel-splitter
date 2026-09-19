// 运行历史模块
(function(){
  const LOG = { page:1, page_size:20, status:"", total:0, total_pages:1, list:[] };

  function $(id){ return document.getElementById(id); }
  function esc(s){ if(s==null) return ""; const d=document.createElement("div"); d.textContent=s; return d.innerHTML; }
  function toast(msg, type){ const t=document.createElement("div"); t.className="toast "+(type||"ok"); t.textContent=msg; document.body.appendChild(t); setTimeout(()=>t.remove(),2500); }

  // 加载统计
  async function loadStats(){
    try{
      const r = await fetch("/api/logs/stats");
      const j = await r.json();
      if(j.ok){
        const s = j.data;
        const el = $("logStats");
        if(el){
          el.innerHTML = `
            <div class="stat-card">
              <div class="stat-num">${s.total}</div>
              <div class="stat-label">近7天总次数</div>
            </div>
            <div class="stat-card success">
              <div class="stat-num">${s.success}</div>
              <div class="stat-label">成功</div>
            </div>
            <div class="stat-card failed">
              <div class="stat-num">${s.failed}</div>
              <div class="stat-label">失败</div>
            </div>
            <div class="stat-card">
              <div class="stat-num">${s.avg_duration}<span style="font-size:14px">ms</span></div>
              <div class="stat-label">平均耗时</div>
            </div>`;
        }
      }
    }catch(e){ console.error("加载统计失败", e); }
  }

  // 加载日志列表
  async function loadLogs(){
    const params = new URLSearchParams({
      page: LOG.page, page_size: LOG.page_size,
    });
    if(LOG.status) params.append("status", LOG.status);
    try{
      const r = await fetch("/api/logs?" + params.toString());
      const j = await r.json();
      if(j.ok){
        LOG.list = j.data;
        LOG.total = j.pagination.total;
        LOG.total_pages = j.pagination.total_pages;
        renderList();
        renderPagination();
      }
    }catch(e){ toast("加载日志失败", "err"); }
  }

  // 渲染列表
  function renderList(){
    const el = $("logList");
    if(!el) return;
    if(LOG.list.length === 0){
      el.innerHTML = `<div style="text-align:center;padding:40px;color:var(--faint)">暂无运行记录</div>`;
      return;
    }
    el.innerHTML = LOG.list.map(log => {
      const statusCls = log.status === "success" ? "status-ok" : "status-err";
      const statusText = log.status === "success" ? "成功" : "失败";
      const channelMap = {excel:"Excel", folder:"文件夹", crawler:"代码爬取", database:"数据库", distribute:"分发"};
      const channelText = channelMap[log.source_channel] || log.source_channel || "-";
      return `
        <div class="log-row" onclick="LOG_showDetail(${log.id})">
          <div class="log-time">${esc(log.created_at)}</div>
          <div class="log-source">${esc(log.source_name || "未知数据源")}</div>
          <div class="log-channel"><span class="channel-tag">${esc(channelText)}</span></div>
          <div class="log-status"><span class="${statusCls}">${statusText}</span></div>
          <div class="log-rows">${log.row_count || 0} 行</div>
          <div class="log-duration">${log.duration_ms || 0} ms</div>
        </div>`;
    }).join("");
  }

  // 渲染分页
  function renderPagination(){
    const el = $("logPagination");
    if(!el) return;
    if(LOG.total_pages <= 1){ el.innerHTML = ""; return; }
    el.innerHTML = `
      <div class="pg-info">共 ${LOG.total} 条，第 ${LOG.page}/${LOG.total_pages} 页</div>
      <div class="pg-controls">
        <select class="pg-size" onchange="LOG_changePageSize(this.value)">
          <option value="20" ${LOG.page_size===20?"selected":""}>每页20条</option>
          <option value="50" ${LOG.page_size===50?"selected":""}>每页50条</option>
          <option value="100" ${LOG.page_size===100?"selected":""}>每页100条</option>
        </select>
        <button class="btn btn-ghost pg-btn" onclick="LOG_goPage(${LOG.page-1})" ${LOG.page<=1?"disabled":""}>上一页</button>
        <button class="btn btn-ghost pg-btn" onclick="LOG_goPage(${LOG.page+1})" ${LOG.page>=LOG.total_pages?"disabled":""}>下一页</button>
      </div>`;
  }

  // 显示详情
  window.LOG_showDetail = async function(logId){
    try{
      const r = await fetch("/api/logs/" + logId);
      const j = await r.json();
      if(j.ok){
        const log = j.data;
        const statusText = log.status === "success" ? "成功" : "失败";
        const statusCls = log.status === "success" ? "status-ok" : "status-err";
        $("logDetailBody").innerHTML = `
          <div class="detail-grid">
            <div class="detail-item"><label>日志ID</label><span>${log.id}</span></div>
            <div class="detail-item"><label>状态</label><span class="${statusCls}">${statusText}</span></div>
            <div class="detail-item"><label>数据源</label><span>${esc(log.source_name || "-")}</span></div>
            <div class="detail-item"><label>采集通道</label><span>${esc(log.source_channel || "-")}</span></div>
            <div class="detail-item"><label>行数</label><span>${log.row_count || 0}</span></div>
            <div class="detail-item"><label>耗时</label><span>${log.duration_ms || 0} ms</span></div>
            <div class="detail-item"><label>创建时间</label><span>${esc(log.created_at)}</span></div>
          </div>
          ${log.error_msg ? `
            <div style="margin-top:16px">
              <label style="font-weight:600;color:#c0392b">错误信息</label>
              <div style="margin-top:8px;padding:12px;background:#fdf0ef;border:1px solid #f5c6c2;border-radius:8px;font-family:Consolas,monospace;font-size:12px;color:#c0392b;white-space:pre-wrap;max-height:200px;overflow:auto">${esc(log.error_msg)}</div>
            </div>` : ""}
          <div style="margin-top:16px;text-align:right">
            <button class="btn btn-ghost" onclick="LOG_closeDetail()">关闭</button>
          </div>`;
        showModal("logDetailModal");
      }
    }catch(e){ toast("加载详情失败", "err"); }
  };

  window.LOG_closeDetail = function(){ hideModal("logDetailModal"); };
  window.LOG_goPage = function(p){ if(p<1||p>LOG.total_pages) return; LOG.page=p; loadLogs(); };
  window.LOG_changePageSize = function(sz){ LOG.page_size=parseInt(sz); LOG.page=1; loadLogs(); };
  window.LOG_filterStatus = function(s){ LOG.status=s; LOG.page=1; loadLogs(); };
  window.LOG_refresh = function(){ loadStats(); loadLogs(); };

  // 页面初始化
  window.LOG_init = function(){
    loadStats();
    loadLogs();
  };
})();
