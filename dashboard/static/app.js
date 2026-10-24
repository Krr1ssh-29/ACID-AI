/**
 * ACID AI — Repository-First & Presentation Demo Client Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  let currentProviderMode = 'mock';
  let activeScenarioId = 'missing_dependency';

  // Tabs & Panels
  const tabRepoMode = document.getElementById('tab-repo-mode');
  const tabDemoMode = document.getElementById('tab-demo-mode');
  const panelRepoFirst = document.getElementById('panel-repo-first');
  const panelDemoMode = document.getElementById('panel-demo-mode');

  // Repository-First Elements
  const inputRepoPath = document.getElementById('input-repo-path');
  const btnInspectRepo = document.getElementById('btn-inspect-repo');
  const btnRunAnalysis = document.getElementById('btn-run-analysis');
  const valBranch = document.getElementById('val-branch');
  const valCommit = document.getElementById('val-commit');
  const valClean = document.getElementById('val-clean');
  const repoDetectedTags = document.getElementById('repo-detected-tags');
  const repoValidationFeedback = document.getElementById('repo-validation-feedback');

  // Run Status Area Elements
  const runStatusDot = document.getElementById('run-status-dot');
  const runStatusTitle = document.getElementById('run-status-title');
  const runStatusSubtitle = document.getElementById('run-status-subtitle');
  const tagRunId = document.getElementById('tag-run-id');
  const tagRunMode = document.getElementById('tag-run-mode');
  const tagRunAttempts = document.getElementById('tag-run-attempts');
  const tagRunTime = document.getElementById('tag-run-time');

  // Provider Toggles
  const btnToggleMock = document.getElementById('toggle-mock');
  const btnToggleGemini = document.getElementById('toggle-gemini');
  const btnToggleClaude = document.getElementById('toggle-claude');
  const btnToggleRepoMock = document.getElementById('toggle-repo-mock');
  const btnToggleRepoGemini = document.getElementById('toggle-repo-gemini');
  const btnToggleRepoClaude = document.getElementById('toggle-repo-claude');

  // Workspace & Cards Elements
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
  const badgeFinalStatus = document.getElementById('badge-final-status');
  const valLoopFinalStatus = document.getElementById('val-loop-final-status');
  const valLoopAttemptsCount = document.getElementById('val-loop-attempts-count');
  const valLoopVerifiedPatches = document.getElementById('val-loop-verified-patches');
  const stopReasonBox = document.getElementById('stop-reason-box');
  const valStopReason = document.getElementById('val-stop-reason');
  const attemptsTimeline = document.getElementById('attempts-timeline');
  const historyTableBody = document.getElementById('history-tbody');
  const resetBtn = document.getElementById('btn-reset');

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

  // 2. Repository inspection & auto-detection
  async function inspectRepository(path) {
    if (!path || !path.trim()) {
      setRepoFeedback(false, 'Please enter a valid local repository path.');
      if (btnRunAnalysis) btnRunAnalysis.disabled = true;
      return;
    }

    setRepoFeedback(null, 'Inspecting repository Git metadata...');
    try {
      const res = await fetch('/api/repo/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: path.trim() }),
      });
      const data = await res.json();

      if (res.ok && data.is_valid && data.repo) {
        renderRepoMetadata(data.repo);
        setRepoFeedback(true, `✓ Valid Git Repository: ${escapeHtml(data.repo.name)}`);
        if (btnRunAnalysis) btnRunAnalysis.disabled = false;
      } else {
        setRepoFeedback(false, `✗ ${escapeHtml(data.error || 'Path is not a valid Git repository.')}`);
        if (btnRunAnalysis) btnRunAnalysis.disabled = true;
      }
    } catch (e) {
      setRepoFeedback(false, `Network error validating repository: ${e.message}`);
      if (btnRunAnalysis) btnRunAnalysis.disabled = true;
    }
  }

  async function loadCurrentRepository() {
    try {
      const res = await fetch('/api/repo/current');
      const data = await res.json();
      if (res.ok && data.is_valid && data.repo) {
        if (inputRepoPath) inputRepoPath.value = data.repo.path;
        renderRepoMetadata(data.repo);
        setRepoFeedback(true, `✓ Active Workspace: ${escapeHtml(data.repo.name)}`);
        if (btnRunAnalysis) btnRunAnalysis.disabled = false;
      } else {
        setRepoFeedback(false, `Could not inspect default repository: ${data.error || 'Unknown'}`);
      }
    } catch (e) {
      console.error('Failed to load current repository:', e);
    }
  }

  function renderRepoMetadata(repo) {
    if (valBranch) valBranch.textContent = repo.branch || 'unknown';
    if (valCommit) valCommit.textContent = repo.short_sha || 'unknown';
    if (valClean) {
      valClean.textContent = repo.is_clean ? 'Clean' : 'Modified (Dirty)';
      valClean.style.color = repo.is_clean ? 'var(--color-success)' : 'var(--color-warning)';
    }

    const valRemote = document.getElementById('val-remote');
    if (valRemote) {
      if (repo.github_repo) {
        valRemote.textContent = repo.github_repo;
        valRemote.style.color = '#67e8f9';
      } else if (repo.remote_url) {
        valRemote.textContent = repo.remote_url;
        valRemote.style.color = '#67e8f9';
      } else {
        valRemote.textContent = 'local only';
        valRemote.style.color = 'var(--text-muted)';
      }
    }

    if (repoDetectedTags) {
      repoDetectedTags.innerHTML = '';
      const files = repo.detected_files || [];
      if (files.length === 0) {
        repoDetectedTags.innerHTML = '<span class="repo-tag">No manifests detected</span>';
      } else {
        files.forEach((f) => {
          const tag = document.createElement('span');
          tag.className = 'repo-tag';
          tag.textContent = f;
          repoDetectedTags.appendChild(tag);
        });
      }
    }
  }

  function setRepoFeedback(isValid, message) {
    if (!repoValidationFeedback) return;
    repoValidationFeedback.className = 'repo-validation-feedback';
    if (isValid === true) {
      repoValidationFeedback.classList.add('valid');
    } else if (isValid === false) {
      repoValidationFeedback.classList.add('invalid');
    }
    repoValidationFeedback.textContent = message;
  }

  // 3. Tab switching (Repository Analysis vs Demo Scenarios)
  if (tabRepoMode && tabDemoMode) {
    tabRepoMode.addEventListener('click', () => {
      tabRepoMode.classList.add('active');
      tabDemoMode.classList.remove('active');
      panelRepoFirst.classList.remove('hidden');
      panelDemoMode.classList.add('hidden');
    });

    tabDemoMode.addEventListener('click', () => {
      tabDemoMode.classList.add('active');
      tabRepoMode.classList.remove('active');
      panelDemoMode.classList.remove('hidden');
      panelRepoFirst.classList.add('hidden');
    });
  }

  // 4. Provider mode toggles
  function setProviderMode(mode) {
    currentProviderMode = mode;
    const isMock = mode === 'mock';
    const isGemini = mode === 'gemini';
    const isClaude = mode === 'claude';

    if (btnToggleMock) btnToggleMock.classList.toggle('active', isMock);
    if (btnToggleGemini) btnToggleGemini.classList.toggle('active', isGemini);
    if (btnToggleClaude) btnToggleClaude.classList.toggle('active', isClaude);
    if (btnToggleRepoMock) btnToggleRepoMock.classList.toggle('active', isMock);
    if (btnToggleRepoGemini) btnToggleRepoGemini.classList.toggle('active', isGemini);
    if (btnToggleRepoClaude) btnToggleRepoClaude.classList.toggle('active', isClaude);
  }

  if (btnToggleMock && btnToggleGemini) {
    btnToggleMock.addEventListener('click', () => setProviderMode('mock'));
    btnToggleGemini.addEventListener('click', () => setProviderMode('gemini'));
    if (btnToggleClaude) btnToggleClaude.addEventListener('click', () => setProviderMode('claude'));
  }
  if (btnToggleRepoMock && btnToggleRepoGemini) {
    btnToggleRepoMock.addEventListener('click', () => setProviderMode('mock'));
    btnToggleRepoGemini.addEventListener('click', () => setProviderMode('gemini'));
    if (btnToggleRepoClaude) btnToggleRepoClaude.addEventListener('click', () => setProviderMode('claude'));
  }

  // 5. Inspect button event listeners
  if (btnInspectRepo && inputRepoPath) {
    btnInspectRepo.addEventListener('click', () => inspectRepository(inputRepoPath.value));
    inputRepoPath.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        inspectRepository(inputRepoPath.value);
      }
    });
  }

  // 6. Stepper animator
  function updateStepper(stepStates) {
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

  // 7. Diff syntax styler
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

  // Helper to reset report card and disable export buttons during new runs
  function resetReportCardState() {
    const summaryOutcome = document.getElementById('summary-outcome');
    const summaryWhat = document.getElementById('summary-what');
    const summaryWhy = document.getElementById('summary-why');
    const summaryAttempted = document.getElementById('summary-attempted');
    const summaryWorked = document.getElementById('summary-worked');
    const summaryStopped = document.getElementById('summary-stopped');
    const summaryNext = document.getElementById('summary-next');
    const summaryPub = document.getElementById('summary-pub');

    if (summaryOutcome) summaryOutcome.innerHTML = '<strong>Outcome:</strong> <span>Awaiting run...</span>';
    if (summaryWhat) summaryWhat.innerHTML = '<strong>What Happened:</strong> <span>-</span>';
    if (summaryWhy) summaryWhy.innerHTML = '<strong>Why It Happened:</strong> <span>-</span>';
    if (summaryAttempted) summaryAttempted.innerHTML = '<strong>What ACID AI Attempted:</strong> <span>-</span>';
    if (summaryWorked) summaryWorked.innerHTML = '<strong>Did the Repair Work:</strong> <span>-</span>';
    if (summaryStopped) summaryStopped.innerHTML = '<strong>Why ACID AI Stopped:</strong> <span>-</span>';
    if (summaryNext) summaryNext.innerHTML = '<strong>What to Do Next:</strong> <span>-</span>';
    if (summaryPub) summaryPub.innerHTML = '<strong>Publication Status:</strong> <span>-</span>';

    const btnViewReport = document.getElementById('btn-view-report');
    const btnExportPdf = document.getElementById('btn-export-pdf');
    const btnExportMarkdown = document.getElementById('btn-export-markdown');
    const btnExportJson = document.getElementById('btn-export-json');
    if (btnViewReport) btnViewReport.disabled = true;
    if (btnExportPdf) btnExportPdf.disabled = true;
    if (btnExportMarkdown) btnExportMarkdown.disabled = true;
    if (btnExportJson) btnExportJson.disabled = true;
  }

  // 8. Primary Action: Run Analysis & Repair on Repository
  async function executeRepoRun() {
    const targetPath = inputRepoPath ? inputRepoPath.value.trim() : '';
    if (!targetPath) {
      setRepoFeedback(false, 'Specify a repository path before running analysis.');
      return;
    }

    resetReportCardState();

    // Set UI into pending running state
    updateStepper(['active', 'idle', 'idle', 'idle', 'idle']);
    if (runStatusDot) runStatusDot.className = 'run-status-indicator running';
    if (runStatusTitle) runStatusTitle.textContent = 'Running Analysis in Disposable Workspace...';
    if (runStatusSubtitle) {
      runStatusSubtitle.textContent = 'Provisioned ephemeral copy (Zero Host Mutation). Running tests and triage...';
    }
    if (tagRunId) tagRunId.textContent = 'ID: Initializing...';
    if (tagRunMode) tagRunMode.textContent = `Mode: ${currentProviderMode.toUpperCase()}`;
    if (tagRunAttempts) tagRunAttempts.textContent = 'Attempts: Running...';
    if (tagRunTime) tagRunTime.textContent = 'Duration: ...';
    if (btnRunAnalysis) btnRunAnalysis.disabled = true;

    terminalLogs.textContent = 'Provisioning ephemeral disposable workspace...\nExecuting test discovery and autonomous self-healing loop...';

    const chkEnablePr = document.getElementById('chk-enable-pr');
    const inputGithubToken = document.getElementById('input-github-token');
    const enablePublishing = chkEnablePr ? chkEnablePr.checked : false;
    const githubToken = (inputGithubToken && inputGithubToken.value.trim()) ? inputGithubToken.value.trim() : undefined;

    try {
      const res = await fetch('/api/repo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_path: targetPath,
          provider_mode: currentProviderMode,
          enable_publishing: enablePublishing,
          github_token: githubToken,
        }),
      });

      if (!res.ok) {
        let err;
        try {
          err = await res.json();
        } catch (_) {
          err = { error: `Server error (HTTP ${res.status}: ${res.statusText || 'Error'})` };
        }
        const errMsg = err.error || 'Server error';
        terminalLogs.textContent = `Error executing repository analysis: ${errMsg}`;
        updateStepper(['blocked', 'idle', 'idle', 'idle', 'idle']);
        if (runStatusDot) runStatusDot.className = 'run-status-indicator failed';
        if (runStatusTitle) runStatusTitle.textContent = `Analysis Run Failed (HTTP ${res.status})`;
        if (runStatusSubtitle) runStatusSubtitle.textContent = errMsg;
        if (tagRunId) tagRunId.textContent = 'ID: Failed';
        if (tagRunAttempts) tagRunAttempts.textContent = 'Attempts: Failed';
        if (tagRunTime) tagRunTime.textContent = 'Duration: Stopped';
        if (btnRunAnalysis) btnRunAnalysis.disabled = false;
        return;
      }

      const data = await res.json();
      renderRunResult(data);

      // Update Run Status Area with truthful final metadata
      const rec = data.run_record || {};
      const finalStatus = data.final_status || (data.is_healthy ? 'healthy' : 'unresolved');
      const statusClassMap = {
        repaired: 'repaired',
        'partially repaired': 'partially-repaired',
        healthy: 'healthy',
        blocked: 'blocked',
        unresolved: 'unresolved',
      };
      if (runStatusDot) {
        runStatusDot.className = `run-status-indicator ${statusClassMap[finalStatus] || 'failed'}`;
      }
      if (runStatusTitle) {
        const titleMap = {
          repaired: 'Status: Fully Repaired (Autonomous Loop)',
          'partially repaired': 'Status: Partially Repaired',
          healthy: 'Status: Pipeline Healthy',
          blocked: 'Status: Execution Blocked',
          unresolved: 'Status: Unresolved Failure',
        };
        runStatusTitle.textContent = titleMap[finalStatus] || `Status: ${finalStatus.toUpperCase()}`;
      }
      if (runStatusSubtitle) {
        runStatusSubtitle.textContent = data.stop_reason || (data.is_healthy
          ? 'Silent Healthy Bypass: 0 tokens spent. Zero PR comments posted.'
          : `Triaged ${data.classification?.detected?.length || 0} failure stage(s). Autonomous repair loop complete.`);
      }
      if (tagRunId) tagRunId.textContent = `ID: ${rec.run_id || data.run_id}`;
      if (tagRunMode) tagRunMode.textContent = `Mode: ${(rec.mode || currentProviderMode).toUpperCase()}`;
      if (tagRunAttempts) {
        const used = data.retry_count || (data.attempts ? data.attempts.length : 0);
        const maxAtt = data.max_attempts || 3;
        tagRunAttempts.textContent = `Attempts: ${used}/${maxAtt}`;
      }
      if (tagRunTime) tagRunTime.textContent = `Duration: ${data.elapsed_seconds || 0}s`;

      loadHistory();
    } catch (e) {
      const isNetworkErr = (e instanceof TypeError && (e.message.toLowerCase().includes('fetch') || e.message.toLowerCase().includes('network') || e.message.toLowerCase().includes('failed to fetch'))) || (typeof navigator !== 'undefined' && !navigator.onLine);
      const category = isNetworkErr ? 'Execution Network Error' : (e.name ? `Client Error (${e.name})` : 'Execution Error');
      const detailMsg = e.message || 'An unexpected error occurred during repository analysis.';

      terminalLogs.textContent = `[${category}] ${detailMsg}\n${e.stack || ''}`;
      updateStepper(['blocked', 'idle', 'idle', 'idle', 'idle']);
      if (runStatusDot) runStatusDot.className = 'run-status-indicator failed';
      if (runStatusTitle) runStatusTitle.textContent = category;
      if (runStatusSubtitle) runStatusSubtitle.textContent = detailMsg;
      if (tagRunId) tagRunId.textContent = 'ID: Aborted';
      if (tagRunAttempts) tagRunAttempts.textContent = 'Attempts: Aborted';
      if (tagRunTime) tagRunTime.textContent = 'Duration: Stopped';
    } finally {
      if (btnRunAnalysis) btnRunAnalysis.disabled = false;
    }
  }

  if (btnRunAnalysis) {
    btnRunAnalysis.addEventListener('click', executeRepoRun);
  }

  // 9. Execute Scenario Run (Demo Mode)
  async function executeRun(scenarioId) {
    resetReportCardState();
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
        let err;
        try {
          err = await res.json();
        } catch (_) {
          err = { error: `Server error (HTTP ${res.status}: ${res.statusText || 'Error'})` };
        }
        const errMsg = err.error || 'Server error';
        terminalLogs.textContent = `Error executing scenario: ${errMsg}`;
        updateStepper(['blocked', 'idle', 'idle', 'idle', 'idle']);
        return;
      }

      const data = await res.json();
      renderRunResult(data);
      loadHistory();
    } catch (e) {
      const isNetworkErr = (e instanceof TypeError && (e.message.toLowerCase().includes('fetch') || e.message.toLowerCase().includes('network') || e.message.toLowerCase().includes('failed to fetch'))) || (typeof navigator !== 'undefined' && !navigator.onLine);
      const category = isNetworkErr ? 'Network Connection Error' : (e.name ? `Client Error (${e.name})` : 'Execution Error');
      terminalLogs.textContent = `[${category}] ${e.message || e}`;
      updateStepper(['blocked', 'idle', 'idle', 'idle', 'idle']);
    }
  }

  // 10. Load demonstration scenarios
  async function loadScenarios() {
    try {
      const res = await fetch('/api/scenarios');
      const data = await res.json();
      if (!scenariosContainer) return;
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

  // 11. Render complete run result
  function renderRunResult(data) {
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
    if (aiProviderBadge) {
      aiProviderBadge.textContent = data.truthfulness?.ai_provider || 'N/A';
    }

    // Autonomous Repair Loop Card Render
    const finalStatus = data.final_status || (data.is_healthy ? 'healthy' : 'unresolved');
    const attempts = data.attempts || [];
    const retryCount = data.retry_count != null ? data.retry_count : attempts.length;
    const maxAttempts = data.max_attempts || 3;
    const verifiedPatches = data.verified_patches || [];
    const patch = data.patch || {};

    if (valLoopFinalStatus) {
      valLoopFinalStatus.textContent = finalStatus.toUpperCase();
      if (finalStatus === 'repaired' || finalStatus === 'healthy') {
        valLoopFinalStatus.style.color = 'var(--color-success)';
      } else if (finalStatus === 'partially repaired') {
        valLoopFinalStatus.style.color = 'var(--color-info)';
      } else if (finalStatus === 'blocked') {
        valLoopFinalStatus.style.color = 'var(--color-warning)';
      } else {
        valLoopFinalStatus.style.color = 'var(--color-failure)';
      }
    }

    if (valLoopAttemptsCount) {
      valLoopAttemptsCount.textContent = `${retryCount} / ${maxAttempts}`;
    }

    if (valLoopVerifiedPatches) {
      valLoopVerifiedPatches.textContent = `${verifiedPatches.length}`;
    }

    if (badgeFinalStatus) {
      const badgeClasses = {
        repaired: 'verified',
        healthy: 'verified',
        'partially repaired': 'warning',
        blocked: 'blocked',
        unresolved: 'blocked',
      };
      badgeFinalStatus.className = `badge-pill ${badgeClasses[finalStatus] || 'blocked'}`;
      badgeFinalStatus.textContent = finalStatus.toUpperCase();
    }

    if (stopReasonBox && valStopReason) {
      if (data.stop_reason) {
        stopReasonBox.style.display = 'block';
        valStopReason.textContent = data.stop_reason;
      } else {
        stopReasonBox.style.display = 'none';
      }
    }

    if (attemptsTimeline) {
      attemptsTimeline.innerHTML = '';
      if (data.is_healthy) {
        attemptsTimeline.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:4px 0;">No repair attempts needed (repository healthy).</div>';
      } else if (attempts.length === 0) {
        attemptsTimeline.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:4px 0;">No repair attempts executed.</div>';
      } else {
        attempts.forEach((att) => {
          const item = document.createElement('div');
          const statusClass = att.status === 'VERIFIED_SUCCESS' ? 'verified' : (att.status === 'VERIFIED_FAILED' ? 'verification_failed' : 'blocked');
          item.className = `attempt-item ${statusClass}`;
          const badgeClass = att.status === 'VERIFIED_SUCCESS' ? 'verified' : (att.status === 'VERIFIED_FAILED' ? 'failed' : 'blocked');
          const patchFiles = formatFileList(att.patch && att.patch.files);
          const rootCause = att.diagnosis ? (att.diagnosis.root_cause || 'Diagnosis completed') : 'Diagnosis unavailable';

          item.innerHTML = `
            <div class="attempt-header">
              <span class="attempt-title">Attempt #${att.attempt}: <code>${escapeHtml(att.failure_category || 'actionable_failure')}</code></span>
              <span class="badge-pill ${badgeClass}" style="font-size:10px;padding:2px 8px;">${escapeHtml(att.status)}</span>
            </div>
            <div class="attempt-details">
              <div><strong>Diagnosis:</strong> ${escapeHtml(rootCause)}</div>
              <div><strong>Candidate Files:</strong> <code>${escapeHtml(patchFiles)}</code></div>
              <div><strong>Outcome:</strong> ${escapeHtml(att.reason || 'Verification completed')}</div>
            </div>
          `;
          attemptsTimeline.appendChild(item);
        });
      }
    }

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
    const verifState = data.verification?.is_verified ? 'completed' : 'blocked';
    updateStepper(['completed', 'completed', 'completed', verifState, 'blocked']);

    // Diagnosis Card
    const diag = data.diagnosis || {};
    diagnosisRootCause.innerHTML = `<strong>Root Cause:</strong> ${escapeHtml(diag.root_cause || 'Diagnosing root cause...')}`;
    diagnosisMeta.innerHTML = `
      <div class="meta-box"><span class="meta-box-label">Category</span><div class="meta-box-val">${escapeHtml((diag.failure_types || []).join(', ') || 'N/A')}</div></div>
      <div class="meta-box"><span class="meta-box-label">Severity</span><div class="meta-box-val" style="color:${diag.severity === 'high' || diag.severity === 'critical' ? 'var(--color-failure)' : 'var(--color-warning)'}">${escapeHtml((diag.severity || 'unknown').toUpperCase())}</div></div>
      <div class="meta-box"><span class="meta-box-label">Confidence</span><div class="meta-box-val" style="color:var(--color-success)">${escapeHtml((diag.confidence || 'medium').toUpperCase())}</div></div>
    `;

    // Fixes
    diagnosisFixes.innerHTML = '';
    if (diag.fixes && diag.fixes.length > 0) {
      diag.fixes.forEach((f) => {
        const fixBox = document.createElement('div');
        fixBox.className = 'fix-item';
        fixBox.innerHTML = `
          <div class="fix-title">[${escapeHtml(((f.type || 'fix')).toUpperCase())}] ${escapeHtml(f.title || '')}</div>
          <div class="fix-desc">${escapeHtml(f.description || '')}</div>
          ${f.code ? `<code class="fix-code">${escapeHtml(f.code)}</code>` : ''}
        `;
        diagnosisFixes.appendChild(fixBox);
      });
    } else {
      const isLiveAiReq = (data.status === 'BLOCKED' || data.final_status === 'blocked' || (patch.validation_errors || []).some((e) => e.code === 'LIVE_AI_REQUIRED' || e.code === 'PROVIDER_UNAVAILABLE'));
      const emptyMsg = isLiveAiReq
        ? 'Automated candidate patch synthesis is unavailable in offline mock mode (LIVE_AI_REQUIRED). Genuine failure logs and affected files have been captured and triaged. Provide live AI credentials (GEMINI_API_KEY or ANTHROPIC_API_KEY) to generate candidate code repairs.'
        : 'No specific automated code fixes proposed for this failure.';
      diagnosisFixes.innerHTML = `
        <div class="fix-item" style="border-left-color: var(--color-warning);">
          <div class="fix-title" style="color: var(--color-warning);">Offline Triage / Live AI Required</div>
          <div class="fix-desc">${escapeHtml(emptyMsg)}</div>
        </div>
      `;
    }

    diagnosisEvidence.textContent = diag.log_evidence || 'No cited evidence.';

    // Patch Review Card
    if (!patch.diff) {
      const isOfflineMock = (data.status === 'BLOCKED' || data.final_status === 'blocked' || (patch.validation_errors || []).some((e) => e.code === 'LIVE_AI_REQUIRED' || e.code === 'PROVIDER_UNAVAILABLE'));
      const bannerTitle = isOfflineMock ? 'Live AI Required for Automated Patch Synthesis' : 'No Candidate Patch Generated';
      const explanationText = patch.explanation || (isOfflineMock
        ? 'Candidate patch generation is unavailable in offline mock mode (LIVE_AI_REQUIRED). Real repository tests were executed and genuine failure evidence was captured.'
        : 'No diff available for this run.');
      patchDiffContainer.innerHTML = `
        <div style="padding:16px;background:rgba(255,255,255,0.02);border-radius:6px;border:1px dashed rgba(255,255,255,0.1);">
          <div style="color:var(--color-warning);font-weight:600;margin-bottom:6px;display:flex;align-items:center;gap:6px;">
            <span>ℹ️</span> <span>${escapeHtml(bannerTitle)}</span>
          </div>
          <div style="font-family:var(--font-mono);font-size:12px;color:var(--text-muted);line-height:1.5;">
            ${escapeHtml(explanationText)}
          </div>
        </div>
      `;
    } else {
      patchDiffContainer.innerHTML = renderSyntaxDiff(patch.diff);
    }
    const targetFiles = (patch.files && patch.files.length)
      ? patch.files
      : (data.affected_files && data.affected_files.length ? data.affected_files : []);
    patchFilesList.textContent = formatFileList(targetFiles);

    if (patch.is_valid) {
      patchPolicyChecks.innerHTML = `
        <span class="policy-chip">✓ Path Allowlist Enforced</span>
        <span class="policy-chip">✓ Traversal Blocked</span>
        <span class="policy-chip">✓ Prohibited Files Protected (.git, .github)</span>
        <span class="policy-chip">✓ Bounds Checked (&le; ${patch.max_lines || 150} lines, &le; ${patch.max_files || 5} files)</span>
        <span class="policy-chip">✓ In-Memory AST Matching Passed</span>
      `;
    } else {
      const errList = (patch.validation_errors || []).map((e) => `[${e.code}] ${e.message}`).join('; ');
      patchPolicyChecks.innerHTML = `
        <span class="policy-chip" style="color:var(--color-failure);border-color:rgba(239,68,68,0.4)">
          Policy Status: ${escapeHtml(errList || patch.explanation || 'Patch not validated')}
        </span>
      `;
    }

    // Safety & Verification Card
    const verif = data.verification || {};
    verifStatusBadge.className = `badge-pill ${verif.badge_type || 'blocked'}`;
    verifStatusBadge.textContent = verif.display || 'BLOCKED';

    verifAlert.className = `safety-alert ${verif.badge_type === 'verified' ? 'verified' : 'blocked'}`;
    verifAlert.innerHTML = `
      <div class="alert-icon">${verif.badge_type === 'verified' ? '🛡️' : '⚠️'}</div>
      <div class="alert-text">
        <h4>${verif.badge_type === 'verified' ? 'Container Isolation Verified' : 'Fail-Closed Safety Gate Active'}</h4>
        <p>${escapeHtml(verif.message || 'Verification outcome recorded.')}</p>
        ${verif.error_detail ? `<p style="margin-top:6px;font-family:var(--font-mono);font-size:11px;opacity:0.8;">Detail: ${escapeHtml(verif.error_detail)}</p>` : ''}
      </div>
    `;

    // Repair Delivery Card (Phase 5)
    const pub = data.publication || {};
    const pubStatus = (pub.status || 'none').toLowerCase();
    const isPubSuccess = pubStatus === 'published' || pubStatus === 'success';

    if (isPubSuccess && pub.pr_url) {
      pubStatusBadge.className = 'badge-pill verified';
      pubStatusBadge.textContent = pub.display || `Draft PR #${pub.pr_number || ''}`;
      pubAlert.className = 'safety-alert verified';
      pubAlert.innerHTML = `
        <div class="alert-icon">🚀</div>
        <div class="alert-text">
          <h4>Verified Draft PR Created</h4>
          <p>
            Successfully published Draft Pull Request:
            <a href="${escapeHtml(pub.pr_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--text-link);font-weight:600;text-decoration:underline;">
              Draft PR #${escapeHtml(String(pub.pr_number || ''))}
            </a>
            on dedicated branch <code>${escapeHtml(pub.branch_name || '')}</code>.
          </p>
          <p style="margin-top:6px;font-size:11px;color:var(--text-muted);">
            Human engineering review and approval remain mandatory before merging.
          </p>
        </div>
      `;
    } else if (pubStatus === 'skipped_already_exists') {
      pubStatusBadge.className = 'badge-pill verified';
      pubStatusBadge.textContent = `Existing PR #${pub.pr_number || ''}`;
      pubAlert.className = 'safety-alert verified';
      pubAlert.innerHTML = `
        <div class="alert-icon">ℹ️</div>
        <div class="alert-text">
          <h4>Repair PR Already Exists</h4>
          <p>
            An active Draft Pull Request already exists for this branch:
            <a href="${escapeHtml(pub.pr_url || '#')}" target="_blank" rel="noopener noreferrer" style="color:var(--text-link);text-decoration:underline;">
              Draft PR #${escapeHtml(String(pub.pr_number || ''))}
            </a>.
          </p>
        </div>
      `;
    } else if (pubStatus === 'skipped_healthy') {
      pubStatusBadge.className = 'badge-pill verified';
      pubStatusBadge.textContent = 'Skipped (Healthy)';
      pubAlert.className = 'safety-alert healthy';
      pubAlert.innerHTML = `
        <div class="alert-icon">✅</div>
        <div class="alert-text">
          <h4>Zero Superfluous Pull Requests</h4>
          <p>Repository is healthy; no pull request needed.</p>
        </div>
      `;
    } else if (pubStatus === 'skipped_missing_token') {
      pubStatusBadge.className = 'badge-pill blocked';
      pubStatusBadge.textContent = 'SKIPPED — Missing Token';
      pubAlert.className = 'safety-alert blocked';
      pubAlert.innerHTML = `
        <div class="alert-icon">🔒</div>
        <div class="alert-text">
          <h4>GitHub Token Missing</h4>
          <p>${escapeHtml(pub.message || 'Draft PR publishing is enabled, but no GitHub token was provided.')}</p>
        </div>
      `;
    } else if (pubStatus === 'skipped_missing_remote') {
      pubStatusBadge.className = 'badge-pill blocked';
      pubStatusBadge.textContent = 'SKIPPED — Missing Remote';
      pubAlert.className = 'safety-alert blocked';
      pubAlert.innerHTML = `
        <div class="alert-icon">🔗</div>
        <div class="alert-text">
          <h4>GitHub Remote Origin Missing</h4>
          <p>${escapeHtml(pub.message || 'Repository does not have a configured GitHub remote origin.')}</p>
        </div>
      `;
    } else if (pubStatus === 'permission_error') {
      pubStatusBadge.className = 'badge-pill blocked';
      pubStatusBadge.textContent = 'PERMISSION ERROR';
      pubAlert.className = 'safety-alert blocked';
      pubAlert.innerHTML = `
        <div class="alert-icon">⚠️</div>
        <div class="alert-text">
          <h4>GitHub Authentication / Permission Error</h4>
          <p>${escapeHtml(pub.message || 'Authentication failed or insufficient repository write scopes.')}</p>
        </div>
      `;
    } else if (pubStatus === 'fork_limitation') {
      pubStatusBadge.className = 'badge-pill blocked';
      pubStatusBadge.textContent = 'FORK LIMITATION';
      pubAlert.className = 'safety-alert blocked';
      pubAlert.innerHTML = `
        <div class="alert-icon">🍴</div>
        <div class="alert-text">
          <h4>Fork Limitation Active</h4>
          <p>${escapeHtml(pub.message || 'Write permissions restricted on fork.')}</p>
        </div>
      `;
    } else {
      pubStatusBadge.className = 'badge-pill blocked';
      pubStatusBadge.textContent = pub.display || 'BLOCKED';
      pubAlert.className = 'safety-alert blocked';
      pubAlert.innerHTML = `
        <div class="alert-icon">🔒</div>
        <div class="alert-text">
          <h4>${escapeHtml(pub.display || 'Publication Gate')}</h4>
          <p>${escapeHtml(pub.message || 'Draft PR publishing is not active.')}</p>
        </div>
      `;
    }

    // --- Verified Final Report Card (Phase 5) ---
    const finalRep = data.final_report;
    const reportOutcomeBadge = document.getElementById('report-outcome-badge');
    const reportValRunId = document.getElementById('report-val-run-id');
    const reportValOutcome = document.getElementById('report-val-outcome');
    const reportValAttempts = document.getElementById('report-val-attempts');
    const reportValDelivery = document.getElementById('report-val-delivery');
    const reportValScope = document.getElementById('report-val-scope');
    const btnViewReport = document.getElementById('btn-view-report');
    const btnExportPdf = document.getElementById('btn-export-pdf');
    const btnExportMarkdown = document.getElementById('btn-export-markdown');
    const btnExportJson = document.getElementById('btn-export-json');

    if (finalRep) {
      if (reportValRunId) reportValRunId.textContent = finalRep.run_id || data.run_id;
      const outcome = (finalRep.outcome || 'unresolved').toLowerCase();
      const outcomeLabels = {
        repaired: 'REPAIRED',
        healthy: 'HEALTHY',
        'partially repaired': 'PARTIALLY REPAIRED',
        blocked: 'BLOCKED',
        unresolved: 'UNRESOLVED',
      };
      const outcomeColors = {
        repaired: 'var(--color-success)',
        healthy: 'var(--color-success)',
        'partially repaired': 'var(--color-info)',
        blocked: 'var(--color-warning)',
        unresolved: 'var(--color-failure)',
      };
      if (reportValOutcome) {
        reportValOutcome.textContent = outcomeLabels[outcome] || outcome.toUpperCase();
        reportValOutcome.style.color = outcomeColors[outcome] || 'var(--text-primary)';
      }
      if (reportOutcomeBadge) {
        reportOutcomeBadge.className = `badge-pill ${outcome === 'repaired' || outcome === 'healthy' ? 'verified' : (outcome === 'partially repaired' ? 'info' : 'blocked')}`;
        reportOutcomeBadge.textContent = outcomeLabels[outcome] || outcome.toUpperCase();
      }
      if (reportValAttempts) {
        reportValAttempts.textContent = `${finalRep.retry_count || 0} / ${data.max_attempts || 3}`;
      }
      if (reportValDelivery) {
        if (isPubSuccess) {
          reportValDelivery.textContent = `Published (PR #${pub.pr_number || ''})`;
          reportValDelivery.style.color = 'var(--color-success)';
        } else if (pubStatus.includes('skipped')) {
          reportValDelivery.textContent = 'Skipped';
          reportValDelivery.style.color = 'var(--text-secondary)';
        } else {
          reportValDelivery.textContent = 'Blocked';
          reportValDelivery.style.color = 'var(--color-warning)';
        }
      }
      if (reportValScope) {
        reportValScope.textContent = finalRep.verification_scope_statement || 'Truthful verification scope active.';
      }

      // Plain-English Run Summary (Level 1)
      const summary = (finalRep && finalRep.summary) ? finalRep.summary : (data.summary || null);
      const summaryOutcome = document.getElementById('summary-outcome');
      const summaryWhat = document.getElementById('summary-what');
      const summaryWhy = document.getElementById('summary-why');
      const summaryAttempted = document.getElementById('summary-attempted');
      const summaryWorked = document.getElementById('summary-worked');
      const summaryStopped = document.getElementById('summary-stopped');
      const summaryNext = document.getElementById('summary-next');
      const summaryPub = document.getElementById('summary-pub');

      if (summary) {
        if (summaryOutcome) {
          const outText = summary.overall_outcome_text || summary.overall_outcome || outcomeLabels[outcome] || outcome.toUpperCase();
          summaryOutcome.innerHTML = `<strong>Outcome:</strong> <span style="font-weight:600;color:${outcomeColors[outcome] || 'var(--text-primary)'};">${escapeHtml(outText)}</span>`;
        }
        if (summaryWhat) {
          summaryWhat.innerHTML = `<strong>What Happened:</strong> <span>${escapeHtml(summary.what_happened || '-')}</span>`;
        }
        if (summaryWhy) {
          summaryWhy.innerHTML = `<strong>Why It Happened:</strong> <span>${escapeHtml(summary.why_it_happened || '-')}</span>`;
        }
        if (summaryAttempted) {
          summaryAttempted.innerHTML = `<strong>What ACID AI Attempted:</strong> <span>${escapeHtml(summary.what_acid_attempted || '-')}</span>`;
        }
        if (summaryWorked) {
          summaryWorked.innerHTML = `<strong>Did the Repair Work:</strong> <span>${escapeHtml(summary.did_repair_work || '-')}</span>`;
        }
        if (summaryStopped) {
          summaryStopped.innerHTML = `<strong>Why ACID AI Stopped:</strong> <span>${escapeHtml(summary.why_agent_stopped || '-')}</span>`;
        }
        if (summaryNext) {
          summaryNext.innerHTML = `<strong>What to Do Next:</strong> <span>${escapeHtml(summary.what_to_do_next || '-')}</span>`;
        }
        if (summaryPub) {
          if (summary.pr_url) {
            summaryPub.innerHTML = `<strong>Publication Status:</strong> <a href="${escapeHtml(summary.pr_url)}" target="_blank" rel="noopener noreferrer" style="color:#67e8f9;text-decoration:underline;">${escapeHtml(summary.publication_status)} (PR #${summary.pr_number || ''})</a>`;
          } else {
            summaryPub.innerHTML = `<strong>Publication Status:</strong> <span>${escapeHtml(summary.publication_status || '-')}</span>`;
          }
        }
      }

      // Enable action buttons
      if (btnViewReport) {
        btnViewReport.disabled = false;
        btnViewReport.onclick = () => openReportModal(finalRep);
      }
      if (btnExportPdf) {
        btnExportPdf.disabled = false;
        btnExportPdf.onclick = () => downloadReportPdf(finalRep.run_id || data.run_id, btnExportPdf);
      }
      if (btnExportMarkdown) {
        btnExportMarkdown.disabled = false;
        btnExportMarkdown.onclick = () => downloadFile(`${finalRep.run_id}-report.md`, finalRep.markdown || '', 'text/markdown');
      }
      if (btnExportJson) {
        btnExportJson.disabled = false;
        btnExportJson.onclick = () => downloadFile(`${finalRep.run_id}-report.json`, JSON.stringify(finalRep, null, 2), 'application/json');
      }
    }
  }

  // Report Modal and File Export Handlers
  function openReportModal(report) {
    const modal = document.getElementById('modal-report-overlay');
    const content = document.getElementById('modal-report-content');
    const title = document.getElementById('modal-report-title');
    const btnModalPdf = document.getElementById('btn-modal-pdf');
    const modalSummaryBox = document.getElementById('modal-summary-box');
    const modalSummaryContent = document.getElementById('modal-summary-content');

    if (!modal || !content) return;

    if (title) title.textContent = `Report — ${report.run_id} (${(report.outcome || '').toUpperCase()})`;
    content.textContent = report.markdown || JSON.stringify(report, null, 2);

    if (btnModalPdf) {
      btnModalPdf.onclick = () => downloadReportPdf(report.run_id, btnModalPdf);
    }

    if (modalSummaryBox && modalSummaryContent) {
      if (report.summary) {
        modalSummaryBox.style.display = 'block';
        const s = report.summary;
        modalSummaryContent.innerHTML = `
          <div style="display:grid;grid-template-columns:1fr;gap:6px;">
            <div><strong>Overall Outcome:</strong> ${escapeHtml(s.overall_outcome_text || s.overall_outcome)}</div>
            <div><strong>What Happened:</strong> ${escapeHtml(s.what_happened)}</div>
            <div><strong>Why It Happened:</strong> ${escapeHtml(s.why_it_happened)}</div>
            <div><strong>What ACID AI Attempted:</strong> ${escapeHtml(s.what_acid_attempted)}</div>
            <div><strong>Did the Repair Work:</strong> ${escapeHtml(s.did_repair_work)}</div>
            <div><strong>Why ACID AI Stopped:</strong> ${escapeHtml(s.why_agent_stopped)}</div>
            <div><strong>What to Do Next:</strong> ${escapeHtml(s.what_to_do_next)}</div>
            <div><strong>Publication Status:</strong> ${s.pr_url ? `<a href="${escapeHtml(s.pr_url)}" target="_blank" rel="noopener noreferrer" style="color:#67e8f9;text-decoration:underline;">${escapeHtml(s.publication_status)}</a>` : escapeHtml(s.publication_status)}</div>
          </div>
        `;
      } else {
        modalSummaryBox.style.display = 'none';
      }
    }

    modal.classList.remove('hidden');
  }

  function closeReportModal() {
    const modal = document.getElementById('modal-report-overlay');
    if (modal) modal.classList.add('hidden');
  }

  function downloadFile(filename, text, mimeType) {
    const blob = new Blob([text], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // Trigger PDF Report Download with user feedback
  async function downloadReportPdf(runId, buttonElement) {
    if (!runId) return;
    const originalText = buttonElement ? buttonElement.innerHTML : '';
    if (buttonElement) {
      buttonElement.disabled = true;
      buttonElement.innerHTML = '<span>⏳</span> Generating PDF...';
    }
    try {
      const res = await fetch(`/api/reports/${encodeURIComponent(runId)}/pdf`);
      if (!res.ok) {
        let errMessage = `HTTP ${res.status}`;
        try {
          const errData = await res.json();
          if (errData && errData.error) errMessage = errData.error;
        } catch (_) {}
        alert(`Failed to download PDF report: ${errMessage}`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `acid-ai-report-${runId}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Network error downloading PDF report: ${e.message}`);
    } finally {
      if (buttonElement) {
        buttonElement.disabled = false;
        buttonElement.innerHTML = originalText;
      }
    }
  }

  // Wire Modal buttons
  const btnModalClose = document.getElementById('btn-modal-close');
  const btnModalCopy = document.getElementById('btn-modal-copy');
  const modalOverlay = document.getElementById('modal-report-overlay');

  if (btnModalClose) btnModalClose.addEventListener('click', closeReportModal);
  if (modalOverlay) {
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) closeReportModal();
    });
  }
  if (btnModalCopy) {
    btnModalCopy.addEventListener('click', () => {
      const content = document.getElementById('modal-report-content');
      if (content && content.textContent) {
        navigator.clipboard.writeText(content.textContent).then(() => {
          btnModalCopy.textContent = '✓ Copied!';
          setTimeout(() => { btnModalCopy.textContent = 'Copy Markdown'; }, 2000);
        });
      }
    });
  }

  // 12. Load run history
  async function loadHistory() {
    try {
      const res = await fetch('/api/history');
      const data = await res.json();
      historyTableBody.innerHTML = '';

      if (!data.history || !data.history.length) {
        historyTableBody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No runs recorded in this session.</td></tr>';
        return;
      }

      data.history.forEach((h) => {
        const tr = document.createElement('tr');
        const isRepo = (h.failure_type === 'repository' || !h.scenario_id);
        const modeBadge = isRepo
          ? '<span class="tab-badge live">REAL REPO</span>'
          : '<span class="tab-badge mock">MOCK DEMO</span>';

        const statusText = h.final_status || h.status;
        let statusColor = 'var(--color-failure)';
        if (h.is_healthy || statusText === 'repaired' || statusText === 'healthy') {
          statusColor = 'var(--color-success)';
        } else if (statusText === 'partially repaired') {
          statusColor = 'var(--color-info)';
        } else if (statusText === 'blocked') {
          statusColor = 'var(--color-warning)';
        }

        tr.innerHTML = `
          <td><code>${escapeHtml(h.run_id)}</code></td>
          <td>${escapeHtml(h.scenario_name)}</td>
          <td>${modeBadge}</td>
          <td><span style="color:${statusColor};font-weight:600;">${escapeHtml(statusText)}</span></td>
          <td><code>${escapeHtml(h.verification_display)}</code></td>
          <td>${escapeHtml(h.timestamp)}</td>
        `;
        historyTableBody.appendChild(tr);
      });
    } catch (e) {
      console.error('Failed to load history:', e);
    }
  }

  // 13. Reset history
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/reset', { method: 'POST' });
        loadHistory();
      } catch (e) {
        console.error('Failed to reset history:', e);
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

  // Helper function to format candidate file lists safely
  function formatFileList(files) {
    if (!files) return 'None';
    if (typeof files === 'string') {
      const s = files.trim();
      return s || 'None';
    }
    if (typeof files === 'object' && !Array.isArray(files)) {
      const p = files.path || files.name || files.target_path || files.file_path;
      if (p) return String(p).trim();
      const keys = Object.keys(files);
      if (keys.length > 0 && !keys.includes('0')) return keys.join(', ');
      return 'None';
    }
    if (Array.isArray(files)) {
      if (files.length === 0) return 'None';
      const formatted = files.map((f) => {
        if (!f) return '';
        if (typeof f === 'string') return f.trim();
        if (typeof f === 'object') {
          return f.path || f.name || f.target_path || f.file_path || '';
        }
        return String(f);
      }).filter(Boolean);
      return formatted.length > 0 ? formatted.join(', ') : 'None';
    }
    return String(files);
  }

  // Initial load
  loadSystemStatus();
  loadCurrentRepository();
  loadScenarios();
  loadHistory();
});
