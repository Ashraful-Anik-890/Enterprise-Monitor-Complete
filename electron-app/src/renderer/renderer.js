// Global state
let isAuthenticated = false;
let currentTab = 'overview';
let currentSubTab = 'app-tracking';
let charts = {}; // Store chart instances
let currentDate = new Date().toISOString().split('T')[0]; // YYYY-MM-DD

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
  // Set date picker to today
  document.getElementById('date-picker').value = currentDate;

  await checkAuthentication();
  setupEventListeners();

  if (isAuthenticated) {
    initializeCharts();
  }
});

// Check if user is authenticated
async function checkAuthentication() {
  try {
    const result = await window.electronAPI.checkAuth();
    isAuthenticated = result.authenticated;

    if (isAuthenticated) {
      showDashboard();
      initializeCharts(); // Initialize charts if auth check passes
      await loadDashboardData();
    } else {
      showLogin();
    }
  } catch (error) {
    console.error('Auth check failed:', error);
    showLogin();
  }
}

// Show login screen
function showLogin() {
  document.getElementById('login-container').classList.add('active');
  document.getElementById('dashboard-container').classList.remove('active');
}

// Show dashboard
function showDashboard() {
  document.getElementById('login-container').classList.remove('active');
  document.getElementById('dashboard-container').classList.add('active');
}

// Setup event listeners
function setupEventListeners() {
  // Login form
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await handleLogin();
  });

  // Logout button
  document.getElementById('logout-btn').addEventListener('click', async () => {
    await handleLogout();
  });

  // Refresh button
  document.getElementById('refresh-btn').addEventListener('click', async () => {
    await loadDashboardData();
  });

  // Date Picker
  document.getElementById('date-picker').addEventListener('change', (e) => {
    currentDate = e.target.value;
    loadDashboardData();
  });

  // Today Button
  document.getElementById('today-btn').addEventListener('click', () => {
    currentDate = new Date().toISOString().split('T')[0];
    document.getElementById('date-picker').value = currentDate;
    loadDashboardData();
  });

  // Tab buttons
  document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', (e) => {
      switchTab(e.target.dataset.tab);
    });
  });

  // Sub-tab buttons
  document.querySelectorAll('.sub-tab-btn').forEach(button => {
    button.addEventListener('click', (e) => {
      switchSubTab(e.target.dataset.subtab);
    });
  });

  // Monitoring controls
  document.getElementById('pause-btn').addEventListener('click', async () => {
    await pauseMonitoring();
  });

  document.getElementById('resume-btn').addEventListener('click', async () => {
    await resumeMonitoring();
  });
}

// Initialize Chart.js charts
function initializeCharts() {
  if (charts.timeline) return; // Already initialized

  // Timeline Chart (Horizontal Bar)
  const timelineCtx = document.getElementById('timeline-chart').getContext('2d');
  charts.timeline = new Chart(timelineCtx, {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { stacked: true }, y: { stacked: true } },
      plugins: { legend: { display: false } }
    }
  });

  // App Usage Chart (Bar)
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

  // Category/Distribution Chart (Doughnut)
  const catCtx = document.getElementById('category-chart').getContext('2d');
  charts.category = new Chart(catCtx, {
    type: 'doughnut',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
    }
  });
}

