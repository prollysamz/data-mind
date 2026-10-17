// DataMind Frontend Application Logic

let currentResult = null;

document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  initModal();
  await loadConfig();

  const form = document.getElementById('askForm');
  const input = document.getElementById('questionInput');
  const chips = document.querySelectorAll('.chip');

  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      input.value = chip.getAttribute('data-q');
      form.dispatchEvent(new Event('submit'));
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    await executeQuery(query);
  });
});

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    const data = await res.json();
    document.getElementById('backendName').textContent = data.backend.toUpperCase();
    document.getElementById('modelName').textContent = data.model_name;
  } catch (err) {
    console.error('Failed to load config:', err);
    document.getElementById('backendName').textContent = 'OFFLINE';
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

  // Toggle loading UI states
  if (emptyState) emptyState.style.display = 'none';
  if (resultsContainer) resultsContainer.style.display = 'none';
  if (errorState) errorState.style.display = 'none';
  if (loadingState) loadingState.style.display = 'flex';

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        permissive: !isStrict,
      }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      if (data.error_type === 'budget_exceeded') {
        const err = new Error(data.message || data.error || 'Cloud or session budget ceiling reached.');
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
      document.getElementById('errorTitle').textContent = err.isBudget ? 'Budget Limit Reached' : 'Query Execution Failed';
      document.getElementById('errorMessage').textContent = err.message || 'An unexpected error occurred during execution.';
      errorState.style.display = 'flex';
    }
  } finally {
    submitBtn.disabled = false;
    btnSpinner.style.display = 'none';
    sendIcon.style.display = 'block';
    btnText.textContent = 'Run Query';
  }
}

function renderResult(data) {
  document.getElementById('questionEcho').textContent = data.question;

  // Render Trust Badges
  const trustDiv = document.getElementById('trustSummary');
  trustDiv.innerHTML = '';

  const isClean = data.citation_report && data.citation_report.is_clean;
  const verifiedCount = data.citation_report ? data.citation_report.verified_numbers_count : 0;
  const discrepancies = data.citation_report ? data.citation_report.discrepancy_count : 0;
  const unsupported = data.citation_report ? data.citation_report.unsupported_claims_count : 0;

  // Check for Refusal or Schema limitation
  const isTruncated = data.is_truncated || (data.citation_report && data.citation_report.is_truncated) || data.finish_reason === 'length';
  const ansLower = (data.answer || '').toLowerCase();
  const isRefusal = ansLower.includes('does not contain') || ansLower.includes('not available') || ansLower.includes('do not have') || ansLower.includes('cannot answer') || ansLower.includes('no table');
  const isClarification = (data.answer || '').includes('?') && (ansLower.includes('clarify') || ansLower.includes('specify') || ansLower.includes('which'));
  const isPartial = (
    ansLower.includes('search failed') ||
    ansLower.includes('cannot report') ||
    ansLower.includes('unable to retrieve') ||
    ansLower.includes('partially answered') ||
    ansLower.includes('could not find customer complaints') ||
    ansLower.includes('sub-question is unanswered') ||
    ansLower.includes('retrieval failed')
  );

  if (isTruncated) {
    const truncBadge = document.createElement('span');
    truncBadge.className = 'trust-badge badge-clean-fail';
    truncBadge.style.background = 'rgba(239, 68, 68, 0.15)';
    truncBadge.style.color = '#ef4444';
    truncBadge.style.border = '1px solid rgba(239, 68, 68, 0.35)';
    truncBadge.innerHTML = '&#9888; Partially Answered (Token Limit Truncated)';
    trustDiv.appendChild(truncBadge);
  } else if (isRefusal) {
    const refBadge = document.createElement('span');
    refBadge.className = 'trust-badge';
    refBadge.style.background = 'rgba(245, 158, 11, 0.15)';
    refBadge.style.color = '#f59e0b';
    refBadge.style.border = '1px solid rgba(245, 158, 11, 0.35)';
    refBadge.innerHTML = '&#9888; Refusal: Schema Boundary';
    trustDiv.appendChild(refBadge);
  } else if (isClarification) {
    const clarBadge = document.createElement('span');
    clarBadge.className = 'trust-badge';
    clarBadge.style.background = 'rgba(168, 85, 247, 0.15)';
    clarBadge.style.color = '#a855f7';
    clarBadge.style.border = '1px solid rgba(168, 85, 247, 0.35)';
    clarBadge.innerHTML = '&#9432; Clarification Requested';
    trustDiv.appendChild(clarBadge);
  } else if (isPartial) {
    const partBadge = document.createElement('span');
    partBadge.className = 'trust-badge';
    partBadge.style.background = 'rgba(234, 179, 8, 0.15)';
    partBadge.style.color = '#eab308';
    partBadge.style.border = '1px solid rgba(234, 179, 8, 0.35)';
    partBadge.innerHTML = '&#9888; Partially Answered (Tool Limitation)';
    trustDiv.appendChild(partBadge);
  } else if (!isClean || discrepancies > 0 || unsupported > 0) {
    const failBadge = document.createElement('span');
    failBadge.className = 'trust-badge badge-clean-fail';
    failBadge.innerHTML = '&#9888; Verification Discrepancy';
    trustDiv.appendChild(failBadge);
  } else {
    const cleanBadge = document.createElement('span');
    cleanBadge.className = 'trust-badge badge-clean-pass';
    cleanBadge.innerHTML = '&#10003; 100% Grounded & Verified';
    trustDiv.appendChild(cleanBadge);
  }

  if (verifiedCount > 0) {
    const numBadge = document.createElement('span');
    numBadge.className = 'trust-badge badge-num-verified';
    numBadge.textContent = `${verifiedCount} Numbers Verified`;
    trustDiv.appendChild(numBadge);
  }

  if (discrepancies > 0) {
    const discBadge = document.createElement('span');
    discBadge.className = 'trust-badge badge-clean-fail';
    discBadge.textContent = `${discrepancies} Discrepancies`;
    trustDiv.appendChild(discBadge);
  }

  // Render Answer with Interactive Citations
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

  // Render Visual Chart if numeric data is available
  renderChart(data);

  // Render Inspector Tab 1: SQL Queries
  const queries = (data.evidence && data.evidence.queries) || [];
  document.getElementById('sqlCount').textContent = queries.length;
  renderQueries(queries);

  // Render Inspector Tab 2: Document Chunks
  const docs = (data.evidence && data.evidence.chunks) || [];
  document.getElementById('docsCount').textContent = docs.length;
  renderDocs(docs);

  // Render Inspector Tab 3: Numeric Checks
  const checks = (data.citation_report && data.citation_report.numeric_checks) || [];
  document.getElementById('numChecksCount').textContent = checks.length;
  renderNumericChecks(checks);
}

