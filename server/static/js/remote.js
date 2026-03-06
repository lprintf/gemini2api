/**
 * Remote Control Logic
 */

let selectedBrowser = null;
let selectedTab = null;
let viewportWidth = 1280;
let viewportHeight = 900;
let autoRefresh = true;
let isLoading = false;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadBrowsers();
    setupScreenshotEvents();
    setupKeyboardShortcuts();
});

// 加载浏览器列表
async function loadBrowsers() {
    try {
        const data = await apiFetch('/browsers');
        const list = document.getElementById('browserList');

        if (data.browsers.length === 0) {
            list.innerHTML = '<li class="browser-item" style="color: #666;">No browsers available</li>';
            return;
        }

        const sortedBrowsers = data.browsers.sort((a, b) => a.browser_id.localeCompare(b.browser_id, undefined, { numeric: true }));

        list.innerHTML = sortedBrowsers.map(b => `
            <li class="browser-item ${selectedBrowser === b.browser_id ? 'active' : ''}"
                onclick="selectBrowser('${b.browser_id}')"
                data-browser-id="${b.browser_id}">
                <span class="toggle-btn ${b.is_enabled ? 'on' : 'off'}" 
                      onclick="event.stopPropagation(); toggleBrowserEnabled('${b.browser_id}', ${!b.is_enabled})"
                      title="${b.is_enabled ? 'Enabled (Click to Disable)' : 'Disabled (Click to Enable)'}">
                    ${b.is_enabled ? '✓' : ''}
                </span>
                <span>${b.browser_id}</span>
                <span class="status ${b.status}"></span>
                <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    ${escapeHtml(b.account_name)}
                </span>
            </li>
        `).join('');

    } catch (e) {
        showToast('Failed to load browsers: ' + e.message, 'error');
    }
}

// 切换浏览器启用状态
async function toggleBrowserEnabled(id, enabled) {
    try {
        await apiFetch(`/browsers/${id}`, {
            method: 'PUT',
            body: { is_enabled: enabled }
        });
        showToast(`Browser ${id} ${enabled ? 'Enabled' : 'Disabled'}`, 'success');
        loadBrowsers();
    } catch (e) {
        showToast('Action failed: ' + e.message, 'error');
    }
}

// 选择浏览器
async function selectBrowser(browserId) {
    selectedBrowser = browserId;
    selectedTab = null;

    // 更新 UI
    document.querySelectorAll('.browser-item').forEach(el => {
        el.classList.toggle('active', el.dataset.browserId === browserId);
    });

    // 加载标签页
    await loadTabs(browserId);
}

// 加载标签页列表
async function loadTabs(browserId) {
    try {
        const data = await apiFetch(`/browsers/${browserId}/tabs`);
        const list = document.getElementById('tabList');

        if (data.tabs.length === 0) {
            list.innerHTML = '<li class="tab-item" style="color: #666;">No tabs available</li>';
            return;
        }

        list.innerHTML = data.tabs.map(t => `
            <li class="tab-item ${selectedTab === t.tab_id ? 'active' : ''}"
                onclick="selectTab(${t.tab_id})"
                data-tab-id="${t.tab_id}">
                <span class="status ${t.status}"></span>
                Tab ${t.tab_id} 
                ${t.status === 'busy' && t.activity ? `<small style="opacity:0.7">(${escapeHtml(t.activity)})</small>` : ''}
                ${t.status === 'sleep' ? `<small style="opacity:0.7; color: #ff6b6b"> (Sleep until ${formatTime(t.sleep_until)})</small>` : ''}
                <span class="model-badge">${t.model}</span>
            </li>
        `).join('');

    } catch (e) {
        showToast('Failed to load tabs: ' + e.message, 'error');
    }
}

// 选择标签页
async function selectTab(tabId) {
    selectedTab = tabId;

    // 更新 UI
    document.querySelectorAll('.tab-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.tabId) === tabId);
    });

    // 刷新截图
    await refreshScreenshot();
}

