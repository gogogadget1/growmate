/**
 * GrowMate – Geräte-Verwaltung
 * Steckdosen ein-/ausschalten, Geräte hinzufügen/entfernen.
 */

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ─── Phase 1: Kategorien & Typen ────────────────────────────────────

const DEVICE_CATEGORIES = {
    power:      { label: 'Strom',     icon: '⚡', types: ['tapo_plug', 'shelly_device', 'smart_outlet', 'timer_plug'] },
    sensor:     { label: 'Sensoren',  icon: '🌡️', types: ['govee_ble', 'tapo_sensor', 'mqtt_device', 'co2_sensor', 'soil_sensor', 'water_temp', 'ph_sensor', 'ec_sensor', 'leak_sensor'] },
    light:      { label: 'Licht',     icon: '💡', types: ['tapo_plug', 'grow_light', 'hps_light', 'led_dimmer'] },
    ventilation:{ label: 'Lüftung',   icon: '💨', types: ['tapo_plug', 'inline_fan', 'circulation_fan', 'fan_controller'] },
    irrigation: { label: 'Wasser',    icon: '💧', types: ['tapo_plug', 'water_pump', 'dosing_pump', 'drain_pump'] },
    climate:    { label: 'Klima',     icon: '🌬️', types: ['tapo_plug', 'dehumidifier', 'humidifier', 'ac_unit', 'heat_mat', 'co2_generator'] },
    hub:        { label: 'Hubs',      icon: '🔗', types: ['hub', 'tapo_hub', 'zigbee_hub'] },
};

function getCategoryForType(type, explicitCategory) {
    // Explizite Kategorie vom Backend hat immer Vorrang
    if (explicitCategory && DEVICE_CATEGORIES[explicitCategory]) {
        return explicitCategory;
    }
    if (!type) return 'power';
    for (const [catKey, cat] of Object.entries(DEVICE_CATEGORIES)) {
        if (cat.types.includes(type)) return catKey;
    }
    return 'power';
}

// ─── Geräte laden & Render-Logik ────────────────────────────────────

class TentStorage {
    static async getAll() {
        try {
            const res = await API.get('/api/tents');
            return res.success ? res.data : [];
        } catch(e) { return []; }
    }
    static async save(tent) {
        return await API.post('/api/tents', tent);
    }
    static async remove(id) {
        return await API.delete(`/api/tents/${id}`);
    }
}

let allDevices = [];
let allTents = [];
let currentCategory = 'all';
let currentDeviceView = 'tents'; // 'tents' oder 'all'
let selectedUnassignedDevices = []; // GLOBAL STATE FOR SELECTION


async function loadDevices() {
    const container = document.getElementById('device-cards');
    if (!container) return;

    if (allDevices.length === 0) {
        container.innerHTML = `
            <div class="glass card-body skeleton" style="height: 180px;"></div>
            <div class="glass card-body skeleton" style="height: 180px;"></div>
            <div class="glass card-body skeleton" style="height: 180px;"></div>
        `;
    }

    try {
        const [res, configsRes, tentsRes] = await Promise.all([
            API.get('/api/devices'),
            API.get('/api/devices/config'),
            TentStorage.getAll()
        ]);

        if (!res.success) {
            showToast('Fehler beim Laden der Geräte', 'error');
            return;
        }

        allDevices = res.data || [];
        allTents = tentsRes || [];
        const configs = {};
        if (configsRes.success) {
            configsRes.data.forEach(c => configs[c.device_name] = c);
        }

        if (Array.isArray(allDevices)) {
            allDevices.forEach(d => {
                if (!d) return;
                d.config = configs[d.name] || {};
                // Backend-Kategorie hat Vorrang vor Type-Ableitung
                d.category = getCategoryForType(d.type, d.category);
                // Assign tent_id safely handling missing/None
                d.tent_id = d.tent_id || null;
            });
        }

        renderDeviceUI();
        updateStatusBar();
        if(typeof updateGlobalTentStats === 'function') updateGlobalTentStats();
        console.log('Devices loaded successfully:', allDevices.length, 'Tents:', allTents.length);
        updateCategoryCounts();

    } catch (err) {
        console.error('CRITICAL Device Load Error:', err);
        container.innerHTML = `
            <div class="glass card-body center error-text" style="grid-column: 1/-1;">
                <span style="font-size: 2rem;">😵</span>
                <h3>Systemfehler beim Abrufen der Geräte-Daten</h3>
                <p class="text-muted">${err.message}</p>
                <button class="btn btn-outline" onclick="loadDevices()" style="margin-top: 12px;">Erneut versuchen</button>
            </div>`;
    }
}

