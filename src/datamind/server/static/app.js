'use strict';

const state = {
  config: null,
  result: null,
  abortController: null,
  timer: null,
  startedAt: 0,
  activeUploadSession: null,
  uploadTable: null,
  history: [],
  activeConversationId: null,
  selectedTurnId: null,
  runningConversationId: null,
};
const conversationStore = ConversationHistory.createStore();

document.addEventListener('DOMContentLoaded', async () => {
  initSmoke();
  initInteractions();
  initLayout();
  setView('empty');
  await restoreHistory();
  await loadConfig();
});

function $(id) { return document.getElementById(id); }

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function initInteractions() {
  document.querySelector('.wordmark').addEventListener('click', (event) => { event.preventDefault(); startNewAnalysis(); });
  $('askForm').addEventListener('submit', (event) => {
    event.preventDefault();
    const question = $('questionInput').value.trim();
    if (question) executeQuery(question);
  });

  $('questionInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      $('askForm').requestSubmit();
    }
  });
  $('questionInput').addEventListener('input', autoSizeInput);

  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      openPalette();
    }
    if (event.key === 'Escape') closeOverlays();
  });

  ['sidebarNewBtn', 'workspaceBtn'].forEach((id) => $(id).addEventListener('click', startNewAnalysis));
  ['catalogBtn', 'sidebarCatalogBtn', 'overviewCatalogBtn'].forEach((id) => $(id).addEventListener('click', openCatalog));
  $('drawerScrim').addEventListener('click', closeCatalog);
  document.querySelectorAll('[data-close="catalogDrawer"]').forEach((button) => button.addEventListener('click', closeCatalog));
  document.querySelectorAll('[data-modal-close]').forEach((button) => button.addEventListener('click', () => closeModal(button.closest('.modal'))));
  document.querySelectorAll('.modal').forEach((modal) => modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal(modal);
  }));

  $('cancelQueryBtn').addEventListener('click', () => state.abortController?.abort());
  $('paletteBtn').addEventListener('click', () => openPalette());
  $('dismissErrorBtn').addEventListener('click', () => { $('errorState').hidden = true; });
  $('clearHistoryBtn').addEventListener('click', clearHistory);
  const latestAction = (action) => () => { selectTurn($('resultsContainer').dataset.turnId); action(); };
  $('copyAnswerBtn').addEventListener('click', latestAction(copyAnswer));
  $('copySqlBtn').addEventListener('click', latestAction(copySql));
  $('exportCsvBtn').addEventListener('click', latestAction(exportResultCsv));
  $('receiptBtn').addEventListener('click', latestAction(showReceipt));
  $('secondOpinionBtn').addEventListener('click', latestAction(requestSecondOpinion));
  $('redTeamBtn').addEventListener('click', latestAction(requestRedTeam));
  $('inspectEvidenceBtn').addEventListener('click', () => selectTurn($('resultsContainer').dataset.turnId));

  document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => selectTab(button)));
  initUploads();
}

function initLayout() {
  const app = $('app');
  const compact = () => window.matchMedia('(max-width: 1100px)').matches;
  try { if (localStorage.getItem('datamind.navCollapsed') === '1') app.classList.add('nav-collapsed'); } catch { /* storage unavailable */ }
  $('navToggleBtn').addEventListener('click', () => {
    if (compact()) { app.classList.toggle('nav-open'); return; }
    app.classList.toggle('nav-collapsed');
    try { localStorage.setItem('datamind.navCollapsed', app.classList.contains('nav-collapsed') ? '1' : '0'); } catch { /* storage unavailable */ }
  });
  $('sidebar').addEventListener('click', (event) => { if (compact() && event.target.closest('button')) app.classList.remove('nav-open'); });

  const menu = $('moreMenu');
  const setMenu = (open) => { menu.hidden = !open; $('moreBtn').setAttribute('aria-expanded', String(open)); };
  $('moreBtn').addEventListener('click', (event) => { event.stopPropagation(); setMenu(menu.hidden); });
  menu.addEventListener('click', () => setMenu(false));
  document.addEventListener('click', (event) => { if (!event.target.closest('.menu')) setMenu(false); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setMenu(false); });

  $('inspectEvidenceBtn').addEventListener('click', () => {
    const panel = $('evidencePanel');
    panel.classList.remove('flash'); void panel.offsetWidth; panel.classList.add('flash');
    if (compact()) app.classList.toggle('evidence-open');
    else panel.querySelector('.tab.active')?.focus();
  });
  $('closeEvidenceBtn').addEventListener('click', () => app.classList.remove('evidence-open'));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') app.classList.remove('evidence-open', 'nav-open');
    if (event.key.toLowerCase() === 'n' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.target.closest('input, textarea, select, [contenteditable]')) startNewAnalysis();
  });

  document.addEventListener('click', (event) => {
    const header = event.target.closest('.data-table th[data-sort]');
    if (header) sortTable(header);
  });

  const resizer = $('evidenceResizer');
  const setWidth = (px) => {
    const width = Math.min(640, Math.max(300, Math.round(px)));
    app.style.setProperty('--evidence-w', `${width}px`);
    return width;
  };
  try { const saved = Number(localStorage.getItem('datamind.evidenceWidth')); if (saved) setWidth(saved); } catch { /* storage unavailable */ }
  resizer.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    resizer.setPointerCapture(event.pointerId);
    resizer.classList.add('dragging');
    const move = (e) => setWidth(window.innerWidth - e.clientX);
    const up = (e) => {
      resizer.classList.remove('dragging');
      resizer.removeEventListener('pointermove', move);
      resizer.removeEventListener('pointerup', up);
      try { localStorage.setItem('datamind.evidenceWidth', String(setWidth(window.innerWidth - e.clientX))); } catch { /* storage unavailable */ }
    };
    resizer.addEventListener('pointermove', move);
    resizer.addEventListener('pointerup', up);
  });
  resizer.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    const current = $('evidencePanel').getBoundingClientRect().width;
    setWidth(current + (event.key === 'ArrowLeft' ? 24 : -24));
  });

  initPalette();
}

