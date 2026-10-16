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
  const isStrict = document.getElementById('strictModeToggle').checked;

  submitBtn.disabled = true;
  btnSpinner.style.display = 'block';
  sendIcon.style.display = 'none';
  btnText.textContent = 'Analyzing...';

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        permissive: !isStrict,
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `Server returned error ${res.status}`);
    }

    const data = await res.json();
    currentResult = data;
    renderResult(data);

    emptyState.style.display = 'none';
    resultsContainer.style.display = 'flex';
  } catch (err) {
    alert(`Query execution failed: ${err.message}`);
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

  const cleanBadge = document.createElement('span');
  cleanBadge.className = `trust-badge ${isClean ? 'badge-clean-pass' : 'badge-clean-fail'}`;
  cleanBadge.innerHTML = isClean
    ? '&#10003; 100% Grounded & Verified'
    : '&#9888; Verification Discrepancy';
  trustDiv.appendChild(cleanBadge);

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

function formatMarkdownWithCitations(text, data) {
  if (!text) return '<p>No answer text produced.</p>';

  let formatted = text;

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

  formatted = outputLines.join('\n');

  // Convert paragraph breaks
  formatted = formatted.replace(/\n\n+/g, '</p><p>');
  if (!formatted.startsWith('<table') && !formatted.startsWith('<p>')) {
    formatted = '<p>' + formatted + '</p>';
  }

  // Replace citation bracket tokens [[...]] with interactive pills
  formatted = formatted.replace(/\[\[(Q\d+:R\d+)\]\]/g, (match, id) => {
    return `<a href="#${id}" class="citation-token token-sql" data-citation="${id}">[&#9670; ${id}]</a>`;
  });

  formatted = formatted.replace(/\[\[(D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\]\]/g, (match, id) => {
    return `<a href="#${id}" class="citation-token token-doc" data-citation="${id}">[&#128196; ${id}]</a>`;
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