// Update Charts with Data
function updateCharts(activityData, timelineData) {
  // 1. App Usage Chart
  const labels = activityData.map(a => a.app_name);
  const data = activityData.map(a => (a.total_seconds / 60).toFixed(1)); // Minutes

  charts.appUsage.data = {
    labels: labels,
    datasets: [{
      label: 'Minutes',
      data: data,
      backgroundColor: 'rgba(54, 162, 235, 0.6)',
      borderColor: 'rgba(54, 162, 235, 1)',
      borderWidth: 1
    }]
  };
  charts.appUsage.update();

  // 2. Category Chart (Using same data for now, mocking categories)
  // In future, map apps to categories
  charts.category.data = {
    labels: labels.slice(0, 5), // Top 5
    datasets: [{
      data: data.slice(0, 5),
      backgroundColor: [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF'
      ]
    }]
  };
  charts.category.update();

  // 3. Timeline Chart (Simplified visualization)
  // Group timeline data by hour
  const hourlyData = new Array(24).fill(0);
  timelineData.forEach(item => {
    const hour = new Date(item.timestamp).getHours();
    hourlyData[hour] += item.duration_seconds / 60; // Minutes
  });

  charts.timeline.data = {
    labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
    datasets: [{
      label: 'Activity (Min)',
      data: hourlyData,
      backgroundColor: 'rgba(75, 192, 192, 0.6)'
    }]
  };
  charts.timeline.update();
}

// Handle login
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

// Handle logout
async function handleLogout() {
  try {
    await window.electronAPI.logout();
    isAuthenticated = false;
    showLogin();

    // Clear form
    document.getElementById('login-form').reset();
  } catch (error) {
    console.error('Logout failed:', error);
  }
}

// Load dashboard data
async function loadDashboardData() {
  if (!isAuthenticated) return;

  try {
    await Promise.all([
      loadStatistics(),
      loadChartsData(), // New function for charts
      loadMonitoringStatus()
    ]);
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
  }
}

// Load charts data
async function loadChartsData() {
  try {
    // Fetch aggregated activity stats
    const activityData = await window.electronAPI.getActivityStats({
      start: currentDate,
      end: currentDate
    });

    // Fetch timeline data
    const timelineData = await window.electronAPI.getTimelineData({
      date: currentDate
    });

    console.log('Activity Data:', activityData);
    console.log('Timeline Data:', timelineData);

    updateCharts(activityData, timelineData);
  } catch (e) {
    console.error("Failed to load charts data", e);
  }
}

// Helper to get token (Needs to be exposed from preload/main or stored)
// Since we don't have direct access to token in renderer (it's HttpOnly cookie or internal state in main),
// we might need to update Electron API to proxy these requests or expose token.
// HOWEVER, looking at main.ts, the client is in main process.
// renderer.js uses window.electronAPI.
// WE NEED TO ADD THESE METHODS TO PRELOAD/MAIN.
// Wait! simpler solution: Add methods to window.electronAPI in main.ts
// For now, I will assume window.electronAPI needs update.
// Actually, fetch from renderer might fail CORS if not configured, but backend allows CORs.
// Problem: Authentication! I don't have the token in renderer variable.
// The main process handles API calls.
// I should add `getChartsData` or similar to `preload` and `main.ts`.

// REVERTING fetch calls here to use window.electronAPI
// I will need to update main.ts first.

// For now, I will put placeholder logic and then update main.ts
// Or better: Use window.electronAPI.invoke('get-stats-data', ...)

// Load statistics
async function loadStatistics() {
  try {
    const stats = await window.electronAPI.getStatistics();

    document.getElementById('stat-screenshots').textContent =
      stats.total_screenshots || 0;
    document.getElementById('stat-hours').textContent =
      (stats.active_hours_today || 0).toFixed(1);
    document.getElementById('stat-apps').textContent =
      stats.apps_tracked || 0;
    document.getElementById('stat-clipboard').textContent =
      stats.clipboard_events || 0;
  } catch (error) {
    console.error('Failed to load statistics:', error);
  }
}

// ... rest of file (loadMonitoringStatus, loadScreenshots, etc.) UNCHANGED ...
// I need to use `multi_replace` or ensure I copy the rest correctly.
// Since I am replacing the whole file, I must be careful.

// I will STOP here to re-plan slightly: I need to update `main.ts` and `preload.ts` (if exists) to expose the new API endpoints!
// The user has `d:\Codes\Skillers_Zone_LTD\enterprise-monitor-complete\electron-app\src\main\main.ts`.
// I need to check `preload.ts` too.


