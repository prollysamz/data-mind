let currentResult = null;
let currentAbortController = null;
let queryTimerInterval = null;
let queryStartTime = null;
let activeUploadSession = null;
let currentUploadTableMeta = null;

document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  initModal();
  initActions();
  initUploads();
  await loadConfig();

  const form = document.getElementById('askForm');
  const input = document.getElementById('questionInput');
  const newChatBtn = document.getElementById('newChatBtn');
  const cancelBtn = document.getElementById('cancelQueryBtn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    await executeQuery(query);
  });

  if (newChatBtn) {
    newChatBtn.addEventListener('click', () => {
      resetConversation();
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (currentAbortController) {
        currentAbortController.abort();
      }
    });
  }
});

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    const backendEl = document.getElementById('backendName');
    if (backendEl && data.backend) {
      backendEl.textContent = data.backend.toUpperCase();
    }
    const modelEl = document.getElementById('modelName');
    if (modelEl && data.model_name) {
      modelEl.textContent = data.model_name;
    }

    const privacyEl = document.getElementById('privacyStatus');
    if (privacyEl && data.privacy_indicator) {
      privacyEl.textContent = data.privacy_indicator;
    }

    // Dynamic Sample Questions from Semantic Model
    const chipsList = document.getElementById('chipsList');
    if (chipsList && data.sample_questions && data.sample_questions.length) {
      chipsList.innerHTML = '';
      data.sample_questions.forEach(q => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'chip';
        btn.textContent = q.length > 55 ? q.substring(0, 52) + '...' : q;
        btn.title = q;
        btn.setAttribute('data-q', q);
        btn.addEventListener('click', () => {
          document.getElementById('questionInput').value = q;
          document.getElementById('askForm').dispatchEvent(new Event('submit'));
        });
        chipsList.appendChild(btn);
      });
    }
  } catch (err) {
    console.error('Failed to load config:', err);
    document.getElementById('backendName').textContent = 'OFFLINE';
  }
}

function resetConversation() {
  currentResult = null;
  document.getElementById('questionInput').value = '';
  document.getElementById('resultsContainer').style.display = 'none';
  document.getElementById('errorState').style.display = 'none';
  document.getElementById('loadingState').style.display = 'none';
  document.getElementById('emptyState').style.display = 'flex';
  document.getElementById('conversationThread').innerHTML = '';
}

function startTimer() {
  queryStartTime = performance.now();
  const timerEl = document.getElementById('elapsedTimer');
  const stagePlanning = document.getElementById('stagePlanning');
  const stageGuard = document.getElementById('stageGuard');
  const stageExec = document.getElementById('stageExec');
  const stageAudit = document.getElementById('stageAudit');

  // Reset stages
  [stagePlanning, stageGuard, stageExec, stageAudit].forEach(s => {
    if (s) {
      s.className = 'stage-pill';
    }
  });
  if (stagePlanning) stagePlanning.className = 'stage-pill active';

  queryTimerInterval = setInterval(() => {
    const elapsedSec = ((performance.now() - queryStartTime) / 1000).toFixed(1);
    if (timerEl) timerEl.textContent = `${elapsedSec}s`;

    // Progress simulation through real lifecycle stages
    if (elapsedSec > 0.8 && stageGuard && !stageGuard.classList.contains('active') && !stageGuard.classList.contains('done')) {
      if (stagePlanning) stagePlanning.className = 'stage-pill done';
      stageGuard.className = 'stage-pill active';
    }
    if (elapsedSec > 1.8 && stageExec && !stageExec.classList.contains('active') && !stageExec.classList.contains('done')) {
      if (stageGuard) stageGuard.className = 'stage-pill done';
      stageExec.className = 'stage-pill active';
    }
    if (elapsedSec > 3.2 && stageAudit && !stageAudit.classList.contains('active') && !stageAudit.classList.contains('done')) {
      if (stageExec) stageExec.className = 'stage-pill done';
      stageAudit.className = 'stage-pill active';
    }
  }, 100);
}

function stopTimer() {
  if (queryTimerInterval) {
    clearInterval(queryTimerInterval);
    queryTimerInterval = null;
  }
}

async function executeQuery(question) {
  const submitBtn = document.getElementById('submitBtn');
  const btnSpinner = document.getElementById('btnSpinner');
  const btnText = submitBtn.querySelector('.btn-text');
  const sendIcon = submitBtn.querySelector('.send-icon');
  const emptyState = document.getElementById('emptyState');
  const resultsContainer = document.getElementById('resultsContainer');
  const loadingState = document.getElementById('loadingState');
  const errorState = document.getElementById('errorState');
  const isStrict = document.getElementById('strictModeToggle').checked;

  submitBtn.disabled = true;
  btnSpinner.style.display = 'block';
  sendIcon.style.display = 'none';
  btnText.textContent = 'Analyzing...';

  if (emptyState) emptyState.style.display = 'none';
  if (resultsContainer) resultsContainer.style.display = 'none';
  if (errorState) errorState.style.display = 'none';
  if (loadingState) loadingState.style.display = 'flex';

  currentAbortController = new AbortController();
  startTimer();

  try {
    const targetUrl = activeUploadSession ? `/api/uploads/${activeUploadSession}/ask` : '/api/ask';
    const selectedPreset = document.getElementById('modelPresetSelect')?.value || 'local';
    const res = await fetch(targetUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        permissive: !isStrict,
        preset: selectedPreset,
      }),
      signal: currentAbortController.signal,
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      if (data.error_type === 'budget_exceeded') {
        const err = new Error(data.message || data.error || 'Budget limit reached.');
        err.isBudget = true;
        throw err;
      }
      throw new Error(data.error || `Server returned HTTP ${res.status}`);
    }

    currentResult = data;
    renderResult(data);

    if (loadingState) loadingState.style.display = 'none';
    if (resultsContainer) resultsContainer.style.display = 'flex';
  } catch (err) {
    if (loadingState) loadingState.style.display = 'none';
    if (errorState) {
      if (err.name === 'AbortError') {
        document.getElementById('errorTitle').textContent = 'Query Cancelled';
        document.getElementById('errorMessage').textContent = 'Query execution was cancelled by user.';
      } else {
        document.getElementById('errorTitle').textContent = err.isBudget ? 'Budget Limit Reached' : 'Query Execution Failed';
        document.getElementById('errorMessage').textContent = err.message || 'An unexpected error occurred during execution.';
      }
      errorState.style.display = 'flex';
    }
  } finally {
    stopTimer();
    currentAbortController = null;
    submitBtn.disabled = false;
    btnSpinner.style.display = 'none';
    sendIcon.style.display = 'block';
    btnText.textContent = 'Run Query';
  }
}

