// ============================================================
// renderer.js — Enterprise Monitor
// Includes: credential modal, screen recording UI, video list,
//           login/dashboard UI updates, all existing features preserved.
// ============================================================

// ─── GLOBAL STATE ────────────────────────────────────────────
let isAuthenticated = false;
let currentTab = 'overview';
let currentSubTab = 'app-tracking';
let charts = {};

function getLocalDateString() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

let currentDate = getLocalDateString();
let currentTimezone = 'UTC';

// ─── INIT ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('date-picker').value = currentDate;
  setupEventListeners();
  await checkAuthentication();
});

// ─── AUTH ────────────────────────────────────────────────────
async function checkAuthentication() {
  try {
    const result = await window.electronAPI.checkAuth();
    isAuthenticated = result.authenticated;
    if (isAuthenticated) {
      showDashboard();
      initializeCharts();
      await loadDashboardData();
    } else {
      showLogin();
    }
  } catch (error) {
    console.error('Auth check failed:', error);
    showLogin();
  }
}

function showLogin() {
  document.getElementById('login-container').classList.add('active');
  document.getElementById('dashboard-container').classList.remove('active');
}

function showDashboard() {
  document.getElementById('login-container').classList.remove('active');
  document.getElementById('dashboard-container').classList.add('active');
  startTokenCountdown();
}

// ─── EVENT LISTENERS ─────────────────────────────────────────
function setupEventListeners() {
  // Login
  document.getElementById('login-btn').addEventListener('click', handleLoginClick);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const loginCont = document.getElementById('login-container');
      if (loginCont.classList.contains('active')) handleLoginClick();
    }
  });

  // Header
  document.getElementById('logout-btn').addEventListener('click', handleLogout);
  document.getElementById('refresh-btn').addEventListener('click', () => loadDashboardData());
  document.getElementById('change-credentials-btn').addEventListener('click', openCredentialsModal);

  // Date controls
  document.getElementById('date-picker').addEventListener('change', (e) => { currentDate = e.target.value; });
  document.getElementById('today-btn').addEventListener('click', () => {
    currentDate = getLocalDateString();
    document.getElementById('date-picker').value = currentDate;
    loadDashboardData();
  });
  document.getElementById('search-btn').addEventListener('click', () => {
    const v = document.getElementById('date-picker').value;
    if (v) currentDate = v;
    loadDashboardData();
  });

  // Timezone — must be top-level, NOT nested inside search-btn
  const tzSelect = document.getElementById('timezone-select');
  if (tzSelect) {
    tzSelect.addEventListener('change', (e) => saveTimezone(e.target.value));
  }

  // Pause / Resume (header controls + overview tab)
  document.getElementById('pause-btn').addEventListener('click', pauseMonitoring);
  document.getElementById('resume-btn').addEventListener('click', resumeMonitoring);
  const pause2 = document.getElementById('pause-btn2');
  const resume2 = document.getElementById('resume-btn2');
  if (pause2) pause2.addEventListener('click', pauseMonitoring);
  if (resume2) resume2.addEventListener('click', resumeMonitoring);

  // Tabs
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.addEventListener('click', (e) => switchTab(e.currentTarget.dataset.tab));
  });
  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => switchSubTab(e.currentTarget.dataset.subtab));
  });

  // Identity
  document.getElementById('update-device-alias-btn').addEventListener('click', () => updateIdentityAlias('device'));
  document.getElementById('update-user-alias-btn').addEventListener('click', () => updateIdentityAlias('user'));

  // Credentials modal
  document.getElementById('modal-cancel-btn').addEventListener('click', closeCredentialsModal);
  document.getElementById('modal-submit-btn').addEventListener('click', handleUpdateCredentials);
  document.getElementById('credentials-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeCredentialsModal();
  });

  // Server config modal
  const scModal = document.getElementById('server-config-modal');
  if (scModal) {
    document.getElementById('sc-cancel-btn').addEventListener('click', closeServerConfigModal);
    document.getElementById('sc-save-btn').addEventListener('click', handleSaveServerConfig);
    scModal.addEventListener('click', (e) => { if (e.target === scModal) closeServerConfigModal(); });
  }

  // Recording toggle
  document.getElementById('recording-toggle').addEventListener('change', handleRecordingToggle);
}