function initPalette() {
  const input = $('paletteInput'), list = $('paletteList');
  let items = [], active = 0;
  const commands = () => {
    const entries = [
      { label: 'New analysis', hint: 'Command', run: startNewAnalysis },
      { label: 'Open data catalog', hint: 'Command', run: openCatalog },
      { label: 'Toggle navigation', hint: 'Command', run: () => $('navToggleBtn').click() },
    ];
    if (state.config?.uploads_enabled !== false) entries.push({ label: 'Add data', hint: 'Command', run: openUploadModal });
    if (state.result) {
      entries.push({ label: 'Copy answer', hint: 'Result', run: copyAnswer }, { label: 'Copy SQL', hint: 'Result', run: copySql }, { label: 'Export CSV', hint: 'Result', run: exportResultCsv });
    }
    state.history.forEach((conversation) => entries.push({ label: conversation.title, hint: 'Chat', run: () => openConversation(conversation.id) }));
    const asked = new Set();
    (state.config?.sample_questions || []).forEach((question) => {
      if (asked.has(question)) return;
      asked.add(question);
      entries.push({ label: question, hint: 'Ask', run: () => { startNewAnalysis(); $('questionInput').value = question; autoSizeInput(); $('questionInput').focus(); } });
    });
    return entries;
  };
  const render = () => {
    const query = input.value.trim().toLowerCase();
    items = commands().filter((item) => item.label.toLowerCase().includes(query)).slice(0, 12);
    active = Math.min(active, Math.max(0, items.length - 1));
    list.innerHTML = items.length ? '' : '<li class="empty">No matches</li>';
    items.forEach((item, index) => {
      const row = document.createElement('li');
      row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(index === active));
      row.innerHTML = `<span>${escapeHtml(item.label)}</span><span>${item.hint}</span>`;
      row.addEventListener('click', () => choose(index));
      list.appendChild(row);
    });
  };
  const choose = (index) => {
    const item = items[index];
    if (!item) return;
    closeModal($('paletteModal'));
    item.run();
  };
  input.addEventListener('input', () => { active = 0; render(); });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % Math.max(1, items.length);
      render();
      list.children[active]?.scrollIntoView({ block: 'nearest' });
    } else if (event.key === 'Enter') { event.preventDefault(); choose(active); }
  });
  openPalette = () => {
    input.value = ''; active = 0; render();
    const modal = $('paletteModal');
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    input.focus();
  };
}

let openPalette = () => {};

