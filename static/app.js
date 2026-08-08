const state = { config: null, statusLabels: {}, sources: [], materials: [] };

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function toast(message, error = false) {
  const node = $('#toast');
  node.textContent = message;
  node.style.background = error ? '#b23b45' : '#17212b';
  node.classList.add('show');
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove('show'), 3000);
}

function statusLabel(status) { return state.statusLabels[status] || status || '-'; }

async function loadConfig() {
  const data = await api('/api/config');
  state.config = data;
  state.statusLabels = data.status_labels || {};
  state.sources = data.sources || [];
  const key = data.material_api.key_configured;
  const dqdHeaders = data.dqd.headers_configured;
  $('#config-status').textContent = `素材 SK ${key ? '已配置' : '未配置'} · 草稿鉴权 ${dqdHeaders ? '已配置' : '待确认'}`;
  const statusSelect = $('#filter-status');
  statusSelect.innerHTML = '<option value="">全部状态</option>' + Object.entries(state.statusLabels).map(([key, label]) => `<option value="${key}">${label}</option>`).join('');
  const sourceSelect = $('#filter-source');
  sourceSelect.innerHTML = '<option value="">全部 source</option>' + state.sources.map((item) => `<option value="${escapeHtml(item.source)}">${escapeHtml(item.source)}</option>`).join('');
  renderSources();
}

async function loadDashboard() {
  const data = await api('/api/dashboard');
  const counts = data.counts || {};
  const cards = [
    ['总素材', data.total || 0, ''], ['已接收', counts.RECEIVED || 0, 'RECEIVED'], ['待复核', counts.NEEDS_REVIEW || 0, 'NEEDS_REVIEW'],
    ['待创建草稿', counts.READY_TO_CREATE || 0, 'READY_TO_CREATE'], ['栏目未配置', counts.TAB_UNMAPPED || 0, 'TAB_UNMAPPED'], ['草稿已创建', counts.DRAFT_CREATED || 0, 'DRAFT_CREATED'],
  ];
  $('#metrics').innerHTML = cards.map(([label, value, status]) => `<button class="metric ${status ? 'metric-button' : ''}" ${status ? `data-status="${status}"` : ''}><div class="label">${label}</div><div class="value">${value}</div><div class="label">${status ? status : '当前数据库'}</div></button>`).join('');
  document.querySelectorAll('.metric-button').forEach((node) => node.addEventListener('click', () => { $('#filter-status').value = node.dataset.status; loadMaterials(); }));
  renderRuns(data.runs || []);
}

function renderSources() {
  const node = $('#sources');
  if (!state.sources.length) { node.innerHTML = '<div class="empty">尚未配置 source</div>'; return; }
  node.innerHTML = state.sources.map((item) => `<div class="source-row">
    <div class="source-main"><strong>${escapeHtml(item.source)}</strong><span>${escapeHtml(item.display_name || '未设置名称')}</span></div>
    <div class="source-meta"><b>${item.tab_id ?? '未配置'}</b><br>${escapeHtml(item.tab_name || '后台栏目 ID')}</div>
    <div class="source-meta">${item.enabled ? '启用拉取' : '已停用'}</div>
    <div class="source-actions"><button class="button small edit-source" data-source="${escapeHtml(item.source)}">编辑</button></div>
  </div>`).join('');
  document.querySelectorAll('.edit-source').forEach((button) => button.addEventListener('click', () => editSource(button.dataset.source)));
}

function renderRuns(runs) {
  $('#runs').innerHTML = runs.length ? runs.map((run) => `<div class="run-row"><span>${escapeHtml((run.started_at || '').replace('T', ' ').slice(0, 16))}</span><span><b>${escapeHtml((run.requested_sources || []).join(', ') || '-')}</b><span class="run-count"> 拉取 ${run.fetched_count} · 新增 ${run.inserted_count} · 更新 ${run.updated_count}</span></span><span class="status-pill ${run.status === 'FAILED' ? 'status-REJECTED' : ''}">${escapeHtml(run.status)}</span></div>`).join('') : '<div class="empty">暂无拉取记录</div>';
}

