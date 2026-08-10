const state = { config: null, statusLabels: {}, sources: [], materials: [], openPlatform: {} };

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
const setBusy = (ids, busy) => {
  for (const id of ids) {
    const node = document.getElementById(id);
    if (node) node.disabled = busy;
  }
};
async function withBusy(ids, fn) {
  setBusy(ids, true);
  try {
    return await fn();
  } finally {
    setBusy(ids, false);
  }
}

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

function workflowHint(status) {
  const hints = {
    RECEIVED: '已接收，等待质检',
    QUALITY_CHECKING: '质检中',
    TITLE_CHECKING: '质检通过，标题检查中',
    NEEDS_REVIEW: '需要人工复核',
    TAB_UNMAPPED: '质检/标题已过，等待栏目映射',
    READY_TO_CREATE: '栏目已匹配，可以创建草稿',
    DRAFT_CREATING: '正在创建草稿',
    DRAFT_CREATED: '草稿已创建',
    ALREADY_HAS_ARCHIVE: '上游已有文章',
    AUTH_REQUIRED: '需要重新授权',
    AUTH_EXPIRED: '授权已过期',
    CREATE_ERROR: '创建失败，可重试',
    REJECTED: '质检未通过',
  };
  return hints[status] || '状态待确认';
}

function humanSeconds(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  const seconds = Number(value);
  if (seconds < 0) return '已过期';
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))} 秒`;
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days} 天 ${hours % 24} 小时`;
  if (hours > 0) return `${hours} 小时 ${minutes % 60} 分`;
  return `${minutes} 分`;
}

async function loadConfig() {
  const data = await api('/api/config');
  state.config = data;
  state.statusLabels = data.status_labels || {};
  state.sources = data.sources || [];
  state.openPlatform = data.dqd?.auth || {};
  const key = data.material_api.key_configured;
  const dqdHeaders = data.dqd.headers_configured;
  $('#config-status').textContent = `素材 SK ${key ? '已配置' : '未配置'} · 草稿鉴权 ${dqdHeaders ? '已配置' : '待确认'} · 开放平台 ${state.openPlatform.auth_status_label || '未授权'} · 拉取后自动处理 ${data.pull_auto_process ? '开启' : '关闭'} · 草稿链接模板 ${data.dqd?.draft_url_template ? '已配置' : '未配置'}`;
  const statusSelect = $('#filter-status');
  statusSelect.innerHTML = '<option value="">全部状态</option>' + Object.entries(state.statusLabels).map(([key, label]) => `<option value="${key}">${label}</option>`).join('');
  const sourceSelect = $('#filter-source');
  sourceSelect.innerHTML = '<option value="">全部 source</option>' + state.sources.map((item) => `<option value="${escapeHtml(item.source)}">${escapeHtml(item.source)}</option>`).join('');
  renderSources();
  renderAuthPanel();
}