// ─── LOGIN / LOGOUT ──────────────────────────────────────────
async function handleLoginClick() {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  const errorDiv = document.getElementById('login-error');
  const loginBtn = document.getElementById('login-btn');

  errorDiv.textContent = '';
  loginBtn.disabled = true;
  loginBtn.textContent = 'Signing in…';

  try {
    const result = await window.electronAPI.login({ username, password });
    if (result.success) {
      isAuthenticated = true;
      showDashboard();
      initializeCharts();
      await loadDashboardData();
    } else {
      errorDiv.textContent = result.error || 'Invalid credentials';
    }
  } catch (error) {
    errorDiv.textContent = 'Login failed. Check if the backend service is running.';
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = 'Login';
  }
}

async function handleLogout() {
  try {
    clearTokenCountdown();
    await window.electronAPI.logout();
    isAuthenticated = false;
    showLogin();
    document.getElementById('username').value = '';
    document.getElementById('password').value = '';
    document.getElementById('login-error').textContent = '';
  } catch (error) {
    console.error('Logout failed:', error);
  }
}

// ─── CHANGE CREDENTIALS MODAL ────────────────────────────────
function openCredentialsModal() {
  document.getElementById('modal-new-username').value = '';
  document.getElementById('modal-new-password').value = '';
  document.getElementById('modal-confirm-password').value = '';
  document.getElementById('modal-sq1').value = '';
  document.getElementById('modal-sa1').value = '';
  document.getElementById('modal-sq2').value = '';
  document.getElementById('modal-sa2').value = '';
  document.getElementById('modal-error').style.display = 'none';
  document.getElementById('modal-success').style.display = 'none';
  document.getElementById('modal-submit-btn').disabled = false;
  document.getElementById('credentials-modal').classList.add('open');
}

function closeCredentialsModal() {
  document.getElementById('credentials-modal').classList.remove('open');
}

async function handleUpdateCredentials() {
  const newUsername = document.getElementById('modal-new-username').value.trim();
  const newPassword = document.getElementById('modal-new-password').value;
  const confirmPass = document.getElementById('modal-confirm-password').value;
  const sq1 = document.getElementById('modal-sq1').value;
  const sa1 = document.getElementById('modal-sa1').value.trim();
  const sq2 = document.getElementById('modal-sq2').value;
  const sa2 = document.getElementById('modal-sa2').value.trim();

  const errorEl = document.getElementById('modal-error');
  const successEl = document.getElementById('modal-success');
  const submitBtn = document.getElementById('modal-submit-btn');

  errorEl.style.display = 'none';
  successEl.style.display = 'none';

  // Client-side validation
  if (!newUsername) return showModalError('Username is required.');
  if (!newPassword) return showModalError('Password is required.');
  if (newPassword !== confirmPass) return showModalError('Passwords do not match.');
  if (!sq1 || !sa1) return showModalError('Security Question 1 and its answer are required.');
  if (!sq2 || !sa2) return showModalError('Security Question 2 and its answer are required.');
  if (sq1 === sq2) return showModalError('Please choose two different security questions.');

  submitBtn.disabled = true;
  submitBtn.textContent = 'Saving…';

  try {
    const result = await window.electronAPI.updateCredentials({
      new_username: newUsername,
      new_password: newPassword,
      security_q1: sq1, security_a1: sa1,
      security_q2: sq2, security_a2: sa2,
    });

    if (result.success) {
      successEl.textContent = 'Credentials updated! You will be logged out now.';
      successEl.style.display = 'block';
      setTimeout(async () => {
        closeCredentialsModal();
        await handleLogout();
      }, 2000);
    } else {
      showModalError(result.error || 'Failed to update credentials.');
    }
  } catch (err) {
    showModalError('Request failed. Check backend connection.');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = '💾 Save Changes';
  }
}