function autoSizeInput() {
  const input = $('questionInput');
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 190)}px`;
}

async function loadConfig() {
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    state.config = config;
    $('backendName').textContent = String(config.backend || 'Connected').toUpperCase();
    $('backendBadge').classList.add('online');
    $('privacyStatus').textContent = config.privacy_indicator || (config.is_local ? 'Local-only execution' : 'Metered cloud endpoint');
    $('executionMode').textContent = config.is_local ? 'Local execution' : 'Cloud execution';
    $('modelLabel').textContent = config.model_name || 'Configured model';
    $('tableCount').textContent = (config.tables || []).length;
    renderSuggestions(config.sample_questions || []);
    renderCatalog(config.tables || []);
    renderWelcome(config);
    $('uploadModalBtn').hidden = config.uploads_enabled === false;
  } catch (error) {
    $('backendName').textContent = 'OFFLINE';
    $('privacyStatus').textContent = 'Server unavailable';
    renderSuggestions([
      'What is the total sales revenue?',
      'Which products declined month over month?',
    ]);
    console.error('Could not load Data Mind configuration:', error);
  }
}


function renderWelcome(config) {
  const tables = config.tables || [];
  const fields = tables.reduce((total, table) => total + (table.columns || []).length, 0);
  $('welcomeMeta').textContent = tables.length
    ? `${tables.length} tables · ${fields} fields · ${config.semantic_model || 'Semantic model'}`
    : 'No tables are currently available.';
  $('datasetTables').innerHTML = '';
  tables.slice(0, 3).forEach((table) => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'dataset-table';
    button.innerHTML = `<strong>${escapeHtml(table.name)}</strong><span>${(table.columns || []).length} fields</span>`;
    button.title = table.description || table.name;
    button.addEventListener('click', openCatalog);
    $('datasetTables').appendChild(button);
  });
}

function renderSuggestions(questions) {
  const container = $('chipsList');
  container.innerHTML = '';
  questions.slice(0, 4).forEach((question, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'suggestion';
    button.innerHTML = `<span class="suggestion-index">0${index + 1}</span><span class="suggestion-copy">${escapeHtml(question)}</span><span class="suggestion-arrow" aria-hidden="true">↗</span>`;
    button.title = question;
    button.addEventListener('click', () => {
      $('questionInput').value = question;
      autoSizeInput();
      $('questionInput').focus();
    });
    container.appendChild(button);
  });
}

function renderCatalog(tables) {
  const container = $('catalogContent');
  if (!tables.length) {
    container.innerHTML = '<p class="evidence-empty">No schema information is available.</p>';
    return;
  }
  container.innerHTML = tables.map((table, index) => `
    <details class="catalog-table" ${index === 0 ? 'open' : ''}>
      <summary><strong>${escapeHtml(table.name)}</strong><span>${(table.columns || []).length} fields</span></summary>
      ${table.description ? `<p>${escapeHtml(table.description)}</p>` : ''}
      <div class="column-list">${(table.columns || []).map((column) => `<span class="column-chip">${escapeHtml(column)}</span>`).join('')}</div>
    </details>
  `).join('');
}

function openCatalog() {
  $('catalogDrawer').classList.add('open');
  $('catalogDrawer').setAttribute('aria-hidden', 'false');
  $('drawerScrim').hidden = false;
}

function closeCatalog() {
  $('catalogDrawer').classList.remove('open');
  $('catalogDrawer').setAttribute('aria-hidden', 'true');
  $('drawerScrim').hidden = true;
}

function closeOverlays() {
  closeCatalog();
  document.querySelectorAll('.modal:not([hidden])').forEach(closeModal);
}

function openModal(modal) {
  modal.hidden = false;
  document.body.style.overflow = 'hidden';
  modal.querySelector('.icon-button, button')?.focus();
}

function closeModal(modal) {
  if (!modal) return;
  modal.hidden = true;
  document.body.style.overflow = '';
}

// The shader stays behind the workspace; opaque reading surfaces protect results.
function setView(view) {
  document.body.dataset.view = view;
  $('emptyState').hidden = view !== 'empty';
  $('evidencePlaceholder').hidden = view === 'result';
  $('evidenceBody').hidden = view !== 'result';
  $('viewLabel').textContent = view === 'result' ? 'Analysis' : view === 'loading' ? 'Analyzing' : 'New analysis';
  if (view !== 'result') $('app').classList.remove('evidence-open');
}

function startNewAnalysis() {
  state.activeConversationId = null;
  state.selectedTurnId = null;
  state.result = null;
  try { localStorage.removeItem('datamind.activeConversation'); } catch { /* storage unavailable */ }
  $('questionInput').value = '';
  autoSizeInput();
  $('resultsContainer').hidden = true;
  $('loadingState').hidden = true;
  $('errorState').hidden = true;
  $('archivedTurns').replaceChildren();
  setView('empty');
  renderHistory();
  $('questionInput').focus();
  $('canvasScroll').scrollTo({ top: 0 });
}

function startTimer() {
  state.startedAt = performance.now();
  $('elapsedTimer').textContent = '0.0s';
  state.timer = window.setInterval(() => {
    $('elapsedTimer').textContent = `${((performance.now() - state.startedAt) / 1000).toFixed(1)}s`;
  }, 100);
}

function stopTimer() {
  if (state.timer) window.clearInterval(state.timer);
  state.timer = null;
}

async function executeQuery(question) {
  if (state.abortController) return;
  let conversation = state.history.find((item) => item.id === state.activeConversationId);
  if (conversation && conversation.dataset !== state.activeUploadSession) {
    showToast('Start a new analysis to use the currently active dataset.');
    return;
  }
  if (!conversation) {
    conversation = ConversationHistory.create(question, state.activeUploadSession);
    state.history.unshift(conversation);
    state.activeConversationId = conversation.id;
  }
  const turn = ConversationHistory.append(conversation, question);
  state.runningConversationId = conversation.id;
  rememberActiveConversation();
  persistConversation(conversation);
  const submit = $('submitBtn');
  submit.disabled = true;
  submit.classList.add('loading');
  submit.querySelector('.btn-text').textContent = 'Analyzing';
  state.abortController = new AbortController();
  $('questionInput').value = '';
  autoSizeInput();
  renderConversation();
  renderHistory();
  scrollToTurn(turn.id);
  startTimer();

  try {
    const endpoint = state.activeUploadSession ? `/api/uploads/${state.activeUploadSession}/ask` : '/api/ask';
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        permissive: !$('strictModeToggle').checked,
        ...($('modelPresetSelect').value === 'local' ? {} : { preset: $('modelPresetSelect').value }),
      }),
      signal: state.abortController.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || `Server returned HTTP ${response.status}`);
    ConversationHistory.finish(conversation, turn.id, data);
  } catch (error) {
    ConversationHistory.finish(conversation, turn.id, null, error.name === 'AbortError' ? 'Analysis cancelled.' : error.message);
  } finally {
    stopTimer();
    state.abortController = null;
    state.runningConversationId = null;
    submit.disabled = false;
    submit.classList.remove('loading');
    submit.querySelector('.btn-text').textContent = 'Ask Data Mind';
    await persistConversation(conversation);
    renderHistory();
    if (state.activeConversationId === conversation.id && conversation.turns.at(-1)?.id === turn.id) {
      renderConversation();
      scrollToTurn(turn.id);
    }
  }
}

function renderResult(data, turnId) {
  $('questionEcho').textContent = data.question || $('questionInput').value;
  renderTrust(data);
  $('answerContent').innerHTML = formatAnswer(data.answer || 'No answer was returned.');
  const inspectCitation = (citation) => { selectTurn(turnId); showCitation(citation); };
  $('answerContent').querySelectorAll('[data-citation]').forEach((button) => button.addEventListener('click', () => inspectCitation(button.dataset.citation)));
  renderClarifications(data);
  renderAssumptions(data.assumptions_card);
  renderChart(data.chart, null, inspectCitation);
  renderEvidence(data);
}

function renderTrust(data) {
  const report = data.citation_report || {};
  const badge = data.trust_badge || {};
  const stateName = badge.state || 'NOT_VERIFIED';
  const tone = stateName === 'VERIFIED' ? 'verified' : stateName === 'PARTIALLY_VERIFIED' || stateName === 'CLARIFICATION' ? 'warning' : 'failed';
  const verdict = $('trustSummary');
  verdict.className = `verdict ${tone}`;
  verdict.textContent = badge.label || stateName.replaceAll('_', ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase());
  const queries = data.evidence?.queries || [];
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const parts = [
    plural(report.valid_count || 0, 'citation'),
    plural(report.verified_numbers_count || 0, 'number') + ' checked',
    plural(queries.length, 'query').replace('querys', 'queries'),
  ];
  if (report.discrepancy_count) parts.push(plural(report.discrepancy_count, 'discrepancy').replace('discrepancys', 'discrepancies'));
  $('trustMetrics').textContent = parts.join(' · ');
}

function formatAnswer(text) {
  let formatted = escapeHtml(text);
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\[\[([^\]]+)\]\]/g, '<button class="citation-token" type="button" data-citation="$1">$1</button>');
  const lines = formatted.split(/\r?\n/);
  let output = '';
  let inList = false;
  lines.forEach((line) => {
    const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (item) {
      if (!inList) { output += '<ul>'; inList = true; }
      output += `<li>${item[1]}</li>`;
    } else {
      if (inList) { output += '</ul>'; inList = false; }
      if (line.trim()) output += `<p>${line}</p>`;
    }
  });
  if (inList) output += '</ul>';
  return output;
}

function renderClarifications(data) {
  const card = $('clarifyCard');
  if (data.response_type !== 'clarification') { card.hidden = true; return; }
  const suggestions = state.config?.sample_questions?.slice(0, 4) || [];
  $('clarifyChips').innerHTML = '';
  suggestions.forEach((question) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = question;
    button.addEventListener('click', () => { $('questionInput').value = question; $('questionInput').focus(); });
    $('clarifyChips').appendChild(button);
  });
  card.hidden = false;
}

function renderAssumptions(card) {
  const box = $('assumptionsBox');
  if (!card) { box.hidden = true; return; }
  const entries = [
    ['Tables', card.tables], ['Join keys', card.join_keys], ['Filters', card.filters],
    ['Group by', card.group_by], ['Metrics', card.metrics], ['Date range', card.date_range],
  ].filter(([, value]) => value && (!Array.isArray(value) || value.length));
  $('assumptionsBody').innerHTML = entries.map(([label, value]) => `<div class="assumption-row"><strong>${label}</strong>${escapeHtml(Array.isArray(value) ? value.join(' · ') : value)}</div>`).join('');
  $('assumptionsBadge').textContent = card.badge_status === 'PARTIALLY_VERIFIED' ? 'Review' : 'Checked';
  box.hidden = false;
  box.open = card.badge_status === 'PARTIALLY_VERIFIED';
}

function renderEvidence(data) {
  const queries = data.evidence?.queries || [];
  const docs = data.evidence?.chunks || [];
  const checks = data.citation_report?.numeric_checks || [];
  $('sqlCount').textContent = queries.length;
  $('docsCount').textContent = docs.length;
  $('numChecksCount').textContent = checks.length;
  renderQueries(queries);
  renderDocs(docs);
  renderNumericChecks(checks);
  const primary = queries[0] || {};
  const hood = data.under_the_hood || {};
  const rowCount = Array.isArray(primary.rows) ? primary.rows.length : 0;
  const fields = [
    ['Backend', data.backend || hood.dialect], ['Model', hood.model || state.config?.model_name],
    ['Rows', rowCount], ['Latency', primary.elapsed_ms ? `${Number(primary.elapsed_ms).toFixed(0)} ms` : null],
    ['Privacy', data.egress_ledger?.summary || state.config?.privacy_indicator],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
  $('hoodMeta').textContent = fields.map(([label, value]) => `${label}: ${value}`).join(' · ');
}

function renderQueries(queries) {
  const container = $('queriesList');
  if (!queries.length) { container.innerHTML = '<p class="evidence-empty">This answer did not require a database query.</p>'; return; }
  container.innerHTML = '';
  queries.forEach((q) => {
    const rows = q.rows || [];
    const columns = q.columns || [];
    const item = document.createElement('section');
    item.className = 'query-item';
    item.innerHTML = `
      <div class="query-item-head"><span class="query-label">${escapeHtml(q.query_label || 'Q')}</span><span class="query-meta">${escapeHtml(String(q.query_id || "local").slice(0, 8))} · ${rows.length} rows · ${Number(q.elapsed_ms || 0).toFixed(0)} ms</span></div>
      ${q.purpose ? `<div class="query-purpose">${escapeHtml(q.purpose)}</div>` : ''}
      <pre class="sql-code">${escapeHtml(q.sql || '')}</pre>
      ${rows.length ? buildTable(columns, rows, q.query_label || 'Q1') : ''}`;
    item.querySelectorAll('[data-row-id]').forEach((row) => row.addEventListener('click', () => showCitation(row.dataset.rowId)));
    container.appendChild(item);
  });
}

const isNumeric = (cell) => cell !== null && cell !== '' && /^[-+$€£]?\s*[\d,]*\.?\d+%?$/.test(String(cell).trim());

function buildTable(columns, rows, queryLabel) {
  const numeric = columns.map((_, index) => rows.length > 0 && rows.slice(0, 20).every((row) => row[index] === null || isNumeric(row[index])));
  const head = columns.map((column, index) => `<th data-sort="${index}"${numeric[index] ? ' class="num"' : ''} scope="col">${escapeHtml(column)}</th>`).join('');
  const body = rows.slice(0, 100).map((row, index) => {
    const rowId = `${queryLabel}:R${index + 1}`;
    const cells = row.map((cell, col) => `<td${numeric[col] ? ' class="num"' : ''}>${cell === null ? '<em>NULL</em>' : escapeHtml(cell)}</td>`).join('');
    return `<tr data-row-id="${escapeHtml(rowId)}"><td><span class="citation-token">${escapeHtml(rowId)}</span></td>${cells}</tr>`;
  }).join('');
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">Source</th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function sortTable(header) {
  const table = header.closest('table');
  const column = Number(header.dataset.sort) + 1;
  const direction = header.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
  table.querySelectorAll('th').forEach((th) => th.removeAttribute('aria-sort'));
  header.setAttribute('aria-sort', direction);
  const toNumber = (text) => Number(String(text).replace(/[^\d.-]/g, ''));
  const rows = [...table.tBodies[0].rows];
  const numeric = rows.every((row) => isNumeric(row.cells[column].textContent) || row.cells[column].textContent === 'NULL');
  rows.sort((a, b) => {
    const left = a.cells[column].textContent, right = b.cells[column].textContent;
    const result = numeric ? toNumber(left) - toNumber(right) : left.localeCompare(right, undefined, { numeric: true });
    return direction === 'ascending' ? result : -result;
  });
  rows.forEach((row) => table.tBodies[0].appendChild(row));
}

function renderDocs(docs) {
  const container = $('docsList');
  if (!docs.length) { container.innerHTML = '<p class="evidence-empty">No documents were retrieved for this answer.</p>'; return; }
  container.innerHTML = docs.map((doc) => `<article class="doc-item" data-chunk-id="${escapeHtml(doc.chunk_id)}"><div class="doc-item-head"><span class="query-label">${escapeHtml(doc.chunk_id)}</span><span class="query-meta">Relevance ${escapeHtml(doc.score)}</span></div><strong>${escapeHtml(doc.doc_name)}</strong><p class="doc-text">${escapeHtml(doc.text)}</p></article>`).join('');
}

function renderNumericChecks(checks) {
  const container = $('numericList');
  if (!checks.length) { container.innerHTML = '<p class="evidence-empty">No numeric claims required reconciliation.</p>'; return; }
  container.innerHTML = checks.map((check) => {
    const passed = check.status === 'VERIFIED';
    return `<article class="audit-item"><span class="audit-status ${passed ? '' : 'fail'}">${passed ? '✓' : '!'}</span><div><p>${escapeHtml(check.message || check.status)}</p><small>${escapeHtml(check.row_id || '')} · ${escapeHtml(check.matched_column || '')}</small></div><span class="audit-value">${escapeHtml(check.claimed_value)}</span></article>`;
  }).join('');
}

function selectTab(button) {
  document.querySelectorAll('.tab').forEach((tab) => { tab.classList.remove('active'); tab.setAttribute('aria-selected', 'false'); });
  document.querySelectorAll('.tab-pane').forEach((pane) => pane.classList.remove('active'));
  button.classList.add('active');
  button.setAttribute('aria-selected', 'true');
  $(button.dataset.tab).classList.add('active');
}

function activateTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) selectTab(tab);
}

// Clicking a citation jumps to the source row (or document) in the evidence panel and highlights it.
function showCitation(citationId) {
  const panel = $('evidencePanel');
  if (window.matchMedia('(max-width: 1100px)').matches) $('app').classList.add('evidence-open');
  document.querySelectorAll('.highlighted').forEach((el) => el.classList.remove('highlighted'));
  let target = null;
  if (citationId.startsWith('D:')) {
    activateTab('docsTab');
    target = [...document.querySelectorAll('.doc-item')].find((el) => el.dataset.chunkId === citationId);
  } else {
    activateTab('sqlTab');
    target = [...document.querySelectorAll('#queriesList tr[data-row-id]')].find((el) => el.dataset.rowId === citationId);
  }
  if (!target) return showToast(`${citationId} is not present in this result`);
  target.classList.add('highlighted');
  target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  panel.classList.remove('flash'); void panel.offsetWidth; panel.classList.add('flash');
}

function copyAnswer() {
  if (!state.result?.answer) return;
  copyText(state.result.answer, 'Answer copied');
}

function copySql() {
  const sql = (state.result?.evidence?.queries || []).map((query) => query.sql).filter(Boolean).join('\n\n');
  if (!sql) return showToast('No SQL to copy');
  copyText(sql, 'SQL copied');
}

async function copyText(text, message) {
  try { await navigator.clipboard.writeText(text); showToast(message); }
  catch { showToast('Clipboard access was unavailable'); }
}

function exportResultCsv() {
  const q = state.result?.evidence?.queries?.[0];
  if (!q?.rows?.length) return showToast('No tabular rows to export');
  const rows = q.rows || [];
  const sanitize = (value) => {
    let cell = value === null || value === undefined ? '' : String(value);
    if (/^[=+\-@]/.test(cell)) cell = `'${cell}`;
    return `"${cell.replace(/"/g, '""')}"`;
  };
  const csv = [[...(q.columns || [])].map(sanitize).join(','), ...rows.map((row) => row.map(sanitize).join(','))].join('\r\n');
  downloadBlob(csv, 'text/csv;charset=utf-8', 'datamind-result.csv');
}

