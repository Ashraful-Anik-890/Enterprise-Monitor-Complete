// renderer.js — Enterprise Monitor
// v5.2.6 patches applied:
//   Patch 1A: Login button onclick removed from HTML; addEventListener is sole binding.
//   Patch 1B: IPC push-event listeners registered at module load (before DOMContentLoaded).
//   Patch 1C: checkAuthentication() checks routing state before calling showLogin().
//   Patch 1D: preload.ts removeAllListeners guards (see preload.ts).

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

// ─── PATCH 1B: IPC PUSH-EVENT LISTENERS — MODULE LOAD ────────
// Registered here, once, at parse time. Never re-registered inside
// checkAuthentication(), showDashboard(), or setupEventListeners().
// preload.ts removeAllListeners() guards ensure the Node-side count
// is always exactly 1 even if this script somehow executes twice.

window.electronAPI.onForceLogout(() => {
  console.warn('[renderer] Force-logout: backend token expired (401)');
  isAuthenticated = false;
  clearTokenCountdown();
  stopSyncStatusPoller();
  showLogin();
  document.getElementById('username').value = '';
  document.getElementById('password').value = '';
  const errEl = document.getElementById('login-error');
  if (errEl) {
    errEl.textContent = 'Session expired. Please log in again.';
    errEl.style.color = '#e74c3c';
  }
});

window.electronAPI.onQuitRequested(() => showQuitAuthDialog());
window.electronAPI.onFirstRunSetup(() => showFirstRunModal());

// ─── INIT ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('date-picker').value = currentDate;
  setupEventListeners();
  await checkAuthentication();
  loadAppVersion();
});