function showModalError(msg) {
  const el = document.getElementById('modal-error');
  el.textContent = msg;
  el.style.display = 'block';
}

// ─── SERVER API CONFIG MODAL ─────────────────────────────────
function openServerConfigModal() {
  const modal = document.getElementById('server-config-modal');
  document.getElementById('server-config-error').style.display = 'none';
  document.getElementById('server-config-success').style.display = 'none';
  modal.classList.add('open');

  // Pre-populate all 6 URL fields + global settings from backend config
  window.electronAPI.getConfig().then(cfg => {
    document.getElementById('sc-api-key').value = cfg.api_key || '';
    document.getElementById('sc-sync-interval').value = cfg.sync_interval_seconds ?? 300;
    document.getElementById('sc-url-app').value = cfg.url_app_activity || '';
    document.getElementById('sc-url-browser').value = cfg.url_browser || '';
    document.getElementById('sc-url-clipboard').value = cfg.url_clipboard || '';
    document.getElementById('sc-url-keystrokes').value = cfg.url_keystrokes || '';
    document.getElementById('sc-url-screenshots').value = cfg.url_screenshots || '';
    document.getElementById('sc-url-videos').value = cfg.url_videos || '';
  }).catch(() => { /* backend not ready yet — fields stay blank */ });
}

function closeServerConfigModal() {
  document.getElementById('server-config-modal').classList.remove('open');
}

async function handleSaveServerConfig() {
  const errorEl = document.getElementById('server-config-error');
  const successEl = document.getElementById('server-config-success');
  const saveBtn = document.getElementById('sc-save-btn');

  errorEl.style.display = 'none';
  successEl.style.display = 'none';

  // Collect all 6 URLs — validate any that are non-empty
  const urlFields = [
    { id: 'sc-url-app', key: 'url_app_activity', label: 'App Activity' },
    { id: 'sc-url-browser', key: 'url_browser', label: 'Browser Activity' },
    { id: 'sc-url-clipboard', key: 'url_clipboard', label: 'Clipboard Events' },
    { id: 'sc-url-keystrokes', key: 'url_keystrokes', label: 'Keystrokes' },
    { id: 'sc-url-screenshots', key: 'url_screenshots', label: 'Screenshots' },
    { id: 'sc-url-videos', key: 'url_videos', label: 'Screen Recordings' },
  ];

  const payload = {
    api_key: document.getElementById('sc-api-key').value.trim(),
    sync_interval_seconds: parseInt(document.getElementById('sc-sync-interval').value, 10) || 300,
  };

  for (const f of urlFields) {
    const val = document.getElementById(f.id).value.trim();
    if (val) {
      try { new URL(val); }
      catch {
        errorEl.textContent = `${f.label}: invalid URL — must start with https://`;
        errorEl.style.display = 'block';
        return;
      }
    }
    payload[f.key] = val;  // empty string = disabled for this type
  }

  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';

  try {
    const result = await window.electronAPI.setConfig(payload);
    if (result && result.success) {
      successEl.textContent = 'All API endpoints saved. Next sync will use the new configuration.';
      successEl.style.display = 'block';
      setTimeout(closeServerConfigModal, 2200);
    } else {
      errorEl.textContent = (result && result.error) || 'Failed to save configuration.';
      errorEl.style.display = 'block';
    }
  } catch (err) {
    errorEl.textContent = 'Request failed. Is the backend service running?';
    errorEl.style.display = 'block';
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = '💾 Save All';
  }
}


// ─── TAB SWITCHING ───────────────────────────────────────────
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelector(`[data-tab="${tab}"]`)?.classList.add('active');
  document.getElementById(`${tab}-tab`)?.classList.add('active');
  loadDashboardData();
}

function switchSubTab(subtab) {
  currentSubTab = subtab;
  document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.sub-tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelector(`[data-subtab="${subtab}"]`)?.classList.add('active');
  document.getElementById(`${subtab}-subtab`)?.classList.add('active');
  loadMonitorData();
}