// Check if user is authenticated
async function checkAuthentication() {
  try {
    const result = await window.electronAPI.checkAuth();
    isAuthenticated = result.authenticated;

    if (isAuthenticated) {
      showDashboard();
      await loadDashboardData();
    } else {
      showLogin();
    }
  } catch (error) {
    console.error('Auth check failed:', error);
    showLogin();
  }
}

// Show login screen
function showLogin() {
  document.getElementById('login-container').classList.add('active');
  document.getElementById('dashboard-container').classList.remove('active');
}

// Show dashboard
function showDashboard() {
  document.getElementById('login-container').classList.remove('active');
  document.getElementById('dashboard-container').classList.add('active');
}

// Setup event listeners
function setupEventListeners() {
  // Login form
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await handleLogin();
  });

  // Logout button
  document.getElementById('logout-btn').addEventListener('click', async () => {
    await handleLogout();
  });

  // Refresh button
  document.getElementById('refresh-btn').addEventListener('click', async () => {
    await loadDashboardData();
  });

  // Tab buttons
  document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', (e) => {
      switchTab(e.target.dataset.tab);
    });
  });

  // Monitoring controls
  document.getElementById('pause-btn').addEventListener('click', async () => {
    await pauseMonitoring();
  });

  document.getElementById('resume-btn').addEventListener('click', async () => {
    await resumeMonitoring();
  });
}

// Handle login
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

// Handle logout
async function handleLogout() {
  try {
    await window.electronAPI.logout();
    isAuthenticated = false;
    showLogin();

    // Clear form
    document.getElementById('login-form').reset();
  } catch (error) {
    console.error('Logout failed:', error);
  }
}

// Load dashboard data
async function loadDashboardData() {
  if (!isAuthenticated) return;

  try {
    // Always load status
    await loadMonitoringStatus();

    if (currentTab === 'overview') {
      await Promise.all([
        loadStatistics(),
        loadChartsData()
      ]);
    } else if (currentTab === 'monitor-data') {
      await loadMonitorData();
    } else if (currentTab === 'screenshots') {
      await loadScreenshots();
    }
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
  }
}

// Load statistics
async function loadStatistics() {
  try {
    const stats = await window.electronAPI.getStatistics();

    document.getElementById('stat-screenshots').textContent =
      stats.total_screenshots || 0;
    document.getElementById('stat-hours').textContent =
      (stats.active_hours_today || 0).toFixed(1);
    document.getElementById('stat-apps').textContent =
      stats.apps_tracked || 0;
    document.getElementById('stat-clipboard').textContent =
      stats.clipboard_events || 0;
  } catch (error) {
    console.error('Failed to load statistics:', error);
  }
}

// Load monitoring status
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
      statusText.textContent = 'Active';
      badge.className = 'status-badge';
      pauseBtn.style.display = 'inline-block';
      resumeBtn.style.display = 'none';
    } else {
      indicator.className = 'status-indicator paused';
      statusText.textContent = 'Paused';
      badge.className = 'status-badge paused';
      pauseBtn.style.display = 'none';
      resumeBtn.style.display = 'inline-block';
    }
  } catch (error) {
    console.error('Failed to load monitoring status:', error);
  }
}

// Load screenshots
async function loadScreenshots() {
  try {
    const screenshots = await window.electronAPI.getScreenshots({ limit: 20 });
    const grid = document.getElementById('screenshots-grid');

    if (screenshots.length === 0) {
      grid.innerHTML = '<div class="loading">No screenshots available yet.</div>';
      return;
    }

    grid.innerHTML = screenshots.map(screenshot => `
      <div class="screenshot-item">
        <img src="${screenshot.file_path}" alt="Screenshot" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22150%22%3E%3Crect fill=%22%23eee%22 width=%22200%22 height=%22150%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 fill=%22%23999%22%3ENo Image%3C/text%3E%3C/svg%3E'">
        <div class="info">
          <div>${new Date(screenshot.timestamp).toLocaleString()}</div>
          <div>${screenshot.active_window || 'Unknown'}</div>
        </div>
      </div>
    `).join('');
  } catch (error) {
    console.error('Failed to load screenshots:', error);
    document.getElementById('screenshots-grid').innerHTML =
      '<div class="loading">Failed to load screenshots.</div>';
  }
}