// ─── AUTH ────────────────────────────────────────────────────
// PATCH 1C (revised): Do not call showLogin() if login-container is
// already active. Checking routing state — not DOM focus — means
// partially-filled credentials survive a background auth re-check
// regardless of whether the user has clicked away from the input.
async function checkAuthentication() {
  try {
    const result = await window.electronAPI.checkAuth();
    isAuthenticated = result.authenticated;
    if (isAuthenticated) {
      showDashboard();
      initializeCharts();
      await loadDashboardData();
      startSyncStatusPoller();
    } else {
      const loginContainer = document.getElementById('login-container');
      const isLoginVisible = loginContainer && loginContainer.classList.contains('active');
      if (!isLoginVisible) {
        showLogin();
      }
    }
  } catch (error) {
    console.error('Auth check failed:', error);
    const loginContainer = document.getElementById('login-container');
    const isLoginVisible = loginContainer && loginContainer.classList.contains('active');
    if (!isLoginVisible) {
      showLogin();
    }
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
// PATCH 1A: login-btn has no onclick attribute in HTML.
// PATCH 1B: IPC push-event listeners removed from this function entirely.
//           Only DOM event bindings live here.
function setupEventListeners() {
  // Login — sole binding (HTML onclick attribute removed in Patch 1A)
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

  // Timezone
  const tzSelect = document.getElementById('timezone-select');
  if (tzSelect) {
    tzSelect.addEventListener('change', (e) => saveTimezone(e.target.value));
  }

  // Pause / Resume (header controls only)
  document.getElementById('pause-btn').addEventListener('click', pauseMonitoring);
  document.getElementById('resume-btn').addEventListener('click', resumeMonitoring);

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
  document.getElementById('update-location-btn')?.addEventListener('click', () => updateIdentityAlias('location'));
  document.getElementById('confirm-credential-btn')?.addEventListener('click', handleConfirmCredential);

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

  // Recording toggles
  document.getElementById('recording-toggle').addEventListener('change', handleRecordingToggle);
  document.getElementById('screenshot-toggle').addEventListener('change', handleScreenshotToggle);

  // Quit / forgot-password / first-run / post-api-cred
  document.getElementById('forgot-password-link')
    ?.addEventListener('click', e => { e.preventDefault(); openForgotPassword(); });
  document.getElementById('quit-cancel-btn')
    ?.addEventListener('click', hideQuitAuthDialog);
  document.getElementById('quit-confirm-btn')
    ?.addEventListener('click', confirmQuit);
  document.getElementById('quit-password')
    ?.addEventListener('keydown', e => { if (e.key === 'Enter') confirmQuit(); });
  document.getElementById('first-run-skip-btn')
    ?.addEventListener('click', dismissFirstRun);
  document.getElementById('first-run-configure-btn')
    ?.addEventListener('click', firstRunConfigure);
  document.getElementById('fp-back-btn')
    ?.addEventListener('click', closeForgotPassword);
  document.getElementById('fp-next-btn')
    ?.addEventListener('click', fpStep1);
  document.getElementById('fp-back2-btn')
    ?.addEventListener('click', fpGoBack);
  document.getElementById('fp-reset-btn')
    ?.addEventListener('click', fpResetPassword);
  document.getElementById('post-api-cred-no-btn')
    ?.addEventListener('click', dismissPostApiCred);
  document.getElementById('post-api-cred-yes-btn')
    ?.addEventListener('click', goToUpdateCredentials);

  // Auto-Update IPC listeners
  setupUpdateListeners();

  // Password Visibility Toggle
  initPasswordToggles();
}

function initPasswordToggles() {
  const toggles = [
    { inputId: 'password', toggleId: 'password-toggle' },
    { inputId: 'modal-new-password', toggleId: 'modal-new-password-toggle' },
    { inputId: 'modal-confirm-password', toggleId: 'modal-confirm-password-toggle' },
    { inputId: 'sc-api-key', toggleId: 'sc-api-key-toggle' },
    { inputId: 'quit-password', toggleId: 'quit-password-toggle' },
    { inputId: 'fp-new-password', toggleId: 'fp-new-password-toggle' },
    { inputId: 'fp-confirm-password', toggleId: 'fp-confirm-password-toggle' }
  ];

  toggles.forEach(({ inputId, toggleId }) => {
    const toggleBtn = document.getElementById(toggleId);
    const input = document.getElementById(inputId);
    if (toggleBtn && input) {
      toggleBtn.addEventListener('click', () => {
        if (input.type === 'password') {
          input.type = 'text';
          toggleBtn.textContent = '🔒'; // Icon to hide
        } else {
          input.type = 'password';
          toggleBtn.textContent = '👁️'; // Icon to show
        }
      });
    }
  });
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
      startSyncStatusPoller();
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

  window.electronAPI.getConfig().then(cfg => {
    const dynamicEnabled = cfg.dynamic_api_enabled !== false;

    const lockedBanner = document.getElementById('sc-locked-banner');
    const dynamicBody = document.getElementById('sc-dynamic-body');
    const saveBtn = document.getElementById('sc-save-btn');

    if (!dynamicEnabled) {
      document.getElementById('sc-locked-company').textContent =
        cfg.company_name || 'your IT Administrator';
      lockedBanner.style.display = 'block';
      dynamicBody.style.display = 'none';
      saveBtn.style.display = 'none';
      return;
    }

    lockedBanner.style.display = 'none';
    dynamicBody.style.display = 'block';
    saveBtn.style.display = '';

    document.getElementById('sc-api-key').value = cfg.api_key || '';
    document.getElementById('sc-sync-interval').value = cfg.sync_interval_seconds ?? 300;
    document.getElementById('sc-base-url').value = cfg.base_url || '';

    const urlFields = [
      { id: 'sc-url-app', val: cfg.url_app_activity, path: cfg.path_app_activity },
      { id: 'sc-url-browser', val: cfg.url_browser, path: cfg.path_browser },
      { id: 'sc-url-clipboard', val: cfg.url_clipboard, path: cfg.path_clipboard },
      { id: 'sc-url-keystrokes', val: cfg.url_keystrokes, path: cfg.path_keystrokes },
      { id: 'sc-url-screenshots', val: cfg.url_screenshots, path: cfg.path_screenshots },
      { id: 'sc-url-videos', val: cfg.url_videos, path: cfg.path_videos },
      { id: 'sc-url-monitoring-settings', val: cfg.url_monitoring_settings, path: cfg.path_monitoring_settings },
      { id: 'sc-url-screenshot-settings', val: cfg.url_screenshot_settings, path: cfg.path_screenshot_settings },
      { id: 'sc-url-video-settings', val: cfg.url_video_settings, path: cfg.path_video_settings },
    ];

    urlFields.forEach(({ id, val, path }) => {
      const el = document.getElementById(id);
      el.value = val || '';
      el.dataset.pathSuffix = path || '';
      if (path) el.placeholder = `https://your-server.com${path}`;
    });

  }).catch(() => { });
}

function closeServerConfigModal() {
  document.getElementById('server-config-modal').classList.remove('open');
}

function applyBaseUrl() {
  const baseUrlEl = document.getElementById('sc-base-url');
  const errorEl = document.getElementById('server-config-error');
  const baseUrlRaw = baseUrlEl.value.trim();

  errorEl.style.display = 'none';

  if (!baseUrlRaw) {
    errorEl.textContent = 'Base URL is empty. Enter a URL like https://api.company.com';
    errorEl.style.display = 'block';
    return;
  }

  try { new URL(baseUrlRaw); }
  catch {
    errorEl.textContent = 'Base URL is invalid — must start with https://';
    errorEl.style.display = 'block';
    return;
  }

  const base = baseUrlRaw.replace(/\/$/, '');

  const urlInputIds = [
    'sc-url-app', 'sc-url-browser', 'sc-url-clipboard', 'sc-url-keystrokes',
    'sc-url-screenshots', 'sc-url-videos', 'sc-url-monitoring-settings',
    'sc-url-screenshot-settings', 'sc-url-video-settings',
  ];

  urlInputIds.forEach(id => {
    const el = document.getElementById(id);
    const path = el.dataset.pathSuffix || '';
    if (path) el.value = base + path;
  });
}

async function handleSaveServerConfig() {
  const errorEl = document.getElementById('server-config-error');
  const successEl = document.getElementById('server-config-success');
  const saveBtn = document.getElementById('sc-save-btn');

  errorEl.style.display = 'none';
  successEl.style.display = 'none';

  const urlFields = [
    { id: 'sc-url-app', key: 'url_app_activity', label: 'App Activity' },
    { id: 'sc-url-browser', key: 'url_browser', label: 'Browser Activity' },
    { id: 'sc-url-clipboard', key: 'url_clipboard', label: 'Clipboard Events' },
    { id: 'sc-url-keystrokes', key: 'url_keystrokes', label: 'Keystrokes' },
    { id: 'sc-url-screenshots', key: 'url_screenshots', label: 'Screenshots' },
    { id: 'sc-url-videos', key: 'url_videos', label: 'Screen Recordings' },
    { id: 'sc-url-monitoring-settings', key: 'url_monitoring_settings', label: 'Monitoring Settings' },
    { id: 'sc-url-screenshot-settings', key: 'url_screenshot_settings', label: 'Screenshot Settings' },
    { id: 'sc-url-video-settings', key: 'url_video_settings', label: 'Video Settings' },
  ];

  const payload = {
    api_key: document.getElementById('sc-api-key').value.trim(),
    sync_interval_seconds: parseInt(document.getElementById('sc-sync-interval').value, 10) || 300,
    base_url: document.getElementById('sc-base-url').value.trim(),
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
    payload[f.key] = val;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';

  try {
    const result = await window.electronAPI.setConfig(payload);
    if (result && result.success) {
      successEl.textContent = 'All API endpoints saved. Next sync will use the new configuration.';
      successEl.style.display = 'block';
      setTimeout(() => {
        closeServerConfigModal();
        if (window._firstRunApiConfiguring) {
          window._firstRunApiConfiguring = false;
          setTimeout(() => showPostApiCredentialPrompt(), 400);
        }
      }, 2200);
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
      await Promise.all([loadStatistics(), loadChartsData(), loadMonitoringStatus()]);
    } else if (currentTab === 'monitor-data') {
      await Promise.all([loadMonitorData(), loadMonitoringStatus()]);
    } else if (currentTab === 'screenshots') {
      await Promise.all([loadScreenshotStatus(), loadScreenshots(), loadMonitoringStatus()]);
    } else if (currentTab === 'screen-recording') {
      await Promise.all([loadVideoTab(), loadMonitoringStatus()]);
    }
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
  }
}

async function loadStatistics() {
  try {
    const stats = await window.electronAPI.getStatistics({ date: currentDate });
    document.getElementById('stat-screenshots').textContent = stats.total_screenshots ?? 0;
    document.getElementById('stat-hours').textContent       = (stats.active_hours_today ?? 0).toFixed(1);
    document.getElementById('stat-apps').textContent        = stats.apps_tracked ?? 0;
    document.getElementById('stat-clipboard').textContent   = stats.clipboard_events ?? 0;

    // Show archived badge if stats come from daily_summary fallback
    ['stat-screenshots','stat-hours','stat-apps','stat-clipboard'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const badge = el.parentElement.querySelector('.archived-badge');
      if (stats.archived) {
        if (!badge) {
          const b = document.createElement('span');
          b.className = 'archived-badge';
          b.textContent = 'Archived';
          el.parentElement.appendChild(b);
        }
      } else {
        if (badge) badge.remove();
      }
    });
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
    console.warn('Could not load timezone config:', e);
  }
}

async function saveTimezone(tz) {
  try {
    currentTimezone = tz;
    updateTzBadge();
    await window.electronAPI.setTimezone(tz);
    if (currentTab === 'overview') {
      await loadChartsData();
    }
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

    const deviceLabel = document.querySelector('#identity-section .identity-card:first-child .identity-label');
    const userLabel   = document.querySelector('#identity-section .identity-card:nth-child(2) .identity-label');
    if (deviceLabel) deviceLabel.textContent = identity.device_alias || identity.machine_id;
    if (userLabel)   userLabel.textContent   = identity.user_alias   || identity.os_user;

    const mid     = document.getElementById('identity-machine-id');
    const osu     = document.getElementById('identity-os-user');
    const mac     = document.getElementById('display-mac-address');
    const logUser = document.getElementById('identity-login-user');
    const locDisp = document.getElementById('identity-location-display');

    if (mid)     mid.textContent     = `Raw: ${identity.machine_id}`;
    if (osu)     osu.textContent     = `Raw: ${identity.os_user}`;
    if (mac)     mac.textContent     = identity.mac_address || 'Unavailable';
    if (logUser) logUser.textContent = identity.login_username || 'Unknown';
    if (locDisp) locDisp.textContent = identity.location || 'Not set';

    const di  = document.getElementById('device-alias-input');
    const ui  = document.getElementById('user-alias-input');
    const loc = document.getElementById('location-input');
    if (di)  { di.value  = identity.device_alias || ''; di.placeholder  = identity.machine_id; }
    if (ui)  { ui.value  = identity.user_alias   || ''; ui.placeholder  = identity.os_user; }
    if (loc) { loc.value = identity.location     || ''; }

    // Update confirm-credential button state
    _updateConfirmBtn(identity);
  } catch (err) {
    console.error('Failed to load identity:', err);
  }
}

function _updateConfirmBtn(identity) {
  const btn = document.getElementById('confirm-credential-btn');
  if (!btn) return;

  if (identity.credential_drifted) {
    btn.className = 'state-drifted';
    btn.textContent = '⚠️ Re-Confirm Credential';
    btn.disabled = false;
  } else if (!identity.credential_confirmed) {
    btn.className = 'state-unconfirmed';
    btn.textContent = '🔒 Confirm Credential';
    btn.disabled = false;
  } else {
    btn.className = 'state-confirmed';
    btn.textContent = '✅ Credential Confirmed';
    btn.disabled = true;
  }
}

async function handleConfirmCredential() {
  const btn = document.getElementById('confirm-credential-btn');
  const deviceAlias = (document.getElementById('device-alias-input')?.value || '').trim();
  const userAlias   = (document.getElementById('user-alias-input')?.value   || '').trim();
  const location    = (document.getElementById('location-input')?.value     || '').trim();

  if (!deviceAlias || !userAlias) {
    showIdentityFeedback('Enter Device Name and User Alias before confirming.', 'error');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Confirming…';

  try {
    const result = await window.electronAPI.confirmCredential({
      device_alias: deviceAlias,
      user_alias:   userAlias,
      location:     location,
    });
    if (result.success) {
      btn.className   = 'state-confirmed';
      btn.textContent = '✅ Credential Confirmed';
      btn.disabled    = true;
      showIdentityFeedback('Credentials confirmed. Syncing is now active.', 'success');
      // Refresh identity display
      await loadIdentity();
    } else {
      btn.disabled = false;
      _updateConfirmBtn({ credential_confirmed: false });
      showIdentityFeedback(result.error || 'Confirmation failed.', 'error');
    }
  } catch (err) {
    btn.disabled = false;
    _updateConfirmBtn({ credential_confirmed: false });
    showIdentityFeedback('Request failed.', 'error');
  }
}

async function updateIdentityAlias(which) {
  const inputIdMap = {
    device:   'device-alias-input',
    user:     'user-alias-input',
    location: 'location-input',
  };
  const btnIdMap = {
    device:   'update-device-alias-btn',
    user:     'update-user-alias-btn',
    location: 'update-location-btn',
  };
  const labelMap = {
    device:   'Device',
    user:     'User',
    location: 'Location',
  };

  const input = document.getElementById(inputIdMap[which]);
  const btn   = document.getElementById(btnIdMap[which]);
  if (!input || !btn) return;

  const val = input.value.trim();
  if (!val) { showIdentityFeedback('Value cannot be empty.', 'error'); return; }

  btn.disabled    = true;
  btn.textContent = '…';

  try {
    const payload = {};
    if (which === 'device')   payload.device_alias = val;
    if (which === 'user')     payload.user_alias   = val;
    if (which === 'location') payload.location     = val;

    const result = await window.electronAPI.updateIdentity(payload);
    if (result.success) {
      showIdentityFeedback(`${labelMap[which]} alias updated.`, 'success');
      // If alias changed after confirmation, button may need to turn yellow again
      await loadIdentity();
    } else {
      showIdentityFeedback(result.error || 'Update failed.', 'error');
    }
  } catch (err) {
    showIdentityFeedback('Request failed.', 'error');
  } finally {
    btn.disabled    = false;
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
}

// ─── APP VERSION ─────────────────────────────────────────────
async function loadAppVersion() {
  try {
    const version = await window.electronAPI.getAppVersion();
    const label = `Enterprise Monitor v${version}`;
    const footerEl = document.getElementById('footer-version');
    const loginEl = document.getElementById('login-version');
    if (footerEl) footerEl.textContent = label;
    if (loginEl) loginEl.textContent = label;
  } catch (e) {
    console.warn('Could not load app version:', e);
  }
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
async function loadScreenshotStatus() {
  try {
    const status = await window.electronAPI.getScreenshotStatus();
    const toggle = document.getElementById('screenshot-toggle');
    const badge = document.getElementById('ss-badge');
    const badgeTxt = document.getElementById('ss-badge-text');
    const dot = badge.querySelector('.rec-dot');

    toggle.checked = status.recording;

    if (status.recording) {
      badge.className = 'rec-badge on';
      badgeTxt.textContent = 'ON';
      dot.classList.add('blink');
    } else {
      badge.className = 'rec-badge off';
      badgeTxt.textContent = 'OFF';
      dot.classList.remove('blink');
    }
  } catch (err) {
    console.error('Failed to load screenshot status:', err);
  }
}

async function handleScreenshotToggle() {
  const toggle = document.getElementById('screenshot-toggle');
  toggle.disabled = true;
  try {
    const result = await window.electronAPI.toggleScreenshotCapturing();
    if (result.success) {
      await loadScreenshotStatus();
    } else {
      toggle.checked = !toggle.checked;
      console.error('Screenshot toggle failed:', result.error);
    }
  } catch (err) {
    toggle.checked = !toggle.checked;
    console.error('Screenshot toggle request failed:', err);
  } finally {
    toggle.disabled = false;
  }
}

async function loadScreenshots() {
  const container = document.getElementById('screenshots-container');
  container.innerHTML = '<div class="loading">Loading screenshots…</div>';
  try {
    const screenshots = await window.electronAPI.getScreenshots({ limit: 50 });
    if (!screenshots?.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">📸</div><p>No screenshots yet.</p></div>';
      return;
    }
    container.innerHTML = screenshots.map(s => {
      const syncedBadge = s.synced
        ? '<span class="ss-sync-badge synced" title="Synced to server">✓</span>'
        : '<span class="ss-sync-badge pending" title="Pending sync">⏳</span>';
      return `
        <div class="screenshot-item">
          <div class="screenshot-img-wrap">
            <img src="file://${s.file_path}" alt="Screenshot" onerror="this.style.display='none'">
            ${syncedBadge}
          </div>
          <div class="info">
            <div class="timestamp">${formatWithTZ(s.timestamp)}</div>
            <div class="app-name">${escapeHtml(s.active_app || 'Unknown')}</div>
          </div>
        </div>`;
    }).join('');
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
  if (typeof Chart === 'undefined') {
    // Chart.js not ready — retry when the load event fires
    document.addEventListener('chartjs-ready', function onReady() {
      document.removeEventListener('chartjs-ready', onReady);
      initializeCharts();
    });
    // Also try a simple poll as ultimate fallback
    setTimeout(() => {
      if (typeof Chart !== 'undefined' && !charts.appUsage) initializeCharts();
    }, 3000);
    return;
  }

  const appCtx = document.getElementById('appUsageChart');
  const tlCtx  = document.getElementById('timelineChart');
  if (!appCtx || !tlCtx) return;
  if (charts.appUsage) return; // already initialized

  charts.appUsage = new Chart(appCtx.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: [],
      datasets: [{
        data: [],
        backgroundColor: ['#667eea','#f0a500','#28a745','#e94560','#17a2b8','#764ba2','#fd7e14'],
        borderWidth: 2,
        borderColor: 'rgba(255,255,255,0.8)'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { font: { size: 11 }, boxWidth: 12, padding: 10 } } },
      cutout: '68%'
    },
  });

  charts.timeline = new Chart(tlCtx.getContext('2d'), {
    type: 'bar',
    data: {
      labels: [],
      datasets: [{
        label: 'Active (min)',
        data: [],
        backgroundColor: 'rgba(102,126,234,0.75)',
        borderColor: '#667eea',
        borderWidth: 1,
        borderRadius: 5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 } } },
        y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { font: { size: 11 } } }
      }
    },
  });
}

async function loadChartsData() {
  try {
    const today = currentDate;

    const [activity, timeline] = await Promise.all([
      window.electronAPI.getActivityStats({ start: today, end: today }),
      window.electronAPI.getTimelineData({ date: today }),
    ]);

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

    if (Array.isArray(timeline) && timeline.length > 0 && charts.timeline) {
      const hourMap = {};
      for (let h = 0; h < 24; h++) {
        hourMap[String(h).padStart(2, '0') + ':00'] = 0;
      }
      const tzForChart = currentTimezone || 'UTC';
      timeline.forEach(t => {
        if (!t.timestamp) return;
        let tsStr = t.timestamp;
        if (!tsStr.endsWith('Z') && !tsStr.includes('+') && !tsStr.match(/-\d\d:\d\d$/)) {
          tsStr = tsStr.replace(' ', 'T');
          if (!tsStr.endsWith('Z')) tsStr += 'Z';
        }

        let hourStr = new Intl.DateTimeFormat('en-US', {
          timeZone: tzForChart,
          hour: '2-digit',
          hour12: false,
        }).format(new Date(tsStr));

        if (hourStr === '24') hourStr = '00';
        const label = hourStr.padStart(2, '0') + ':00';
        hourMap[label] = (hourMap[label] || 0) + (t.duration_seconds || 0);
      });

      const allHours = Object.entries(hourMap);
      const firstNonZero = allHours.findIndex(([, v]) => v > 0);
      const lastNonZero = allHours.reduce((acc, [, v], i) => v > 0 ? i : acc, -1);

      const visible = firstNonZero >= 0
        ? allHours.slice(Math.max(0, firstNonZero - 1), lastNonZero + 2)
        : allHours.slice(7, 19);

      charts.timeline.data.labels = visible.map(([label]) => label);
      charts.timeline.data.datasets[0].data = visible.map(([, secs]) =>
        Math.round(secs / 60)
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

function formatWithTZ(isoString, tz) {
  if (!isoString) return '—';
  try {
    let tsStr = isoString;
    if (typeof tsStr === 'string' && !tsStr.endsWith('Z') && !tsStr.includes('+') && !tsStr.match(/-\d\d:\d\d$/)) {
      tsStr = tsStr.replace(' ', 'T');
      if (!tsStr.endsWith('Z')) tsStr += 'Z';
    }

    const zone = tz || currentTimezone || 'UTC';
    return new Date(tsStr).toLocaleString('en-US', {
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
  if (!el) return;

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
      el.style.color = remaining <= 120 ? '#e74c3c' : '#aab';
    }
    remaining--;
  }

  tick();
  _tokenCountdownInterval = setInterval(tick, 1000);
}

// ─── STATE ───────────────────────────────────────────────────────────────────
window._firstRunApiConfiguring = false;
let _syncPollerInterval = null;

// ─── SYNC STATUS BANNER ──────────────────────────────────────────────────────
function startSyncStatusPoller() {
  updateSyncStatus();
  loadMonitoringStatus();
  _syncPollerInterval = setInterval(() => {
    updateSyncStatus();
    loadMonitoringStatus();
  }, 60_000);
}

function stopSyncStatusPoller() {
  if (_syncPollerInterval) { clearInterval(_syncPollerInterval); _syncPollerInterval = null; }
}

async function updateSyncStatus() {
  try {
    const status = await window.electronAPI.getSyncStatus();
    const banner = document.getElementById('sync-status-banner');
    if (!banner) return;

    if (status.last_error) {
      banner.textContent = `⚠ ${status.last_error}`;
      banner.style.background = '#fff3cd';
      banner.style.color = '#856404';
      banner.style.display = 'block';
    } else if (status.last_sync && status.server_reachable !== false) {
      const t = new Date(status.last_sync).toLocaleTimeString();
      banner.textContent = `✓ Last synced: ${t}`;
      banner.style.background = '#d1edff';
      banner.style.color = '#0c5460';
      banner.style.display = 'block';
    } else if (status.last_sync && status.server_reachable === false) {
      banner.textContent = `⚠ Server unreachable — monitoring active, data queued`;
      banner.style.background = '#fff3cd';
      banner.style.color = '#856404';
      banner.style.display = 'block';
    } else {
      banner.style.display = 'none';
    }
  } catch {
    // backend offline
  }
}

// ─── QUIT AUTHENTICATION DIALOG ──────────────────────────────────────────────
function showQuitAuthDialog() {
  const overlay = document.getElementById('quit-auth-overlay');
  if (!overlay) return;
  document.getElementById('quit-username').value = '';
  document.getElementById('quit-password').value = '';
  document.getElementById('quit-auth-error').style.display = 'none';
  overlay.style.display = 'flex';
  setTimeout(() => document.getElementById('quit-username')?.focus(), 50);
}

function hideQuitAuthDialog() {
  const overlay = document.getElementById('quit-auth-overlay');
  if (overlay) overlay.style.display = 'none';
}

async function confirmQuit() {
  const username = document.getElementById('quit-username').value.trim();
  const password = document.getElementById('quit-password').value;
  const errorEl = document.getElementById('quit-auth-error');
  const btn = document.getElementById('quit-confirm-btn');

  errorEl.style.display = 'none';

  if (!username || !password) {
    errorEl.textContent = 'Both fields are required.';
    errorEl.style.display = 'block';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Verifying…';

  try {
    const result = await window.electronAPI.verifyCredentials({ username, password });
    if (result.success) {
      await window.electronAPI.quitApp();
    } else {
      const isOffline = result.error && (
        result.error.includes('ECONNREFUSED') ||
        result.error.includes('Network Error') ||
        result.error.includes('timeout')
      );

      if (isOffline) {
        errorEl.innerHTML =
          '⚠ Backend is offline — monitoring is <strong>not running</strong>.<br>' +
          '<a href="#" id="quit-force-link" style="color:#e74c3c">Force quit anyway</a>';
        errorEl.style.display = 'block';
        document.getElementById('quit-force-link')?.addEventListener('click', async (e) => {
          e.preventDefault();
          await window.electronAPI.quitApp();
        });
      } else {
        errorEl.textContent = 'Incorrect credentials. Quit denied — monitoring continues.';
        errorEl.style.display = 'block';
      }
    }
  } catch {
    errorEl.textContent = 'Unexpected error. Try again.';
    errorEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = '⏹ Quit';
  }
}

// ─── FORGOT PASSWORD FLOW ────────────────────────────────────────────────────
let _fpUsername = '';

function openForgotPassword() {
  _fpUsername = '';
  document.getElementById('fp-username').value = '';
  document.getElementById('fp-step1-error').style.display = 'none';
  document.getElementById('fp-step1').style.display = 'block';
  document.getElementById('fp-step2').style.display = 'none';
  document.getElementById('fp-step2-error').style.display = 'none';
  document.getElementById('fp-step2-success').style.display = 'none';
  document.getElementById('forgot-password-modal').style.display = 'flex';
}

function closeForgotPassword() {
  document.getElementById('forgot-password-modal').style.display = 'none';
}

function fpGoBack() {
  document.getElementById('fp-step2').style.display = 'none';
  document.getElementById('fp-step1').style.display = 'block';
}

async function fpStep1() {
  const username = document.getElementById('fp-username').value.trim();
  const errorEl = document.getElementById('fp-step1-error');
  const btn = document.getElementById('fp-next-btn');

  errorEl.style.display = 'none';
  if (!username) { errorEl.textContent = 'Enter your username.'; errorEl.style.display = 'block'; return; }

  btn.disabled = true; btn.textContent = 'Looking up…';

  try {
    const result = await window.electronAPI.getSecurityQuestions(username);
    if (!result.success || !result.questions || result.questions.length < 2) {
      errorEl.textContent = result.error || 'No security questions on file for this username.';
      errorEl.style.display = 'block';
      return;
    }
    _fpUsername = username;
    document.getElementById('fp-q1-label').textContent = result.questions[0].question;
    document.getElementById('fp-q2-label').textContent = result.questions[1].question;
    document.getElementById('fp-a1').value = '';
    document.getElementById('fp-a2').value = '';
    document.getElementById('fp-new-password').value = '';
    document.getElementById('fp-confirm-password').value = '';
    document.getElementById('fp-step1').style.display = 'none';
    document.getElementById('fp-step2').style.display = 'block';
  } catch {
    errorEl.textContent = 'Backend unreachable.';
    errorEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Next →';
  }
}

async function fpResetPassword() {
  const answer1 = document.getElementById('fp-a1').value.trim();
  const answer2 = document.getElementById('fp-a2').value.trim();
  const newPass = document.getElementById('fp-new-password').value;
  const confirm = document.getElementById('fp-confirm-password').value;
  const errorEl = document.getElementById('fp-step2-error');
  const successEl = document.getElementById('fp-step2-success');
  const btn = document.getElementById('fp-reset-btn');

  errorEl.style.display = 'none'; successEl.style.display = 'none';

  if (!answer1 || !answer2) { errorEl.textContent = 'Both answers required.'; errorEl.style.display = 'block'; return; }
  if (!newPass) { errorEl.textContent = 'New password required.'; errorEl.style.display = 'block'; return; }
  if (newPass !== confirm) { errorEl.textContent = 'Passwords do not match.'; errorEl.style.display = 'block'; return; }

  btn.disabled = true; btn.textContent = 'Resetting…';

  try {
    const result = await window.electronAPI.resetPassword({
      username: _fpUsername, answer1, answer2, new_password: newPass,
    });
    if (result.success) {
      successEl.textContent = 'Password reset! Returning to login…';
      successEl.style.display = 'block';
      setTimeout(() => {
        closeForgotPassword();
        const uField = document.getElementById('username');
        if (uField) uField.value = _fpUsername;
        document.getElementById('password').value = '';
        document.getElementById('login-error').textContent = '';
      }, 1800);
    } else {
      errorEl.textContent = result.error || 'Check your answers and try again.';
      errorEl.style.display = 'block';
    }
  } catch {
    errorEl.textContent = 'Backend unreachable.';
    errorEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Reset Password';
  }
}

// ─── FIRST-RUN SETUP FLOW ────────────────────────────────────────────────────
function showFirstRunModal() {
  const dash = document.getElementById('dashboard-container');
  if (!dash || !dash.classList.contains('active')) return;
  document.getElementById('first-run-modal').style.display = 'flex';
}

function dismissFirstRun() {
  document.getElementById('first-run-modal').style.display = 'none';
  window.electronAPI.firstRunComplete();
  showInfoToast('Monitoring is active. You can configure APIs anytime via ⚙ Configure Server APIs.');
}

function firstRunConfigure() {
  document.getElementById('first-run-modal').style.display = 'none';
  window.electronAPI.firstRunComplete();
  window._firstRunApiConfiguring = true;
  if (typeof openServerConfigModal === 'function') openServerConfigModal();
}

function showPostApiCredentialPrompt() {
  document.getElementById('post-api-cred-modal').style.display = 'flex';
}

function dismissPostApiCred() {
  document.getElementById('post-api-cred-modal').style.display = 'none';
  showInfoToast('Setup complete! Monitoring is active on this device.');
}

function goToUpdateCredentials() {
  document.getElementById('post-api-cred-modal').style.display = 'none';
  if (typeof openCredentialsModal === 'function') openCredentialsModal();
}

// ─── UTILITY: Toast ──────────────────────────────────────────────────────────
function showInfoToast(message) {
  const existing = document.getElementById('info-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.id = 'info-toast';
  toast.textContent = message;
  Object.assign(toast.style, {
    position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%)',
    background: '#1a1a2e', color: '#fff', padding: '12px 20px', borderRadius: '8px',
    fontSize: '13px', zIndex: '99999', boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
    maxWidth: '420px', textAlign: 'center', lineHeight: '1.5',
  });
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

// ─── AUTO-UPDATE HANDLERS ─────────────────────────────────────────────────────
let _currentUpdateVersion = null;

function showUpdateDownloadingModal(version, releaseNotes) {
  _currentUpdateVersion = version;

  const text = document.getElementById('update-available-text');
  if (text) {
    text.textContent = `Version ${version} is downloading in the background. This may take a few minutes.`;
  }

  const bar = document.getElementById('update-progress-bar');
  if (bar) bar.style.width = '0%';
  const pct = document.getElementById('update-progress-percent');
  if (pct) pct.textContent = '0%';
  const speed = document.getElementById('update-progress-speed');
  if (speed) speed.textContent = '';

  const dlState = document.getElementById('update-downloading-state');
  const rdState = document.getElementById('update-ready-state');
  if (dlState) dlState.style.display = 'block';
  if (rdState) rdState.style.display = 'none';

  document.getElementById('update-modal').style.display = 'flex';
}

function updateDownloadProgress(percent, bytesPerSecond) {
  const bar = document.getElementById('update-progress-bar');
  if (bar) bar.style.width = `${percent}%`;

  const pct = document.getElementById('update-progress-percent');
  if (pct) pct.textContent = `${percent}%`;

  const speed = document.getElementById('update-progress-speed');
  if (speed) {
    const mbps = (bytesPerSecond / 1024 / 1024).toFixed(1);
    speed.textContent = `${mbps} MB/s`;
  }
}

function showUpdateReadyModal(version) {
  _currentUpdateVersion = version;

  const text = document.getElementById('update-ready-text');
  if (text) {
    text.textContent = `Version ${version} has been downloaded and verified. Ready to install.`;
  }

  const dlState = document.getElementById('update-downloading-state');
  const rdState = document.getElementById('update-ready-state');
  if (dlState) dlState.style.display = 'none';
  if (rdState) rdState.style.display = 'block';

  document.getElementById('update-modal').style.display = 'flex';
}

function dismissUpdateModal() {
  const modal = document.getElementById('update-modal');
  if (modal) modal.style.display = 'none';
}

function deferUpdateInstall() {
  window.electronAPI.deferUpdate().catch(console.error);
  dismissUpdateModal();
  showInfoToast(`Update v${_currentUpdateVersion} will install on next app restart.`);
}

async function installUpdateNow() {
  dismissUpdateModal();
  showInfoToast(`Installing v${_currentUpdateVersion}… The app will close and restart.`);

  await new Promise(resolve => setTimeout(resolve, 1200));

  const result = await window.electronAPI.installUpdate();
  if (!result || !result.success) {
    showInfoToast('Install failed: ' + ((result && result.error) || 'Unknown error'));
  }
}

function showUpdateCompleteToast(version, previousVersion) {
  const textEl = document.getElementById('update-complete-text');
  if (textEl) {
    textEl.textContent = `✓ Updated to v${version}`;
  }

  const toast = document.getElementById('update-complete-toast');
  if (toast) {
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 6000);
  }
}

// setupUpdateListeners uses the now-guarded preload methods (Patch 1D).
// The removeAllListeners in preload ensures these are safe to call here.
function setupUpdateListeners() {
  if (!window.electronAPI || !window.electronAPI.onUpdateAvailable) return;

  window.electronAPI.onUpdateAvailable((_event, info) => {
    console.log('[renderer] Update available:', info.version);
    showUpdateDownloadingModal(info.version, info.releaseNotes);
  });

  window.electronAPI.onDownloadProgress((_event, progress) => {
    updateDownloadProgress(progress.percent, progress.bytesPerSecond);
  });

  window.electronAPI.onUpdateDownloaded((_event, info) => {
    console.log('[renderer] Update downloaded and ready:', info.version);
    showUpdateReadyModal(info.version);
  });

  window.electronAPI.onUpdateComplete((_event, info) => {
    console.log('[renderer] Post-update restart detected:', info.version);
    showUpdateCompleteToast(info.version, info.previousVersion);
  });

  window.electronAPI.onUpdateError((_event, info) => {
    console.error('[renderer] Update error:', info.message);
    showInfoToast(`Update error: ${info.message}`);
  });
}