function renderResult(data) {
  document.getElementById('questionEcho').textContent = data.question;

  // Render Three-State Trust Badges
  const trustDiv = document.getElementById('trustSummary');
  trustDiv.innerHTML = '';

  const badgeInfo = data.trust_badge || {};
  const badgeState = badgeInfo.state || 'VERIFIED';

  const mainBadge = document.createElement('span');
  mainBadge.className = 'trust-badge';

  if (badgeState === 'VERIFIED') {
    mainBadge.classList.add('badge-clean-pass');
    mainBadge.innerHTML = `&#10003; ${badgeInfo.label || 'Verified Grounded'}`;
  } else if (badgeState === 'PARTIALLY_VERIFIED') {
    mainBadge.style.background = 'rgba(234, 179, 8, 0.15)';
    mainBadge.style.color = '#eab308';
    mainBadge.style.border = '1px solid rgba(234, 179, 8, 0.4)';
    mainBadge.innerHTML = `&#9888; ${badgeInfo.label || 'Partially Verified'}`;
  } else if (badgeState === 'NOT_VERIFIED') {
    mainBadge.classList.add('badge-clean-fail');
    mainBadge.innerHTML = `&#9888; ${badgeInfo.label || 'Not Verified'}`;
  } else if (badgeState === 'REFUSAL') {
    mainBadge.style.background = 'rgba(245, 158, 11, 0.15)';
    mainBadge.style.color = '#f59e0b';
    mainBadge.style.border = '1px solid rgba(245, 158, 11, 0.4)';
    mainBadge.innerHTML = `&#9888; ${badgeInfo.label || 'Schema Boundary'}`;
  } else if (badgeState === 'CLARIFICATION') {
    mainBadge.style.background = 'rgba(168, 85, 247, 0.15)';
    mainBadge.style.color = '#a855f7';
    mainBadge.style.border = '1px solid rgba(168, 85, 247, 0.4)';
    mainBadge.innerHTML = `&#9432; ${badgeInfo.label || 'Clarification'}`;
  }
  trustDiv.appendChild(mainBadge);

  const citReport = data.citation_report || {};
  if (citReport.verified_numbers_count > 0) {
    const numBadge = document.createElement('span');
    numBadge.className = 'trust-badge badge-num-verified';
    numBadge.textContent = `${citReport.verified_numbers_count} Numbers Verified`;
    trustDiv.appendChild(numBadge);
  }

  if (citReport.discrepancy_count > 0) {
    const discBadge = document.createElement('span');
    discBadge.className = 'trust-badge badge-clean-fail';
    discBadge.textContent = `${citReport.discrepancy_count} Discrepancies`;
    trustDiv.appendChild(discBadge);
  }

  // Handle Clarification state quick-replies
  const clarifyCard = document.getElementById('clarifyCard');
  const clarifyChips = document.getElementById('clarifyChips');
  if (data.response_type === 'clarification') {
    clarifyCard.style.display = 'block';
    clarifyChips.innerHTML = '';
    const suggestions = [
      'Total revenue across all products',
      'Month-over-month revenue decline',
      'Customer support tickets by priority',
      'Average order line amount',
    ];
    suggestions.forEach(s => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'clarify-chip';
      btn.textContent = s;
      btn.addEventListener('click', () => {
        document.getElementById('questionInput').value = s;
        document.getElementById('askForm').dispatchEvent(new Event('submit'));
      });
      clarifyChips.appendChild(btn);
    });
  } else {
    clarifyCard.style.display = 'none';
  }

  // Render Query Method & Assumptions Card (AST Linter Integrity)
  renderAssumptionsCard(data.assumptions_card);

  // Render Answer Markdown
  const answerContent = document.getElementById('answerContent');
  answerContent.innerHTML = formatMarkdownWithCitations(data.answer, data);

  // Bind click handlers to citation pills
  answerContent.querySelectorAll('.citation-token').forEach(pill => {
    pill.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = pill.getAttribute('data-citation');
      handleCitationClick(targetId);
    });
  });

  // Render SVG Chart
  renderChart(data.chart);

  // Render Under The Hood Metadata
  renderUnderTheHood(data);

  // Render Inspector Tab 1: SQL Queries
  const queries = (data.evidence && data.evidence.queries) || [];
  document.getElementById('sqlCount').textContent = queries.length;
  renderQueries(queries);

  // Render Inspector Tab 2: Document Chunks
  const docs = (data.evidence && data.evidence.chunks) || [];
  document.getElementById('docsCount').textContent = docs.length;
  renderDocs(docs);

  // Render Inspector Tab 3: Numeric Checks
  const checks = (citReport.numeric_checks) || [];
  document.getElementById('numChecksCount').textContent = checks.length;
  renderNumericChecks(checks);
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderAssumptionsCard(card) {
  const box = document.getElementById('assumptionsBox');
  const badge = document.getElementById('assumptionsBadge');
  const body = document.getElementById('assumptionsBody');
  if (!box || !badge || !body) return;

  if (!card) {
    box.style.display = 'none';
    return;
  }

  box.style.display = 'block';
  const isAmber = card.badge_status === 'PARTIALLY_VERIFIED';
  badge.textContent = isAmber ? 'Partially Verified Method' : 'Verified Method';
  if (isAmber) {
    badge.className = 'assumptions-badge badge-amber';
    box.open = true; // Auto-expand when there are lint diagnostics
  } else {
    badge.className = 'assumptions-badge';
    box.open = false;
  }

  let html = '<div class="assumptions-grid">';
  if (card.tables && card.tables.length) {
    html += `<div class="assumptions-item"><div class="assumptions-item-label">Tables Used</div><div class="assumptions-item-val">${escapeHtml(card.tables.join(', '))}</div></div>`;
  }
  if (card.join_keys && card.join_keys.length) {
    html += `<div class="assumptions-item"><div class="assumptions-item-label">Join Keys</div><div class="assumptions-item-val">${escapeHtml(card.join_keys.join('; '))}</div></div>`;
  }
  if (card.filters && card.filters.length) {
    html += `<div class="assumptions-item"><div class="assumptions-item-label">Business Filters</div><div class="assumptions-item-val">${escapeHtml(card.filters.join(' AND '))}</div></div>`;
  }
  if (card.group_by && card.group_by.length) {
    html += `<div class="assumptions-item"><div class="assumptions-item-label">Grouping</div><div class="assumptions-item-val">${escapeHtml(card.group_by.join(', '))}</div></div>`;
  }
  if (card.metrics && card.metrics.length) {
    html += `<div class="assumptions-item"><div class="assumptions-item-label">Metric Aggregations</div><div class="assumptions-item-val">${escapeHtml(card.metrics.join(', '))}</div></div>`;
  }
  if (card.date_range) {
    html += `<div class="assumptions-item"><div class="assumptions-item-label">Date Window</div><div class="assumptions-item-val">${escapeHtml(card.date_range)}</div></div>`;
  }
  html += '</div>';

  if (card.plain_language_assumptions && card.plain_language_assumptions.length) {
    html += '<ul style="margin: 0.5rem 0 0.5rem 1.25rem; padding: 0;">';
    card.plain_language_assumptions.forEach(item => {
      html += `<li>${escapeHtml(item)}</li>`;
    });
    html += '</ul>';
  }

  if (card.lint_findings && card.lint_findings.length) {
    html += '<div class="assumptions-warnings">';
    html += '<div class="assumptions-warning-title">&#9888; Structural Integrity &amp; Lint Diagnostics:</div>';
    html += '<ul style="margin: 0.25rem 0 0 1.25rem; padding: 0;">';
    card.lint_findings.forEach(f => {
      html += `<li><strong>[${escapeHtml((f.severity || '').toUpperCase())}]</strong> ${escapeHtml(f.message)}</li>`;
    });
    html += '</ul></div>';
  }

  body.innerHTML = html;
}