function showReceipt() {
  const receipt = state.result?.receipt;
  if (!receipt) return showToast('No receipt is available for this result');
  $('detailModalTitle').textContent = 'Verifiable answer receipt';
  $('detailModalBody').innerHTML = `<div class="detail-block"><h4>SHA-256 root hash</h4><div class="hash-box">${escapeHtml(receipt.root_hash || 'Unavailable')}</div></div><div class="detail-block"><p>This receipt binds the question, answer, evidence and verification state into one tamper-evident record.</p><button class="button button-dark" id="downloadReceiptBtn" type="button">Download JSON receipt</button></div>`;
  openModal($('detailModal'));
  $('downloadReceiptBtn').addEventListener('click', () => downloadBlob(JSON.stringify(receipt, null, 2), 'application/json', `datamind-receipt-${String(receipt.root_hash || 'result').slice(0, 8)}.json`));
}

async function requestSecondOpinion() {
  const query = state.result?.evidence?.queries?.[0];
  if (!query?.sql) return showToast('Run a SQL-backed analysis first');
  const button = $('secondOpinionBtn');
  button.disabled = true; button.textContent = 'Comparing…';
  try {
    const response = await fetch('/api/second_opinion', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ primary_sql: query.sql, primary_model: state.result?.under_the_hood?.model, secondary_model: 'gemma4:e4b' }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Second opinion failed');
    $('detailModalTitle').textContent = data.verdict_label || data.verdict || 'Second opinion';
    $('detailModalBody').innerHTML = `<div class="detail-block"><h4>Consensus</h4><p>${escapeHtml(data.explanation || 'The comparison completed.')}</p></div><div class="detail-block"><h4>Primary SQL</h4><pre class="sql-code">${escapeHtml(data.primary_sql || query.sql)}</pre></div><div class="detail-block"><h4>Secondary SQL</h4><pre class="sql-code">${escapeHtml(data.secondary_sql || '')}</pre></div>`;
    openModal($('detailModal'));
  } catch (error) { showToast(error.message); }
  finally { button.disabled = false; button.textContent = 'Second opinion'; }
}

