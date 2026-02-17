// ============================================================
// renderer.js
//
// ROOT CAUSE OF ALL EMPTY DATA:
//   package.json copy-assets only copied index.html to dist/.
//   renderer.js was NEVER copied to dist/renderer/, so Electron
//   was always running the original broken version regardless of
//   what was saved in src/renderer/renderer.js.
//   Fixed in package.json. This file now gets deployed correctly.
//
// ADDITIONAL FIX vs previous version:
//   Today button and date init now use LOCAL date instead of UTC.
//   new Date().toISOString() returns UTC — if you're UTC+n, your
//   local date is ahead; you'd see "yesterday" in the picker and
//   get zero results because data is stored against local date.
// ============================================================

// Global state
let isAuthenticated = false;
let currentTab = 'overview';
let currentSubTab = 'app-tracking';
let charts = {};

// Use LOCAL date (not UTC) so the picker matches data on disk
function getLocalDateString() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

let currentDate = getLocalDateString();

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
}

// ─── EVENT LISTENERS ─────────────────────────────────────────
function setupEventListeners() {
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await handleLogin();
  });

  document.getElementById('logout-btn').addEventListener('click', async () => {
    await handleLogout();
  });

  document.getElementById('refresh-btn').addEventListener('click', async () => {
    await loadDashboardData();
  });

  // Date picker: update variable but wait for Search click
  document.getElementById('date-picker').addEventListener('change', (e) => {
    currentDate = e.target.value;
  });

  // Today: use LOCAL date, load immediately
  document.getElementById('today-btn').addEventListener('click', () => {
    currentDate = getLocalDateString();
    document.getElementById('date-picker').value = currentDate;
    loadDashboardData();
  });

  // Search: explicit trigger with selected date
  document.getElementById('search-btn').addEventListener('click', () => {
    const pickerVal = document.getElementById('date-picker').value;
    if (pickerVal) currentDate = pickerVal;
    loadDashboardData();
  });

  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.addEventListener('click', (e) => switchTab(e.currentTarget.dataset.tab));
  });

  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => switchSubTab(e.currentTarget.dataset.subtab));
  });

  document.getElementById('pause-btn').addEventListener('click', async () => {
    await pauseMonitoring();
  });

  document.getElementById('resume-btn').addEventListener('click', async () => {
    await resumeMonitoring();
  });
}

// ─── LOGIN / LOGOUT ──────────────────────────────────────────
async function handleLogin() {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  const errorDiv = document.getElementById('login-error');
  const loginBtn = document.getElementById('login-btn');

  errorDiv.textContent = '';
  loginBtn.disabled = true;
  loginBtn.textContent = 'Logging in...';

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
    errorDiv.textContent = 'Login failed. Please check if the backend service is running.';
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = 'Login';
  }
}

async function handleLogout() {
  try {
    await window.electronAPI.logout();
    isAuthenticated = false;
    showLogin();
    document.getElementById('login-form').reset();
  } catch (error) {
    console.error('Logout failed:', error);
  }
}

// ─── DATA LOADING ────────────────────────────────────────────
async function loadDashboardData() {
  if (!isAuthenticated) return;
  try {
    await loadMonitoringStatus();
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
    document.getElementById('stat-screenshots').textContent = stats.total_screenshots || 0;
    document.getElementById('stat-hours').textContent = (stats.active_hours_today || 0).toFixed(1);
    document.getElementById('stat-apps').textContent = stats.apps_tracked || 0;
    document.getElementById('stat-clipboard').textContent = stats.clipboard_events || 0;
  } catch (error) {
    console.error('Failed to load statistics:', error);
  }
}

