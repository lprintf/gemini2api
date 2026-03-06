/**
 * Admin Dashboard Logic
 */

let currentTab = 'dashboard';
let browserData = [];
let tabsData = [];

// Tab navigation
document.querySelectorAll('.nav-btn').forEach(btn => {
    if (btn.dataset.tab) {
        btn.addEventListener('click', () => {
            switchTab(btn.dataset.tab);
        });
    }
});

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.nav-btn[data-tab="${tab}"]`).classList.add('active');
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(tab).classList.add('active');
    refreshCurrentTab();
}

function refreshCurrentTab() {
    switch (currentTab) {
        case 'dashboard': loadDashboard(); break;
        case 'browsers': loadBrowsers(); break;
        case 'tabs': loadTabs(); break;
        case 'tasks': loadTasks(); break;
        case 'config': loadConfig(); break;
        case 'logs': loadLogs(); break;
    }
}

// Helper for strings
function truncate(str, len) {
    if (!str) return '-';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

// Dashboard
async function loadDashboard() {
    try {
        const data = await apiFetch('/dashboard');

        document.getElementById('totalBrowsers').textContent = data.browsers.total;
        document.getElementById('idleBrowsers').textContent = data.browsers.status_count.idle || 0;
        document.getElementById('busyBrowsers').textContent = data.browsers.status_count.busy || 0;
        document.getElementById('todayTasks').textContent = data.tasks.today_tasks;

        document.getElementById('statTotalTasks').textContent = data.tasks.total_tasks;
        document.getElementById('statCompleted').textContent = data.tasks.completed_tasks;
        document.getElementById('statFailed').textContent = data.tasks.failed_tasks;

        const totalFinished = data.tasks.completed_tasks + data.tasks.failed_tasks;
        const successRate = totalFinished > 0
            ? (data.tasks.completed_tasks / totalFinished * 100).toFixed(1) + '%'
            : '-%';
        document.getElementById('statSuccessRate').textContent = successRate;

        document.getElementById('statAvgDuration').textContent = data.tasks.avg_duration
            ? data.tasks.avg_duration.toFixed(2) + 's' : '-';

        // 错误统计
        const errorStats = data.tasks.error_stats || {};
        const errorEntries = Object.entries(errorStats);
        const errorCard = document.getElementById('errorStatsCard');
        if (errorEntries.length > 0) {
            errorCard.style.display = 'block';
            const errorHtml = errorEntries.map(([msg, count]) => `
                <div class="log-item" style="display: flex; justify-content: space-between;">
                    <span style="color: #d9534f; font-weight: 500;">${escapeHtml(msg)}</span>
                    <span class="status-badge status-failed">${count}</span>
                </div>
            `).join('');
            document.getElementById('errorStatsList').innerHTML = errorHtml;
        } else {
            errorCard.style.display = 'none';
        }

        const logsHtml = data.recent_logs.map(log => `
            <div class="log-item">
                <span class="log-time">${formatTime(log.created_at)}</span>
                <span class="log-level ${log.level}">${log.level}</span>
                ${log.browser_id ? `<span class="log-browser">[${log.browser_id}]</span>` : ''}
                <span>${escapeHtml(log.message)}</span>
            </div>
        `).join('');
        document.getElementById('recentLogs').innerHTML = logsHtml || '<div class="empty-state">No recent logs</div>';

        const statusEl = document.getElementById('serverStatus');
        statusEl.textContent = 'Connected';
        statusEl.style.color = '#90EE90';
    } catch (e) {
        showToast('Failed to load dashboard: ' + e.message, 'error');
        const statusEl = document.getElementById('serverStatus');
        statusEl.textContent = 'Disconnected';
        statusEl.style.color = '#FF6B6B';
    }
}

// Browsers
async function loadBrowsers() {
    try {
        const data = await apiFetch('/browsers');
        browserData = data.browsers;

        browserData.sort((a, b) => a.browser_id.localeCompare(b.browser_id, undefined, { numeric: true }));

        updateBrowserFilters();

        const listEl = document.getElementById('browserList');
        const emptyEl = document.getElementById('browserEmpty');

        if (browserData.length === 0) {
            listEl.innerHTML = '';
            emptyEl.style.display = 'block';
            return;
        }

        emptyEl.style.display = 'none';

        const html = browserData.map(b => `
            <tr>
                <td><strong>${b.browser_id}</strong></td>
                <td>${escapeHtml(b.account_name)}</td>
                <td><span class="status-badge status-${b.status}">${b.status}</span></td>
                <td>${b.idle_tabs || 0} idle, ${b.sleeping_tabs || 0} sleep / ${b.total_tabs || 0}</td>
                <td>${b.total_tasks} (${b.failed_tasks} failed)</td>
                <td>
                    ${b.is_enabled
                ? `<button class="btn btn-secondary" onclick="toggleBrowserEnabled('${b.browser_id}', false)">Disable</button>`
                : `<button class="btn btn-success" onclick="toggleBrowserEnabled('${b.browser_id}', true)">Enable</button>`
            }
                    ${b.status === 'closed'
                ? `<button class="btn btn-success" onclick="launchBrowser('${b.browser_id}')">Launch</button>`
                : `<button class="btn btn-warning" onclick="closeBrowser('${b.browser_id}')">Close</button>`
            }
                    <button class="btn btn-primary" onclick="showEditBrowserModal('${b.browser_id}')">Edit</button>
                    <button class="btn btn-danger" onclick="deleteBrowser('${b.browser_id}')">Delete</button>
                </td>
            </tr>
        `).join('');

        listEl.innerHTML = html;
    } catch (e) {
        showToast('Failed to load browsers: ' + e.message, 'error');
    }
}

function updateBrowserFilters() {
    const options = browserData.map(b =>
        `<option value="${b.browser_id}">${b.browser_id} - ${escapeHtml(b.account_name)}</option>`
    ).join('');

    const taskFilter = document.getElementById('taskBrowserFilter');
    const logFilter = document.getElementById('logBrowserFilter');
    if (taskFilter) taskFilter.innerHTML = '<option value="">All Browsers</option>' + options;
    if (logFilter) logFilter.innerHTML = '<option value="">All Browsers</option>' + options;
}

async function launchBrowser(id) {
    try {
        await apiFetch(`/browsers/${id}/launch`, { method: 'POST' });
        showToast(`Browser ${id} launched`, 'success');
        loadBrowsers();
    } catch (e) {
        showToast('Failed to launch browser: ' + e.message, 'error');
    }
}

async function closeBrowser(id) {
    try {
        await apiFetch(`/browsers/${id}/close`, { method: 'POST' });
        showToast(`Browser ${id} closed`, 'success');
        loadBrowsers();
    } catch (e) {
        showToast('Failed to close browser: ' + e.message, 'error');
    }
}

async function toggleBrowserEnabled(id, enabled) {
    try {
        await apiFetch(`/browsers/${id}`, { method: 'PUT', body: { is_enabled: enabled } });
        showToast(`Browser ${id} is now ${enabled ? 'Online' : 'Offline'}`, 'success');
        loadBrowsers();
    } catch (e) {
        showToast('Operation failed: ' + e.message, 'error');
    }
}

async function deleteBrowser(id) {
    if (!confirm(`Delete browser ${id}?`)) return;
    try {
        await apiFetch(`/browsers/${id}`, { method: 'DELETE' });
        showToast(`Browser ${id} deleted`, 'success');
        loadBrowsers();
    } catch (e) {
        showToast('Failed to delete browser: ' + e.message, 'error');
    }
}

function showCreateBrowserModal() {
    document.getElementById('createBrowserForm').reset();
    document.getElementById('newAutoStart').checked = true;
    showModal('createBrowserModal');
}

async function createBrowser(e) {
    e.preventDefault();
    try {
        const data = {
            auto_start: document.getElementById('newAutoStart').checked,
        };

        const browserId = document.getElementById('newBrowserId').value;
        if (browserId) data.browser_id = parseInt(browserId);

        const accountName = document.getElementById('newAccountName').value;
        if (accountName) data.account_name = accountName;

        const proxy = document.getElementById('newProxy').value;
        if (proxy) data.proxy = proxy;

        const maxTabs = document.getElementById('newMaxTabs').value;
        if (maxTabs) data.max_tabs = parseInt(maxTabs);

        await apiFetch('/browsers', { method: 'POST', body: data });
        showToast('Browser created', 'success');
        hideModal('createBrowserModal');
        loadBrowsers();
    } catch (e) {
        showToast('Failed to create browser: ' + e.message, 'error');
    }
}

function showEditBrowserModal(id) {
    const browser = browserData.find(b => b.browser_id === id);
    if (!browser) return;

    document.getElementById('editBrowserId').value = id;
    document.getElementById('editAccountName').value = browser.account_name;
    document.getElementById('editProxy').value = browser.proxy || '';
    document.getElementById('editAutoStart').checked = true;

    showModal('editBrowserModal');
}

async function updateBrowser(e) {
    e.preventDefault();
    try {
        const id = document.getElementById('editBrowserId').value;
        const data = {
            account_name: document.getElementById('editAccountName').value,
            proxy: document.getElementById('editProxy').value || null,
            auto_start: document.getElementById('editAutoStart').checked,
        };

        await apiFetch(`/browsers/${id}`, { method: 'PUT', body: data });
        showToast('Browser updated', 'success');
        hideModal('editBrowserModal');
        loadBrowsers();
    } catch (e) {
        showToast('Failed to update browser: ' + e.message, 'error');
    }
}

// Tabs
async function loadTabs() {
    try {
        const data = await apiFetch('/tabs');
        tabsData = data.tabs;

        // 更新统计卡片
        document.getElementById('totalTabs').textContent = data.total;
        document.getElementById('idleTabs').textContent = data.status_count.idle || 0;
        document.getElementById('busyTabs').textContent = data.status_count.busy || 0;
        document.getElementById('sleepTabs').textContent = data.status_count.sleep || 0;
        document.getElementById('errorTabs').textContent = (data.status_count.error || 0) + (data.status_count.disabled || 0) + (data.status_count.closed || 0) + (data.status_count.launching || 0);

        // 更新浏览器筛选器
        const browsers = [...new Set(tabsData.map(t => t.browser_id))];
        const browserOptions = browsers.map(id => `<option value="${id}">${id}</option>`).join('');
        document.getElementById('tabBrowserFilter').innerHTML = '<option value="">All Browsers</option>' + browserOptions;

        // 应用筛选
        const statusFilter = document.getElementById('tabStatusFilter').value;
        const browserFilter = document.getElementById('tabBrowserFilter').value;

        let filteredTabs = tabsData;
        if (statusFilter) {
            filteredTabs = filteredTabs.filter(t => t.status === statusFilter);
        }
        if (browserFilter) {
            filteredTabs = filteredTabs.filter(t => t.browser_id === browserFilter);
        }

        const listEl = document.getElementById('tabList');
        const emptyEl = document.getElementById('tabEmpty');

        if (filteredTabs.length === 0) {
            listEl.innerHTML = '';
            emptyEl.style.display = 'block';
            return;
        }

        emptyEl.style.display = 'none';

        const html = filteredTabs.map(t => `
            <tr>
                <td><strong>${t.browser_id}</strong></td>
                <td>Tab ${t.tab_id}</td>
                <td><span class="status-badge ${t.model === 'Pro' ? 'status-processing' : 'status-completed'}">${t.model}</span></td>
                <td>
                    <span class="status-badge status-${t.status}">
                        ${t.status === 'busy' ? escapeHtml(t.activity || 'Busy') : (t.status === 'sleep' ? 'Sleep until ' + formatTime(t.sleep_until) : t.status)}
                    </span>
                </td>
                <td>${t.total_tasks}</td>
                <td>${t.failed_tasks} (${t.consecutive_failures} consecutive)</td>
                <td>${formatTime(t.last_active_at)}</td>
                <td>
                    <button class="btn btn-warning" onclick="reinitializeTab('${t.browser_id}', ${t.tab_id})" ${t.status === 'busy' ? 'disabled' : ''}>Reinit</button>
                    <a class="btn btn-secondary" href="/remote?browser=${t.browser_id}&tab=${t.tab_id}" target="_blank">Remote</a>
                </td>
            </tr>
        `).join('');

        listEl.innerHTML = html;
    } catch (e) {
        showToast('Failed to load tabs: ' + e.message, 'error');
    }
}

async function reinitializeTab(browserId, tabId) {
    try {
        showToast(`Reinitializing ${browserId} Tab ${tabId}...`);
        const result = await apiFetch(`/browsers/${browserId}/tabs/${tabId}/reinitialize`, { method: 'POST' });
        if (result.success) {
            showToast(`Tab ${browserId}-${tabId} reinitialized`, 'success');
        } else {
            showToast(`Tab ${browserId}-${tabId} reinitialize failed`, 'error');
        }
        loadTabs();
    } catch (e) {
        showToast('Failed to reinitialize tab: ' + e.message, 'error');
    }
}

async function reinitializeErrorTabs() {
    const errorTabs = tabsData.filter(t => t.status === 'error');
    if (errorTabs.length === 0) {
        showToast('No error tabs to reinitialize', 'success');
        return;
    }

    if (!confirm(`Reinitialize ${errorTabs.length} error tab(s)?`)) return;

    showToast(`Reinitializing ${errorTabs.length} error tabs...`);
    let successCount = 0;
    for (const tab of errorTabs) {
        try {
            const result = await apiFetch(`/browsers/${tab.browser_id}/tabs/${tab.tab_id}/reinitialize`, { method: 'POST' });
            if (result.success) successCount++;
        } catch (e) {
            console.error(`Failed to reinit ${tab.browser_id}-${tab.tab_id}:`, e);
        }
    }
    showToast(`Reinitialized ${successCount}/${errorTabs.length} tabs`, successCount === errorTabs.length ? 'success' : 'error');
    loadTabs();
}

// Tasks
async function loadTasks() {
    try {
        const status = document.getElementById('taskStatusFilter').value;
        const browserId = document.getElementById('taskBrowserFilter').value;

        let endpoint = '/tasks?limit=50';
        if (status) endpoint += `&status=${status}`;
        if (browserId) endpoint += `&browser_id=${browserId}`;

        const data = await apiFetch(endpoint);

        const listEl = document.getElementById('taskList');
        const emptyEl = document.getElementById('taskEmpty');

        if (data.tasks.length === 0) {
            listEl.innerHTML = '';
            emptyEl.style.display = 'block';
            return;
        }

        emptyEl.style.display = 'none';

        const html = data.tasks.map(t => `
            <tr>
                <td><code>${t.task_id.substring(0, 8)}...</code></td>
                <td>${t.browser_id || '-'}</td>
                <td>${t.tab_id || '-'}</td>
                <td title="${escapeHtml(t.prompt)}">${truncate(t.prompt, 50)}</td>
                <td><span class="status-badge status-${t.status}">${t.status}</span></td>
                <td>${t.duration ? t.duration.toFixed(2) + 's' : '-'}</td>
                <td>${formatTime(t.created_at)}</td>
            </tr>
        `).join('');

        listEl.innerHTML = html;
    } catch (e) {
        showToast('Failed to load tasks: ' + e.message, 'error');
    }
}

// Config
async function loadConfig() {
    try {
        const data = await apiFetch('/config');

        document.getElementById('cfgServerHost').value = data.server_host;
        document.getElementById('cfgServerPort').value = data.server_port;
        document.getElementById('cfgMinBrowsers').value = data.min_browsers;
        document.getElementById('cfgMaxBrowsers').value = data.max_browsers;
        document.getElementById('cfgLbStrategy').value = data.lb_strategy;
        document.getElementById('cfgLogLevel').value = data.log_level;
        document.getElementById('cfgAdminUsername').value = data.admin_username;
    } catch (e) {
        showToast('Failed to load config: ' + e.message, 'error');
    }
}

async function saveConfig(e) {
    e.preventDefault();
    try {
        const data = {
            server_host: document.getElementById('cfgServerHost').value,
            server_port: parseInt(document.getElementById('cfgServerPort').value),
            min_browsers: parseInt(document.getElementById('cfgMinBrowsers').value),
            max_browsers: parseInt(document.getElementById('cfgMaxBrowsers').value),
            lb_strategy: document.getElementById('cfgLbStrategy').value,
            log_level: document.getElementById('cfgLogLevel').value,
            admin_username: document.getElementById('cfgAdminUsername').value,
        };

        const password = document.getElementById('cfgAdminPassword').value;
        if (password) data.admin_password = password;

        await apiFetch('/config', { method: 'PUT', body: data });
        showToast('Configuration saved', 'success');
        document.getElementById('cfgAdminPassword').value = '';
    } catch (e) {
        showToast('Failed to save config: ' + e.message, 'error');
    }
}

// Logs
async function loadLogs() {
    try {
        const level = document.getElementById('logLevelFilter').value;
        const browserId = document.getElementById('logBrowserFilter').value;

        let endpoint = '/logs?limit=100';
        if (level) endpoint += `&level=${level}`;
        if (browserId) endpoint += `&browser_id=${browserId}`;

        const data = await apiFetch(endpoint);

        const listEl = document.getElementById('logList');
        const emptyEl = document.getElementById('logEmpty');

        if (data.logs.length === 0) {
            listEl.innerHTML = '';
            emptyEl.style.display = 'block';
            return;
        }

        emptyEl.style.display = 'none';

        const html = data.logs.map(log => `
            <div class="log-item">
                <span class="log-time">${formatTime(log.created_at)}</span>
                <span class="log-level ${log.level}">${log.level}</span>
                ${log.browser_id ? `<span class="log-browser">[${log.browser_id}]</span>` : ''}
                <span>${escapeHtml(log.message)}</span>
            </div>
        `).join('');

        listEl.innerHTML = html;
    } catch (e) {
        showToast('Failed to load logs: ' + e.message, 'error');
    }
}

async function clearOldLogs() {
    if (!confirm('Clear logs older than 7 days?')) return;
    try {
        await apiFetch('/logs?days=7', { method: 'DELETE' });
        showToast('Old logs cleared', 'success');
        loadLogs();
    } catch (e) {
        showToast('Failed to clear logs: ' + e.message, 'error');
    }
}

async function resetAllStats() {
    if (!confirm('确定要重置所有任务统计并清空今日日志/调试文件吗？此操作不可恢复。')) {
        return;
    }

    try {
        const taskRes = await apiFetch('/tasks/reset', { method: 'DELETE' });
        const logRes = await apiFetch('/logs/today', { method: 'DELETE' });

        if (taskRes.success && logRes.success) {
            showToast('重置成功：统计已归零，今日日志已清空', 'success');
            refreshCurrentTab();
        } else {
            showToast('重置部分失败，请检查后端日志', 'error');
        }
    } catch (err) {
        showToast('重置请求失败: ' + err.message, 'error');
    }
}

// Modals
function showModal(id) {
    document.getElementById(id).classList.add('show');
}

function hideModal(id) {
    document.getElementById(id).classList.remove('show');
}

// Global Modal Backdrop Click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        e.target.classList.remove('show');
    }
});

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    setInterval(refreshCurrentTab, 30000);
});