// -------------------------------------------------------------
// Pure SVG Dependency-Free Chart Renderer (Bar, Horizontal Bar, Line, KPI)
// -------------------------------------------------------------
function renderChart(chartSpec) {
  const chartCard = document.getElementById('chartCard');
  const chartBody = document.getElementById('chartBody');
  const chartTitle = document.getElementById('chartTitle');
  const chartBadge = document.getElementById('chartTypeBadge');
  const chartNote = document.getElementById('chartNote');

  chartBody.innerHTML = '';
  chartNote.style.display = 'none';

  if (!chartSpec || chartSpec.type === 'table' || !chartSpec.points || !chartSpec.points.length) {
    chartCard.style.display = 'none';
    return;
  }

  chartCard.style.display = 'flex';
  chartTitle.textContent = chartSpec.title || 'Data Visualization';
  chartBadge.textContent = (chartSpec.type || 'chart').replace('_', ' ').toUpperCase();

  if (chartSpec.alt_text) {
    chartBody.setAttribute('aria-label', chartSpec.alt_text);
  }

  if (chartSpec.note) {
    chartNote.textContent = chartSpec.note;
    chartNote.style.display = 'block';
  }

  try {
    if (chartSpec.type === 'kpi') {
      renderKpiChart(chartBody, chartSpec);
    } else if (chartSpec.type === 'horizontal_bar') {
      renderHorizontalBarChart(chartBody, chartSpec);
    } else if (chartSpec.type === 'diverging_bar') {
      renderDivergingBarChart(chartBody, chartSpec);
    } else if (chartSpec.type === 'line') {
      renderLineChart(chartBody, chartSpec);
    } else {
      chartCard.style.display = 'none';
    }
  } catch (err) {
    console.warn('SVG chart render fallback to table:', err);
    chartBody.innerHTML = '<p class="chart-footer-note">Detailed tabular rows available in the inspector table below.</p>';
  }
}

function renderKpiChart(container, spec) {
  const wrap = document.createElement('div');
  wrap.className = 'chart-kpi-container';
  wrap.innerHTML = `
    <div class="chart-kpi-value">${spec.kpi_value || '0'}</div>
    <div class="chart-kpi-label">${spec.kpi_label || spec.title}</div>
  `;
  container.appendChild(wrap);
}

function renderHorizontalBarChart(container, spec) {
  const points = spec.points || [];
  if (!points.length) return;

  const width = 760;
  const barHeight = 24;
  const barGap = 12;
  const labelWidth = 140;
  const valueWidth = 100;
  const plotWidth = width - labelWidth - valueWidth;
  const height = points.length * (barHeight + barGap) + 30;

  const maxVal = Math.max(...points.map(p => Number(p.y) || 0), 1);

  let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" role="img">`;

  points.forEach((p, idx) => {
    const y = idx * (barHeight + barGap) + 10;
    const val = Number(p.y) || 0;
    const barW = Math.max(4, (val / maxVal) * plotWidth);
    const label = String(p.x || '');
    const cleanLabel = label.length > 18 ? label.substring(0, 16) + '...' : label;
    const formattedVal = val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });

    svg += `
      <g class="chart-bar-group" data-row-id="${p.row_id}" tabindex="0" role="button" aria-label="${label}: ${formattedVal}">
        <title>${label}: ${formattedVal} (Click to inspect row ${p.row_id})</title>
        <text x="${labelWidth - 10}" y="${y + 16}" text-anchor="end" class="chart-axis-text">${cleanLabel}</text>
        <rect x="${labelWidth}" y="${y}" width="${plotWidth}" height="${barHeight}" rx="4" fill="rgba(255,255,255,0.03)" />
        <rect x="${labelWidth}" y="${y}" width="${barW}" height="${barHeight}" rx="4" fill="url(#barGrad)" class="chart-bar-rect" data-row-id="${p.row_id}" />
        <text x="${labelWidth + barW + 10}" y="${y + 16}" class="chart-bar-value" fill="#38bdf8">${formattedVal}</text>
      </g>
    `;
  });

  svg += `
    <defs>
      <linearGradient id="barGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#6366f1" />
        <stop offset="100%" stop-color="#38bdf8" />
      </linearGradient>
    </defs>
  </svg>`;

  container.innerHTML = svg;
  bindChartClicks(container);
}

function renderDivergingBarChart(container, spec) {
  const points = spec.points || [];
  if (!points.length) return;

  const width = 760;
  const barHeight = 24;
  const barGap = 12;
  const labelWidth = 140;
  const plotWidth = width - labelWidth - 40;
  const height = points.length * (barHeight + barGap) + 30;

  const maxAbs = Math.max(...points.map(p => Math.abs(Number(p.y) || 0)), 1);
  const midX = labelWidth + plotWidth / 2;

  let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" role="img">`;
  svg += `<line x1="${midX}" y1="5" x2="${midX}" y2="${height - 10}" stroke="rgba(255,255,255,0.25)" stroke-width="1.5" />`;

  points.forEach((p, idx) => {
    const y = idx * (barHeight + barGap) + 10;
    const val = Number(p.y) || 0;
    const barW = Math.max(4, (Math.abs(val) / maxAbs) * (plotWidth / 2));
    const isNeg = val < 0;
    const barX = isNeg ? midX - barW : midX;
    const color = isNeg ? '#ef4444' : '#10b981';
    const label = String(p.x || '');
    const cleanLabel = label.length > 18 ? label.substring(0, 16) + '...' : label;
    const formattedVal = val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });

    svg += `
      <g class="chart-bar-group" data-row-id="${p.row_id}" tabindex="0" role="button" aria-label="${label}: ${formattedVal}">
        <title>${label}: ${formattedVal} (Click to inspect row ${p.row_id})</title>
        <text x="${labelWidth - 10}" y="${y + 16}" text-anchor="end" class="chart-axis-text">${cleanLabel}</text>
        <rect x="${barX}" y="${y}" width="${barW}" height="${barHeight}" rx="4" fill="${color}" class="chart-bar-rect ${isNeg ? 'chart-bar-neg' : ''}" data-row-id="${p.row_id}" />
        <text x="${isNeg ? barX - 8 : barX + barW + 8}" y="${y + 16}" text-anchor="${isNeg ? 'end' : 'start'}" class="chart-bar-value" fill="${color}">${formattedVal}</text>
      </g>
    `;
  });

  svg += '</svg>';
  container.innerHTML = svg;
  bindChartClicks(container);
}