async function loadMonitoringStatus() {
  try {
    const status = await window.electronAPI.getMonitoringStatus();
    const indicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    const badge = document.getElementById('status-badge');
    const pauseBtn = document.getElementById('pause-btn');
    const resumeBtn = document.getElementById('resume-btn');

    if (status.is_monitoring) {
      indicator.className = 'status-indicator active';
      statusText.textContent = 'Monitoring Active';
      badge.className = 'status-badge';
      pauseBtn.style.display = 'inline-block';
      resumeBtn.style.display = 'none';
    } else {
      indicator.className = 'status-indicator paused';
      statusText.textContent = 'Monitoring Paused';
      badge.className = 'status-badge paused';
      pauseBtn.style.display = 'none';
      resumeBtn.style.display = 'inline-block';
    }
  } catch (error) {
    console.error('Failed to load monitoring status:', error);
  }
}

async function loadChartsData() {
  try {
    const [activityData, timelineData] = await Promise.all([
      window.electronAPI.getActivityStats({ start: currentDate, end: currentDate }),
      window.electronAPI.getTimelineData({ date: currentDate })
    ]);
    updateCharts(activityData, timelineData);
  } catch (e) {
    console.error('Failed to load charts data:', e);
  }
}

async function loadScreenshots() {
  try {
    const screenshots = await window.electronAPI.getScreenshots({ limit: 20 });
    const grid = document.getElementById('screenshots-grid');
    if (!screenshots || screenshots.length === 0) {
      grid.innerHTML = '<div class="loading">No screenshots available yet.</div>';
      return;
    }
    const placeholder = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='280' height='160'%3E%3Crect fill='%23eee' width='280' height='160'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' fill='%23999' dy='.3em'%3ENo Image%3C/text%3E%3C/svg%3E";
    grid.innerHTML = screenshots.map(s => {
      const appLabel = s.active_app || s.active_window || 'Unknown';
      return `
        <div class="screenshot-item">
          <img src="${s.file_path}" alt="Screenshot" onerror="this.src='${placeholder}'">
          <div class="info">
            <div class="timestamp">${new Date(s.timestamp).toLocaleString()}</div>
            <div class="app-name">📱 ${escapeHtml(appLabel)}</div>
          </div>
        </div>`;
    }).join('');
  } catch (error) {
    console.error('Failed to load screenshots:', error);
    document.getElementById('screenshots-grid').innerHTML =
      '<div class="loading">Failed to load screenshots.</div>';
  }
}

// ─── MONITORING CONTROLS ─────────────────────────────────────
async function pauseMonitoring() {
  try {
    await window.electronAPI.pauseMonitoring();
    await loadMonitoringStatus();
  } catch (error) {
    alert('Failed to pause monitoring');
  }
}

async function resumeMonitoring() {
  try {
    await window.electronAPI.resumeMonitoring();
    await loadMonitoringStatus();
  } catch (error) {
    alert('Failed to resume monitoring');
  }
}

// ─── TAB SWITCHING ───────────────────────────────────────────
function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
  const pane = document.getElementById(`${tabName}-tab`);
  if (pane) pane.classList.add('active');
  loadDashboardData();
}

function switchSubTab(subTabName) {
  currentSubTab = subTabName;
  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.subtab === subTabName);
  });
  document.querySelectorAll('.sub-view').forEach(view => (view.style.display = 'none'));
  const view = document.getElementById(`${subTabName}-view`);
  if (view) view.style.display = 'block';
  loadMonitorData();
}

// ─── MONITOR DATA TABLES ─────────────────────────────────────
async function loadMonitorData() {
  if (currentSubTab === 'app-tracking') await loadAppLogs();
  else if (currentSubTab === 'browser-tracking') await loadBrowserLogs();
  else if (currentSubTab === 'clipboard-tracking') await loadClipboardLogs();
}