async function requestRedTeam() {
  if (!state.result) return showToast('Run an analysis first');
  const button = $('redTeamBtn');
  button.disabled = true; button.textContent = 'Challenging…';
  try {
    const response = await fetch('/api/red_team', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer: state.result.answer, evidence: state.result.evidence }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Challenge failed');
    $('detailModalTitle').textContent = 'Adversarial verifier challenge';
    $('detailModalBody').innerHTML = `<div class="detail-block"><h4>${escapeHtml(data.caught_count)} of ${escapeHtml(data.total_mutations)} mutations caught · ${escapeHtml(data.catch_rate_pct)}%</h4></div>${(data.mutations || []).map((mutation) => `<article class="audit-item"><span class="audit-status ${mutation.caught ? '' : 'fail'}">${mutation.caught ? '✓' : '!'}</span><div><p>${escapeHtml(mutation.name)}</p><small>${escapeHtml(mutation.diagnostic)}</small></div></article>`).join('')}`;
    openModal($('detailModal'));
  } catch (error) { showToast(error.message); }
  finally { button.disabled = false; button.textContent = 'Challenge'; }
}

function downloadBlob(content, type, filename) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast(`${filename} downloaded`);
}

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toast'; toast.textContent = message; $('toastRegion').appendChild(toast);
  window.setTimeout(() => toast.remove(), 2800);
}