async function loadDashboard() {
  const data = await api('/api/dashboard');
  const counts = data.counts || {};
  const cards = [['总素材', data.total || 0, '']];
  Object.entries(state.statusLabels).forEach(([status, label]) => {
    cards.push([label, counts[status] || 0, status]);
  });
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

function renderAuthPanel() {
  const auth = state.openPlatform || {};
  const configured = state.config?.dqd?.appid_configured && state.config?.dqd?.appsecret_configured;
  const user = auth.authorized_user || {};
  const statusClass = auth.auth_status ? `status-${escapeHtml(auth.auth_status)}` : 'status-UNAUTHORIZED';
  const lastError = auth.last_error ? `<div class="auth-item" style="grid-column:1 / -1"><div class="label">最近错误</div><div class="value">${escapeHtml(auth.last_error)}</div></div>` : '';
  $('#auth-card').innerHTML = `
    <div class="auth-status-row">
      <span class="status-pill ${statusClass}">${escapeHtml(auth.auth_status_label || '未授权')}</span>
      <span class="muted">${configured ? 'AppID / AppSecret 已配置' : 'AppID / AppSecret 未配置'}</span>
      <span class="muted">回调：${escapeHtml(state.config?.dqd?.redirect_uri || '-')}</span>
    </div>
    <div class="auth-note">Access token 接近到期时会自动用 refresh token 续期；如果 refresh 失效，系统会把状态切回待授权。</div>
    <div class="auth-grid">
      <div class="auth-item"><div class="label">Access Token</div><div class="value">${auth.has_access_token ? '已保存' : '未保存'}</div></div>
      <div class="auth-item"><div class="label">Access 到期</div><div class="value">${humanSeconds(auth.expires_in_seconds)}</div></div>
      <div class="auth-item"><div class="label">Refresh Token</div><div class="value">${auth.has_refresh_token ? '已保存' : '未保存'}</div></div>
      <div class="auth-item"><div class="label">Refresh 到期</div><div class="value">${humanSeconds(auth.refresh_expires_in_seconds)}</div></div>
      <div class="auth-item"><div class="label">授权用户</div><div class="value">${escapeHtml(user.username || user.user_name || user.user_id || '-')}</div></div>
      <div class="auth-item"><div class="label">用户 ID</div><div class="value">${escapeHtml(user.user_id || '-')}</div></div>
      <div class="auth-item"><div class="label">pending state</div><div class="value">${escapeHtml(auth.pending_state || '-')}</div></div>
      <div class="auth-item"><div class="label">上次授权 URL</div><div class="value">${escapeHtml(auth.last_authorize_url || '-')}</div></div>
      ${lastError}
    </div>`;
}

async function loadMaterials() {
  const params = new URLSearchParams({ status: $('#filter-status').value, source: $('#filter-source').value, search: $('#filter-search').value, limit: '100' });
  const data = await api(`/api/materials?${params}`);
  state.materials = data.items || [];
  $('#empty').classList.toggle('hidden', state.materials.length > 0);
  $('#materials').innerHTML = state.materials.map((item) => `<tr>
    <td><div class="status-stack"><span class="status-pill status-${escapeHtml(item.status)}">${escapeHtml(item.status_label)}</span><small class="stage-hint">${escapeHtml(workflowHint(item.status))}</small></div></td>
    <td class="title-cell"><strong>${escapeHtml(item.title_final || item.title_original || '无标题')}</strong>${item.title_final && item.title_final !== item.title_original ? `<small>原题：${escapeHtml(item.title_original)}</small>` : ''}<small class="url">${escapeHtml(item.source_url)}</small></td>
    <td class="source-cell"><strong>${escapeHtml(item.source)}</strong><small>tab: ${state.sources.find((source) => source.source === item.source)?.tab_id ?? '未配置'}</small></td>
    <td class="channels">${item.channels?.length ? escapeHtml(item.channels.join(', ')) : '<span class="muted">无标签</span>'}</td>
    <td><span class="key">${escapeHtml(item.material_key)}</span><small class="url">更新 ${escapeHtml((item.updated_at || '').replace('T', ' ').slice(0, 16))}</small></td>
    <td><div class="row-actions"><button class="button detail" data-id="${item.id}">详情</button>${item.draft_url ? `<a class="button small primary" href="${escapeHtml(item.draft_url)}" target="_blank" rel="noreferrer">打开草稿</a>` : ''}${['RECEIVED','CREATE_ERROR','TAB_UNMAPPED'].includes(item.status) ? `<button class="button process" data-id="${item.id}">重新处理</button>` : ''}${['READY_TO_CREATE','CREATE_ERROR','AUTH_REQUIRED','AUTH_EXPIRED'].includes(item.status) ? `<button class="button primary draft" data-id="${item.id}">${['AUTH_REQUIRED','AUTH_EXPIRED'].includes(item.status) ? '重试创建' : '创建草稿'}</button>` : ''}</div></td>
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

async function runAction(path, body, success, buttonIds = []) {
  try {
    return await withBusy(buttonIds, async () => {
      const result = await api(path, { method: 'POST', body: JSON.stringify(body || {}) });
      await refresh();
      toast(success);
      return result;
    });
  } catch (error) {
    toast(error.message, true);
  }
}
async function processOne(id, create) { await runAction(`/api/materials/${id}/process`, { create }, create ? '处理并创建草稿完成' : '素材处理完成'); }
async function createOne(id) { await runAction(`/api/materials/${id}/create-draft`, {}, '草稿创建请求已完成'); }

async function openDetail(id) {
  try {
    const data = await api(`/api/materials/${id}`); const item = data.item;
    $('#drawer-title').textContent = item.title_final || item.title_original || '素材详情';
    const quality = JSON.stringify(item.quality || {}, null, 2);
    const titleCheck = JSON.stringify(item.title_check || {}, null, 2);
    const draftUrlNode = item.draft_url ? `<a href="${escapeHtml(item.draft_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.draft_url)}</a>` : '<span class="muted">尚未创建</span>';
    const draftIdNode = item.dqd_archive_id ? (item.draft_url ? `<a href="${escapeHtml(item.draft_url)}" target="_blank" rel="noreferrer">${item.dqd_archive_id}</a>` : String(item.dqd_archive_id)) : '尚未创建';
    const bodyPreview = item.body_html ? escapeHtml(item.body_html) : '<span class="muted">正文为空</span>';
    $('#drawer-body').innerHTML = `<div class="detail-block"><h3>状态</h3><div class="detail-grid"><dt>当前状态</dt><dd><span class="status-pill status-${escapeHtml(item.status)}">${escapeHtml(item.status_label)}</span></dd><dt>当前阶段</dt><dd>${escapeHtml(workflowHint(item.status))}</dd><dt>等级</dt><dd>B（系统固定）</dd><dt>source</dt><dd>${escapeHtml(item.source)}</dd><dt>后台栏目</dt><dd>${item.source_config?.tab_id ?? '未配置'} ${escapeHtml(item.source_config?.tab_name || '')}</dd><dt>上游 archive_id</dt><dd>${item.upstream_archive_id || 0}</dd><dt>草稿 archive_id</dt><dd>${draftIdNode}</dd><dt>草稿链接</dt><dd>${draftUrlNode}</dd></div></div>
      <div class="detail-block"><h3>主键与来源</h3><div class="detail-grid"><dt>material_key</dt><dd>${escapeHtml(item.material_key)}</dd><dt>规范化 URL</dt><dd>${escapeHtml(item.canonical_url)}</dd><dt>source_url</dt><dd><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_url)}</a></dd></div></div>
      <div class="detail-block"><h3>标签 ID</h3><div class="json">${escapeHtml(JSON.stringify(item.channels || []))}</div></div>
      <div class="detail-block"><h3>质量检测</h3><div class="json">${escapeHtml(quality)}</div></div>
      <div class="detail-block"><h3>标题检查</h3><div class="json">${escapeHtml(titleCheck)}</div></div>
      <div class="detail-block"><h3>正文</h3><div class="body-preview">${bodyPreview}</div></div>
      <div class="detail-block"><h3>状态时间线</h3><div class="timeline">${(item.events || []).map((event) => `<div class="event"><b>${escapeHtml(event.to_status_label)}</b><span> · ${escapeHtml(event.event_type)}</span><time>${escapeHtml(event.created_at)}</time>${Object.keys(event.detail || {}).length ? `<div class="json">${escapeHtml(JSON.stringify(event.detail, null, 2))}</div>` : ''}</div>`).join('')}</div></div>`;
    $('#drawer').classList.remove('hidden'); $('#drawer').setAttribute('aria-hidden', 'false');
  } catch (error) { toast(error.message, true); }
}

async function startAuthorization() {
  try {
    const result = await withBusy(['auth-start-btn'], async () => {
      const response = await api('/api/open/auth/start', { method: 'POST', body: JSON.stringify({}) });
      await refresh();
      return response;
    });
    toast('已打开开放平台授权页');
    const opened = window.open(result.authorize_url, '_blank', 'noopener');
    if (!opened) window.location.href = result.authorize_url;
  } catch (error) {
    toast(error.message, true);
  }
}

async function refreshAuthorization() {
  await runAction('/api/open/auth/refresh', {}, '开放平台 token 已刷新', ['auth-refresh-btn']);
}

async function resetAuthorization() {
  if (!window.confirm('确定清除当前开放平台授权吗？')) return;
  await runAction('/api/open/auth/reset', {}, '开放平台授权已清除', ['auth-reset-btn']);
}

async function refresh() {
  await loadConfig();
  await Promise.all([loadDashboard(), loadMaterials()]);
}

$('#new-source-btn').addEventListener('click', () => { resetSourceForm(); $('#source-form').classList.remove('hidden'); $('#source-value').focus(); });
$('#cancel-source-btn').addEventListener('click', resetSourceForm);
$('#source-form').addEventListener('submit', saveSource);
$('#close-drawer').addEventListener('click', () => { $('#drawer').classList.add('hidden'); $('#drawer').setAttribute('aria-hidden', 'true'); });
$('#refresh-btn').addEventListener('click', () => refresh().catch((error) => toast(error.message, true)));
$('#auth-start-btn').addEventListener('click', startAuthorization);
$('#auth-refresh-btn').addEventListener('click', refreshAuthorization);
$('#auth-reset-btn').addEventListener('click', resetAuthorization);
$('#filter-status').addEventListener('change', () => loadMaterials().catch((error) => toast(error.message, true)));
$('#filter-source').addEventListener('change', () => loadMaterials().catch((error) => toast(error.message, true)));
let searchTimer; $('#filter-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadMaterials().catch((error) => toast(error.message, true)), 250); });
$('#pull-btn').addEventListener('click', async () => { const hours = window.prompt('拉取最近几小时？', 6); if (hours === null) return; await runAction('/api/pull', { hours: Number(hours), limit: 100, process: false }, '仅拉取完成', ['pull-btn']); });
$('#pull-create-btn').addEventListener('click', async () => { const hours = window.prompt('拉取最近几小时并创建草稿？', 6); if (hours === null) return; await runAction('/api/pull', { hours: Number(hours), limit: 100, process: true, create: true }, '素材已拉取，并已进入自动处理/创建草稿流程', ['pull-create-btn']); });
$('#process-btn').addEventListener('click', () => runAction('/api/process', { limit: 50, create: false }, '待处理素材已完成检查', ['process-btn']));
$('#draft-btn').addEventListener('click', () => runAction('/api/process', { limit: 50, create: true }, '批量创建草稿已完成', ['draft-btn']));
window.setInterval(() => refresh().catch(() => {}), 15000);
refresh().catch((error) => toast(error.message, true));