async function loadAppLogs() {
  const tbody = document.getElementById('app-logs-body');
  tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;">Loading...</td></tr>';
  try {
    const logs = await window.electronAPI.getAppLogs({ limit: 50 });
    if (!logs || logs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#888;">No app activity recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${new Date(log.timestamp).toLocaleString()}</td>
        <td>${escapeHtml(log.app_name || '-')}</td>
        <td>${escapeHtml(log.window_title || '-')}</td>
        <td>${formatDuration(log.duration_seconds)}</td>
      </tr>`).join('');
  } catch (e) {
    console.error('Failed to load app logs:', e);
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#dc3545;">Failed to load data.</td></tr>';
  }
}

async function loadBrowserLogs() {
  const tbody = document.getElementById('browser-logs-body');
  tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;">Loading...</td></tr>';
  try {
    const logs = await window.electronAPI.getBrowserLogs({ limit: 50 });
    if (!logs || logs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#888;">No browser activity recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${new Date(log.timestamp).toLocaleString()}</td>
        <td>${escapeHtml(log.app_name || '-')}</td>
        <td>${escapeHtml(log.window_title || '-')}</td>
        <td>${formatDuration(log.duration_seconds)}</td>
      </tr>`).join('');
  } catch (e) {
    console.error('Failed to load browser logs:', e);
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px;color:#dc3545;">Failed to load data.</td></tr>';
  }
}

async function loadClipboardLogs() {
  const tbody = document.getElementById('clipboard-logs-body');
  tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:20px;">Loading...</td></tr>';
  try {
    const logs = await window.electronAPI.getClipboardLogs({ limit: 50 });
    if (!logs || logs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:20px;color:#888;">No clipboard events recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${new Date(log.timestamp).toLocaleString()}</td>
        <td>${escapeHtml(log.content_type || '-')}</td>
        <td>${escapeHtml(log.content_preview || '')}</td>
      </tr>`).join('');
  } catch (e) {
    console.error('Failed to load clipboard logs:', e);
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:20px;color:#dc3545;">Failed to load data.</td></tr>';
  }
}

// ─── CHARTS ──────────────────────────────────────────────────
function initializeCharts() {
  if (charts.timeline) return; // already initialized

  const timelineCtx = document.getElementById('timeline-chart').getContext('2d');
  charts.timeline = new Chart(timelineCtx, {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { title: { display: true, text: 'Hour of Day' } } }
    }
  });

  const appCtx = document.getElementById('app-usage-chart').getContext('2d');
  charts.appUsage = new Chart(appCtx, {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } }
    }
  });

  const catCtx = document.getElementById('category-chart').getContext('2d');
  charts.category = new Chart(catCtx, {
    type: 'doughnut',
    data: { labels: [], datasets: [] },
    options: { responsive: true, maintainAspectRatio: false }
  });
}

function updateCharts(activityData, timelineData) {
  if (!charts.appUsage || !charts.category || !charts.timeline) {
    console.warn('Charts not initialized — skipping update');
    return;
  }

  // App usage (backend returns { app_name, total_seconds })
  const labels = (activityData || []).map(a => a.app_name);
  const data = (activityData || []).map(a => parseFloat((a.total_seconds / 60).toFixed(1)));

  charts.appUsage.data = {
    labels,
    datasets: [{ label: 'Minutes', data, backgroundColor: 'rgba(102,126,234,0.7)', borderColor: 'rgba(102,126,234,1)', borderWidth: 1 }]
  };
  charts.appUsage.update();

  charts.category.data = {
    labels: labels.slice(0, 5),
    datasets: [{ data: data.slice(0, 5), backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF'] }]
  };
  charts.category.update();

  // Timeline: bucket activity by hour
  const hourlyData = new Array(24).fill(0);
  (timelineData || []).forEach(item => {
    if (item.timestamp) {
      const hour = new Date(item.timestamp).getHours();
      hourlyData[hour] += (item.duration_seconds || 0) / 60;
    }
  });

  charts.timeline.data = {
    labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
    datasets: [{
      label: 'Minutes Active',
      data: hourlyData.map(v => parseFloat(v.toFixed(1))),
      backgroundColor: 'rgba(75,192,192,0.6)',
      borderColor: 'rgba(75,192,192,1)',
      borderWidth: 1
    }]
  };
  charts.timeline.update();
}

// ─── HELPERS ─────────────────────────────────────────────────
function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '0s';
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}