async function restoreHistory() {
  try {
    state.history = (await conversationStore.load()).filter((item) => item && typeof item.id === 'string' && Array.isArray(item.turns));
    if (!state.history.length) {
      const old = JSON.parse(localStorage.getItem('datamind.history') || '[]');
      if (Array.isArray(old)) {
        state.history = ConversationHistory.migrate(old);
        for (const conversation of state.history) await conversationStore.save(conversation);
      }
    }
    // A reload cannot resume an HTTP request from the previous document.
    for (const conversation of state.history) {
      let interrupted = false;
      conversation.turns.forEach((turn) => {
        if (turn.status === 'pending') { turn.status = 'error'; turn.error = 'This analysis was interrupted before its answer was saved.'; interrupted = true; }
      });
      if (interrupted) await conversationStore.save(conversation);
    }
    const activeId = localStorage.getItem('datamind.activeConversation');
    if (state.history.some((item) => item.id === activeId)) openConversation(activeId);
  } catch (error) {
    console.error('Could not restore conversations:', error);
    showToast('Saved conversations could not be loaded in this browser.');
  }
  renderHistory();
}

function rememberActiveConversation() {
  try { localStorage.setItem('datamind.activeConversation', state.activeConversationId); } catch { /* storage unavailable */ }
}

async function persistConversation(conversation) {
  if (!state.history.some((item) => item.id === conversation.id)) return;
  try { await conversationStore.save(conversation); }
  catch (error) {
    console.error('Could not save conversation:', error);
    showToast('This conversation is available now, but could not be saved for reopening.');
  }
}

function openConversation(id) {
  const conversation = state.history.find((item) => item.id === id);
  if (!conversation) return;
  state.activeConversationId = id;
  state.selectedTurnId = null;
  $('questionInput').value = '';
  autoSizeInput();
  rememberActiveConversation();
  renderConversation();
  renderHistory();
  $('app').classList.remove('nav-open');
  $('canvasScroll').scrollTo({ top: 0 });
}

async function clearHistory() {
  const previous = state.history;
  state.history = [];
  try {
    await conversationStore.clear();
    localStorage.removeItem('datamind.history');
    localStorage.removeItem('datamind.activeConversation');
    startNewAnalysis();
    showToast('Saved conversations cleared');
  } catch (error) { state.history = previous; renderHistory(); showToast('Could not clear conversations: ' + error.message); }
}

function renderHistory() {
  $('recentList').replaceChildren();
  const container = $('historyList');
  container.replaceChildren();
  if (!state.history.length) {
    container.innerHTML = '<p class="history-empty">Your conversations will appear here.</p>';
    return;
  }
  [...state.history].sort((a, b) => b.updatedAt - a.updatedAt).forEach((conversation) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item';
    button.classList.toggle('active', conversation.id === state.activeConversationId);
    if (conversation.id === state.activeConversationId) button.setAttribute('aria-current', 'page');
    const count = conversation.turns.length;
    const legacy = conversation.turns.every((turn) => turn.status === 'legacy');
    const summary = legacy ? 'Older question only' : count + (count === 1 ? ' question' : ' questions');
    button.innerHTML = '<strong>' + escapeHtml(conversation.title) + '</strong><small>' + summary + ' · ' + formatRelativeTime(conversation.updatedAt) + '</small>';
    button.title = conversation.title;
    button.addEventListener('click', () => openConversation(conversation.id));
    container.appendChild(button);
  });
}

function renderConversation() {
  const conversation = state.history.find((item) => item.id === state.activeConversationId);
  if (!conversation) return;
  const last = conversation.turns.at(-1);
  const completed = conversation.turns.filter((turn) => turn.result);
  const archived = $('archivedTurns');
  archived.replaceChildren();
  $('resultsContainer').hidden = !last?.result;
  $('errorState').hidden = true;
  const pending = conversation.turns.find((turn) => turn.status === 'pending');
  $('loadingState').hidden = !pending;
  if (pending) {
    $('pendingQuestion').textContent = pending.question;
    $('loadingState').dataset.turnId = pending.id;
  }
  conversation.turns.forEach((turn) => {
    if (turn.status !== 'pending' && !(last === turn && turn.result)) archived.appendChild(renderArchivedTurn(turn));
  });
  const latestResult = completed.at(-1);
  state.result = latestResult?.result || null;
  state.selectedTurnId = latestResult?.id || null;
  if (last?.result) {
    $('resultsContainer').dataset.turnId = last.id;
    renderResult(last.result, last.id);
  } else if (latestResult) {
    renderAssumptions(latestResult.result.assumptions_card);
    renderEvidence(latestResult.result);
  }
  setView(completed.length || !pending ? 'result' : 'loading');
  $('evidencePlaceholder').hidden = Boolean(state.result);
  $('evidenceBody').hidden = !state.result;
  if (state.result) selectTurn(state.selectedTurnId);
}

function renderArchivedTurn(turn) {
  const article = document.createElement('article');
  article.className = 'chat-turn results';
  article.dataset.turnId = turn.id;
  if (!turn.result) {
    article.innerHTML = '<header class="result-head"><h2>' + escapeHtml(turn.question) + '</h2></header><p class="saved-turn-notice">' + escapeHtml(turn.error || 'This older history entry only saved the question. Its answer and evidence were not stored.') + '</p>';
    return article;
  }
  const data = turn.result;
  const badge = data.trust_badge || {};
  const tone = badge.state === 'VERIFIED' ? 'verified' : badge.state === 'PARTIALLY_VERIFIED' || badge.state === 'CLARIFICATION' ? 'warning' : 'failed';
  article.innerHTML = '<header class="result-head"><h2>' + escapeHtml(turn.question) + '</h2><div class="verdict-row"><span class="verdict ' + tone + '">' + escapeHtml(badge.label || 'Saved answer') + '</span><span class="verdict-meta">Saved with source evidence</span></div></header>' +
    '<div class="answer-content">' + formatAnswer(data.answer || 'No answer was returned.') + '</div>' +
    '<section class="chart-block" data-chart-card hidden><h3 data-chart-title></h3><div class="chart-body" data-chart-body role="img"></div><p class="chart-note" data-chart-note hidden></p></section>' +
    '<div class="result-actions"><button class="ghost-btn" type="button" data-turn-action="copy">Copy</button><button class="ghost-btn" type="button" data-turn-action="csv">Export CSV</button><button class="ghost-btn" type="button" data-turn-action="evidence">Inspect evidence</button></div>';
  const inspect = (citation) => { selectTurn(turn.id); showCitation(citation); };
  article.querySelectorAll('[data-citation]').forEach((button) => button.addEventListener('click', () => inspect(button.dataset.citation)));
  renderChart(data.chart, {
    card: article.querySelector('[data-chart-card]'), body: article.querySelector('[data-chart-body]'),
    title: article.querySelector('[data-chart-title]'), note: article.querySelector('[data-chart-note]'),
  }, inspect);
  article.querySelectorAll('[data-turn-action]').forEach((button) => button.addEventListener('click', () => {
    selectTurn(turn.id);
    if (button.dataset.turnAction === 'copy') copyAnswer();
    else if (button.dataset.turnAction === 'csv') exportResultCsv();
    else if (matchMedia('(max-width: 1100px)').matches) $('app').classList.add('evidence-open');
    else $('evidencePanel').querySelector('.tab.active')?.focus();
  }));
  return article;
}