// ─── DATA LOADING ────────────────────────────────────────────
async function loadDashboardData() {
  if (!isAuthenticated) return;
  try {
    await loadIdentity();
    if (currentTab === 'overview') {
      await Promise.all([loadStatistics(), loadChartsData()]);
    } else if (currentTab === 'monitor-data') {
      await loadMonitorData();
    } else if (currentTab === 'screenshots') {
      await loadScreenshots();
    }
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
  }
}

async function loadStatistics() {
  try {
    const stats = await window.electronAPI.getStatistics({ date: currentDate });
    document.getElementById('stat-screenshots').textContent = stats.total_screenshots ?? 0;
    document.getElementById('stat-hours').textContent = (stats.active_hours_today ?? 0).toFixed(1);
    document.getElementById('stat-apps').textContent = stats.apps_tracked ?? 0;
    document.getElementById('stat-clipboard').textContent = stats.clipboard_events ?? 0;
  } catch (err) {
    console.error('Failed to load statistics:', err);
  }
}

async function loadMonitoringStatus() {
  try {
    const status = await window.electronAPI.getMonitoringStatus();
    const badge = document.getElementById('status-badge');
    const ind = document.getElementById('status-indicator');
    const txt = document.getElementById('status-text');
    const pauseBtn = document.getElementById('pause-btn');
    const resumeBtn = document.getElementById('resume-btn');

    if (status.is_monitoring) {
      ind?.classList.replace('paused', 'active');
      if (txt) txt.textContent = 'Active';
      if (badge) badge.style.color = '#1a8a52';
      if (pauseBtn) pauseBtn.style.display = '';
      if (resumeBtn) resumeBtn.style.display = 'none';
    } else {
      ind?.classList.replace('active', 'paused');
      if (txt) txt.textContent = 'Paused';
      if (badge) badge.style.color = '#b8860b';
      if (pauseBtn) pauseBtn.style.display = 'none';
      if (resumeBtn) resumeBtn.style.display = '';
    }
  } catch (err) {
    console.error('Failed to load monitoring status:', err);
  }
}

// ─── TIMEZONE ─────────────────────────────────────────────────
async function loadTimezone() {
  try {
    const result = await window.electronAPI.getTimezone();
    currentTimezone = result.timezone || 'UTC';
    const sel = document.getElementById('timezone-select');
    if (sel) sel.value = currentTimezone;
    updateTzBadge();
  } catch (e) {
    // Non-fatal — keep UTC default
    console.warn('Could not load timezone config:', e);
  }
}

async function saveTimezone(tz) {
  try {
    currentTimezone = tz;
    updateTzBadge();
    await window.electronAPI.setTimezone(tz);
    // Re-render only the charts — no need to reload all data or re-fetch timezone
    if (currentTab === 'overview') {
      await loadChartsData();
    }
    // If on monitor-data tab, timestamps in the tables use formatWithTZ() which
    // reads currentTimezone directly — reload the active subtab only
    if (currentTab === 'monitor-data') {
      await loadMonitorData();
    }
  } catch (e) {
    console.error('Failed to save timezone:', e);
  }
}

function updateTzBadge() {
  const badge = document.getElementById('tz-badge');
  if (!badge) return;
  try {
    // Show current UTC offset for the selected zone
    const now = new Date();
    const offset = new Intl.DateTimeFormat('en', {
      timeZone: currentTimezone,
      timeZoneName: 'short',
    }).formatToParts(now).find(p => p.type === 'timeZoneName')?.value || '';
    badge.textContent = offset ? `(${offset})` : '';
  } catch {
    badge.textContent = '';
  }
}