function renderChart(data) {
  const chartCard = document.getElementById('chartCard');
  const chartBody = document.getElementById('chartBody');
  chartBody.innerHTML = '';

  const queries = (data.evidence && data.evidence.queries) || [];
  if (!queries.length) {
    chartCard.style.display = 'none';
    return;
  }

  // Look for query with at least 2 rows and columns suitable for charting
  let targetQuery = null;
  for (let q of queries) {
    if (q.result && q.result.rows && q.result.rows.length >= 2) {
      targetQuery = q;
      break;
    }
  }

  if (!targetQuery) {
    chartCard.style.display = 'none';
    return;
  }

  const cols = targetQuery.result.columns || [];
  const rows = targetQuery.result.rows || [];

  function parseNum(v) {
    if (typeof v === 'number') return v;
    if (v === null || v === undefined) return NaN;
    const cleaned = String(v).replace(/[$,£€]/g, '').trim();
    if (cleaned === '') return NaN;
    return Number(cleaned);
  }

  // Find a string/label column and a numeric column (prioritize last numeric column like decline or sales)
  let labelColIdx = 0;
  let valColIdx = -1;

  for (let c = cols.length - 1; c >= 0; c--) {
    const num = parseNum(rows[0][c]);
    if (!isNaN(num)) {
      valColIdx = c;
      break;
    }
  }

  if (valColIdx === -1) {
    chartCard.style.display = 'none';
    return;
  }

  // Find label column (first non-numeric column)
  for (let c = 0; c < cols.length; c++) {
    if (isNaN(parseNum(rows[0][c]))) {
      labelColIdx = c;
      break;
    }
  }

  // Extract top items (up to 6)
  const items = rows.slice(0, 6).map(r => ({
    label: String(r[labelColIdx] ?? `Item`),
    value: parseNum(r[valColIdx]),
  })).filter(item => !isNaN(item.value));

  if (!items.length) {
    chartCard.style.display = 'none';
    return;
  }

  const maxVal = Math.max(...items.map(it => Math.abs(it.value)), 1);

  document.getElementById('chartTitle').textContent = `Metric Comparison: ${cols[valColIdx] || 'Value'} by ${cols[labelColIdx] || 'Dimension'}`;

  items.forEach(it => {
    const pct = Math.min(100, Math.max(5, Math.round((Math.abs(it.value) / maxVal) * 100)));
    const formattedVal = it.value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });

    const row = document.createElement('div');
    row.className = 'chart-bar-row';
    row.innerHTML = `
      <div class="chart-bar-meta">
        <span class="chart-bar-label">${it.label}</span>
        <span class="chart-bar-value">${formattedVal}</span>
      </div>
      <div class="chart-bar-track">
        <div class="chart-bar-fill" style="width: ${pct}%"></div>
      </div>
    `;
    chartBody.appendChild(row);
  });

  chartCard.style.display = 'flex';
}

