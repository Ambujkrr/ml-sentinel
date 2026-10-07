const $ = (selector) => document.querySelector(selector);
const state = { models: [], datasets: [], runs: [], alerts: [], modelId: null, currentRun: null };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`);
  }
  return body;
}

function flash(message, isError = false) {
  const element = $('#flash');
  element.hidden = false;
  element.textContent = message;
  element.classList.toggle('error', isError);
  clearTimeout(flash.timer);
  flash.timer = setTimeout(() => { element.hidden = true; }, 6500);
}

function badge(status) {
  const safe = ['healthy', 'warning', 'critical', 'resolved', 'insufficient_data', 'incompatible'];
  return `<span class="badge ${safe.includes(status) ? status : 'insufficient_data'}">${escapeHtml(status || 'unknown')}</span>`;
}

function date(value) {
  return value ? new Date(value).toLocaleString() : '—';
}

function decimal(value, digits = 3) {
  return typeof value === 'number' ? value.toFixed(digits) : '—';
}

function table(headers, rows, emptyMessage) {
  if (!rows.length) return `<div class="empty">${escapeHtml(emptyMessage)}</div>`;
  return `<table class="data-table"><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
}

async function refresh(keepModel = true) {
  try {
    const [models, runs, alerts] = await Promise.all([
      api('/models?limit=200'), api('/monitoring/runs?limit=200'), api('/alerts?limit=200')
    ]);
    state.models = models; state.runs = runs; state.alerts = alerts;
    if (!keepModel || !models.some((model) => model.id === state.modelId)) {
      state.modelId = models[0]?.id ?? null;
    }
    $('#model-select').innerHTML = models.length
      ? models.map((model) => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)} · ${escapeHtml(model.model_version)}</option>`).join('')
      : '<option value="">No models yet</option>';
    $('#model-select').value = state.modelId || '';
    await loadModel();
    $('#stat-models').textContent = models.length;
    $('#stat-runs').textContent = runs.length;
    $('#stat-alerts').textContent = alerts.filter((alert) => !alert.resolved_at).length;
    renderRuns();
    renderAlerts();
  } catch (error) {
    flash(`${error.message} Check that the database is running and migrations have been applied.`, true);
  }
}

async function loadModel() {
  const model = state.models.find((item) => item.id === state.modelId);
  state.datasets = model ? await api(`/models/${model.id}/datasets?limit=200`) : [];
  $('#stat-datasets').textContent = state.datasets.length;
  $('#model-summary').textContent = model
    ? `${model.name} · Version ${model.model_version} · ${model.description || 'No description'}`
    : 'Register a model to get started.';
  $('#dataset-list').innerHTML = table(['DATASET', 'TYPE', 'ROWS', 'COLUMNS', 'UPLOADED', 'QUALITY'],
    state.datasets.map((dataset) => `<tr><td>${escapeHtml(dataset.name)}</td><td>${badge(dataset.dataset_type)}</td><td>${dataset.row_count}</td><td>${dataset.column_count}</td><td>${date(dataset.created_at)}</td><td><button data-profile="${dataset.id}">View report</button></td></tr>`),
    'No datasets uploaded for this model.');
  for (const [selector, type] of [['#reference-select', 'reference'], ['#production-select', 'production']]) {
    const items = state.datasets.filter((dataset) => dataset.dataset_type === type);
    $(selector).innerHTML = items.length
      ? items.map((dataset) => `<option value="${dataset.id}">${escapeHtml(dataset.name)} (${dataset.row_count} rows)</option>`).join('')
      : `<option value="">No ${type} dataset</option>`;
  }
}

function renderRuns() {
  const selected = state.runs.filter((run) => run.model_id === state.modelId);
  $('#run-list').innerHTML = table(['DATE', 'STATUS', 'FEATURES DRIFTED', 'BASELINE', 'PRODUCTION', 'DETAILS'],
    selected.map((run) => {
      const ref = state.datasets.find((item) => item.id === run.reference_dataset_id);
      const prod = state.datasets.find((item) => item.id === run.production_dataset_id);
      return `<tr><td>${date(run.created_at)}</td><td>${badge(run.overall_status)}</td><td>${run.drifted_feature_count} / ${run.total_feature_count}</td><td>${escapeHtml(ref?.name || run.reference_dataset_id.slice(0, 8))}</td><td>${escapeHtml(prod?.name || run.production_dataset_id.slice(0, 8))}</td><td><button data-run="${run.id}">Inspect run</button></td></tr>`;
    }), 'No monitoring runs for this model yet.');
}

function renderAlerts() {
  const selected = state.alerts.filter((alert) => alert.model_id === state.modelId);
  $('#alert-list').innerHTML = table(['DATE', 'SEVERITY', 'TYPE', 'MESSAGE', 'STATE'],
    selected.map((alert) => `<tr><td>${date(alert.created_at)}</td><td>${badge(alert.severity)}</td><td>${escapeHtml(alert.alert_type.replaceAll('_', ' '))}</td><td>${escapeHtml(alert.message)}</td><td>${alert.resolved_at ? badge('resolved') : `<button data-resolve="${alert.id}">Resolve</button>`}</td></tr>`),
    'No alerts for this model.');
}

async function showProfile(datasetId) {
  try {
    const [profile, quality] = await Promise.all([
      api(`/datasets/${datasetId}/profile`), api(`/datasets/${datasetId}/quality`)
    ]);
    const dataset = state.datasets.find((item) => item.id === datasetId);
    const columns = profile.columns.map((column) => `<tr><td>${escapeHtml(column.name)}</td><td>${escapeHtml(column.type)}</td><td>${column.missing_count} (${decimal(column.missing_percentage, 1)}%)</td><td>${column.unique_count}</td><td>${decimal(column.statistics?.mean)}</td><td>${column.statistics?.outlier_count ?? '—'}</td></tr>`);
    $('#detail-section').hidden = false;
    $('#detail-title').textContent = `Dataset: ${dataset?.name || datasetId}`;
    $('#detail-subtitle').textContent = `${profile.row_count} rows · ${profile.column_count} columns · Profiled at upload`;
    $('#detail-status').innerHTML = badge(quality.status);
    $('#detail-summary').innerHTML = `<div class="detail-card"><span>ROWS</span><strong>${profile.row_count}</strong></div><div class="detail-card"><span>COLUMNS</span><strong>${profile.column_count}</strong></div><div class="detail-card"><span>DUPLICATE ROWS</span><strong>${quality.duplicate_row_count}</strong></div>`;
    $('#schema-panel').innerHTML = quality.issues.length
      ? `<div class="note-block">${quality.issues.map((issue) => `${escapeHtml(issue.message)} (${escapeHtml(issue.severity)})`).join('<br>')}</div>`
      : '<div class="note-block">No data quality issues found.</div>';
    $('#feature-panel').innerHTML = table(['COLUMN', 'TYPE', 'MISSING', 'UNIQUE', 'MEAN', 'IQR OUTLIERS'], columns, 'No columns.');
    $('#performance-panel').innerHTML = '';
    $('#feature-select').innerHTML = '';
    $('#chart').innerHTML = '<div class="empty">Distribution comparisons appear on monitoring runs.</div>';
    $('#detail-section').scrollIntoView({ behavior: 'smooth' });
  } catch (error) { flash(error.message, true); }
}

async function showRun(runId) {
  try {
    const run = await api(`/monitoring/runs/${runId}`);
    state.currentRun = run;
    const report = run.report;
    $('#detail-section').hidden = false;
    $('#detail-title').textContent = 'Monitoring run details';
    $('#detail-subtitle').textContent = `${date(run.created_at)} · ${report.summary}`;
    $('#detail-status').innerHTML = badge(run.overall_status);
    const perf = report.performance;
    $('#detail-summary').innerHTML = `<div class="detail-card"><span>FEATURES DRIFTED</span><strong>${run.drifted_feature_count} / ${run.total_feature_count}</strong></div><div class="detail-card"><span>SCHEMA CHANGES</span><strong>${report.schema_changes.missing_columns.length + report.schema_changes.unexpected_columns.length + report.schema_changes.type_changes.length}</strong></div><div class="detail-card"><span>PRODUCTION MACRO F1</span><strong>${decimal(perf?.production_metrics?.f1)}</strong></div>`;
    $('#performance-panel').innerHTML = perf
      ? `<div class="note-block">Classification performance: ${badge(perf.status)} Baseline F1 ${decimal(perf.reference_metrics?.f1)} → production F1 ${decimal(perf.production_metrics?.f1)}. ${escapeHtml(perf.reason || '')}</div>`
      : '<div class="note-block">Performance was not requested for this run.</div>';
    const schema = report.schema_changes;
    const changes = [...schema.missing_columns.map((name) => `Missing: ${name}`),
      ...schema.unexpected_columns.map((name) => `New: ${name}`),
      ...schema.type_changes.map((change) => `${change.column}: ${change.reference_type} → ${change.production_type}`)];
    $('#schema-panel').innerHTML = changes.length
      ? `<div class="note-block">${changes.map(escapeHtml).join('<br>')}</div>`
      : '<div class="note-block">No schema changes detected.</div>';
    const features = [...report.features, ...(report.prediction_drift ? [report.prediction_drift] : [])];
    $('#feature-panel').innerHTML = table(['FEATURE', 'STATUS', 'METHOD', 'STATISTIC', 'P-VALUE', 'PSI', 'REASON'],
      features.map((item) => `<tr><td>${escapeHtml(item.feature)}</td><td>${badge(item.status)}</td><td>${escapeHtml(item.method || '—')}</td><td>${decimal(item.statistic)}</td><td>${decimal(item.p_value, 4)}</td><td>${decimal(item.psi)}</td><td>${escapeHtml(item.reason || '—')}</td></tr>`), 'No comparable features.');
    $('#feature-select').innerHTML = features.map((item, index) => `<option value="${index}">${escapeHtml(item.feature)}</option>`).join('');
    drawChart(features[0]?.distribution);
    $('#detail-section').scrollIntoView({ behavior: 'smooth' });
  } catch (error) { flash(error.message, true); }
}

function drawChart(distribution) {
  const container = $('#chart');
  container.replaceChildren();
  if (!distribution || !distribution.labels?.length) {
    container.innerHTML = '<div class="empty">A valid distribution could not be calculated for this feature.</div>';
    return;
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 800 250');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Reference and production distribution comparison');
  const count = distribution.labels.length;
  const groupWidth = 730 / count;
  const maxValue = Math.max(0.05, ...distribution.reference, ...distribution.production);
  const element = (name, attributes, label) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    if (label !== undefined) node.textContent = label;
    svg.appendChild(node);
  };
  for (let i = 0; i <= 4; i += 1) {
    const y = 190 - i * 40;
    element('line', { x1: 42, x2: 790, y1: y, y2: y, stroke: '#294259' });
    element('text', { x: 2, y: y + 4, fill: '#8ba5b8', 'font-size': 11 }, `${(maxValue * i / 4 * 100).toFixed(0)}%`);
  }
  distribution.labels.forEach((label, index) => {
    const x = 50 + index * groupWidth;
    const barWidth = Math.min(26, groupWidth / 2 - 3);
    for (const [side, rates, fill] of [[0, distribution.reference, '#42d4b4'], [1, distribution.production, '#7d89e8']]) {
      const height = 160 * rates[index] / maxValue;
      element('rect', { x: x + side * barWidth, y: 190 - height, width: barWidth - 2,
        height, fill, rx: 2 });
    }
    const shortened = label.length > 13 ? `${label.slice(0, 12)}…` : label;
    element('text', { x: x + barWidth, y: 217, fill: '#9bb2c3', 'font-size': 10,
      'text-anchor': 'middle' }, shortened);
  });
  container.appendChild(svg);
}

$('#model-select').addEventListener('change', async (event) => {
  state.modelId = event.target.value || null;
  try { await loadModel(); renderRuns(); renderAlerts(); $('#detail-section').hidden = true; }
  catch (error) { flash(error.message, true); }
});

$('#refresh').addEventListener('click', () => refresh());

$('#model-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const model = await api('/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    await refresh(false);
    state.modelId = model.id;
    await refresh();
    form.reset();
    flash(`Registered ${model.name}.`);
  } catch (error) { flash(error.message, true); }
});

$('#upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.modelId) return flash('Register or select a model first.', true);
  const form = event.currentTarget;
  try {
    const dataset = await api(`/models/${state.modelId}/datasets`, { method: 'POST', body: new FormData(form) });
    await refresh();
    form.reset();
    flash(`Uploaded ${dataset.name}: ${dataset.row_count} rows profiled.`);
  } catch (error) { flash(error.message, true); }
});

$('#run-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  if (!data.reference_dataset_id || !data.production_dataset_id) return flash('Upload reference and production datasets first.', true);
  if (!data.prediction_column) delete data.prediction_column;
  if (!data.target_column) delete data.target_column;
  try {
    const run = await api('/monitoring/drift', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    await refresh();
    await showRun(run.id);
    flash(`Monitoring finished: ${run.overall_status}.`);
  } catch (error) { flash(error.message, true); }
});

document.addEventListener('click', async (event) => {
  const target = event.target;
  if (target.dataset.profile) return showProfile(target.dataset.profile);
  if (target.dataset.run) return showRun(target.dataset.run);
  if (target.dataset.resolve) {
    try { await api(`/alerts/${target.dataset.resolve}/resolve`, { method: 'PATCH' }); await refresh(); flash('Alert marked resolved.'); }
    catch (error) { flash(error.message, true); }
  }
});

$('#feature-select').addEventListener('change', (event) => {
  const report = state.currentRun?.report;
  if (!report) return;
  const features = [...report.features, ...(report.prediction_drift ? [report.prediction_drift] : [])];
  drawChart(features[Number(event.target.value)]?.distribution);
});

refresh();