function selectTurn(id) {
  const conversation = state.history.find((item) => item.id === state.activeConversationId);
  const turn = conversation?.turns.find((item) => item.id === id);
  if (!turn?.result) return;
  state.result = turn.result;
  state.selectedTurnId = turn.id;
  renderAssumptions(turn.result.assumptions_card);
  renderEvidence(turn.result);
  document.querySelectorAll('[data-turn-id]').forEach((element) => element.classList.toggle('evidence-selected', element.dataset.turnId === id));
}

function scrollToTurn(id) {
  requestAnimationFrame(() => {
    const turn = [...document.querySelectorAll('[data-turn-id]')].find((item) => !item.hidden && item.dataset.turnId === id);
    if (!turn) return;
    const scroller = $('canvasScroll');
    scroller.scrollTo({ top: Math.max(0, turn.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 24), behavior: 'smooth' });
  });
}

function formatRelativeTime(timestamp) {
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return new Date(timestamp).toLocaleDateString();
}

function initUploads() {
  $('uploadModalBtn').addEventListener('click', openUploadModal);
  $('browseFilesBtn').addEventListener('click', () => $('filePickerInput').click());
  $('filePickerInput').addEventListener('change', (event) => event.target.files?.[0] && processUpload(event.target.files[0]));
  const dropzone = $('fileDropzone');
  ['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove('dragover'); }));
  dropzone.addEventListener('drop', (event) => event.dataTransfer.files?.[0] && processUpload(event.dataTransfer.files[0]));
  dropzone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') $('filePickerInput').click(); });
  $('confirmUploadBtn').addEventListener('click', confirmUpload);
  $('deleteDatasetBtn').addEventListener('click', deleteDataset);
}

async function openUploadModal() {
  $('uploadStatus').textContent = '';
  $('uploadStatus').className = 'upload-status';
  $('fileDropzone').hidden = false; $('uploadProgress').hidden = true; $('uploadReview').hidden = true;
  openModal($('uploadModal'));
  try {
    const response = await fetch('/api/uploads/status'); const status = await response.json();
    if (!status.enabled) {
      $('uploadStatus').textContent = 'Uploads are disabled. Restart Data Mind with --enable-uploads to use this feature.';
      $('uploadStatus').classList.add('error'); $('fileDropzone').hidden = true;
    } else {
      $('uploadStatus').textContent = `CSV or Parquet · up to ${Math.round(status.max_file_size_bytes / 1048576)} MB · ${Number(status.max_rows).toLocaleString()} rows`;
    }
  } catch { $('uploadStatus').textContent = 'Could not check upload availability.'; $('uploadStatus').classList.add('error'); }
}

async function processUpload(file) {
  $('fileDropzone').hidden = true; $('uploadProgress').hidden = false; $('uploadReview').hidden = true;
  try {
    const sessionResponse = await fetch('/api/uploads/session/create', { method: 'POST' });
    const session = await sessionResponse.json();
    if (!sessionResponse.ok) throw new Error(session.error || 'Could not create an upload session');
    state.activeUploadSession = session.session_id;
    const contentBase64 = await fileToBase64(file);
    const response = await fetch(`/api/uploads/${session.session_id}/upload`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: file.name, content_base64: contentBase64 }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Upload failed');
    state.uploadTable = data.table;
    renderUploadReview(data.table);
    $('uploadProgress').hidden = true; $('uploadReview').hidden = false;
  } catch (error) {
    $('uploadProgress').hidden = true; $('fileDropzone').hidden = false;
    $('uploadStatus').textContent = error.message; $('uploadStatus').classList.add('error');
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onerror = reject;
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.readAsDataURL(file);
  });
}

function renderUploadReview(table) {
  $('reviewTableName').textContent = table.table_name;
  $('reviewTableStats').textContent = `${Number(table.total_rows).toLocaleString()} rows · ${table.total_columns} columns · ${table.original_filename}`;
  $('uploadColumnsTbody').innerHTML = (table.columns || []).map((column) => `<tr><td><input type="checkbox" data-upload-use="${escapeHtml(column.name)}" checked></td><td><strong>${escapeHtml(column.name)}</strong>${column.pii_warning ? `<br><small>${escapeHtml(column.pii_warning)}</small>` : ''}</td><td><code>${escapeHtml(column.inferred_type)}</code></td><td><input class="review-description" data-upload-description="${escapeHtml(column.name)}" value="${escapeHtml(column.original_name || column.name)} column"></td></tr>`).join('');
}