// Pause monitoring
async function pauseMonitoring() {
  try {
    await window.electronAPI.pauseMonitoring();
    await loadMonitoringStatus();
  } catch (error) {
    console.error('Failed to pause monitoring:', error);
    alert('Failed to pause monitoring');
  }
}

// Resume monitoring
async function resumeMonitoring() {
  try {
    await window.electronAPI.resumeMonitoring();
    await loadMonitoringStatus();
  } catch (error) {
    console.error('Failed to resume monitoring:', error);
    alert('Failed to resume monitoring');
  }
}

// Switch tabs
function switchTab(tabName) {
  currentTab = tabName;

  // Update buttons
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('active');
    if (btn.dataset.tab === tabName) {
      btn.classList.add('active');
    }
  });

  // Update panes
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.remove('active');
  });
  const pane = document.getElementById(`${tabName}-tab`);
  if (pane) pane.classList.add('active');

  // Load data for active tab
  loadDashboardData();
}

// Switch sub-tabs
function switchSubTab(subTabName) {
  currentSubTab = subTabName;

  // Update buttons
  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.classList.remove('active');
    if (btn.dataset.subtab === subTabName) {
      btn.classList.add('active');
    }
  });

  // Update views
  document.querySelectorAll('.sub-view').forEach(view => {
    view.style.display = 'none';
  });
  document.getElementById(`${subTabName}-view`).style.display = 'block';

  // Load data
  loadMonitorData();
}

// Load Monitor Data
async function loadMonitorData() {
  if (currentSubTab === 'app-tracking') {
    await loadAppLogs();
  } else if (currentSubTab === 'browser-tracking') {
    await loadBrowserLogs();
  } else if (currentSubTab === 'clipboard-tracking') {
    await loadClipboardLogs();
  }
}

async function loadAppLogs() {
  try {
    const logs = await window.electronAPI.getAppLogs({ limit: 50 });
    const tbody = document.getElementById('app-logs-body');
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${new Date(log.timestamp).toLocaleString()}</td>
        <td>${log.app_name}</td>
        <td>${log.window_title || '-'}</td>
        <td>${formatDuration(log.duration_seconds)}</td>
      </tr>
    `).join('');
  } catch (e) {
    console.error("Failed to load app logs", e);
  }
}

async function loadBrowserLogs() {
  try {
    const logs = await window.electronAPI.getBrowserLogs({ limit: 50 });
    const tbody = document.getElementById('browser-logs-body');
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${new Date(log.timestamp).toLocaleString()}</td>
        <td>${log.app_name}</td>
        <td>${log.window_title || '-'}</td>
        <td>${formatDuration(log.duration_seconds)}</td>
      </tr>
    `).join('');
  } catch (e) {
    console.error("Failed to load browser logs", e);
  }
}

async function loadClipboardLogs() {
  try {
    const logs = await window.electronAPI.getClipboardLogs({ limit: 50 });
    const tbody = document.getElementById('clipboard-logs-body');
    tbody.innerHTML = logs.map(log => `
      <tr>
        <td>${new Date(log.timestamp).toLocaleString()}</td>
        <td>${log.content_type}</td>
        <td>${escapeHtml(log.content_preview || '')}</td>
      </tr>
    `).join('');
  } catch (e) {
    console.error("Failed to load clipboard logs", e);
  }
}

function formatDuration(seconds) {
  if (!seconds) return '0s';
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
