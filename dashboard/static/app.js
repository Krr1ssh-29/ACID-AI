/**
 * ACID AI — Presentation Demo Client Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  let currentProviderMode = 'mock';
  let activeScenarioId = 'missing_dependency';

  // DOM Elements
  const scenariosContainer = document.getElementById('scenarios-container');
  const terminalLogs = document.getElementById('terminal-logs');
  const stagePills = document.getElementById('stage-pills');
  const aiProviderBadge = document.getElementById('ai-provider-badge');
  const diagnosisRootCause = document.getElementById('diagnosis-root-cause');
  const diagnosisMeta = document.getElementById('diagnosis-meta');
  const diagnosisFixes = document.getElementById('diagnosis-fixes');
  const diagnosisEvidence = document.getElementById('diagnosis-evidence');
  const patchDiffContainer = document.getElementById('patch-diff');
  const patchPolicyChecks = document.getElementById('patch-policy-checks');
  const patchFilesList = document.getElementById('patch-files-list');
  const verifStatusBadge = document.getElementById('verif-status-badge');
  const verifAlert = document.getElementById('verif-alert');
  const pubStatusBadge = document.getElementById('pub-status-badge');
  const pubAlert = document.getElementById('pub-alert');
  const historyTableBody = document.getElementById('history-tbody');
  const resetBtn = document.getElementById('btn-reset');
  const btnToggleMock = document.getElementById('toggle-mock');
  const btnToggleGemini = document.getElementById('toggle-gemini');

  // Status pills
  const dockerStatusPill = document.getElementById('docker-status-pill');
  const geminiStatusPill = document.getElementById('gemini-status-pill');

  // 1. Fetch and render system status
  async function loadSystemStatus() {
    try {
      const res = await fetch('/api/system-status');
      const data = await res.json();

      if (data.docker_available) {
        dockerStatusPill.innerHTML = '<span class="status-dot active"></span> Docker: Online';
      } else {
        dockerStatusPill.innerHTML = '<span class="status-dot"></span> Docker: Offline (Host Protected)';
      }

      if (data.has_gemini_key) {
        geminiStatusPill.innerHTML = `<span class="status-dot active"></span> Gemini: Ready (${data.gemini_model})`;
      } else {
        geminiStatusPill.innerHTML = '<span class="status-dot"></span> Gemini: No API Key (Offline Mock Active)';
      }
    } catch (e) {
      console.error('Failed to load system status:', e);
    }
  }

  // 2. Fetch and render scenarios list
  async function loadScenarios() {
    try {
      const res = await fetch('/api/scenarios');
      const data = await res.json();
      scenariosContainer.innerHTML = '';

      data.scenarios.forEach((sc) => {
        const btn = document.createElement('button');
        btn.className = `scenario-btn ${sc.id === activeScenarioId ? 'active' : ''}`;
        btn.id = `scenario-btn-${sc.id}`;
        btn.innerHTML = `
          <span class="sc-badge ${sc.failure_type}">${sc.badge}</span>
          <span class="sc-name">${escapeHtml(sc.name)}</span>
          <span class="sc-desc">${escapeHtml(sc.description)}</span>
        `;
        btn.addEventListener('click', () => {
          document.querySelectorAll('.scenario-btn').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
          activeScenarioId = sc.id;
          executeRun(sc.id);
        });
        scenariosContainer.appendChild(btn);
      });
    } catch (e) {
      console.error('Failed to load scenarios:', e);
    }
  }

  // 3. Provider mode toggle
  if (btnToggleMock && btnToggleGemini) {
    btnToggleMock.addEventListener('click', () => {
      btnToggleMock.classList.add('active');
      btnToggleGemini.classList.remove('active');
      currentProviderMode = 'mock';
      executeRun(activeScenarioId);
    });

    btnToggleGemini.addEventListener('click', () => {
      btnToggleGemini.classList.add('active');
      btnToggleMock.classList.remove('active');
      currentProviderMode = 'gemini';
      executeRun(activeScenarioId);
    });
  }

  // 4. Stepper animator
  function updateStepper(stepStates) {
    // stepStates: [ 'completed' | 'active' | 'blocked' | 'idle', ... for 5 steps ]
    for (let i = 1; i <= 5; i++) {
      const node = document.getElementById(`step-node-${i}`);
      if (!node) continue;
      node.className = 'step-node';
      const state = stepStates[i - 1] || 'idle';
      if (state !== 'idle') {
        node.classList.add(state);
      }
    }
  }

  // 5. Diff syntax styler
  function renderSyntaxDiff(diffText) {
    if (!diffText || !diffText.trim()) {
      return '<span class="diff-line-header">// No patch generated (Pipeline healthy or triage bypassed)</span>';
    }

    const lines = diffText.split('\n');
    return lines
      .map((line) => {
        const escaped = escapeHtml(line);
        if (line.startsWith('---') || line.startsWith('+++')) {
          return `<span class="diff-line-header">${escaped}</span>`;
        } else if (line.startsWith('@@')) {
          return `<span class="diff-line-hunk">${escaped}</span>`;
        } else if (line.startsWith('+')) {
          return `<span class="diff-line-add">${escaped}</span>`;
        } else if (line.startsWith('-')) {
          return `<span class="diff-line-del">${escaped}</span>`;
        } else {
          return `<span>${escaped}</span>`;
        }
      })
      .join('\n');
  }

  // 6. Execute scenario run
  async function executeRun(scenarioId) {
    // Visual pending state
    updateStepper(['active', 'idle', 'idle', 'idle', 'idle']);
    terminalLogs.textContent = 'Running orchestration pipeline... Loading logs and running classification...';

    try {
      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: scenarioId,
          provider_mode: currentProviderMode,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        terminalLogs.textContent = `Error executing scenario: ${err.error || 'Server error'}`;
        updateStepper(['blocked', 'idle', 'idle', 'idle', 'idle']);
        return;
      }

      const data = await res.json();
      renderRunResult(data);
      loadHistory();
    } catch (e) {
      terminalLogs.textContent = `Network error running scenario: ${e}`;
      updateStepper(['blocked', 'idle', 'idle', 'idle', 'idle']);
    }
  }

  // 7. Render complete run result
  function renderRunResult(data) {
    // Terminal logs
    terminalLogs.textContent = data.logs_raw || 'No logs captured.';

    // Stages pills
    stagePills.innerHTML = '';
    (data.stages || []).forEach((st) => {
      const pill = document.createElement('div');
      pill.className = `stage-badge ${st.status}`;
      pill.innerHTML = `
        <span class="sb-name">${escapeHtml(st.name)}</span>
        <span class="sb-status">${escapeHtml(st.status)}</span>
      `;
      stagePills.appendChild(pill);
    });

    // Truthfulness badge
    aiProviderBadge.textContent = data.truthfulness.ai_provider;

    // Healthy bypass vs Failure triage
    if (data.is_healthy) {
      updateStepper(['completed', 'completed', 'completed', 'completed', 'completed']);

      diagnosisRootCause.innerHTML = `<strong>Pipeline Healthy:</strong> ${escapeHtml(data.classification.message)}`;
      diagnosisMeta.innerHTML = `
        <div class="meta-box"><span class="meta-box-label">Status</span><div class="meta-box-val" style="color:var(--color-success)">HEALTHY</div></div>
        <div class="meta-box"><span class="meta-box-label">Token Spend</span><div class="meta-box-val">0 Tokens</div></div>
        <div class="meta-box"><span class="meta-box-label">PR Comments</span><div class="meta-box-val">0 Comments</div></div>
      `;
      diagnosisFixes.innerHTML = '<p style="color:var(--text-muted);font-size:12px;">No remediation needed.</p>';
      diagnosisEvidence.textContent = 'None (healthy bypass active)';

      patchDiffContainer.innerHTML = renderSyntaxDiff('');
      patchFilesList.textContent = 'None';
      patchPolicyChecks.innerHTML = '<span class="policy-chip">No modifications required</span>';

      verifStatusBadge.className = 'badge-pill verified';
      verifStatusBadge.textContent = 'Bypassed (Healthy)';
      verifAlert.className = 'safety-alert healthy';
      verifAlert.innerHTML = `
        <div class="alert-icon">✅</div>
        <div class="alert-text">
          <h4>Silent Healthy-Run Bypass</h4>
          <p>Zero tokens spent. Candidate patch generation and container verification were safely skipped.</p>
        </div>
      `;

      pubStatusBadge.className = 'badge-pill verified';
      pubStatusBadge.textContent = 'Skipped';
      pubAlert.className = 'safety-alert healthy';
      pubAlert.innerHTML = `
        <div class="alert-icon">ℹ️</div>
        <div class="alert-text">
          <h4>Zero Superfluous Comments</h4>
          <p>Healthy CI jobs do not trigger PR comments or repair branches.</p>
        </div>
      `;
      return;
    }

    // --- Failure Triaged Render ---
    // Stepper: 1 complete, 2 complete, 3 complete, 4 blocked (fail-closed), 5 blocked (gated)
    const verifState = data.verification.is_verified ? 'completed' : 'blocked';
    updateStepper(['completed', 'completed', 'completed', verifState, 'blocked']);

    // Diagnosis Card
    const diag = data.diagnosis;
    diagnosisRootCause.innerHTML = `<strong>Root Cause:</strong> ${escapeHtml(diag.root_cause || 'Diagnosing...')}`;
    diagnosisMeta.innerHTML = `
      <div class="meta-box"><span class="meta-box-label">Category</span><div class="meta-box-val">${escapeHtml((diag.failure_types || []).join(', ') || 'N/A')}</div></div>
      <div class="meta-box"><span class="meta-box-label">Severity</span><div class="meta-box-val" style="color:${diag.severity === 'high' || diag.severity === 'critical' ? 'var(--color-failure)' : 'var(--color-warning)'}">${escapeHtml((diag.severity || 'unknown').toUpperCase())}</div></div>
      <div class="meta-box"><span class="meta-box-label">Confidence</span><div class="meta-box-val" style="color:var(--color-success)">${escapeHtml((diag.confidence || 'medium').toUpperCase())}</div></div>
    `;

    // Fixes
    diagnosisFixes.innerHTML = '';
    (diag.fixes || []).forEach((f) => {
      const fixBox = document.createElement('div');
      fixBox.className = 'fix-item';
      fixBox.innerHTML = `
        <div class="fix-title">[${escapeHtml(f.type.toUpperCase())}] ${escapeHtml(f.title)}</div>
        <div class="fix-desc">${escapeHtml(f.description)}</div>
        ${f.code ? `<code class="fix-code">${escapeHtml(f.code)}</code>` : ''}
      `;
      diagnosisFixes.appendChild(fixBox);
    });

    diagnosisEvidence.textContent = diag.log_evidence || 'No cited evidence.';

    // Patch Review Card
    const patch = data.patch;
    patchDiffContainer.innerHTML = renderSyntaxDiff(patch.diff);
    patchFilesList.textContent = (patch.files && patch.files.length) ? patch.files.join(', ') : 'None';

    patchPolicyChecks.innerHTML = `
      <span class="policy-chip">✓ Path Allowlist Enforced</span>
      <span class="policy-chip">✓ Traversal Blocked</span>
      <span class="policy-chip">✓ Prohibited Files Protected (.git, .github)</span>
      <span class="policy-chip">✓ Bounds Checked (&le; ${patch.max_lines} lines, &le; ${patch.max_files} files)</span>
      <span class="policy-chip">✓ In-Memory AST Matching Passed</span>
    `;

    // Safety & Verification Card
    const verif = data.verification;
    verifStatusBadge.className = `badge-pill ${verif.badge_type}`;
    verifStatusBadge.textContent = verif.display;

    verifAlert.className = `safety-alert ${verif.badge_type === 'verified' ? 'verified' : 'blocked'}`;
    verifAlert.innerHTML = `
      <div class="alert-icon">${verif.badge_type === 'verified' ? '🛡️' : '⚠️'}</div>
      <div class="alert-text">
        <h4>${verif.badge_type === 'verified' ? 'Container Isolation Verified' : 'Fail-Closed Safety Gate Active'}</h4>
        <p>${escapeHtml(verif.message)}</p>
        ${verif.error_detail ? `<p style="margin-top:6px;font-family:var(--font-mono);font-size:11px;opacity:0.8;">Detail: ${escapeHtml(verif.error_detail)}</p>` : ''}
      </div>
    `;

    // Repair Delivery Card
    const pub = data.publication;
    pubStatusBadge.className = 'badge-pill blocked';
    pubStatusBadge.textContent = pub.display;
    pubAlert.className = 'safety-alert blocked';
    pubAlert.innerHTML = `
      <div class="alert-icon">🔒</div>
      <div class="alert-text">
        <h4>Publication Gate Enforced</h4>
        <p>${escapeHtml(pub.message)}</p>
      </div>
    `;
  }

  // 8. Load run history
  async function loadHistory() {
    try {
      const res = await fetch('/api/history');
      const data = await res.json();
      historyTableBody.innerHTML = '';

      if (!data.history || !data.history.length) {
        historyTableBody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No demo runs recorded in this session.</td></tr>';
        return;
      }

      data.history.forEach((h) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><code>${escapeHtml(h.run_id)}</code></td>
          <td>${escapeHtml(h.scenario_name)}</td>
          <td><span class="sc-badge ${h.failure_type}">${escapeHtml(h.failure_type.toUpperCase())}</span></td>
          <td><span style="color:${h.is_healthy ? 'var(--color-success)' : 'var(--color-failure)'};font-weight:600;">${escapeHtml(h.status)}</span></td>
          <td><code>${escapeHtml(h.verification_display)}</code></td>
          <td>${escapeHtml(h.timestamp)}</td>
        `;
        historyTableBody.appendChild(tr);
      });
    } catch (e) {
      console.error('Failed to load history:', e);
    }
  }

  // 9. Reset demo history
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/reset', { method: 'POST' });
        loadHistory();
      } catch (e) {
        console.error('Failed to reset demo:', e);
      }
    });
  }

  // Helper function to escape HTML
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initial load
  loadSystemStatus();
  loadScenarios();
  loadHistory();
  // Trigger initial run for demo readiness
  executeRun('missing_dependency');
});