function renderLineChart(container, spec) {
  const points = spec.points || [];
  if (!points.length) return;

  const width = 760;
  const height = 280;
  const padLeft = 70;
  const padRight = 30;
  const padTop = 20;
  const padBottom = 40;

  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const values = points.map(p => Number(Array.isArray(p.y) ? p.y[0] : p.y) || 0);
  const minVal = Math.min(0, ...values);
  const maxVal = Math.max(...values, 1);
  const valRange = maxVal - minVal || 1;

  const xStep = points.length > 1 ? plotW / (points.length - 1) : plotW / 2;

  const coords = points.map((p, idx) => {
    const val = Number(Array.isArray(p.y) ? p.y[0] : p.y) || 0;
    const cx = padLeft + idx * xStep;
    const cy = padTop + plotH - ((val - minVal) / valRange) * plotH;
    return { cx, cy, p, val };
  });

  const pathD = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.cx.toFixed(1)} ${c.cy.toFixed(1)}`).join(' ');

  let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" role="img">`;

  // Grid lines
  for (let i = 0; i <= 4; i++) {
    const gy = padTop + (plotH / 4) * i;
    const gVal = (maxVal - (valRange / 4) * i).toLocaleString(undefined, { maximumFractionDigits: 0 });
    svg += `
      <line x1="${padLeft}" y1="${gy}" x2="${width - padRight}" y2="${gy}" class="chart-grid-line" />
      <text x="${padLeft - 8}" y="${gy + 4}" text-anchor="end" class="chart-axis-text">${gVal}</text>
    `;
  }

  // Line path
  svg += `<path d="${pathD}" class="chart-line-path" stroke="url(#lineGrad)" />`;

  // Data points
  coords.forEach(c => {
    const label = String(c.p.x || '');
    const formattedVal = c.val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    svg += `
      <g data-row-id="${c.p.row_id}" tabindex="0" role="button" aria-label="${label}: ${formattedVal}">
        <title>${label}: ${formattedVal} (Click to inspect row ${c.p.row_id})</title>
        <circle cx="${c.cx}" cy="${c.cy}" r="5" fill="#38bdf8" stroke="#0f172a" stroke-width="2" class="chart-point-circle" data-row-id="${c.p.row_id}" />
        <text x="${c.cx}" y="${height - padBottom + 18}" text-anchor="middle" class="chart-axis-text">${label}</text>
      </g>
    `;
  });

  svg += `
    <defs>
      <linearGradient id="lineGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#38bdf8" />
        <stop offset="100%" stop-color="#818cf8" />
      </linearGradient>
    </defs>
  </svg>`;

  container.innerHTML = svg;
  bindChartClicks(container);
}

function bindChartClicks(container) {
  container.querySelectorAll('[data-row-id]').forEach(el => {
    el.addEventListener('click', () => {
      const rowId = el.getAttribute('data-row-id');
      if (rowId) {
        highlightTableRow(rowId);
      }
    });
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const rowId = el.getAttribute('data-row-id');
        if (rowId) highlightTableRow(rowId);
      }
    });
  });
}