function renderDeviceUI() {
    const zoneTents = document.getElementById('zone-tents');
    const zoneAll = document.getElementById('zone-all');
    
    if (currentDeviceView === 'tents') {
        if(zoneAll && !zoneAll.classList.contains('zone-out')) {
            zoneAll.classList.remove('zone-in');
            zoneAll.classList.add('zone-out');
            setTimeout(() => {
                zoneAll.style.display = 'none';
                if(zoneTents) {
                    zoneTents.style.display = 'block';
                    zoneTents.classList.remove('zone-out');
                    zoneTents.classList.add('zone-in');
                }
            }, 180);
        } else if (zoneTents && zoneTents.style.display === 'none') {
            zoneTents.style.display = 'block';
            zoneTents.classList.remove('zone-out');
            zoneTents.classList.add('zone-in');
        }
        renderTentUI();
        renderUnassignedUI();
    } else {
        if(zoneTents && !zoneTents.classList.contains('zone-out')) {
            zoneTents.classList.remove('zone-in');
            zoneTents.classList.add('zone-out');
            setTimeout(() => {
                zoneTents.style.display = 'none';
                if(zoneAll) {
                    zoneAll.style.display = 'block';
                    zoneAll.classList.remove('zone-out');
                    zoneAll.classList.add('zone-in');
                }
            }, 180);
        } else if (zoneAll && zoneAll.style.display === 'none') {
            zoneAll.style.display = 'block';
            zoneAll.classList.remove('zone-out');
            zoneAll.classList.add('zone-in');
        }
        renderAllDevicesUI();
    }
}

function renderAllDevicesUI() {
    const container = document.getElementById('device-cards');
    if (!container) return;

    const filtered = currentCategory === 'all' 
        ? allDevices 
        : allDevices.filter(d => d.category === currentCategory);

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="glass card-body center" style="grid-column: 1/-1; padding: 40px;">
                <div class="text-ghost" style="font-size: 3rem; margin-bottom: 10px;">🔌</div>
                <p class="text-muted">Keine Geräte in dieser Kategorie gefunden.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.map((device, idx) => buildDeviceCard(device, idx)).join('');
    bindDeviceEvents(container);
}