async function loadMaterials() {
  const params = new URLSearchParams({ status: $('#filter-status').value, source: $('#filter-source').value, search: $('#filter-search').value, limit: '100' });
  const data = await api(`/api/materials?${params}`);
  state.materials = data.items || [];
  $('#empty').classList.toggle('hidden', state.materials.length > 0);
  $('#materials').innerHTML = state.materials.map((item) => `<tr>
    <td><span class="status-pill status-${escapeHtml(item.status)}">${escapeHtml(item.status_label)}</span></td>
    <td class="title-cell"><strong>${escapeHtml(item.title_final || item.title_original || '无标题')}</strong>${item.title_final && item.title_final !== item.title_original ? `<small>原题：${escapeHtml(item.title_original)}</small>` : ''}<small class="url">${escapeHtml(item.source_url)}</small></td>
    <td class="source-cell"><strong>${escapeHtml(item.source)}</strong><small>tab: ${state.sources.find((source) => source.source === item.source)?.tab_id ?? '未配置'}</small></td>
    <td class="channels">${item.channels?.length ? escapeHtml(item.channels.join(', ')) : '<span class="muted">无标签</span>'}</td>
    <td><span class="key">${escapeHtml(item.material_key)}</span><small class="url">更新 ${escapeHtml((item.updated_at || '').replace('T', ' ').slice(0, 16))}</small></td>
    <td><div class="row-actions"><button class="button detail" data-id="${item.id}">详情</button>${['RECEIVED','CREATE_ERROR','TAB_UNMAPPED'].includes(item.status) ? `<button class="button process" data-id="${item.id}">处理</button>` : ''}${item.status === 'READY_TO_CREATE' ? `<button class="button primary draft" data-id="${item.id}">建草稿</button>` : ''}</div></td>
  </tr>`).join('');
  document.querySelectorAll('.detail').forEach((button) => button.addEventListener('click', () => openDetail(button.dataset.id)));
  document.querySelectorAll('.process').forEach((button) => button.addEventListener('click', () => processOne(button.dataset.id, false)));
  document.querySelectorAll('.draft').forEach((button) => button.addEventListener('click', () => createOne(button.dataset.id)));
}

function editSource(source) {
  const item = state.sources.find((row) => row.source === source);
  if (!item) return;
  $('#source-original').value = item.source;
  $('#source-value').value = item.source;
  $('#source-value').readOnly = true;
  $('#source-name').value = item.display_name || '';
  $('#source-tab').value = item.tab_id ?? '';
  $('#source-tab-name').value = item.tab_name || '';
  $('#source-enabled').checked = !!item.enabled;
  $('#source-form').classList.remove('hidden');
  $('#source-value').focus();
}

function resetSourceForm() {
  $('#source-original').value = ''; $('#source-value').value = ''; $('#source-value').readOnly = false; $('#source-name').value = ''; $('#source-tab').value = ''; $('#source-tab-name').value = ''; $('#source-enabled').checked = true; $('#source-form').classList.add('hidden');
}

async function saveSource(event) {
  event.preventDefault();
  try {
    await api('/api/sources', { method: 'POST', body: JSON.stringify({ source: $('#source-value').value, display_name: $('#source-name').value, tab_id: $('#source-tab').value || null, tab_name: $('#source-tab-name').value, enabled: $('#source-enabled').checked }) });
    resetSourceForm(); await refresh(); toast('source 栏目配置已保存');
  } catch (error) { toast(error.message, true); }
}

async function runAction(path, body, success) {
  try { const result = await api(path, { method: 'POST', body: JSON.stringify(body || {}) }); await refresh(); toast(success); return result; } catch (error) { toast(error.message, true); }
}
async function processOne(id, create) { await runAction(`/api/materials/${id}/process`, { create }, create ? '处理并创建草稿完成' : '素材处理完成'); }
async function createOne(id) { await runAction(`/api/materials/${id}/create-draft`, {}, '草稿创建请求已完成'); }