function formatMarkdownWithCitations(text, data) {
  if (!text) return '<p>No answer text produced.</p>';

  let formatted = text;

  // Clean raw markdown link syntax around citations if pasted e.g. [\[◆ Q1:R1\]](http...) or [Q1:R1](...)
  formatted = formatted.replace(/\[\\?\[?[◆\s]*(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\\?\]?\]\([^\)]+\)/g, '[[$1]]');

  // Convert markdown headings:
  // 1. Heading with newline after it: ### Heading\n
  // 2. Heading without newline (inline with sentence text): ### Heading Sentence starts here...
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

  // Wrap loose paragraphs in <p>...</p>
  const rawParagraphs = formatted.split(/\n\n+/);
  formatted = rawParagraphs.map(p => {
    const trimmed = p.trim();
    if (!trimmed) return '';
    if (trimmed.startsWith('<h') || trimmed.startsWith('<table') || trimmed.startsWith('<ul') || trimmed.startsWith('<div')) {
      return trimmed;
    }
    return `<p>${trimmed}</p>`;
  }).join('\n');

  // Replace single or grouped citation bracket tokens with interactive pills
  formatted = formatted.replace(/\[\[(.*?)\]\]/g, (match, inner) => {
    const ids = inner.match(/Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+/g);
    if (ids && ids.length > 0) {
      return ids.map(id => {
        const isSql = id.startsWith('Q');
        const icon = isSql ? '&#9670;' : '&#128196;';
        const cls = isSql ? 'token-sql' : 'token-doc';
        return `<a href="#${id}" class="citation-token ${cls}" data-citation="${id}">[${icon} ${id}]</a>`;
      }).join(' ');
    }
    return match;
  });

  // Also replace single-bracketed tags if model omitted double brackets
  formatted = formatted.replace(/(?<!\[)\[(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\](?!\])/g, (match, id) => {
    const isSql = id.startsWith('Q');
    const icon = isSql ? '&#9670;' : '&#128196;';
    const cls = isSql ? 'token-sql' : 'token-doc';
    return `<a href="#${id}" class="citation-token ${cls}" data-citation="${id}">[${icon} ${id}]</a>`;
  });

  return formatted;
}

function handleCitationClick(targetId) {
  if (targetId.startsWith('Q')) {
    // Row citation: Q1:R1
    const parts = targetId.split(':');
    const qLabel = parts[0];
    const rIdx = parseInt(parts[1].replace('R', ''), 10);

    // Switch to SQL tab
    switchTab('sqlTab');

    // Highlight row
    const rowEl = document.getElementById(`row-${targetId}`);
    if (rowEl) {
      rowEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      rowEl.classList.add('highlighted-row');
      setTimeout(() => rowEl.classList.remove('highlighted-row'), 2800);
    }
  } else if (targetId.startsWith('D:')) {
    // Document citation: D:SUPPORT_TICKETS:TK-1001
    const chunk = currentResult?.evidence?.chunks?.find(c => c.chunk_id === targetId);
    if (chunk) {
      openModal(targetId, `
        <div style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-purple); margin-bottom: 0.75rem;">
          Collection: ${chunk.doc_name} &bull; BM25 Score: ${chunk.score}
        </div>
        <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-color); white-space: pre-wrap; line-height: 1.6;">
          ${chunk.text}
        </div>
      `);
    } else {
      switchTab('docsTab');
      const docEl = document.getElementById(`doc-${targetId}`);
      if (docEl) docEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }
}

function renderQueries(queries) {
  const container = document.getElementById('queriesList');
  if (!queries || queries.length === 0) {
    container.innerHTML = '<p style="color: var(--text-dim);">No SQL queries were executed for this request.</p>';
    return;
  }

  container.innerHTML = queries.map(q => {
    let rowsHtml = '';
    if (q.rows && q.rows.length > 0) {
      const headerHtml = '<tr><th>RowID</th>' + q.columns.map(c => `<th>${c}</th>`).join('') + '</tr>';
      const bodyHtml = q.rows.map((row, idx) => {
        const rowId = `${q.query_label}:R${idx + 1}`;
        const cellsHtml = `<td><span class="query-pill">${rowId}</span></td>` + row.map(v => `<td>${v !== null ? v : 'NULL'}</td>`).join('');
        return `<tr id="row-${rowId}">${cellsHtml}</tr>`;
      }).join('');

      rowsHtml = `
        <div class="table-preview">
          <table>
            <thead>${headerHtml}</thead>
            <tbody>${bodyHtml}</tbody>
          </table>
        </div>
      `;
    }

    return `
      <div class="query-item" id="query-${q.query_label}">
        <div class="query-header">
          <div class="query-meta">
            <span class="query-pill">${q.query_label}</span>
            <span>Query ID: ${q.query_id || 'local'}</span>
            <span>Elapsed: ${q.elapsed_ms}ms</span>
            <span>Rows: ${q.rows ? q.rows.length : 0}</span>
          </div>
          <div style="color: var(--text-dim); font-size: 0.8rem;">${q.purpose || ''}</div>
        </div>
        <div class="code-container">${escapeHtml(q.sql)}</div>
        ${rowsHtml}
      </div>
    `;
  }).join('');
}

function renderDocs(chunks) {
  const container = document.getElementById('docsList');
  if (!chunks || chunks.length === 0) {
    container.innerHTML = '<p style="color: var(--text-dim);">No document chunks were retrieved for this request.</p>';
    return;
  }

  container.innerHTML = chunks.map(c => `
    <div class="chunk-item" id="doc-${c.chunk_id}">
      <div class="chunk-header">
        <span class="chunk-id">${c.chunk_id} (${c.doc_name})</span>
        <span class="chunk-score">BM25 Relevance: ${c.score}</span>
      </div>
      <div class="chunk-body">${escapeHtml(c.text)}</div>
    </div>
  `).join('');
}

function renderNumericChecks(checks) {
  const container = document.getElementById('numericList');
  if (!checks || checks.length === 0) {
    container.innerHTML = '<p style="color: var(--text-dim);">No numeric assertions found in response.</p>';
    return;
  }

  container.innerHTML = checks.map(nc => {
    let pillClass = 'pill-verified';
    if (nc.status === 'DISCREPANCY') pillClass = 'pill-discrepancy';
    if (nc.status === 'UNSUPPORTED') pillClass = 'pill-unsupported';

    return `
      <div class="numeric-item">
        <span class="status-pill ${pillClass}">${nc.status}</span>
        <div style="flex: 1;">
          <div style="font-weight: 600; color: var(--text-main); margin-bottom: 0.2rem;">
            Claimed ${nc.raw_text}
          </div>
          <div style="color: var(--text-dim); font-size: 0.8rem;">
            ${nc.message}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabId = btn.getAttribute('data-tab');
      switchTab(tabId);
    });
  });
}

function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === tabId);
  });
}

function initModal() {
  const modal = document.getElementById('citationModal');
  const closeBtn = document.getElementById('modalClose');
  closeBtn.addEventListener('click', () => modal.classList.remove('open'));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.remove('open');
  });
}

function openModal(title, contentHtml) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = contentHtml;
  document.getElementById('citationModal').classList.add('open');
}

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