function renderTentUI() {
    const container = document.getElementById('tent-cards-container');
    if (!container) return;
    
    if (allTents.length === 0) {
        container.innerHTML = `
            <div class="tent-empty-state" style="grid-column: 1/-1;">
                <div style="font-size: 3rem; margin-bottom: 16px;">🏕️</div>
                <h3>Noch keine Zelte angelegt</h3>
                <p style="margin-top: 8px;">Erstelle dein erstes Zelt, um Geräte zuzuordnen.</p>
                <button class="btn btn-primary" onclick="document.getElementById('btn-add-tent').click()" style="margin-top: 16px;">+ Zelt anlegen</button>
            </div>
        `;
        return;
    }

    container.innerHTML = allTents.map((tent, idx) => {
        const tDevices = allDevices.filter(d => d.tent_id === tent.id);
        const onlineCount = tDevices.filter(d => d.online !== false).length;
        const totalCount = tDevices.length;
        
        let temps = [], hums = [], watts = 0;
        tDevices.forEach(d => {
            if (d.category === 'sensor' || (d.temperature !== undefined && d.temperature !== null)) {
                if (d.temperature) temps.push(parseFloat(d.temperature));
                if (d.humidity) hums.push(parseFloat(d.humidity));
            }
            if (d.power_w) watts += parseFloat(d.power_w);
        });
        
        const avgTemp = temps.length ? (temps.reduce((a,b)=>a+b,0)/temps.length).toFixed(1) : '—';
        const avgHum = hums.length ? (hums.reduce((a,b)=>a+b,0)/hums.length).toFixed(0) : '—';
        const powerVal = watts > 0 ? watts.toFixed(1) : '—';
        
        const onlineRatio = totalCount > 0 ? (onlineCount / totalCount) * 100 : 0;
        
        let chipsHtml = '';
        if (tDevices.length === 0) {
            chipsHtml = '<span class="text-muted text-sm" style="display:flex; align-items:center; height:100%;">Keine Geräte</span>';
        } else {
            const types = [...new Set(tDevices.map(d=>d.category))];
            types.slice(0, 4).forEach(cat => {
                const icon = DEVICE_CATEGORIES[cat] ? DEVICE_CATEGORIES[cat].icon : '🔌';
                chipsHtml += `<span class="tent-chip">${icon}</span>`;
            });
            if (types.length > 4) chipsHtml += `<span class="tent-chip">+${types.length - 4}</span>`;
        }
        
        return `
            <div class="glass tent-card stagger-item" style="animation-delay: ${idx*50}ms; cursor: pointer;" onclick="openTentPanel('${tent.id}')">
                <div class="tent-card-header">
                    <div>
                        <div class="tent-card-title">${escapeHtml(tent.icon || '🏕️')} ${escapeHtml(tent.name)}</div>
                        <div class="tent-card-subtitle">${escapeHtml(tent.description || 'Keine Beschreibung')}</div>
                    </div>
                </div>
                
                <div class="tent-metrics">
                    <div class="tent-metric"><span class="tent-metric-val" style="color:var(--accent-heat)">${avgTemp}</span><span class="tent-metric-label">Temp</span></div>
                    <div class="tent-metric"><span class="tent-metric-val" style="color:var(--accent-water)">${avgHum}</span><span class="tent-metric-label">RLF</span></div>
                    <div class="tent-metric"><span class="tent-metric-val" style="color:var(--accent-sun)">${powerVal}</span><span class="tent-metric-label">W</span></div>
                </div>
                
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top: auto;">
                    <div class="tent-chips">${chipsHtml}</div>
                    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:8px;">
                        <div class="tent-health-row">
                            <div class="health-bar-bg"><div class="health-bar-fill" style="width:${onlineRatio}%; background:${onlineRatio === 100 ? 'var(--accent-bio)' : 'var(--warning)'}"></div></div>
                            <span style="font-family:'Space Grotesk',sans-serif; font-weight:700; color:${onlineRatio === 100 ? 'var(--accent-bio)' : 'var(--warning)'}">${onlineCount}/${totalCount}</span>
                        </div>
                        <button class="btn-link" style="text-decoration:none; font-weight:600; color:var(--accent-bio)">→ Details</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderUnassignedUI() {
    const section = document.getElementById('unassigned-section');
    const container = document.getElementById('unassigned-container');
    const countEl = document.getElementById('unassigned-count');
    
    if (!section || !container) return;
    
    const unassigned = allDevices.filter(d => !d.tent_id);
    if (unassigned.length === 0) {
        section.style.display = 'none';
        selectedUnassignedDevices = [];
        updateBulkAssignVisibility();
        return;
    }
    
    section.style.display = 'block';
    if(countEl) countEl.textContent = unassigned.length;
    
    container.innerHTML = unassigned.map(d => {
        const cat = DEVICE_CATEGORIES[d.category] || { icon: '❓' };
        const isSelected = selectedUnassignedDevices.includes(d.name);
        const statusZone = isSelected
            ? `<span class="chip-status chip-check">✓</span>`
            : `<span class="chip-status chip-unassigned">Nicht zugewiesen</span>`;
        return `
            <div class="mini-device-card ${isSelected ? 'selected' : ''}" data-device-name="${escapeHtml(d.name)}" onclick="toggleDeviceSelection('${escapeHtml(d.name)}')">
                <span style="font-size:1.2rem; flex-shrink:0;">${cat.icon}</span>
                <span style="font-size:0.85rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; min-width:0;">${escapeHtml(d.name)}</span>
                ${statusZone}
            </div>
        `;
    }).join('');
    
    updateBulkAssignVisibility();
}

window.toggleDeviceSelection = (name) => {
    const isNowSelected = !selectedUnassignedDevices.includes(name);
    if (isNowSelected) {
        selectedUnassignedDevices.push(name);
    } else {
        selectedUnassignedDevices = selectedUnassignedDevices.filter(n => n !== name);
    }

    // Surgically update only the clicked chip — no full re-render to avoid flicker
    const chipEl = document.querySelector(`.mini-device-card[data-device-name="${CSS.escape(name)}"]`);
    if (chipEl) {
        chipEl.classList.toggle('selected', isNowSelected);
        const statusEl = chipEl.querySelector('.chip-status');
        if (statusEl) {
            if (isNowSelected) {
                statusEl.textContent = '✓';
                statusEl.className = 'chip-status chip-check';
            } else {
                statusEl.textContent = 'Nicht zugewiesen';
                statusEl.className = 'chip-status chip-unassigned';
            }
        }
    }

    updateBulkAssignVisibility();
}

function updateBulkAssignVisibility() {
    const btn = document.getElementById('btn-open-bulk-assign');
    const label = document.getElementById('selected-count-label');
    if(!btn || !label) return;
    
    if (selectedUnassignedDevices.length > 0) {
        btn.style.display = 'flex';
        label.textContent = selectedUnassignedDevices.length;
    } else {
        btn.style.display = 'none';
    }
}

function updateGlobalTentStats() {
    const elWatt = document.getElementById('g-stat-watt');
    const elOnline = document.getElementById('g-stat-online');
    const elRatio = document.getElementById('g-stat-ratio');
    if(!elWatt) return; // not initialized
    
    const totalWatt = allDevices.reduce((acc, d) => acc + (d.power_w || 0), 0);
    const online = allDevices.filter(d => d.online !== false).length;
    const total = allDevices.length;
    const ratio = total > 0 ? (online/total)*100 : 0;
    
    elWatt.textContent = totalWatt.toFixed(1);
    elOnline.textContent = online;
    elRatio.style.width = ratio + '%';
    document.getElementById('g-stat-watt-sub').textContent = `${allDevices.filter(d => d.power_w && d.power_w > 0).length} Geräte aktiv`;
    const warnCount = allDevices.filter(d => d.online === false).length;
    document.getElementById('g-stat-warn-val').textContent = warnCount;
    document.getElementById('g-stat-warn-val').style.color = warnCount > 0 ? 'var(--danger)' : 'var(--text-muted)';
    document.getElementById('g-stat-warn-sub').textContent = warnCount > 0 ? 'Offlines' : 'Alles OK';
    
    document.getElementById('g-stat-tents').textContent = allTents.length;
    document.getElementById('g-stat-time').textContent = new Date().toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'});
}

function buildDeviceCard(device, index) {
    const isOnline = device.online !== false;
    const cat = DEVICE_CATEGORIES[device.category] || { icon: '❓', label: 'Unbekannt' };
    const delay = index * 50;
    const isOn = device.device_on === true;
    const isVirtual = device.virtual === true;

    // Phase 2: Neuschreiben der Karten-Logik (Struktur-Korrektur)
    let cardContent = '';

    if (device.type === 'tapo_plug' || ['power', 'light', 'ventilation', 'irrigation', 'climate'].includes(device.category)) {
        const isLight = device.config.is_growth_light || device.category === 'light';
        const iconMapping = {
            'light': '💡',
            'ventilation': '💨',
            'irrigation': '💧',
            'climate': '🌬️',
            'power': '🔌'
        };
        const icon = iconMapping[device.category] || (isLight ? '💡' : '🔌');
        const powerVal = (device.power_w !== undefined && device.power_w !== null) ? parseFloat(device.power_w).toFixed(1) : '0.0';

        cardContent = `
            <div class="card-top">
                <div class="device-info">
                    <span class="device-type-icon">${icon}</span>
                    <div class="device-title-wrap">
                        <h3 class="device-name">${escapeHtml(device.name)}</h3>
                        <span class="device-meta">${device.ip || device.type}</span>
                    </div>
                </div>
                <label class="toggle-switch">
                    <input type="checkbox" class="device-toggle" data-ip="${device.ip}" data-name="${escapeHtml(device.name)}" ${isOn ? 'checked' : ''} ${!isOnline ? 'disabled' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            </div>
            ${isVirtual ? '<div class="virtual-badge">VIRTUAL MODE</div>' : ''}
            <div class="card-body-metric">
                <div class="metric-group">
                    <span class="metric-value" style="color: var(--accent-bio)">${powerVal}</span>
                    <span class="metric-unit">W</span>
                </div>
                ${(device.temperature !== undefined && device.temperature !== null) ? `
                <div class="metric-group">
                    <span class="metric-value" style="color: var(--accent-heat)">${parseFloat(device.temperature).toFixed(1)}</span>
                    <span class="metric-unit">°C</span>
                </div>` : `
                <div class="metric-group">
                    <span class="text-xs text-muted" style="text-transform: uppercase;">Status</span>
                    <div style="font-weight: 700; color: ${isOn ? 'var(--accent-bio)' : 'var(--text-muted)'}">${isOn ? 'AKTIV' : 'STANDBY'}</div>
                </div>`}
            </div>
        `;
    } else if (device.category === 'sensor') {
        const temp = (device.temperature !== undefined && device.temperature !== null) ? parseFloat(device.temperature).toFixed(1) : '—';
        const hum = (device.humidity !== undefined && device.humidity !== null) ? parseFloat(device.humidity).toFixed(0) : '—';
        
        cardContent = `
            <div class="card-top">
                <div class="device-info">
                    <span class="device-type-icon">🌡️</span>
                    <div class="device-title-wrap">
                        <h3 class="device-name">${escapeHtml(device.name)}</h3>
                        <span class="device-meta">${device.mac || 'SENSOR'}</span>
                    </div>
                </div>
                ${isVirtual ? '<span class="status-pill virtual">Virtual</span>' : (isOnline ? '<span class="status-pill online">Live</span>' : '<span class="status-pill offline">Offline</span>')}
            </div>
            <div class="card-body-metric">
                <div class="metric-group">
                    <span class="metric-value" style="color: var(--accent-heat)">${temp}</span>
                    <span class="metric-unit">°C</span>
                </div>
                <div class="metric-group">
                    <span class="metric-value" style="color: var(--accent-water)">${hum}</span>
                    <span class="metric-unit">%</span>
                </div>
            </div>
        `;
    } else {
        // Generic Fallback
        cardContent = `
            <div class="card-top">
                <div class="device-info">
                    <span class="device-type-icon">${cat.icon}</span>
                    <div class="device-title-wrap">
                        <h3 class="device-name">${escapeHtml(device.name)}</h3>
                        <span class="device-meta">${device.type}</span>
                    </div>
                </div>
                ${isVirtual ? '<span class="status-pill virtual">Virtual</span>' : (isOnline ? '<span class="status-pill online">Online</span>' : '<span class="status-pill offline">Offline</span>')}
            </div>
            <div class="card-body-metric">
                <div class="metric-group">
                    <span class="text-muted">${cat.label}</span>
                </div>
            </div>
        `;
    }

    return `
        <div class="glass device-card stagger-item" style="animation-delay: ${delay}ms;" data-name="${escapeHtml(device.name)}">
            ${cardContent}
            <div class="card-footer">
                <div class="device-uptime">
                   <div class="uptime-bar"><div class="uptime-fill" style="width: ${isOnline ? '100%' : '0%'}"></div></div>
                   <span class="text-xs text-muted">Stabilität: ${isOnline ? '100%' : '0%'}</span>
                </div>
                <div class="device-ops">
                    <button class="btn-icon btn-rename-device" data-name="${escapeHtml(device.name)}">✏️</button>
                    <button class="btn-icon btn-remove-device" data-name="${escapeHtml(device.name)}">🗑️</button>
                </div>
            </div>
        </div>
    `;
}

function bindDeviceEvents(container) {
    container.querySelectorAll('.device-toggle').forEach(t => t.addEventListener('change', handleToggle));
    container.querySelectorAll('.btn-rename-device').forEach(b => b.addEventListener('click', handleRenameDevice));
    container.querySelectorAll('.btn-remove-device').forEach(b => b.addEventListener('click', handleRemoveDevice));
}

function updateStatusBar() {
    const online = allDevices.filter(d => d.online !== false).length;
    const offline = allDevices.length - online;
    const totalWatt = allDevices.reduce((acc, d) => acc + (d.power_w || 0), 0);

    document.getElementById('statusbar-online-count').textContent = online;
    document.getElementById('statusbar-offline-count').textContent = offline;
    document.getElementById('statusbar-total-watt').textContent = totalWatt.toFixed(1);

    // Warnings if any device has health issues (placeholder logic)
    const warnCount = allDevices.filter(d => d.online === false).length;
    const warnPill = document.getElementById('statusbar-warn-pill');
    if (warnCount > 0) {
        warnPill.style.display = 'flex';
        document.getElementById('statusbar-warn-count').textContent = warnCount;
    } else {
        warnPill.style.display = 'none';
    }
}

function updateCategoryCounts() {
    document.getElementById('cat-count-all').textContent = allDevices.length;
    for (const catKey of Object.keys(DEVICE_CATEGORIES)) {
        const count = allDevices.filter(d => d.category === catKey).length;
        const el = document.getElementById(`cat-count-${catKey}`);
        if (el) el.textContent = count;
    }
}

// ─── Filter & Navigation (Phase 4) ──────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const tabs = document.querySelectorAll('.cat-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentCategory = tab.dataset.cat;
            renderDeviceUI();
        });
    });
});

// ─── Toggle Handler ─────────────────────────────────────────────────

async function handleToggle(e) {
    const toggle = e.target;
    const ip = toggle.dataset.ip;
    const name = toggle.dataset.name;
    const action = toggle.checked ? 'on' : 'off';

    toggle.disabled = true;
    showToast(`${action === 'on' ? '🟢' : '⚫'} ${name} wird ${action === 'on' ? 'eingeschaltet' : 'ausgeschaltet'}...`, 'info');

    const res = await API.post('/api/devices/toggle', { ip, action });

    if (res.success) {
        showToast(`✅ ${name} ${action === 'on' ? 'eingeschaltet' : 'ausgeschaltet'}`, 'success');
    } else {
        showToast(`❌ Fehler: ${res.message}`, 'error');
        // Toggle zurücksetzen
        toggle.checked = !toggle.checked;
    }

    toggle.disabled = false;
}

// ─── Gerät entfernen ────────────────────────────────────────────────

async function handleRemoveDevice(e) {
    const name = e.currentTarget.dataset.name;
    
    // Erste Bestätigung
    if (!confirm(`Möchtest du das Gerät "${name}" wirklich entfernen?\nAlle zugehörigen Daten könnten verloren gehen.`)) return;
    
    // Zweite Bestätigung (für Pflanzen/Geräte doppelt sicher gehen)
    if (!confirm(`Bist du absolut sicher? Die Entfernung von "${name}" kann nicht rückgängig gemacht werden!`)) return;

    const res = await API.post('/api/devices/remove', { name });
    if (res.success) {
        showToast(`🗑️ ${name} entfernt`, 'success');
        loadDevices();
    } else {
        showToast(`❌ Fehler: ${res.message}`, 'error');
    }
}

// ─── Gerät umbenennen ───────────────────────────────────────────────

async function handleRenameDevice(e) {
    const oldName = e.currentTarget.dataset.name;
    const newName = prompt(`Neuer Name für "${oldName}":`, oldName);
    if (!newName || newName.trim() === '' || newName === oldName) return;

    const res = await API.post('/api/devices/rename', { old_name: oldName, new_name: newName.trim() });
    if (res.success) {
        showToast(`✏️ Gerät in "${newName.trim()}" umbenannt`, 'success');
        loadDevices();
    } else {
        showToast(`❌ Fehler: ${res.message}`, 'error');
    }
}

// ─── Gerät hinzufügen ───────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const btnAdd = document.getElementById('btn-add-device');
    const modal = document.getElementById('modal-add-device');
    const btnClose = document.getElementById('modal-close-device');
    const btnCancel = document.getElementById('btn-cancel-device');
    const form = document.getElementById('form-add-device');
    const typeSelect = document.getElementById('device-type');

    function openModal() {
        modal.classList.add('active');
        form.reset();
        updateDeviceFormFields();
    }

    function closeModal() {
        modal.classList.remove('active');
    }

    function updateDeviceFormFields() {
        const type = typeSelect.value;
        const ipGroup = document.getElementById('group-device-ip');
        const macGroup = document.getElementById('group-device-mac');

        if (type === 'govee_ble') {
            ipGroup.style.display = 'none';
            macGroup.style.display = 'block';
        } else {
            ipGroup.style.display = 'block';
            macGroup.style.display = 'block';
        }
    }

    btnAdd.addEventListener('click', openModal);
    btnClose.addEventListener('click', closeModal);
    btnCancel.addEventListener('click', closeModal);
    typeSelect.addEventListener('change', updateDeviceFormFields);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const data = {
            name: document.getElementById('device-name').value.trim(),
            type: document.getElementById('device-type').value,
            ip: document.getElementById('device-ip').value.trim(),
            mac: document.getElementById('device-mac').value.trim(),
        };

        if (!data.name) {
            showToast('❌ Name ist erforderlich', 'error');
            return;
        }

        const res = await API.post('/api/devices/add', data);
        if (res.success) {
            showToast(`✅ ${data.name} hinzugefügt`, 'success');
            closeModal();
            loadDevices();
        } else {
            showToast(`❌ Fehler: ${res.message}`, 'error');
        }
    });

    // Kategorien Tab-Handler
    document.querySelectorAll('.cat-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.cat-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentCategory = tab.dataset.cat;
            renderDeviceUI();
        });
    });

    // ─── Phase 4 & 5: Tent Panel & Modal Logic ─────────────────────────
    
    // View Toggles
    const btnTents = document.getElementById('toggle-view-tents');
    const btnAll = document.getElementById('toggle-view-all');
    
    if(btnTents && btnAll) {
        btnTents.addEventListener('click', () => {
            currentDeviceView = 'tents';
            btnTents.classList.add('active');
            btnAll.classList.remove('active');
            renderDeviceUI();
        });
        btnAll.addEventListener('click', () => {
            currentDeviceView = 'all';
            btnAll.classList.add('active');
            btnTents.classList.remove('active');
            renderDeviceUI();
        });
    }

    // Modal adding Tent
    const modalTent = document.getElementById('modal-add-tent');
    const btnAddTent = document.getElementById('btn-add-tent');
    const btnCloseTent = document.getElementById('modal-close-tent');
    const btnCancelTent = document.getElementById('btn-cancel-tent');
    const formTent = document.getElementById('form-add-tent');
    
    let selectedTentIcon = '🌿';
    document.querySelectorAll('#tent-icon-picker .icon-picker-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#tent-icon-picker .icon-picker-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedTentIcon = btn.textContent;
        });
    });

    function openTentModal(editMode = false, tentData = null) {
        if(!modalTent) return;
        modalTent.classList.add('active');
        if(editMode && tentData) {
            document.getElementById('modal-tent-title').textContent = 'Zelt bearbeiten';
            document.getElementById('tent-edit-id').value = tentData.id;
            document.getElementById('tent-name').value = tentData.name;
            document.getElementById('tent-desc').value = tentData.description || '';
            document.getElementById('btn-save-tent').textContent = 'Speichern';
            
            selectedTentIcon = tentData.icon || '🌿';
            document.querySelectorAll('#tent-icon-picker .icon-picker-btn').forEach(b => {
                b.classList.toggle('active', b.textContent === selectedTentIcon);
            });
        } else {
            document.getElementById('modal-tent-title').textContent = 'Neues Zelt anlegen';
            if(formTent) formTent.reset();
            document.getElementById('tent-edit-id').value = '';
            document.getElementById('btn-save-tent').textContent = 'Zelt anlegen';
            selectedTentIcon = '🌿';
            document.querySelectorAll('#tent-icon-picker .icon-picker-btn').forEach((b,i) => b.classList.toggle('active', i===0));
        }
    }

    function closeTentModal() {
        if(modalTent) modalTent.classList.remove('active');
    }

    if(btnAddTent) btnAddTent.addEventListener('click', () => openTentModal(false));
    if(btnCloseTent) btnCloseTent.addEventListener('click', closeTentModal);
    if(btnCancelTent) btnCancelTent.addEventListener('click', closeTentModal);
    
    if(formTent) {
        formTent.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('tent-edit-id').value;
            const tent = {
                id: id || 'tent_' + Date.now(),
                name: document.getElementById('tent-name').value.trim(),
                description: document.getElementById('tent-desc').value.trim(),
                icon: selectedTentIcon
            };
            const res = await TentStorage.save(tent);
            if(res.success) {
                showToast('🏕️ Zelt gespeichert', 'success');
                closeTentModal();
                loadDevices(); // Refresh tents
            } else {
                showToast('❌ Fehler beim Speichern', 'error');
            }
        });
    }

    // Slide-In Panel 
    const panelOverlay = document.getElementById('panel-overlay');
    const tentPanel = document.getElementById('tent-panel');
    const btnClosePanel = document.getElementById('btn-close-panel');
    const btnEditTent = document.getElementById('btn-edit-tent');
    const btnDeleteTent = document.getElementById('btn-delete-tent');

    let currentOpenTentId = null;
    let panelTimeout = null; // Track current animation timeout

    window.openTentPanel = (tentId) => {
        const tent = allTents.find(t => t.id === tentId);
        if(!tent) return;
        
        const isAlreadyOpen = tentPanel.classList.contains('open');
        currentOpenTentId = tentId;
        
        document.getElementById('panel-tent-name').textContent = tent.name;
        document.getElementById('panel-tent-icon').textContent = tent.icon || '🏕️';
        
        // Update Metrics
        const tDevices = allDevices.filter(d => d.tent_id === tentId);
        let temps = [], hums = [], watts = 0, health = 100;
        tDevices.forEach(d => {
            if (d.temperature) temps.push(parseFloat(d.temperature));
            if (d.humidity) hums.push(parseFloat(d.humidity));
            if (d.power_w) watts += parseFloat(d.power_w);
        });
        const onlineCount = tDevices.filter(d => d.online !== false).length;
        if(temps.length && ((temps.reduce((a,b)=>a+b,0)/temps.length) < 18 || (temps.reduce((a,b)=>a+b,0)/temps.length) > 30)) health -= 30;
        if (tDevices.length > 0 && onlineCount < tDevices.length) health -= 20;

        document.getElementById('panel-metric-temp').textContent = temps.length ? (temps.reduce((a,b)=>a+b,0)/temps.length).toFixed(1) : '—';
        document.getElementById('panel-metric-hum').textContent = hums.length ? (hums.reduce((a,b)=>a+b,0)/hums.length).toFixed(0) : '—';
        document.getElementById('panel-metric-watt').textContent = watts > 0 ? watts.toFixed(1) : '—';
        document.getElementById('panel-metric-score').textContent = health + '%';
        document.getElementById('panel-metric-score').style.color = health > 70 ? 'var(--accent-bio)' : 'var(--warning)';
        
        // Group Devices
        const groups = {};
        tDevices.forEach(d => {
            if(!groups[d.category]) groups[d.category] = [];
            groups[d.category].push(d);
        });
        
        let catsHtml = '';
        for(const [cat, devs] of Object.entries(groups)) {
            const catInfo = DEVICE_CATEGORIES[cat] || {icon:'?', label:'Andere'};
            const itemsHtml = devs.map(d => `
                <div class="category-item">
                    <div style="display:flex; align-items:center; gap:12px;">
                        <span style="font-size:1.5rem">${catInfo.icon}</span>
                        <div>
                            <div style="font-weight:600; font-size:0.9rem">${escapeHtml(d.name)}</div>
                            <div style="font-size:0.75rem; color:var(--text-muted)">${d.online !== false ? '🟢 Online' : '🔴 Offline'}</div>
                        </div>
                    </div>
                    <button class="btn btn-outline text-sm" onclick="removeDeviceFromTent('${escapeHtml(d.name)}')">Entfernen</button>
                </div>
            `).join('');
            
            catsHtml += `
                <div class="category-row">
                    <div class="category-header">
                        <span style="font-weight:600; color:var(--text-secondary); text-transform:uppercase; font-size:0.8rem; letter-spacing:0.04em">${catInfo.icon} ${catInfo.label}</span>
                        <span class="text-xs text-muted">${devs.length}</span>
                    </div>
                    <div class="category-items">${itemsHtml}</div>
                </div>
            `;
        }
        
        if (tDevices.length === 0) {
            catsHtml = `
                <div class="tent-empty-state" style="min-height: 150px; border:none; padding: 20px;">
                    <span style="font-size: 2rem; margin-bottom: 8px;">📦</span>
                    <p style="margin:0">Keine Geräte in diesem Zelt.</p>
                </div>
            `;
        }
        
        const unassigned = allDevices.filter(d => !d.tent_id);
        if(unassigned.length > 0) {
            const options = unassigned.map(d => `<option value="${escapeHtml(d.name)}">${escapeHtml(d.name)}</option>`).join('');
            catsHtml += `
                <div style="margin-top:24px; display:flex; gap:12px;">
                    <select id="select-assign-device" class="form-input" style="flex:1;">
                        <option value="">Gerät zuweisen...</option>
                        ${options}
                    </select>
                    <button class="btn btn-primary" onclick="assignSelectedDevice()">Hinzufügen</button>
                </div>
            `;
        }

        document.getElementById('panel-device-categories').innerHTML = catsHtml;

        if (panelTimeout) clearTimeout(panelTimeout);
        
        if (!isAlreadyOpen) {
            tentPanel.classList.remove('closing');
            panelOverlay.style.display = 'flex';
            tentPanel.style.display = 'flex';
            
            // Trigger reflow
            void tentPanel.offsetWidth;
            
            panelOverlay.classList.add('active');
            tentPanel.classList.add('open');
            document.addEventListener('keydown', handleEsc);
        } else {
            const body = document.getElementById('panel-tent-body');
            body.classList.remove('panel-content-fade');
            void body.offsetWidth; 
            body.classList.add('panel-content-fade');
        }
    }

    function closePanel() {
        if (panelTimeout) clearTimeout(panelTimeout);
        
        tentPanel.classList.remove('open');
        tentPanel.classList.add('closing');
        panelOverlay.classList.remove('active');
        document.removeEventListener('keydown', handleEsc);
        
        panelTimeout = setTimeout(() => {
            tentPanel.style.display = 'none';
            panelOverlay.style.display = 'none';
            tentPanel.classList.remove('closing');
            currentOpenTentId = null;
            panelTimeout = null;
        }, 300);
    }

    function handleEsc(e) {
        if (e.key === 'Escape') closePanel();
    }

    if(btnClosePanel) btnClosePanel.addEventListener('click', closePanel);
    if(panelOverlay) panelOverlay.addEventListener('click', (e) => {
        if(e.target === panelOverlay) closePanel();
    });
    
    if(btnEditTent) {
        btnEditTent.addEventListener('click', () => {
            const tent = allTents.find(t => t.id === currentOpenTentId);
            if(tent) {
                closePanel();
                openTentModal(true, tent);
            }
        });
    }

    if(btnDeleteTent) {
        btnDeleteTent.addEventListener('click', async () => {
            if(!currentOpenTentId) return;
            const tent = allTents.find(t => t.id === currentOpenTentId);
            if(confirm(`Zelt "${tent.name}" wirklich löschen? Zugeordnete Geräte werden nicht gelöscht, nur die Zuordnung wird entfernt.`)) {
                const res = await TentStorage.remove(currentOpenTentId);
                if(res.success) {
                    showToast('🗑️ Zelt gelöscht', 'success');
                    closePanel();
                    loadDevices();
                } else {
                    showToast('❌ Fehler beim Löschen', 'error');
                }
            }
        });
    }
    
    window.assignSelectedDevice = async () => {
        const sel = document.getElementById('select-assign-device');
        if(!sel || !sel.value || !currentOpenTentId) return;
        const name = sel.value;
        const res = await API.post('/api/devices/update', {name, edits: {tent_id: currentOpenTentId}});
        if(res.success) {
            showToast('✅ Gerät zugewiesen', 'success');
            await loadDevices();
            if(currentOpenTentId) openTentPanel(currentOpenTentId); // refresh panel
        } else {
            showToast('❌ Zuweisung fehlgeschlagen', 'error');
        }
    }
    
    window.removeDeviceFromTent = async (name) => {
        if(!currentOpenTentId) return;
        if(confirm(`"${name}" aus diesem Zelt entfernen?`)) {
            const res = await API.post('/api/devices/update', {name, edits: {tent_id: null}});
            if(res.success) {
                showToast('✅ Gerät entfernt', 'success');
                await loadDevices();
                if(currentOpenTentId) openTentPanel(currentOpenTentId);
            } else {
                showToast('❌ Fehler beim Entfernen', 'error');
            }
        }
    }

    // Bulk Assign Modal Logic
    const modalBulk = document.getElementById('modal-bulk-assign');
    const btnOpenBulk = document.getElementById('btn-open-bulk-assign');
    const btnCloseBulk = document.getElementById('modal-close-bulk');
    const btnCancelBulk = document.getElementById('btn-cancel-bulk');
    const btnConfirmBulk = document.getElementById('btn-confirm-bulk');
    const selectBulkTent = document.getElementById('select-bulk-tent');

    function openBulkModal() {
        if(!modalBulk) return;
        document.getElementById('bulk-assign-count').textContent = selectedUnassignedDevices.length;
        
        // Populate Tents
        if(selectBulkTent) {
            selectBulkTent.innerHTML = '<option value="">Zelt wählen...</option>' + 
                allTents.map(t => `<option value="${t.id}">${t.icon || '🏕️'} ${t.name}</option>`).join('');
        }
        
        modalBulk.classList.add('active');
    }

    function closeBulkModal() {
        if(modalBulk) modalBulk.classList.remove('active');
    }

    if(btnOpenBulk) btnOpenBulk.addEventListener('click', openBulkModal);
    if(btnCloseBulk) btnCloseBulk.addEventListener('click', closeBulkModal);
    if(btnCancelBulk) btnCancelBulk.addEventListener('click', closeBulkModal);

    if(btnConfirmBulk) {
        btnConfirmBulk.addEventListener('click', async () => {
            const tentId = selectBulkTent.value;
            if(!tentId) {
                showToast('⚠️ Bitte wähle ein Zelt aus', 'error');
                return;
            }
            
            btnConfirmBulk.disabled = true;
            btnConfirmBulk.textContent = 'Wird verschoben...';
            
            let successCount = 0;
            for(const name of selectedUnassignedDevices) {
                const res = await API.post('/api/devices/update', {name, edits: {tent_id: tentId}});
                if(res.success) successCount++;
            }
            
            showToast(`✅ ${successCount} Geräte erfolgreich verschoben`, 'success');
            selectedUnassignedDevices = [];
            closeBulkModal();
            loadDevices();
            btnConfirmBulk.disabled = false;
            btnConfirmBulk.textContent = 'Geräte verschieben';
        });
    }

    // Initial load
    loadDevices();
    
    // Auto Refresh alle 30 Sekunden
    setInterval(() => {
        if (GrowMate.currentPage === 'devices') loadDevices();
    }, 30000);
});