function highlightTableRow(rowId) {
  // 1. Switch to SQL Tab
  const sqlTabBtn = document.querySelector('[data-tab="sqlTab"]');
  if (sqlTabBtn) sqlTabBtn.click();

  // 2. Find matching row element
  const targetRow = document.querySelector(`[data-row-id="${rowId}"]`);
  if (targetRow) {
    document.querySelectorAll('.highlighted-row').forEach(r => r.classList.remove('highlighted-row'));
    targetRow.classList.add('highlighted-row');
    targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

function renderUnderTheHood(data) {
  const hoodMeta = document.getElementById('hoodMeta');
  if (!hoodMeta) return;

  const hood = data.under_the_hood || {};
  const queries = (data.evidence && data.evidence.queries) || [];
  const primaryQ = queries[0] || {};
  const elapsedMs = primaryQ.result ? primaryQ.result.elapsed_ms : 0;
  const rowsCount = primaryQ.result && primaryQ.result.rows ? primaryQ.result.rows.length : 0;

  hoodMeta.innerHTML = `
    <span class="hood-pill">Dialect: ${hood.dialect ? hood.dialect.toUpperCase() : 'DUCKDB'}</span>
    <span class="hood-pill">Rows: ${rowsCount}</span>
    <span class="hood-pill">Latency: ${elapsedMs ? elapsedMs.toFixed(1) : '<1'}ms</span>
    <span class="hood-pill">Model: ${hood.model || 'gemma4:e2b'}</span>
    <span class="hood-pill">Status: ${hood.verification_status || 'VERIFIED'}</span>
  `;
}

function initActions() {
  const copyAnswerBtn = document.getElementById('copyAnswerBtn');
  const copySqlBtn = document.getElementById('copySqlBtn');
  const exportCsvBtn = document.getElementById('exportCsvBtn');

  if (copyAnswerBtn) {
    copyAnswerBtn.addEventListener('click', () => {
      if (!currentResult || !currentResult.answer) return;
      navigator.clipboard.writeText(currentResult.answer).then(() => {
        copyAnswerBtn.textContent = '✓ Copied!';
        setTimeout(() => { copyAnswerBtn.textContent = 'Copy Answer'; }, 2000);
      });
    });
  }

  if (copySqlBtn) {
    copySqlBtn.addEventListener('click', () => {
      const queries = (currentResult && currentResult.evidence && currentResult.evidence.queries) || [];
      if (!queries.length) return;
      const sqlText = queries.map(q => q.sql).join('\n\n');
      navigator.clipboard.writeText(sqlText).then(() => {
        copySqlBtn.textContent = '✓ SQL Copied!';
        setTimeout(() => { copySqlBtn.textContent = 'Copy SQL'; }, 2000);
      });
    });
  }

  if (exportCsvBtn) {
    exportCsvBtn.addEventListener('click', () => {
      exportResultCsv();
    });
  }

  // Second Opinion Cross-Model Consensus
  const secondOpinionBtn = document.getElementById('secondOpinionBtn');
  if (secondOpinionBtn) {
    secondOpinionBtn.addEventListener('click', async () => {
      if (!currentResult) {
        alert('Please run a query first before requesting a second opinion.');
        return;
      }
      const queries = (currentResult.evidence && currentResult.evidence.queries) || [];
      const primarySql = queries.length ? queries[0].sql : '';
      if (!primarySql) {
        alert('No executed SQL query available for second opinion.');
        return;
      }
      secondOpinionBtn.textContent = '⏳ Comparing...';
      try {
        const resp = await fetch('/api/second_opinion', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            primary_sql: primarySql,
            primary_model: (currentResult.under_the_hood && currentResult.under_the_hood.model) || 'gemma4:e2b',
            secondary_model: 'gemma4:e4b',
          }),
        });
        const soData = await resp.json();
        openSecondOpinionModal(soData);
      } catch (err) {
        alert('Second opinion error: ' + err);
      } finally {
        secondOpinionBtn.textContent = '👥 Second Opinion';
      }
    });
  }

  // Verifiable Cryptographic Receipt
  const receiptBtn = document.getElementById('receiptBtn');
  if (receiptBtn) {
    receiptBtn.addEventListener('click', () => {
      if (!currentResult) {
        alert('Please run a query first before viewing the cryptographic receipt.');
        return;
      }
      if (!currentResult.receipt) {
        alert('No cryptographic receipt available for this result.');
        return;
      }
      openReceiptModal(currentResult.receipt);
    });
  }

  // Red-Team Live Adversarial Challenge
  const redTeamBtn = document.getElementById('redTeamBtn');
  if (redTeamBtn) {
    redTeamBtn.addEventListener('click', async () => {
      redTeamBtn.textContent = '⚔️ Attacking...';
      try {
        const resp = await fetch('/api/red_team', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            answer: currentResult ? currentResult.answer : '',
            evidence: currentResult ? currentResult.evidence : {},
          }),
        });
        const rtData = await resp.json();
        openRedTeamModal(rtData);
      } catch (err) {
        alert('Red-team error: ' + err);
      } finally {
        redTeamBtn.textContent = '🛡️ Red-Team Attack';
      }
    });
  }

  // Model & Preset Selector + Cloud Consent
  const modelSelect = document.getElementById('modelPresetSelect');
  if (modelSelect) {
    modelSelect.addEventListener('change', (e) => {
      const val = e.target.value;
      if (val === 'cloud_accuracy' || val === 'hybrid_privacy') {
        const consentModal = document.getElementById('cloudConsentModal');
        if (consentModal) consentModal.style.display = 'flex';
      } else {
        const privacyStatus = document.getElementById('privacyStatus');
        if (privacyStatus) privacyStatus.textContent = 'Air-Gapped: 0 Egress';
      }
    });
  }

  // Modal Close Handlers
  const closeSoBtn = document.getElementById('closeSecondOpinionBtn');
  if (closeSoBtn) closeSoBtn.addEventListener('click', () => {
    document.getElementById('secondOpinionModal').style.display = 'none';
  });
  const closeRcBtn = document.getElementById('closeReceiptBtn');
  if (closeRcBtn) closeRcBtn.addEventListener('click', () => {
    document.getElementById('receiptModal').style.display = 'none';
  });
  const closeRtBtn = document.getElementById('closeRedTeamBtn');
  if (closeRtBtn) closeRtBtn.addEventListener('click', () => {
    document.getElementById('redTeamModal').style.display = 'none';
  });
  const closeConsentBtn = document.getElementById('closeConsentBtn');
  if (closeConsentBtn) closeConsentBtn.addEventListener('click', () => {
    document.getElementById('cloudConsentModal').style.display = 'none';
  });
  const cancelConsentBtn = document.getElementById('cancelConsentBtn');
  if (cancelConsentBtn) cancelConsentBtn.addEventListener('click', () => {
    document.getElementById('cloudConsentModal').style.display = 'none';
    if (modelSelect) modelSelect.value = 'local';
    const privacyStatus = document.getElementById('privacyStatus');
    if (privacyStatus) privacyStatus.textContent = 'Air-Gapped: 0 Egress';
  });
  const confirmConsentBtn = document.getElementById('confirmConsentBtn');
  if (confirmConsentBtn) confirmConsentBtn.addEventListener('click', () => {
    document.getElementById('cloudConsentModal').style.display = 'none';
    const privacyStatus = document.getElementById('privacyStatus');
    if (privacyStatus) privacyStatus.textContent = 'Schema-Only Cloud';
  });

  // Receipt Download Buttons
  const dlJsonBtn = document.getElementById('downloadReceiptJsonBtn');
  if (dlJsonBtn) {
    dlJsonBtn.addEventListener('click', () => {
      if (!currentResult || !currentResult.receipt) return;
      const jsonStr = JSON.stringify(currentResult.receipt, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `datamind_receipt_${currentResult.receipt.root_hash.slice(0, 8)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
  }

  const openHtmlBtn = document.getElementById('openReceiptHtmlBtn');
  if (openHtmlBtn) {
    openHtmlBtn.addEventListener('click', async () => {
      if (!currentResult || !currentResult.receipt) return;
      try {
        const resp = await fetch('/api/receipt/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ receipt: currentResult.receipt }),
        });
        const resJson = await resp.json();
        if (resJson.html) {
          const blob = new Blob([resJson.html], { type: 'text/html' });
          const url = URL.createObjectURL(blob);
          window.open(url, '_blank');
        }
      } catch (err) {
        alert('Failed to open HTML receipt: ' + err);
      }
    });
  }
}

function openSecondOpinionModal(data) {
  const modal = document.getElementById('secondOpinionModal');
  if (!modal) return;
  modal.style.display = 'flex';

  const badge = document.getElementById('soVerdictBadge');
  if (badge) {
    badge.textContent = data.verdict_label || data.verdict || 'Opinion';
    badge.className = (data.verdict && data.verdict.startsWith('AGREE')) ? 'badge-pill badge-emerald' : 'badge-pill badge-amber';
  }

  const exp = document.getElementById('soExplanation');
  if (exp) exp.textContent = data.explanation || '';

  const pTag = document.getElementById('soPrimaryModelTag');
  if (pTag) pTag.textContent = `Primary: ${data.primary_model || 'Local'}`;
  const sTag = document.getElementById('soSecondaryModelTag');
  if (sTag) sTag.textContent = `Secondary: ${data.secondary_model || 'Verifier'}`;

  const pSql = document.getElementById('soPrimarySql');
  if (pSql) pSql.textContent = data.primary_sql || '';
  const sSql = document.getElementById('soSecondarySql');
  if (sSql) sSql.textContent = data.secondary_sql || '';

  const pRows = document.getElementById('soPrimaryRows');
  if (pRows) pRows.textContent = `Returned ${data.primary_row_count} rows`;
  const sRows = document.getElementById('soSecondaryRows');
  if (sRows) sRows.textContent = `Returned ${data.secondary_row_count} rows`;

  const diffContent = document.getElementById('soDiffContent');
  if (diffContent && data.assumptions_diff) {
    const diff = data.assumptions_diff;
    let html = '';
    if (diff.filters_diff && diff.filters_diff.length) {
      html += `<div style="margin-bottom:0.4rem;"><strong>Filter Differences:</strong> ${escapeHtml(diff.filters_diff.join('; '))}</div>`;
    }
    if (diff.tables_diff && diff.tables_diff.length) {
      html += `<div style="margin-bottom:0.4rem;"><strong>Table Differences:</strong> ${escapeHtml(diff.tables_diff.join('; '))}</div>`;
    }
    if (diff.metrics_diff && diff.metrics_diff.length) {
      html += `<div style="margin-bottom:0.4rem;"><strong>Metric Expression Differences:</strong> ${escapeHtml(diff.metrics_diff.join('; '))}</div>`;
    }
    if (!html) {
      html = '<div>All query structures, tables, and filters align across both models.</div>';
    }
    diffContent.innerHTML = html;
  }
}

function openReceiptModal(receipt) {
  const modal = document.getElementById('receiptModal');
  if (!modal) return;
  modal.style.display = 'flex';
  const rootBox = document.getElementById('modalRootHash');
  if (rootBox) rootBox.textContent = receipt.root_hash || 'SHA-256 Digest';
}

function openRedTeamModal(data) {
  const modal = document.getElementById('redTeamModal');
  if (!modal) return;
  modal.style.display = 'flex';

  const rateTag = document.getElementById('redTeamCatchRate');
  if (rateTag) rateTag.textContent = `${data.caught_count} / ${data.total_mutations} Caught (${data.catch_rate_pct}%)`;

  const list = document.getElementById('redTeamList');
  if (!list) return;
  list.innerHTML = '';

  (data.mutations || []).forEach(m => {
    const card = document.createElement('div');
    card.className = 'redteam-card';
    card.innerHTML = `
      <div class="redteam-card-header">
        <span class="redteam-mutation-title">${escapeHtml(m.name)}</span>
        <span class="badge-pill ${m.caught ? 'badge-emerald' : 'badge-amber'}">${m.caught ? '✓ CAUGHT BY VERIFIER' : 'MISSED'}</span>
      </div>
      <div class="redteam-mutation-body">${escapeHtml(m.mutated_text)}</div>
      <div class="redteam-diag">&#9888; <strong>Verifier Catch Diagnostic:</strong> ${escapeHtml(m.diagnostic)}</div>
    `;
    list.appendChild(card);
  });
}

function exportResultCsv() {
  const queries = (currentResult && currentResult.evidence && currentResult.evidence.queries) || [];
  if (!queries.length || !queries[0].result) {
    alert('No tabular data available to export.');
    return;
  }

  const q = queries[0];
  const cols = q.result.columns || [];
  const rows = q.result.rows || [];

  function sanitizeCell(cell) {
    if (cell === null || cell === undefined) return '""';
    let s = String(cell);
    // Escape formula injection prefixes: =, +, -, @
    if (/^[=+\-@]/.test(s)) {
      s = "'" + s;
    }
    // Escape quotes
    return '"' + s.replace(/"/g, '""') + '"';
  }

  const csvRows = [];
  csvRows.push(['"Row_ID"', ...cols.map(c => `"${c}"`)].join(','));

  rows.forEach((r, idx) => {
    const rowId = `"${q.query_label || 'Q1'}:R${idx + 1}"`;
    const cells = r.map(c => sanitizeCell(c));
    csvRows.push([rowId, ...cells].join(','));
  });

  const blob = new Blob([csvRows.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', `datamind_result_${Date.now()}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function formatMarkdownWithCitations(text, data) {
  if (!text) return '<p>No answer text produced.</p>';

  let formatted = text;

  // Clean raw markdown link syntax around citations if pasted e.g. [\[◆ Q1:R1\]](http...) or [Q1:R1](...)
  formatted = formatted.replace(/\[\\?\[?[◆\s]*(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\\?\]?\]\([^\)]+\)/g, '[[$1]]');

  // Convert markdown headings
  formatted = formatted.replace(/(?:^|\n)\s*###\s+(Revenue Decline (?:Details|Analysis)|[A-Z][A-Za-z0-9\s/&,\-]{2,40}?)\s+(?=[A-Z][a-z]+)/g, '\n<h3>$1</h3>\n');
  formatted = formatted.replace(/(?:^|\n)\s*####\s*([^\n<]+)/g, '\n<h4>$1</h4>\n');
  formatted = formatted.replace(/(?:^|\n)\s*###\s*([^\n<]+)/g, '\n<h3>$1</h3>\n');
  formatted = formatted.replace(/(?:^|\n)\s*##\s*([^\n<]+)/g, '\n<h2>$1</h2>\n');
  formatted = formatted.replace(/(?:^|\n)\s*#\s*([^\n<]+)/g, '\n<h1>$1</h1>\n');

  // Convert markdown tables
  const lines = formatted.split('\n');
  let inTable = false;
  let tableHtml = [];
  let outputLines = [];

  for (let line of lines) {
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      if (!inTable) {
        inTable = true;
        tableHtml.push('<table>');
      }
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      if (cells.every(c => c.startsWith('---') || c.startsWith(':---') || c.startsWith('---:'))) {
        continue;
      }
      const tag = tableHtml.length === 1 ? 'th' : 'td';
      tableHtml.push('<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>');
    } else {
      if (inTable) {
        tableHtml.push('</table>');
        outputLines.push(tableHtml.join(''));
        tableHtml = [];
        inTable = false;
      }
      outputLines.push(line);
    }
  }
  if (inTable) {
    tableHtml.push('</table>');
    outputLines.push(tableHtml.join(''));
  }

  // Process bullet points and numbered list items into <li>
  let processedLines = outputLines;
  let inList = false;
  let finalLines = [];

  for (let l of processedLines) {
    const listMatch = l.match(/^\s*([*•-]|\d+\.)\s+(.*)$/);
    if (listMatch) {
      if (!inList) {
        inList = true;
        finalLines.push('<ul class="answer-list">');
      }
      finalLines.push(`<li>${listMatch[2]}</li>`);
    } else {
      if (inList) {
        inList = false;
        finalLines.push('</ul>');
      }
      finalLines.push(l);
    }
  }
  if (inList) {
    finalLines.push('</ul>');
  }
  formatted = finalLines.join('\n');

  // Markdown bold, italic, code styling
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
  formatted = formatted.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  // Replace [[Q1:R1]] and [[D:...]] citation pills
  formatted = formatted.replace(/\[\[(Q\d+:R\d+)\]\]/g, (match, id) => {
    return `<a href="#${id}" class="citation-token token-sql" data-citation="${id}" title="Database row evidence: ${id}">&#9670; ${id}</a>`;
  });

  formatted = formatted.replace(/\[\[(D:[^\]]+)\]\]/g, (match, id) => {
    return `<a href="#${id}" class="citation-token token-doc" data-citation="${id}" title="Document chunk evidence: ${id}">&#9632; ${id}</a>`;
  });

  return formatted;
}

function handleCitationClick(targetId) {
  if (!currentResult) return;

  const modal = document.getElementById('citationModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');

  if (targetId.startsWith('Q')) {
    modalTitle.textContent = `SQL Row Evidence [${targetId}]`;
    const queries = (currentResult.evidence && currentResult.evidence.queries) || [];
    const [qLabel, rLabel] = targetId.split(':');
    const rowIdx = parseInt(rLabel.replace('R', ''), 10) - 1;

    let targetQuery = queries.find(q => q.query_label === qLabel);
    if (!targetQuery && queries.length > 0) targetQuery = queries[0];

    if (targetQuery && targetQuery.rows && targetQuery.rows[rowIdx]) {
      const row = targetQuery.rows[rowIdx];
      const cols = targetQuery.columns;

      let tableHtml = '<table class="evidence-table"><thead><tr>';
      cols.forEach(c => tableHtml += `<th>${c}</th>`);
      tableHtml += '</tr></thead><tbody><tr>';
      row.forEach(val => tableHtml += `<td><strong>${val !== null ? val : 'NULL'}</strong></td>`);
      tableHtml += '</tr></tbody></table>';

      tableHtml += `<div style="margin-top: 1rem;"><span class="badge-mini">SQL Query (${targetQuery.query_id || 'LOCAL'})</span><pre class="sql-code-block">${targetQuery.sql}</pre></div>`;
      modalBody.innerHTML = tableHtml;
    } else {
      modalBody.innerHTML = `<p class="error-msg">Row ${targetId} not found in executed queries.</p>`;
    }
  } else if (targetId.startsWith('D:')) {
    modalTitle.textContent = `Document Chunk [${targetId}]`;
    const docs = (currentResult.evidence && currentResult.evidence.chunks) || [];
    const targetDoc = docs.find(d => d.chunk_id === targetId);

    if (targetDoc) {
      modalBody.innerHTML = `
        <div class="doc-card modal-doc">
          <div class="doc-header">
            <span class="doc-badge">&#9632; ${targetDoc.chunk_id}</span>
            <span class="doc-score">BM25 Relevance: ${targetDoc.score}</span>
          </div>
          <div class="doc-title">${targetDoc.doc_name}</div>
          <div class="doc-content">${targetDoc.text}</div>
        </div>
      `;
    } else {
      modalBody.innerHTML = `<p class="error-msg">Document ${targetId} not found in retrieved chunks.</p>`;
    }
  }

  modal.classList.add('open');
  highlightTableRow(targetId);
}

function renderQueries(queries) {
  const container = document.getElementById('queriesList');
  container.innerHTML = '';

  if (!queries.length) {
    container.innerHTML = '<p class="text-muted">No SQL queries were required for this answer.</p>';
    return;
  }

  queries.forEach(q => {
    const item = document.createElement('div');
    item.className = 'query-item';

    const header = document.createElement('div');
    header.className = 'query-header';
    header.innerHTML = `
      <div class="query-meta">
        <span class="query-badge">&#9670; ${q.query_label}</span>
        <span class="query-id">${q.query_id || 'DuckDB'}</span>
        <span class="query-time">${q.elapsed_ms.toFixed(1)}ms</span>
        <span class="query-rows">${q.rows.length} rows</span>
      </div>
      <button class="btn-copy-sql" title="Copy SQL">Copy</button>
    `;

    const copyBtn = header.querySelector('.btn-copy-sql');
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(q.sql);
      copyBtn.textContent = 'Copied!';
      setTimeout(() => copyBtn.textContent = 'Copy', 2000);
    });

    const purpose = document.createElement('div');
    purpose.className = 'query-purpose';
    purpose.textContent = `Purpose: ${q.purpose}`;

    const sqlBlock = document.createElement('pre');
    sqlBlock.className = 'sql-code-block';
    sqlBlock.textContent = q.sql;

    item.appendChild(header);
    item.appendChild(purpose);
    item.appendChild(sqlBlock);

    if (q.rows && q.rows.length) {
      const tableWrapper = document.createElement('div');
      tableWrapper.className = 'table-scroll-wrap';

      const table = document.createElement('table');
      table.className = 'evidence-table';

      let thead = '<thead><tr><th>Row ID</th>';
      q.columns.forEach(c => thead += `<th>${c}</th>`);
      thead += '</tr></thead>';

      let tbody = '<tbody>';
      q.rows.slice(0, 100).forEach((r, idx) => {
        const rowId = `${q.query_label}:R${idx + 1}`;
        tbody += `<tr id="query_${q.query_label}_row_${rowId}" data-row-id="${rowId}">`;
        tbody += `<td class="row-id-cell"><code>${rowId}</code></td>`;
        r.forEach(val => {
          tbody += `<td>${val !== null ? val : '<span class="null-val">NULL</span>'}</td>`;
        });
        tbody += '</tr>';
      });
      tbody += '</tbody>';

      table.innerHTML = thead + tbody;
      tableWrapper.appendChild(table);
      item.appendChild(tableWrapper);
    }

    container.appendChild(item);
  });
}

function renderDocs(docs) {
  const container = document.getElementById('docsList');
  container.innerHTML = '';

  if (!docs.length) {
    container.innerHTML = '<p class="text-muted">No document retrievals were performed for this answer.</p>';
    return;
  }

  docs.forEach(d => {
    const item = document.createElement('div');
    item.className = 'doc-card';
    item.id = `doc_${d.chunk_id}`;
    item.innerHTML = `
      <div class="doc-header">
        <span class="doc-badge">&#9632; ${d.chunk_id}</span>
        <span class="doc-score">BM25 Score: ${d.score}</span>
      </div>
      <div class="doc-title">${d.doc_name}</div>
      <div class="doc-content">${d.text}</div>
    `;
    container.appendChild(item);
  });
}

function renderNumericChecks(checks) {
  const container = document.getElementById('numericList');
  container.innerHTML = '';

  if (!checks.length) {
    container.innerHTML = '<p class="text-muted">No numeric assertions requiring deterministic reconciliation.</p>';
    return;
  }

  let tableHtml = `
    <div class="table-scroll-wrap">
      <table class="evidence-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Claimed in Answer</th>
            <th>Database Cell</th>
            <th>Evidence Row</th>
            <th>Matched Column</th>
            <th>Verification Note</th>
          </tr>
        </thead>
        <tbody>
  `;

  checks.forEach(nc => {
    const isPass = nc.status === 'VERIFIED';
    const statusClass = isPass ? 'badge-clean-pass' : 'badge-clean-fail';
    const statusIcon = isPass ? '&#10003; VERIFIED' : '&#9888; DISCREPANCY';

    tableHtml += `
      <tr>
        <td><span class="trust-badge ${statusClass}" style="font-size: 0.72rem;">${statusIcon}</span></td>
        <td><strong>${nc.claimed_value}</strong></td>
        <td><code>${nc.cell_value !== null ? nc.cell_value : 'N/A'}</code></td>
        <td><a href="#${nc.row_id}" class="citation-token token-sql" onclick="highlightTableRow('${nc.row_id}'); return false;">${nc.row_id}</a></td>
        <td><code>${nc.matched_column || 'N/A'}</code></td>
        <td><span class="check-msg">${nc.message}</span></td>
      </tr>
    `;
  });

  tableHtml += '</tbody></table></div>';
  container.innerHTML = tableHtml;
}

function initTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      const targetId = btn.getAttribute('data-tab');
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add('active');
    });
  });
}