async function confirmUpload() {
  if (!state.activeUploadSession || !state.uploadTable) return;
  const button = $('confirmUploadBtn'); button.disabled = true; button.textContent = 'Activating…';
  try {
    const columns = {};
    (state.uploadTable.columns || []).forEach((column) => {
      columns[column.name] = {
        enabled: document.querySelector(`[data-upload-use="${CSS.escape(column.name)}"]`)?.checked !== false,
        description: document.querySelector(`[data-upload-description="${CSS.escape(column.name)}"]`)?.value || column.name,
        is_primary_key: Boolean(column.is_id),
        is_document: Boolean(column.is_document),
      };
    });
    const reviewConfig = { default_currency: 'USD', tables: { [state.uploadTable.table_name]: { description: `Uploaded dataset: ${state.uploadTable.original_filename}`, columns } } };
    const response = await fetch(`/api/uploads/${state.activeUploadSession}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ review_config: reviewConfig }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Dataset activation failed');
    $('activeDatasetName').textContent = `${state.uploadTable.original_filename} · ${Number(state.uploadTable.total_rows).toLocaleString()} rows`;
    $('activeDatasetBanner').hidden = false; $('backendName').textContent = 'DUCKDB · UPLOAD';
    if (data.sample_questions?.length) renderSuggestions(data.sample_questions);
    closeModal($('uploadModal')); startNewAnalysis(); showToast('Dataset activated');
  } catch (error) { $('uploadStatus').textContent = error.message; $('uploadStatus').classList.add('error'); }
  finally { button.disabled = false; button.textContent = 'Activate dataset'; }
}

async function deleteDataset() {
  if (!state.activeUploadSession) return;
  if (!window.confirm('Remove this isolated upload and return to the default dataset?')) return;
  try {
    await fetch(`/api/uploads/${state.activeUploadSession}/delete`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    state.activeUploadSession = null; state.uploadTable = null; $('activeDatasetBanner').hidden = true;
    await loadConfig(); startNewAnalysis(); showToast('Uploaded dataset removed');
  } catch (error) { showToast(`Could not remove dataset: ${error.message}`); }
}

function renderChart(spec, refs = null, onCitation = showCitation) {
  const card = refs?.card || $('chartCard'); const body = refs?.body || $('chartBody'); const note = refs?.note || $('chartNote');
  body.innerHTML = ''; note.hidden = true;
  if (!spec || spec.type === 'table' || (!spec.points?.length && spec.type !== 'kpi')) { card.hidden = true; return; }
  card.hidden = false; (refs?.title || $('chartTitle')).textContent = spec.title || 'Visual summary';
  if (spec.alt_text) body.setAttribute('aria-label', spec.alt_text);
  if (spec.note) { note.textContent = spec.note; note.hidden = false; }
  if (spec.type === 'kpi') {
    body.innerHTML = `<div class="kpi-chart"><div><strong>${escapeHtml(spec.kpi_value ?? spec.points?.[0]?.y ?? '—')}</strong><span>${escapeHtml(spec.kpi_label || spec.title || '')}</span></div></div>`;
    return;
  }
  const points = spec.points || [];
  if (spec.type === 'line') renderLineChart(body, points, onCitation);
  else renderBarChart(body, points, spec.type === 'diverging_bar', onCitation);
}

function renderBarChart(container, points, diverging, onCitation = showCitation) {
  const width = 840, rowHeight = 42, left = 180, right = 100, height = Math.max(170, points.length * rowHeight + 35);
  const values = points.map((point) => Number(Array.isArray(point.y) ? point.y[0] : point.y) || 0);
  const max = Math.max(...values.map(Math.abs), 1); const plotWidth = width - left - right; const mid = diverging ? left + plotWidth / 2 : left;
  let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">`;
  points.forEach((point, index) => {
    const value = values[index]; const y = 15 + index * rowHeight; const available = diverging ? plotWidth / 2 : plotWidth;
    const barWidth = Math.max(3, Math.abs(value) / max * available); const x = diverging && value < 0 ? mid - barWidth : mid;
    svg += `<g data-row-id="${escapeHtml(point.row_id || '')}"><text class="chart-label" x="${left - 12}" y="${y + 15}" text-anchor="end">${escapeHtml(String(point.x || '').slice(0, 26))}</text><rect class="chart-bar" x="${x}" y="${y}" width="${barWidth}" height="22" rx="5"></rect><text class="chart-value" x="${diverging && value < 0 ? x - 8 : x + barWidth + 8}" y="${y + 15}" text-anchor="${diverging && value < 0 ? 'end' : 'start'}">${escapeHtml(value.toLocaleString(undefined, { maximumFractionDigits: 2 }))}</text></g>`;
  });
  container.innerHTML = `${svg}</svg>`;
  bindChartRows(container, onCitation);
}

function renderLineChart(container, points, onCitation = showCitation) {
  const width = 840, height = 300, left = 60, right = 35, top = 20, bottom = 50;
  const values = points.map((point) => Number(Array.isArray(point.y) ? point.y[0] : point.y) || 0); const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min || 1;
  const coords = points.map((point, index) => ({ point, value: values[index], x: left + (points.length > 1 ? index * (width - left - right) / (points.length - 1) : (width - left - right) / 2), y: top + (height - top - bottom) * (1 - (values[index] - min) / range) }));
  let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">`;
  for (let index = 0; index <= 4; index += 1) { const y = top + index * (height - top - bottom) / 4; svg += `<line class="chart-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line>`; }
  svg += `<path class="chart-line" d="${coords.map((coord, index) => `${index ? 'L' : 'M'} ${coord.x} ${coord.y}`).join(' ')}"></path>`;
  coords.forEach(({ point, value, x, y }, index) => { svg += `<g data-row-id="${escapeHtml(point.row_id || '')}"><circle class="chart-point" cx="${x}" cy="${y}" r="5"></circle><text class="chart-label" x="${x}" y="${height - 20}" text-anchor="middle">${escapeHtml(String(point.x || '').slice(0, 15))}</text>${index === coords.length - 1 ? `<text class="chart-value" x="${x - 6}" y="${y - 12}" text-anchor="end">${escapeHtml(value.toLocaleString(undefined, { maximumFractionDigits: 2 }))}</text>` : ''}</g>`; });
  container.innerHTML = `${svg}</svg>`; bindChartRows(container, onCitation);
}

function bindChartRows(container, onCitation = showCitation) {
  container.querySelectorAll('[data-row-id]').forEach((element) => { element.style.cursor = element.dataset.rowId ? 'pointer' : 'default'; element.addEventListener('click', () => element.dataset.rowId && onCitation(element.dataset.rowId)); });
}