async function openDetail(id) {
  try {
    const data = await api(`/api/materials/${id}`); const item = data.item;
    $('#drawer-title').textContent = item.title_final || item.title_original || '素材详情';
    const quality = JSON.stringify(item.quality || {}, null, 2);
    const titleCheck = JSON.stringify(item.title_check || {}, null, 2);
    $('#drawer-body').innerHTML = `<div class="detail-block"><h3>状态</h3><div class="detail-grid"><dt>当前状态</dt><dd><span class="status-pill status-${escapeHtml(item.status)}">${escapeHtml(item.status_label)}</span></dd><dt>等级</dt><dd>B（系统固定）</dd><dt>source</dt><dd>${escapeHtml(item.source)}</dd><dt>后台栏目</dt><dd>${item.source_config?.tab_id ?? '未配置'} ${escapeHtml(item.source_config?.tab_name || '')}</dd><dt>上游 archive_id</dt><dd>${item.upstream_archive_id || 0}</dd><dt>草稿 archive_id</dt><dd>${item.dqd_archive_id || '尚未创建'}</dd></div></div>
      <div class="detail-block"><h3>主键与来源</h3><div class="detail-grid"><dt>material_key</dt><dd>${escapeHtml(item.material_key)}</dd><dt>规范化 URL</dt><dd>${escapeHtml(item.canonical_url)}</dd><dt>source_url</dt><dd><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_url)}</a></dd></div></div>
      <div class="detail-block"><h3>标签 ID</h3><div class="json">${escapeHtml(JSON.stringify(item.channels || []))}</div></div>
      <div class="detail-block"><h3>质量检测</h3><div class="json">${escapeHtml(quality)}</div></div>
      <div class="detail-block"><h3>标题检查</h3><div class="json">${escapeHtml(titleCheck)}</div></div>
      <div class="detail-block"><h3>正文</h3><div class="body-preview">${item.body_html || '<span class="muted">正文为空</span>'}</div></div>
      <div class="detail-block"><h3>状态时间线</h3><div class="timeline">${(item.events || []).map((event) => `<div class="event"><b>${escapeHtml(event.to_status_label)}</b><span> · ${escapeHtml(event.event_type)}</span><time>${escapeHtml(event.created_at)}</time>${Object.keys(event.detail || {}).length ? `<div class="json">${escapeHtml(JSON.stringify(event.detail, null, 2))}</div>` : ''}</div>`).join('')}</div></div>`;
    $('#drawer').classList.remove('hidden'); $('#drawer').setAttribute('aria-hidden', 'false');
  } catch (error) { toast(error.message, true); }
}

async function refresh() { await Promise.all([loadConfig(), loadDashboard(), loadMaterials()]); }

$('#new-source-btn').addEventListener('click', () => { resetSourceForm(); $('#source-form').classList.remove('hidden'); $('#source-value').focus(); });
$('#cancel-source-btn').addEventListener('click', resetSourceForm);
$('#source-form').addEventListener('submit', saveSource);
$('#close-drawer').addEventListener('click', () => { $('#drawer').classList.add('hidden'); $('#drawer').setAttribute('aria-hidden', 'true'); });
$('#refresh-btn').addEventListener('click', () => refresh().catch((error) => toast(error.message, true)));
$('#filter-status').addEventListener('change', () => loadMaterials().catch((error) => toast(error.message, true)));
$('#filter-source').addEventListener('change', () => loadMaterials().catch((error) => toast(error.message, true)));
let searchTimer; $('#filter-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadMaterials().catch((error) => toast(error.message, true)), 250); });
$('#pull-btn').addEventListener('click', async () => { const hours = window.prompt('拉取最近几小时？', 6); if (hours === null) return; await runAction('/api/pull', { hours: Number(hours), limit: 100, process: false }, '素材拉取完成'); });
$('#process-btn').addEventListener('click', () => runAction('/api/process', { limit: 50, create: false }, '待处理素材已完成检查'));
$('#draft-btn').addEventListener('click', () => runAction('/api/process', { limit: 50, create: true }, '待处理素材已尝试创建草稿'));
window.setInterval(() => refresh().catch(() => {}), 15000);
refresh().catch((error) => toast(error.message, true));