function initModal() {
  const modal = document.getElementById('citationModal');
  const closeBtn = document.getElementById('modalClose');

  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      modal.classList.remove('open');
    });
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('open');
      }
    });
  }
}

function initUploads() {
  const modalBtn = document.getElementById('uploadModalBtn');
  const modal = document.getElementById('uploadModal');
  const closeBtn = document.getElementById('uploadModalClose');
  const cancelBtn = document.getElementById('cancelUploadBtn');
  const confirmBtn = document.getElementById('confirmUploadBtn');
  const browseBtn = document.getElementById('browseFilesBtn');
  const fileInput = document.getElementById('filePickerInput');
  const dropzone = document.getElementById('fileDropzone');
  const deleteBtn = document.getElementById('deleteDatasetBtn');

  let currentSessionId = null;

  if (modalBtn) {
    modalBtn.addEventListener('click', async () => {
      try {
        const statusRes = await fetch('/api/uploads/status').then(r => r.json()).catch(() => ({ enabled: false }));
        if (!statusRes.enabled) {
          alert('User uploads are currently disabled.\nStart the server with --enable-uploads to enable dataset uploads.');
          return;
        }
        document.getElementById('uploadDropzoneSection').style.display = 'block';
        document.getElementById('uploadReviewSection').style.display = 'none';
        document.getElementById('uploadProgress').style.display = 'none';
        document.getElementById('uploadError').style.display = 'none';
        modal.classList.add('open');
      } catch (err) {
        alert('Could not connect to uploads service: ' + err.message);
      }
    });
  }

  const closeModal = () => {
    if (modal) modal.classList.remove('open');
  };

  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });
  }

  if (browseBtn && fileInput) {
    browseBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        processSelectedFile(e.target.files[0]);
      }
    });
  }

  if (dropzone) {
    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        processSelectedFile(e.dataTransfer.files[0]);
      }
    });
  }

  async function processSelectedFile(file) {
    const errorEl = document.getElementById('uploadError');
    const progressEl = document.getElementById('uploadProgress');
    const dropzoneSection = document.getElementById('uploadDropzoneSection');

    errorEl.style.display = 'none';
    progressEl.style.display = 'flex';
    dropzone.style.display = 'none';

    try {
      // 1. Create session
      const sessRes = await fetch('/api/uploads/session/create', { method: 'POST' });
      const sessData = await sessRes.json();
      if (!sessRes.ok) {
        throw new Error(sessData.error || 'Failed to initialize session');
      }
      currentSessionId = sessData.session_id;

      // 2. Read file to Base64
      const b64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const res = reader.result;
          const commaIdx = res.indexOf(',');
          resolve(commaIdx >= 0 ? res.substring(commaIdx + 1) : res);
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });

      // 3. Upload and profile
      const upRes = await fetch(`/api/uploads/${currentSessionId}/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          content_base64: b64,
        }),
      });

      const upData = await upRes.json();
      if (!upRes.ok) {
        throw new Error(upData.error || 'Upload ingestion failed');
      }

      currentUploadTableMeta = upData.table;

      // Render review screen
      renderUploadReviewScreen(upData.table);
      progressEl.style.display = 'none';
      dropzoneSection.style.display = 'none';
      document.getElementById('uploadReviewSection').style.display = 'block';

    } catch (err) {
      console.error('Upload error:', err);
      progressEl.style.display = 'none';
      dropzone.style.display = 'flex';
      errorEl.textContent = 'Upload failed: ' + (err.message || 'Unknown error');
      errorEl.style.display = 'block';
    }
  }

  function renderUploadReviewScreen(tableMeta) {
    document.getElementById('reviewTableName').textContent = `Table: ${tableMeta.table_name}`;
    document.getElementById('reviewTableStats').textContent =
      `${tableMeta.total_rows.toLocaleString()} rows • ${tableMeta.total_columns} columns (${tableMeta.original_filename})`;

    // Preview table
    const previewContainer = document.getElementById('uploadPreviewTableContainer');
    if (tableMeta.preview && tableMeta.preview.columns) {
      let pHtml = '<table class="data-table"><thead><tr>';
      tableMeta.preview.columns.forEach(col => {
        pHtml += `<th>${col}</th>`;
      });
      pHtml += '</tr></thead><tbody>';
      (tableMeta.preview.rows || []).forEach(row => {
        pHtml += '<tr>';
        row.forEach(val => {
          pHtml += `<td>${val !== null && val !== undefined ? String(val) : '<em class="text-dim">null</em>'}</td>`;
        });
        pHtml += '</tr>';
      });
      pHtml += '</tbody></table>';
      previewContainer.innerHTML = pHtml;
    }

    // Columns profiling table
    const tbody = document.getElementById('uploadColumnsTbody');
    tbody.innerHTML = '';
    (tableMeta.columns || []).forEach(col => {
      const tr = document.createElement('tr');
      const sampleText = (col.sample_values || []).join(', ') || '-';
      const piiHtml = col.pii_warning ? `<div class="pii-tag" title="${col.pii_warning}">⚠ PII: ${col.pii_warning}</div>` : '';

      tr.innerHTML = `
        <td style="text-align:center;">
          <input type="checkbox" id="col_${col.name}_enabled" checked>
        </td>
        <td>
          <strong>${col.name}</strong>
          ${col.original_name !== col.name ? `<div class="meta-sub">Original: ${col.original_name}</div>` : ''}
          ${piiHtml}
        </td>
        <td><code>${col.inferred_type}</code></td>
        <td>${(col.null_rate * 100).toFixed(1)}%</td>
        <td>${col.distinct_count.toLocaleString()}</td>
        <td style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${sampleText}">
          ${sampleText}
        </td>
        <td>
          <input type="text" class="input-cell" id="col_${col.name}_desc" value="${col.original_name} column">
        </td>
        <td style="text-align:center;">
          <input type="checkbox" id="col_${col.name}_pk" ${col.is_id ? 'checked' : ''}>
        </td>
        <td style="text-align:center;">
          <input type="checkbox" id="col_${col.name}_doc" ${col.is_document ? 'checked' : ''}>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  if (confirmBtn) {
    confirmBtn.addEventListener('click', async () => {
      if (!currentSessionId || !currentUploadTableMeta) return;

      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Activating...';

      try {
        const colsConfig = {};
        (currentUploadTableMeta.columns || []).forEach(col => {
          const enCb = document.getElementById(`col_${col.name}_enabled`);
          const descInp = document.getElementById(`col_${col.name}_desc`);
          const pkCb = document.getElementById(`col_${col.name}_pk`);
          const docCb = document.getElementById(`col_${col.name}_doc`);

          colsConfig[col.name] = {
            enabled: enCb ? enCb.checked : true,
            description: descInp ? descInp.value.trim() : col.name,
            is_primary_key: pkCb ? pkCb.checked : false,
            is_document: docCb ? docCb.checked : false,
          };
        });

        const reviewConfig = {
          default_currency: document.getElementById('reviewCurrency').value,
          tables: {
            [currentUploadTableMeta.table_name]: {
              description: `Uploaded dataset: ${currentUploadTableMeta.original_filename}`,
              columns: colsConfig,
            },
          },
        };

        const confRes = await fetch(`/api/uploads/${currentSessionId}/confirm`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ review_config: reviewConfig }),
        });

        const confData = await confRes.json();
        if (!confRes.ok) {
          throw new Error(confData.error || 'Activation failed');
        }

        activeUploadSession = currentSessionId;
        closeModal();

        // Show active dataset banner
        const banner = document.getElementById('activeDatasetBanner');
        const nameEl = document.getElementById('activeDatasetName');
        if (banner && nameEl) {
          nameEl.textContent = `${currentUploadTableMeta.original_filename} (${currentUploadTableMeta.table_name})`;
          banner.style.display = 'flex';
        }

        // Update backend badge
        document.getElementById('backendName').textContent = 'DUCKDB (UPLOAD)';

        // Populate sample questions from confirmed model
        const chipsList = document.getElementById('chipsList');
        if (chipsList && confData.sample_questions && confData.sample_questions.length) {
          chipsList.innerHTML = '';
          confData.sample_questions.forEach(q => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'chip';
            btn.textContent = q.length > 55 ? q.substring(0, 52) + '...' : q;
            btn.title = q;
            btn.addEventListener('click', () => {
              document.getElementById('questionInput').value = q;
              document.getElementById('askForm').dispatchEvent(new Event('submit'));
            });
            chipsList.appendChild(btn);
          });
        }

        resetConversation();

      } catch (err) {
        alert('Failed to activate dataset: ' + err.message);
      } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm & Activate Dataset';
      }
    });
  }

  if (deleteBtn) {
    deleteBtn.addEventListener('click', async () => {
      if (!activeUploadSession) return;
      const ok = confirm('Are you sure you want to purge this uploaded dataset session and all its isolated database files?');
      if (!ok) return;

      try {
        await fetch(`/api/uploads/${activeUploadSession}/delete`, { method: 'POST' });
        activeUploadSession = null;
        currentUploadTableMeta = null;
        const banner = document.getElementById('activeDatasetBanner');
        if (banner) banner.style.display = 'none';

        await loadConfig();
        resetConversation();
      } catch (err) {
        alert('Failed to delete dataset: ' + err.message);
      }
    });
  }
}