async function loadIdentity() {
  try {
    const identity = await window.electronAPI.getIdentity();
    const mid = document.getElementById('identity-machine-id');
    const osu = document.getElementById('identity-os-user');
    if (mid) mid.textContent = `Raw: ${identity.machine_id}`;
    if (osu) osu.textContent = `Raw: ${identity.os_user}`;
    const di = document.getElementById('device-alias-input');
    const ui = document.getElementById('user-alias-input');
    if (di) di.value = identity.device_alias || '';
    if (ui) ui.value = identity.user_alias || '';
  } catch (err) {
    console.error('Failed to load identity:', err);
  }
}

async function updateIdentityAlias(which) {
  const inputId = which === 'device' ? 'device-alias-input' : 'user-alias-input';
  const btnId = which === 'device' ? 'update-device-alias-btn' : 'update-user-alias-btn';
  const input = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  if (!input || !btn) return;

  const val = input.value.trim();
  if (!val) { showIdentityFeedback('Alias cannot be empty.', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '…';

  try {
    const payload = which === 'device' ? { device_alias: val } : { user_alias: val };
    const result = await window.electronAPI.updateIdentity(payload);
    if (result.success) {
      showIdentityFeedback(`${which === 'device' ? 'Device' : 'User'} alias updated.`, 'success');
    } else {
      showIdentityFeedback(result.error || 'Update failed.', 'error');
    }
  } catch (err) {
    showIdentityFeedback('Request failed.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Update';
  }
}

function showIdentityFeedback(msg, type) {
  const el = document.getElementById('identity-feedback');
  if (!el) return;
  el.textContent = msg;
  el.className = `identity-feedback ${type}`;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}

// ─── MONITOR DATA ────────────────────────────────────────────
async function loadMonitorData() {
  if (currentSubTab === 'app-tracking') await loadAppLogs();
  else if (currentSubTab === 'browser') await loadBrowserLogs();
  else if (currentSubTab === 'clipboard') await loadClipboardLogs();
  else if (currentSubTab === 'keylogs') await loadKeyLogs();
  else if (currentSubTab === 'video') await loadVideoTab();
}

async function loadAppLogs() {
  const tbody = document.getElementById('app-logs-body');
  tbody.innerHTML = '<tr><td colspan="4" class="loading">Loading…</td></tr>';
  try {
    const logs = await window.electronAPI.getAppLogs({ limit: 100 });
    if (!logs?.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#888;">No app activity recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${formatWithTZ(log.timestamp)}</td>
        <td>${escapeHtml(log.app_name || '-')}</td>
        <td>${escapeHtml(log.window_title || '-')}</td>
        <td>${formatDuration(log.duration_seconds)}</td>
      </tr>`).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#dc3545;padding:20px;">Failed to load data.</td></tr>';
  }
}

async function loadBrowserLogs() {
  const tbody = document.getElementById('browser-logs-body');
  tbody.innerHTML = '<tr><td colspan="4" class="loading">Loading…</td></tr>';
  try {
    const logs = await window.electronAPI.getBrowserLogs({ limit: 100 });
    if (!logs?.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#888;">No browser activity recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${formatWithTZ(log.timestamp)}</td>
        <td>${escapeHtml(log.browser_name || '-')}</td>
        <td>${escapeHtml(log.page_title || '-')}</td>
        <td><a href="${escapeHtml(log.url || '')}" target="_blank" rel="noopener noreferrer"
               style="color:#667eea;text-decoration:none;word-break:break-all;">${escapeHtml(truncate(log.url || '', 80))}</a></td>
      </tr>`).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#dc3545;padding:20px;">Failed to load data.</td></tr>';
  }
}

async function loadClipboardLogs() {
  const tbody = document.getElementById('clipboard-logs-body');
  tbody.innerHTML = '<tr><td colspan="3" class="loading">Loading…</td></tr>';
  try {
    const logs = await window.electronAPI.getClipboardLogs({ limit: 100 });
    if (!logs?.length) {
      tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:20px;color:#888;">No clipboard activity recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${formatWithTZ(log.timestamp)}</td>
        <td>${escapeHtml(log.content_type || '-')}</td>
        <td>${escapeHtml(truncate(log.content_preview || '', 80))}</td>
      </tr>`).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:#dc3545;padding:20px;">Failed to load data.</td></tr>';
  }
}

async function loadKeyLogs() {
  const tbody = document.getElementById('key-logs-body');
  tbody.innerHTML = '<tr><td colspan="4" class="loading">Loading…</td></tr>';
  try {
    const logs = await window.electronAPI.getKeyLogs({ limit: 100 });
    if (!logs?.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#888;">No keystrokes recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${formatWithTZ(log.timestamp)}</td>
        <td>${escapeHtml(log.application || '-')}</td>
        <td>${escapeHtml(log.window_title || '-')}</td>
        <td>${escapeHtml(truncate(log.content || '', 120))}</td>
      </tr>`).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#dc3545;padding:20px;">Failed to load data.</td></tr>';
  }
}

// ─── SCREEN RECORDING TAB ────────────────────────────────────
async function loadVideoTab() {
  await loadVideoStatus();
  await loadVideoList();
}

async function loadVideoStatus() {
  try {
    const status = await window.electronAPI.getVideoStatus();
    const toggle = document.getElementById('recording-toggle');
    const badge = document.getElementById('rec-badge');
    const badgeTxt = document.getElementById('rec-badge-text');
    const dot = badge.querySelector('.rec-dot');

    toggle.checked = status.recording;

    if (status.recording) {
      badge.className = 'rec-badge on';
      badgeTxt.textContent = 'RECORDING';
      dot.classList.add('blink');
    } else {
      badge.className = 'rec-badge off';
      badgeTxt.textContent = 'OFF';
      dot.classList.remove('blink');
    }
  } catch (err) {
    console.error('Failed to load video status:', err);
  }
}

async function handleRecordingToggle() {
  const toggle = document.getElementById('recording-toggle');
  toggle.disabled = true;
  try {
    const result = await window.electronAPI.toggleVideoRecording();
    if (result.success) {
      await loadVideoStatus();
    } else {
      // Revert toggle on failure
      toggle.checked = !toggle.checked;
      console.error('Toggle failed:', result.error);
    }
  } catch (err) {
    toggle.checked = !toggle.checked;
    console.error('Toggle request failed:', err);
  } finally {
    toggle.disabled = false;
  }
}

async function loadVideoList() {
  const container = document.getElementById('video-list-container');
  container.innerHTML = '<div class="loading">Loading recordings…</div>';

  try {
    const videos = await window.electronAPI.getVideos({ limit: 50 });

    if (!videos || videos.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🎥</div>
          <p>No recordings yet.<br>Enable screen recording using the toggle above.</p>
        </div>`;
      return;
    }

    const rows = videos.map(v => {
      const ts = formatWithTZ(v.timestamp);
      const dur = formatDuration(v.duration_seconds);
      const fname = escapeHtml(v.file_path.split('\\').pop() || v.file_path.split('/').pop() || v.file_path);
      const safePath = escapeHtml(v.file_path);
      const status = v.is_synced ? '<span style="color:#28a745;font-weight:600;">✓ Synced</span>' : '<span style="color:#aaa;">Pending</span>';
      return `
        <tr>
          <td>${ts}</td>
          <td style="font-family:monospace;font-size:12px;">${fname}</td>
          <td>${dur}</td>
          <td>${status}</td>
          <td>
            <button class="btn-folder" data-filepath="${safePath}">
              📂 Open
            </button>
          </td>
        </tr>`;
    }).join('');

    container.innerHTML = `
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Recorded At</th>
              <th>Filename</th>
              <th>Duration</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;

    // Attach open-folder listeners via delegation — never use inline onclick for file paths
    // because HTML attribute parsing corrupts Windows backslashes.
    container.querySelectorAll('.btn-folder[data-filepath]').forEach(btn => {
      btn.addEventListener('click', () => openVideoFolder(btn.dataset.filepath));
    });

  } catch (err) {
    container.innerHTML = '<div style="color:#dc3545;padding:20px;text-align:center;">Failed to load recordings.</div>';
  }
}

async function openVideoFolder(filepath) {
  if (!filepath) return;
  try {
    await window.electronAPI.openFolder(filepath);
  } catch (err) {
    console.error('Failed to open folder:', err);
    alert('Could not open folder. Check the Electron console for details.');
  }
}

// ─── SCREENSHOTS ──────────────────────────────────────────────
async function loadScreenshots() {
  const container = document.getElementById('screenshots-container');
  container.innerHTML = '<div class="loading">Loading screenshots…</div>';
  try {
    const screenshots = await window.electronAPI.getScreenshots({ limit: 50 });
    if (!screenshots?.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">📸</div><p>No screenshots yet.</p></div>';
      return;
    }
    container.innerHTML = screenshots.map(s => `
      <div class="screenshot-item">
        <img src="file://${s.file_path}" alt="Screenshot" onerror="this.style.display='none'">
        <div class="info">
          <div class="timestamp">${formatWithTZ(s.timestamp)}</div>
          <div class="app-name">${escapeHtml(s.active_app || 'Unknown')}</div>
        </div>
      </div>`).join('');
  } catch (err) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">❌</div><p>Failed to load screenshots.</p></div>';
  }
}

// ─── MONITORING CONTROLS ──────────────────────────────────────
async function pauseMonitoring() {
  try {
    await window.electronAPI.pauseMonitoring();
    await loadMonitoringStatus();
  } catch (err) {
    console.error('Pause failed:', err);
  }
}

async function resumeMonitoring() {
  try {
    await window.electronAPI.resumeMonitoring();
    await loadMonitoringStatus();
  } catch (err) {
    console.error('Resume failed:', err);
  }
}

// ─── CHARTS ──────────────────────────────────────────────────
function initializeCharts() {
  const appCtx = document.getElementById('appUsageChart');
  const tlCtx = document.getElementById('timelineChart');
  if (!appCtx || !tlCtx) return;

  charts.appUsage = new Chart(appCtx.getContext('2d'), {
    type: 'doughnut',
    data: { labels: [], datasets: [{ data: [], backgroundColor: ['#667eea', '#764ba2', '#f0a500', '#28a745', '#dc3545', '#17a2b8', '#fd7e14'] }] },
    options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { font: { size: 11 } } } } },
  });

  charts.timeline = new Chart(tlCtx.getContext('2d'), {
    type: 'bar',
    data: { labels: [], datasets: [{ label: 'Active (min)', data: [], backgroundColor: 'rgba(102,126,234,0.7)', borderRadius: 4 }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
  });
}

async function loadChartsData() {
  try {
    const today = currentDate;

    // FIX 1: pass ONLY "YYYY-MM-DD" — db_manager appends the time parts internally
    const [activity, timeline] = await Promise.all([
      window.electronAPI.getActivityStats({ start: today, end: today }),
      window.electronAPI.getTimelineData({ date: today }),
    ]);

    // ── App Usage Doughnut ────────────────────────────────────────────────
    // Backend returns: [{app_name: "chrome.exe", total_seconds: 300}, ...]
    if (Array.isArray(activity) && activity.length > 0 && charts.appUsage) {
      const top7 = activity.slice(0, 7);
      charts.appUsage.data.labels = top7.map(e => {
        const name = (e.app_name || 'Unknown').replace(/\.exe$/i, '');
        return name.length > 20 ? name.substring(0, 18) + '…' : name;
      });
      charts.appUsage.data.datasets[0].data = top7.map(e =>
        Math.max(1, Math.round((e.total_seconds || 0) / 60))
      );
      charts.appUsage.update();
    } else if (charts.appUsage) {
      charts.appUsage.data.labels = [];
      charts.appUsage.data.datasets[0].data = [];
      charts.appUsage.update();
    }

    // ── Activity Timeline Bar ─────────────────────────────────────────────
    // FIX 2: Backend returns raw app_activity rows — bucket them into hourly slots
    // [{timestamp: "2026-02-19T08:30:00...", duration_seconds: 45, app_name: "..."}]
    if (Array.isArray(timeline) && timeline.length > 0 && charts.timeline) {
      // Build a full 24-hour map so hours with zero activity still show
      const hourMap = {};
      for (let h = 0; h < 24; h++) {
        hourMap[String(h).padStart(2, '0') + ':00'] = 0;
      }
      const tzForChart = currentTimezone || 'UTC';
      timeline.forEach(t => {
        if (!t.timestamp) return;
        // Extract the hour in the *selected* timezone, not browser local time
        const hourStr = new Intl.DateTimeFormat('en-US', {
          timeZone: tzForChart,
          hour: '2-digit',
          hour12: false,
        }).format(new Date(t.timestamp));
        // hourStr is like "08" or "23"
        const label = hourStr.padStart(2, '0') + ':00';
        hourMap[label] = (hourMap[label] || 0) + (t.duration_seconds || 0);
      });

      // Trim leading/trailing empty hours for a cleaner chart
      const allHours = Object.entries(hourMap);
      const firstNonZero = allHours.findIndex(([, v]) => v > 0);
      const lastNonZero = allHours.reduce((acc, [, v], i) => v > 0 ? i : acc, -1);

      // Show the active window ± 1 hour padding, or fall back to business hours
      const visible = firstNonZero >= 0
        ? allHours.slice(Math.max(0, firstNonZero - 1), lastNonZero + 2)
        : allHours.slice(7, 19);

      charts.timeline.data.labels = visible.map(([label]) => label);
      charts.timeline.data.datasets[0].data = visible.map(([, secs]) =>
        Math.round(secs / 60)   // convert seconds → minutes for readable axis
      );
      charts.timeline.update();
    } else if (charts.timeline) {
      charts.timeline.data.labels = [];
      charts.timeline.data.datasets[0].data = [];
      charts.timeline.update();
    }

  } catch (err) {
    console.error('Failed to load chart data:', err);
  }
}

//param {string} isoString  - UTC ISO-8601 timestamp from the database
//param {string} [tz]       
//returns {string}          

function formatWithTZ(isoString, tz) {
  if (!isoString) return '—';
  try {
    const zone = tz || currentTimezone || 'UTC';
    return new Date(isoString).toLocaleString('en-US', {
      timeZone: zone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch (e) {
    // Fallback: browser default if the TZ string is bad
    return new Date(isoString).toLocaleString();
  }
}
// ─── UTILITIES ────────────────────────────────────────────────
function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = String(str);
  return d.innerHTML;
}

function truncate(str, max) {
  return str.length > max ? str.substring(0, max) + '…' : str;
}

function formatDuration(seconds) {
  if (!seconds) return '0s';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

// ─── JWT COUNTDOWN TIMER ─────────────────────────────────────
let _tokenCountdownInterval = null;

function clearTokenCountdown() {
  if (_tokenCountdownInterval) {
    clearInterval(_tokenCountdownInterval);
    _tokenCountdownInterval = null;
  }
  const el = document.getElementById('token-timer');
  if (el) el.textContent = '';
}

async function startTokenCountdown() {
  clearTokenCountdown();
  const el = document.getElementById('token-timer');
  if (!el) return;   // element not in DOM — no-op

  const { remainingMs } = await window.electronAPI.getTokenExpiry();
  if (remainingMs <= 0) {
    await handleLogout();
    return;
  }

  let remaining = Math.floor(remainingMs / 1000);

  function tick() {
    if (remaining <= 0) {
      clearTokenCountdown();
      if (el) el.textContent = 'Session expired';
      handleLogout();
      return;
    }
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    if (el) {
      el.textContent = `Session: ${m}:${String(s).padStart(2, '0')}`;
      el.style.color = remaining <= 120 ? '#e74c3c' : '#aab';   // red in last 2 min
    }
    remaining--;
  }

  tick();  // paint immediately; don't wait 1s for first render
  _tokenCountdownInterval = setInterval(tick, 1000);
}