// 刷新截图
async function refreshScreenshot() {
    if (!selectedBrowser || selectedTab === null) {
        showToast('Please select a browser and tab first', 'error');
        return;
    }

    if (isLoading) return;
    isLoading = true;

    const wrapper = document.getElementById('screenshotWrapper');
    const placeholder = document.getElementById('placeholder');
    const img = document.getElementById('screenshot');

    wrapper.classList.add('loading');

    try {
        const response = await fetch(
            `/api/admin/browsers/${selectedBrowser}/tabs/${selectedTab}/screenshot?quality=50&_t=${Date.now()}`
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // 获取视口尺寸
        viewportWidth = parseInt(response.headers.get('X-Viewport-Width') || '1280');
        viewportHeight = parseInt(response.headers.get('X-Viewport-Height') || '900');
        document.getElementById('viewportInfo').textContent = `${viewportWidth} x ${viewportHeight}`;

        // 显示图片
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        img.onload = () => {
            URL.revokeObjectURL(img.src);
            wrapper.classList.remove('loading');
            isLoading = false;
        };

        img.src = url;
        placeholder.style.display = 'none';
        wrapper.style.display = 'inline-block';

        document.getElementById('statusTime').textContent = `Updated: ${new Date().toLocaleTimeString()}`;

    } catch (e) {
        showToast('Screenshot failed: ' + e.message, 'error');
        wrapper.classList.remove('loading');
        isLoading = false;
    }
}

// 导航到指定 URL
async function navigateTo() {
    const urlInput = document.getElementById('urlInput');
    const url = urlInput.value.trim();

    if (!url) {
        showToast('Please enter a URL', 'error');
        return;
    }

    if (!selectedBrowser || selectedTab === null) {
        showToast('Please select a browser and tab first', 'error');
        return;
    }

    try {
        showToast('Navigating...', '');

        const result = await apiFetch(
            `/browsers/${selectedBrowser}/tabs/${selectedTab}/navigate`,
            {
                method: 'POST',
                body: { url: url }
            }
        );

        document.getElementById('statusLastAction').textContent = `Navigated to: ${result.title || url}`;
        urlInput.value = result.url; // 更新为实际 URL
        showToast('Navigation successful', 'success');
        await refreshScreenshot();

    } catch (e) {
        showToast('Navigation failed: ' + e.message, 'error');
    }
}

async function clearLastClick() {
    if (!selectedBrowser || selectedTab === null) return;
    await refreshScreenshot();
}

async function runCommand() {
    const inputEl = document.getElementById('cmdInput');
    const cmd = inputEl.value.trim();
    if (!cmd) return;

    if (!selectedBrowser || selectedTab === null) {
        showToast('Please select a browser and tab first', 'error');
        return;
    }

    const btn = event.target.tagName === 'BUTTON' ? event.target : event.target.closest('button');
    const originalText = btn ? btn.textContent : 'Run';
    if (btn) { btn.textContent = 'Running...'; btn.disabled = true; }

    try {
        const result = await apiFetch(`/browsers/${selectedBrowser}/tabs/${selectedTab}/command`, {
            method: 'POST',
            body: { cmd: cmd }
        });

        if (result.success) {
            showToast('Command executed', 'success');
            inputEl.value = '';
            if (autoRefresh) setTimeout(refreshScreenshot, 500);
        } else {
            showToast('Failed: ' + (result.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('API error: ' + e.message, 'error');
    } finally {
        if (btn) { btn.textContent = originalText; btn.disabled = false; }
    }
}

// 执行 JavaScript
async function runJS() {
    const jsCode = document.getElementById('jsInput').value.trim();
    const resultEl = document.getElementById('jsResult');

    if (!jsCode) {
        showToast('Please enter JS code', 'error');
        return;
    }

    if (!selectedBrowser || selectedTab === null) {
        showToast('Please select a browser and tab first', 'error');
        return;
    }

    try {
        const result = await apiFetch(`/browsers/${selectedBrowser}/tabs/${selectedTab}/command`, {
            method: 'POST',
            body: { cmd: `eval "${jsCode.replace(/"/g, '\\"')}"` }
        });

        resultEl.style.display = 'block';

        if (result.success) {
            const val = result.result;
            resultEl.style.color = '#4ade80';
            resultEl.textContent = val !== undefined ? JSON.stringify(val, null, 2) : '(undefined)';
            showToast('JS executed', 'success');
            if (autoRefresh) setTimeout(refreshScreenshot, 300);
        } else {
            resultEl.style.color = '#f87171';
            resultEl.textContent = 'Error: ' + (result.error || 'Unknown');
            showToast('JS failed', 'error');
        }
    } catch (e) {
        resultEl.style.display = 'block';
        resultEl.style.color = '#f87171';
        resultEl.textContent = 'API Error: ' + e.message;
        showToast('API error', 'error');
    }
}

// 后退
async function goBack() {
    if (!selectedBrowser || selectedTab === null) return;
    try {
        await sendKey('Alt+ArrowLeft');
    } catch (e) {
        showToast('Back navigation attempted', '');
    }
}

// 前进
async function goForward() {
    if (!selectedBrowser || selectedTab === null) return;
    try {
        await sendKey('Alt+ArrowRight');
    } catch (e) {
        showToast('Forward navigation attempted', '');
    }
}

// 设置截图交互事件
function setupScreenshotEvents() {
    const img = document.getElementById('screenshot');
    const cursor = document.getElementById('cursorIndicator');

    function getRelativeCoords(e) {
        const rect = img.getBoundingClientRect();
        const relX = (e.clientX - rect.left) / rect.width;
        const relY = (e.clientY - rect.top) / rect.height;

        return {
            x: relX,
            y: relY,
            actualX: Math.round(relX * viewportWidth),
            actualY: Math.round(relY * viewportHeight)
        };
    }

    img.addEventListener('mousemove', (e) => {
        const coords = getRelativeCoords(e);
        document.getElementById('statusCoords').textContent = `Coords: ${coords.actualX}, ${coords.actualY}`;

        const rect = img.getBoundingClientRect();
        cursor.style.display = 'block';
        cursor.style.left = (e.clientX - rect.left) + 'px';
        cursor.style.top = (e.clientY - rect.top) + 'px';
    });

    img.addEventListener('mouseleave', () => {
        cursor.style.display = 'none';
    });

    img.addEventListener('click', async (e) => {
        e.preventDefault();
        const coords = getRelativeCoords(e);
        await sendMouseAction('click', coords.x, coords.y);
    });

    img.addEventListener('contextmenu', async (e) => {
        e.preventDefault();
        const coords = getRelativeCoords(e);
        await sendMouseAction('click', coords.x, coords.y, 'right');
    });

    img.addEventListener('wheel', async (e) => {
        e.preventDefault();
        const coords = getRelativeCoords(e);
        await sendMouseAction('scroll', coords.x, coords.y, 'left', e.deltaY);
    });
}

// 发送鼠标动作
async function sendMouseAction(action, x, y, button = 'left', scrollDelta = 0) {
    if (!selectedBrowser || selectedTab === null) return;

    try {
        const result = await apiFetch(
            `/browsers/${selectedBrowser}/tabs/${selectedTab}/mouse`,
            {
                method: 'POST',
                body: {
                    action: action,
                    x: x,
                    y: y,
                    button: button,
                    scroll_delta: scrollDelta
                }
            }
        );

        document.getElementById('statusLastAction').textContent =
            `Last action: ${action} at (${Math.round(result.x)}, ${Math.round(result.y)})`;

        if (autoRefresh && action === 'click') {
            setTimeout(refreshScreenshot, 300);
        }
    } catch (e) {
        showToast('Mouse action failed: ' + e.message, 'error');
    }
}

// 发送键盘按键
async function sendKey(key) {
    if (!selectedBrowser || selectedTab === null) {
        showToast('Please select a browser and tab first', 'error');
        return;
    }

    try {
        await apiFetch(
            `/browsers/${selectedBrowser}/tabs/${selectedTab}/keyboard`,
            {
                method: 'POST',
                body: {
                    action: 'press',
                    key: key
                }
            }
        );

        document.getElementById('statusLastAction').textContent = `Last action: press ${key}`;
        if (autoRefresh) {
            setTimeout(refreshScreenshot, 300);
        }
    } catch (e) {
        showToast('Key press failed: ' + e.message, 'error');
    }
}

// 发送输入文本
async function sendTypedText() {
    const input = document.getElementById('keyboardInput');
    const text = input.value;

    if (!text) {
        hideKeyboardModal();
        return;
    }

    if (!selectedBrowser || selectedTab === null) {
        showToast('Please select a browser and tab first', 'error');
        return;
    }

    try {
        await apiFetch(
            `/browsers/${selectedBrowser}/tabs/${selectedTab}/keyboard`,
            {
                method: 'POST',
                body: {
                    action: 'type',
                    text: text
                }
            }
        );

        document.getElementById('statusLastAction').textContent = `Last action: typed "${text.substring(0, 20)}..."`;
        hideKeyboardModal();
        input.value = '';
        if (autoRefresh) {
            setTimeout(refreshScreenshot, 300);
        }
    } catch (e) {
        showToast('Type failed: ' + e.message, 'error');
    }
}

// 键盘快捷键
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            if (e.key === 'Enter' && document.getElementById('keyboardModal').classList.contains('show')) {
                e.preventDefault();
                sendTypedText();
            }
            if (e.key === 'Escape') {
                hideKeyboardModal();
            }
            return;
        }

        if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            refreshScreenshot();
        }

        if (e.key === 't' || e.key === 'T') {
            e.preventDefault();
            showKeyboardModal();
        }

        if (e.key === 'Escape') {
            sendKey('Escape');
        }
    });
}

function toggleAutoRefresh() {
    autoRefresh = !autoRefresh;
    document.getElementById('autoRefreshBtn').textContent = `Auto: ${autoRefresh ? 'ON' : 'OFF'}`;
}

function showKeyboardModal() {
    document.getElementById('keyboardModal').classList.add('show');
    document.getElementById('keyboardInput').focus();
}

function hideKeyboardModal() {
    document.getElementById('keyboardModal').classList.remove('show');
}

document.getElementById('keyboardModal').addEventListener('click', (e) => {
    if (e.target.id === 'keyboardModal') {
        hideKeyboardModal();
    }
});
