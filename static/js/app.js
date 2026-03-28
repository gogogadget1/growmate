/**
 * GrowMate – Haupt-Applikationslogik
 * SPA-Navigation, API-Client, Dashboard-Rendering, Toast-System
 */

// ─── Globaler State ─────────────────────────────────────────────────
const GrowMate = {
    currentPage: 'dashboard',
    refreshInterval: null,
    AUTO_REFRESH_MS: 30000,
};

// ─── API Client ─────────────────────────────────────────────────────

const API = {
    async get(url) {
        try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } catch (err) {
            console.error(`API GET ${url}:`, err);
            return { success: false, message: err.message };
        }
    },

    async post(url, data) {
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } catch (err) {
            console.error(`API POST ${url}:`, err);
            return { success: false, message: err.message };
        }
    },

    async put(url, data) {
        try {
            const res = await fetch(url, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } catch (err) {
            console.error(`API PUT ${url}:`, err);
            return { success: false, message: err.message };
        }
    },

    async delete(url) {
        try {
            const res = await fetch(url, { method: 'DELETE' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } catch (err) {
            console.error(`API DELETE ${url}:`, err);
            return { success: false, message: err.message };
        }
    },
};

// ─── Toast Notifications ────────────────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─── SPA Navigation ─────────────────────────────────────────────────

function navigateTo(pageName) {
    // Seiten umschalten
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(`page-${pageName}`);
    if (page) page.classList.add('active');

    // Nav-Links aktualisieren
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const link = document.querySelector(`.nav-link[data-page="${pageName}"]`);
    if (link) link.classList.add('active');

    // Sidebar schließen (mobile)
    document.getElementById('sidebar').classList.remove('open');

    GrowMate.currentPage = pageName;

    // Seitenspezifische Init
    switch (pageName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'history':
            loadHistoryCharts();
            break;
        case 'devices':
            loadDevices();
            break;
        case 'diary':
            loadDiary();
            break;
        case 'settings':
            loadSettings();
            break;
        case 'advisor':
            if (typeof loadAdvisor === 'function') {
                loadAdvisor();
                if (typeof startAdvisorPolling === 'function') startAdvisorPolling();
            }
            break;
        case 'analyse':
            if (typeof loadAnalyse === 'function') {
                loadAnalyse();
            }
            break;
    }
}

// ─── Dashboard ──────────────────────────────────────────────────────

async function loadDashboard() {
    await Promise.all([
        checkSystemStatus(),
        loadSensorCards(),
        loadEnergyCards(),
        loadDashboardCharts(),
        loadDiaryPreview(),
    ]);
}

async function checkSystemStatus() {
    const banner = document.getElementById('global-error-banner');
    const textEl = document.getElementById('global-error-text');
    if (!banner || !textEl) return;

    // Parallel system and advisor checks
    updateAdvisorStatus();

    try {
        const res = await API.get('/api/status');
        if (res.success && res.status === 'error' && res.issues.length > 0) {
            banner.style.display = 'block';
            let html = '<div style="margin-bottom: 5px;"><strong>Achtung: Einige Sensoren sind offline oder liefern keine Daten!</strong></div><ul style="margin: 0; padding-left: 20px; font-size: 0.9em; opacity: 0.9;">';
            res.issues.forEach(issue => {
                html += `<li>${escapeHtml(issue.device)}: ${escapeHtml(issue.message)}</li>`;
            });
            html += '</ul>';
            textEl.innerHTML = html;
        } else {
            banner.style.display = 'none';
        }
    } catch (e) {
        banner.style.display = 'block';
        textEl.innerHTML = '<strong>Achtung:</strong> Die Hintergrund-Dienste sind nicht erreichbar.';
    }
}

async function updateAdvisorStatus() {
    const navAdvisor = document.getElementById('nav-advisor');
    const diaryAlert = document.getElementById('diary-advisor-alert');
    if (!navAdvisor) return;

    try {
        const res = await API.get('/api/analysis');
        if (res.success && res.data && res.data.length > 0) {
            // Wenn wir NICHT auf der Ratgeber-Seite sind, zeige Indikator
            if (GrowMate.currentPage !== 'advisor') {
                navAdvisor.classList.add('has-new-tips');
                navAdvisor.querySelector('.nav-icon').classList.add('advisor-pulse');
                if (diaryAlert) diaryAlert.style.display = 'block';
            } else {
                // Wir sind drauf -> Verstecken
                navAdvisor.classList.remove('has-new-tips');
                navAdvisor.querySelector('.nav-icon').classList.remove('advisor-pulse');
                if (diaryAlert) diaryAlert.style.display = 'none';
            }
        } else {
            navAdvisor.classList.remove('has-new-tips');
            navAdvisor.querySelector('.nav-icon').classList.remove('advisor-pulse');
            if (diaryAlert) diaryAlert.style.display = 'none';
        }
    } catch (e) {
        console.error("Advisor Status Error:", e);
    }
}

async function loadSensorCards() {
    const container = document.getElementById('sensor-cards');
    const res = await API.get('/api/sensors/current');

    if (res.success && res.data && res.data.length > 0) {
        container.innerHTML = res.data.map(sensor => `
            <div class="card glass sensor-card">
                <div class="card-body">
                    <div class="sensor-name">
                        ${sensor.sensor_type === 'govee_ble' ? '📡' : '📱'} ${sensor.sensor_name}
                    </div>
                    <div class="sensor-values">
                        <div class="sensor-value">
                            <span class="value-label">Temperatur</span>
                            <span class="value-number temp">
                                ${sensor.temperature !== null ? sensor.temperature.toFixed(1) : '—'}
                                <span class="value-unit">°C</span>
                            </span>
                        </div>
                        <div class="sensor-value">
                            <span class="value-label">Feuchtigkeit</span>
                            <span class="value-number humidity">
                                ${sensor.humidity !== null ? sensor.humidity.toFixed(1) : '—'}
                                <span class="value-unit">%</span>
                            </span>
                        </div>
                    </div>
                    <div class="sensor-meta">
                        ${sensor.battery !== null ? `<span>🔋 ${sensor.battery}%</span>` : '<span></span>'}
                        <span>${formatTimestamp(sensor.timestamp)}</span>
                    </div>
                </div>
            </div>
        `).join('');
    } else {
        container.innerHTML = `
            <div class="card glass">
                <div class="card-body center">
                    <div class="empty-state">
                        <span class="empty-icon">📡</span>
                        <span class="empty-text">Noch keine Sensordaten vorhanden. Starte einen Scan oder warte auf das nächste Polling.</span>
                    </div>
                </div>
            </div>
        `;
    }
}

async function loadEnergyCards() {
    const container = document.getElementById('energy-cards');
    const res = await API.get('/api/energy/current');

    if (res.success && res.data && res.data.length > 0) {
        const colors = ['#2196f3', '#4caf50', '#ff9800', '#9c27b0', '#e91e63'];
        
        container.innerHTML = res.data.map((device, index) => {
            const color = colors[index % colors.length];
            return `
            <div class="card glass sensor-card energy-card" style="border-top: 4px solid ${color};">
                <div class="card-body">
                    <div class="sensor-name" style="color: ${color};">⚡ ${device.device_name}</div>
                    <div class="sensor-values">
                        <div class="sensor-value">
                            <span class="value-label">Aktuell</span>
                            <span class="value-number power">
                                ${device.power_w !== null ? device.power_w.toFixed(1) : '0.0'}
                                <span class="value-unit">W</span>
                            </span>
                        </div>
                        <div class="sensor-value">
                            <span class="value-label">Heute</span>
                            <span class="value-number power">
                                ${device.energy_today_wh !== null ? (device.energy_today_wh / 1000).toFixed(2) : '0.00'}
                                <span class="value-unit">kWh</span>
                            </span>
                        </div>
                    </div>
                    <div class="sensor-meta">
                        <span>📊 ${device.energy_month_wh !== null ? (device.energy_month_wh / 1000).toFixed(2) + ' kWh/Monat' : '0.00 kWh/Monat'}</span>
                        <span>${formatTimestamp(device.timestamp)}</span>
                    </div>
                </div>
            </div>
        `;
        }).join('');
    } else {
        container.innerHTML = `
            <div class="card glass">
                <div class="card-body center">
                    <div class="empty-state">
                        <span class="empty-icon">⚡</span>
                        <span class="empty-text">Keine Energiedaten vorhanden. Füge Tapo P110 Steckdosen hinzu.</span>
                    </div>
                </div>
            </div>
        `;
    }
}

async function loadDiaryPreview() {
    const container = document.getElementById('diary-preview');
    const res = await API.get('/api/diary?limit=3');

    if (res.success && res.data && res.data.length > 0) {
        container.innerHTML = res.data.map(entry => `
            <div class="card glass diary-entry">
                <div class="diary-entry-header">
                    <span class="diary-entry-type type-${entry.entry_type.toLowerCase()}">${getTypeEmoji(entry.entry_type)} ${entry.entry_type}</span>
                    <span class="diary-entry-date">${formatDate(entry.entry_date)}</span>
                </div>
                <div class="diary-entry-title">${escapeHtml(entry.title)}</div>
                ${entry.content ? `<div class="diary-entry-content">${escapeHtml(entry.content).substring(0, 150)}${entry.content.length > 150 ? '...' : ''}</div>` : ''}
            </div>
        `).join('');
    } else {
        container.innerHTML = `
            <div class="card glass">
                <div class="card-body center">
                    <div class="empty-state">
                        <span class="empty-icon">📓</span>
                        <span class="empty-text">Noch keine Tagebucheinträge. Erstelle deinen ersten Eintrag!</span>
                    </div>
                </div>
            </div>
        `;
    }
}

// ─── Settings ───────────────────────────────────────────────────────

async function loadSettings() {
    const res = await API.get('/api/config');
    if (res.success) {
        const config = res.data;
        document.getElementById('setting-interval').value = config.polling_interval_minutes || 5;
        document.getElementById('setting-ble-duration').value = config.ble_scan_duration_seconds || 10;
        document.getElementById('setting-tapo-email').value = config.tapo_email || '';
        document.getElementById('setting-tapo-password').value = config.tapo_password ? '••••••••' : '';
        renderAutomations(config.automations || []);
    }

    // Scheduler Status
    const status = await API.get('/api/scheduler/status');
    if (status.success) {
        const nextPoll = document.getElementById('next-poll-time');
        if (status.data.next_run) {
            nextPoll.textContent = formatTimestamp(status.data.next_run);
        } else {
            nextPoll.textContent = 'Nicht aktiv';
        }

        const indicator = document.getElementById('scheduler-indicator');
        const dot = indicator.querySelector('.status-dot');
        const text = indicator.querySelector('.status-text');
        if (status.data.running) {
            dot.classList.remove('inactive');
            text.textContent = 'Polling aktiv';
        } else {
            dot.classList.add('inactive');
            text.textContent = 'Polling inaktiv';
        }
    }
}

async function saveSettings() {
    // Determine which automations are on the page
    const autoElements = document.querySelectorAll('.automation-item');
    const automations = [];
    autoElements.forEach(el => {
        automations.push({
            enabled: el.querySelector('.auto-enabled').checked,
            trigger: {
                device_name: el.querySelector('.auto-trigger-device').value.trim(),
                state: el.querySelector('.auto-trigger-state').value
            },
            actions: [{
                device_name: el.querySelector('.auto-action-device').value.trim(),
                action: el.querySelector('.auto-action-cmd').value
            }]
        });
    });

    const data = {
        polling_interval_minutes: parseInt(document.getElementById('setting-interval').value),
        ble_scan_duration_seconds: parseInt(document.getElementById('setting-ble-duration').value),
        tapo_email: document.getElementById('setting-tapo-email').value,
        tapo_password: document.getElementById('setting-tapo-password').value,
        automations: automations
    };

    const res = await API.put('/api/config', data);
    if (res.success) {
        showToast('✅ Einstellungen gespeichert', 'success');
        loadSettings(); // Reload to refresh automations list
    } else {
        showToast('❌ Fehler beim Speichern', 'error');
    }
}

async function testTapo() {
    const btn = document.getElementById('btn-test-tapo');
    const email = document.getElementById('setting-tapo-email').value;
    const pwd = document.getElementById('setting-tapo-password').value;
    
    if (!email || !pwd || pwd === '••••••••') {
        showToast('Bitte gültige E-Mail und Passwort eingeben', 'error');
        return;
    }
    
    btn.disabled = true;
    btn.textContent = '⏳ Teste...';
    
    const res = await API.post('/api/config/test-tapo', {
        tapo_email: email, tapo_password: pwd
    });
    
    if (res.success) {
        showToast('✅ Tapo Zugangsdaten sind gültig', 'success');
    } else {
        showToast('❌ Tapo Login fehlgeschlagen: ' + res.message, 'error');
    }
    
    btn.disabled = false;
    btn.textContent = '🔄 Zugangsdaten testen';
}

async function runDiagnostics() {
    const btn = document.getElementById('btn-run-diagnostics');
    const container = document.getElementById('diagnostics-results');
    
    container.style.display = 'block';
    container.innerHTML = '<div class="center"><div class="spinner"></div><p>Starte Diagnose (Dauer: ca. 5-10 Sekunden)...</p></div>';
    btn.disabled = true;
    
    try {
        const res = await API.get('/api/diagnostics');
        if (res.success && res.diagnostics) {
            const bt = res.diagnostics.bluetooth;
            const tapos = res.diagnostics.tapo;
            
            let html = `<h3>Bluetooth Status: ${bt.status === 'ok' ? '✅' : (bt.status === 'warning' ? '⚠️' : '❌')}</h3>`;
            html += `<p>${bt.message}</p>`;
            
            if (tapos.length > 0) {
                html += `<h3 style="margin-top: 15px;">Tapo & WLAN Geräte:</h3><ul style="list-style: none; padding: 0;">`;
                tapos.forEach(t => {
                    const icon = t.status === 'ok' ? '✅' : (t.status === 'warning' ? '⚠️' : '❌');
                    html += `<li style="margin-bottom: 10px; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 5px;">
                        <strong>${icon} ${t.name} (${t.ip})</strong><br>
                        <span style="color: ${t.status === 'error' ? 'var(--danger)' : 'inherit'};">${t.message}</span>
                    </li>`;
                });
                html += `</ul>`;
            } else {
                html += `<p class="text-muted" style="margin-top: 15px;">Keine Tapo-Geräte zur Diagnose konfiguriert.</p>`;
            }
            
            container.innerHTML = html;
        } else {
            container.innerHTML = `<p class="text-danger">❌ Fehler beim Ausführen der Diagnose.</p>`;
        }
    } catch(err) {
        container.innerHTML = `<p class="text-danger">❌ Fehler: API nicht erreichbar.</p>`;
    }
    
    btn.disabled = false;
}

function renderAutomations(automations) {
    const container = document.getElementById('automations-container');
    container.innerHTML = '';
    
    if (!automations || automations.length === 0) {
        container.innerHTML = '<p class="text-muted">Keine Automatisierungen eingerichtet.</p>';
        return;
    }
    
    automations.forEach((auto, idx) => {
        addAutomationRow(auto, idx);
    });
}

function addAutomationRow(auto = null, idx = Date.now()) {
    const container = document.getElementById('automations-container');
    
    // Remove "No automations" text if exists
    if (container.querySelector('.text-muted')) {
        container.innerHTML = '';
    }
    
    const t_dev = auto ? auto.trigger.device_name : '';
    const t_state = auto ? auto.trigger.state : 'leak';
    const a_dev = auto ? auto.actions[0].device_name : '';
    const a_cmd = auto ? auto.actions[0].action : 'off';
    const enabled = auto ? auto.enabled : true;
    
    const html = `
        <div class="automation-item" style="border: 1px solid rgba(255,255,255,0.1); padding: 15px; margin-bottom: 15px; border-radius: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <strong>Regel</strong>
                <label class="toggle-switch">
                    <input type="checkbox" class="auto-enabled" ${enabled ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div style="display: flex; gap: 10px; margin-bottom: 10px; flex-wrap: wrap;">
                <span>WENN Sensor</span>
                <input type="text" class="form-control auto-trigger-device" placeholder="Hub Name - T300 Name" value="${escapeHtml(t_dev)}" style="flex: 1; min-width: 150px;">
                <span>meldet</span>
                <select class="form-control auto-trigger-state" style="width: 120px;">
                    <option value="leak" ${t_state === 'leak' ? 'selected' : ''}>Wasserleck</option>
                    <option value="dry" ${t_state === 'dry' ? 'selected' : ''}>Trocken</option>
                </select>
            </div>
            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                <span>DANN schalte Steckdose</span>
                <input type="text" class="form-control auto-action-device" placeholder="Steckdosen Name" value="${escapeHtml(a_dev)}" style="flex: 1; min-width: 150px;">
                <select class="form-control auto-action-cmd" style="width: 100px;">
                    <option value="off" ${a_cmd === 'off' ? 'selected' : ''}>Aus</option>
                    <option value="on" ${a_cmd === 'on' ? 'selected' : ''}>Ein</option>
                </select>
                <button class="btn btn-danger btn-icon" onclick="this.closest('.automation-item').remove()" title="Löschen">🗑️</button>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', html);
}

// ─── Manual Poll ────────────────────────────────────────────────────

async function manualPoll() {
    const btn = document.getElementById('btn-manual-poll');
    btn.disabled = true;
    btn.textContent = '⏳ Polling läuft...';
    showToast('🔄 Sensordaten werden abgefragt...', 'info');

    const res = await API.post('/api/poll');
    if (res.success) {
        showToast('✅ Polling abgeschlossen', 'success');
        loadDashboard();
    } else {
        showToast('❌ Polling fehlgeschlagen: ' + res.message, 'error');
    }

    btn.disabled = false;
    btn.textContent = '🔄 Jetzt aktualisieren';
}

// ─── Helpers ────────────────────────────────────────────────────────

function formatTimestamp(ts) {
    if (!ts) return '—';
    try {
        const d = new Date(ts);
        if (isNaN(d.getTime())) return ts;
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        const time = d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
        return isToday ? `Heute ${time}` : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }) + ` ${time}`;
    } catch {
        return ts;
    }
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: 'long', year: 'numeric' });
    } catch {
        return dateStr;
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function getTypeEmoji(type) {
    const emojis = {
        'Düngung': '🧪',
        'Bewässerung': '💧',
        'Messung': '📏',
        'Umtopfen': '🪴',
        'Beschneidung': '✂️',
        'Schädlinge': '🐛',
        'Sonstiges': '📝',
        'Keimung': '🌱',
        'Sämling': '🌿',
        'Vegetativ': '🍀',
        'Blüte': '🌸',
        'Ernte': '✂️',
    };
    return emojis[type] || '📝';
}

// ─── Auto Refresh ───────────────────────────────────────────────────

function startAutoRefresh() {
    if (GrowMate.refreshInterval) clearInterval(GrowMate.refreshInterval);
    
    // Führe initial einmal checkSystemStatus aus, auch wenn nicht auf dashboard
    checkSystemStatus();

    GrowMate.refreshInterval = setInterval(() => {
        checkSystemStatus(); // Check errors globally on all pages
        if (GrowMate.currentPage === 'dashboard') {
            loadSensorCards();
            loadEnergyCards();
        }
    }, GrowMate.AUTO_REFRESH_MS);
}

// ─── Event Listeners ────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Navigation
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(link.dataset.page);
        });
    });

    // Link-Buttons (z.B. "Alle anzeigen" im Dashboard)
    document.querySelectorAll('.link-btn[data-page]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(btn.dataset.page);
        });
    });

    // Hash-Navigation
    window.addEventListener('hashchange', () => {
        const page = window.location.hash.replace('#', '') || 'dashboard';
        navigateTo(page);
    });

    // Mobile Menu
    document.getElementById('menu-toggle').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('open');
    });

    // Klick außerhalb der Sidebar schließt sie
    document.getElementById('main-content').addEventListener('click', () => {
        document.getElementById('sidebar').classList.remove('open');
    });

    // Manual Poll
    document.getElementById('btn-manual-poll').addEventListener('click', manualPoll);
    document.getElementById('mobile-refresh-btn').addEventListener('click', manualPoll);

    // Settings
    document.getElementById('btn-test-tapo').addEventListener('click', testTapo);
    document.getElementById('btn-run-diagnostics').addEventListener('click', runDiagnostics);
    document.getElementById('btn-add-automation').addEventListener('click', () => addAutomationRow());
    document.getElementById('btn-save-settings').addEventListener('click', saveSettings);

    // Backup & Restore
    document.getElementById('btn-admin-backup').addEventListener('click', async () => {
        showToast('📦 Backup wird vorbereitet...', 'info');
        window.location.href = '/api/admin/backup';
    });

    const restoreFile = document.getElementById('restore-file');
    const restoreBtn = document.getElementById('btn-admin-restore');
    const restoreFilename = document.getElementById('restore-filename');

    restoreFile.addEventListener('change', () => {
        if (restoreFile.files.length > 0) {
            restoreFilename.textContent = restoreFile.files[0].name;
            restoreBtn.disabled = false;
        } else {
            restoreFilename.textContent = 'Keine Datei gewählt';
            restoreBtn.disabled = true;
        }
    });

    restoreBtn.addEventListener('click', async () => {
        if (restoreFile.files.length === 0) return;
        
        if (!confirm('ACHTUNG: Dies überschreibt deine aktuellen Datenbanken und Einstellungen. Fortfahren?')) {
            return;
        }

        const formData = new FormData();
        formData.append('file', restoreFile.files[0]);

        restoreBtn.disabled = true;
        restoreBtn.textContent = '⏳ Lädt...';
        showToast('⏫ Restore läuft...', 'info');

        try {
            const res = await fetch('/api/admin/restore', {
                method: 'POST',
                body: formData
            });
            const result = await res.json();
            if (result.success) {
                showToast('✅ Restore erfolgreich! Die Seite wird neu geladen.', 'success');
                setTimeout(() => window.location.reload(), 2000);
            } else {
                showToast('❌ Restore fehlgeschlagen: ' + result.message, 'error');
            }
        } catch (err) {
            showToast('❌ Netzwerkfehler beim Restore', 'error');
        } finally {
            restoreBtn.disabled = false;
            restoreBtn.textContent = '⏫ Restore starten';
        }
    });

    // Initiale Seite laden
    const initialPage = window.location.hash.replace('#', '') || 'dashboard';
    navigateTo(initialPage);

    // Auto-Refresh starten
    startAutoRefresh();
});
