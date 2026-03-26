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
    power:      { label: 'Strom',     icon: '⚡', types: ['tapo_plug', 'smart_outlet', 'timer_plug'] },
    sensor:     { label: 'Sensoren',  icon: '🌡️', types: ['govee_ble', 'tapo_sensor', 'co2_sensor', 'soil_sensor', 'water_temp', 'ph_sensor', 'ec_sensor', 'leak_sensor'] },
    light:      { label: 'Licht',     icon: '💡', types: ['grow_light', 'hps_light', 'led_dimmer'] },
    ventilation:{ label: 'Lüftung',   icon: '💨', types: ['inline_fan', 'circulation_fan', 'fan_controller'] },
    irrigation: { label: 'Wasser',    icon: '💧', types: ['water_pump', 'dosing_pump', 'drain_pump'] },
    climate:    { label: 'Klima',     icon: '🌬️', types: ['dehumidifier', 'humidifier', 'ac_unit', 'heat_mat', 'co2_generator'] },
    hub:        { label: 'Hubs',      icon: '🔗', types: ['tapo_hub', 'zigbee_hub'] },
};

function getCategoryForType(type) {
    if (!type) return 'power';
    for (const [catKey, cat] of Object.entries(DEVICE_CATEGORIES)) {
        if (cat.types.includes(type)) return catKey;
    }
    return 'power'; // Fallback
}

// ─── Geräte laden ───────────────────────────────────────────────────

// ─── Geräte laden & Render-Logik ────────────────────────────────────

let allDevices = [];
let currentCategory = 'all';

async function loadDevices() {
    const container = document.getElementById('device-cards');
    if (!container) return;

    // Loading State
    container.innerHTML = `
        <div class="glass card-body skeleton" style="height: 180px;"></div>
        <div class="glass card-body skeleton" style="height: 180px;"></div>
        <div class="glass card-body skeleton" style="height: 180px;"></div>
    `;

    try {
        const [res, configsRes] = await Promise.all([
            API.get('/api/devices'),
            API.get('/api/devices/config')
        ]);

        if (!res.success) {
            showToast('Fehler beim Laden der Geräte', 'error');
            return;
        }

        allDevices = res.data || [];
        const configs = {};
        if (configsRes.success) {
            configsRes.data.forEach(c => configs[c.device_name] = c);
        }

        // Attach config to device objects
        allDevices.forEach(d => {
            d.config = configs[d.name] || {};
            d.category = getCategoryForType(d.type);
        });

        renderDeviceUI();
        updateStatusBar();
        updateCategoryCounts();

    } catch (err) {
        console.error('Device Load Error:', err);
        container.innerHTML = `<div class="glass card-body center error-text">Systemfehler beim Abrufen der Geräte-Daten.</div>`;
    }
}

function renderDeviceUI() {
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

    // Re-bind Events
    bindDeviceEvents(container);
}

function buildDeviceCard(device, index) {
    const isOnline = device.online !== false;
    const cat = DEVICE_CATEGORIES[device.category] || { icon: '❓', label: 'Unbekannt' };
    const delay = index * 50;
    const isOn = device.device_on === true;

    // Phase 2: Neuschreiben der Karten-Logik (Struktur-Korrektur)
    let cardContent = '';

    if (device.type === 'tapo_plug') {
        const isLight = device.config.is_growth_light;
        const icon = isLight ? '💡' : '🔌';
        const powerVal = device.power_w !== undefined ? device.power_w.toFixed(1) : '0.0';

        cardContent = `
            <div class="card-top">
                <div class="device-info">
                    <span class="device-type-icon">${icon}</span>
                    <div class="device-title-wrap">
                        <h3 class="device-name">${escapeHtml(device.name)}</h3>
                        <span class="device-meta">${device.ip}</span>
                    </div>
                </div>
                <label class="toggle-switch">
                    <input type="checkbox" class="device-toggle" data-ip="${device.ip}" data-name="${escapeHtml(device.name)}" ${isOn ? 'checked' : ''} ${!isOnline ? 'disabled' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="card-body-metric">
                <div class="metric-group">
                    <span class="metric-value" style="color: var(--accent-bio)">${powerVal}</span>
                    <span class="metric-unit">W</span>
                </div>
                <div class="metric-group">
                    <span class="text-xs text-muted" style="text-transform: uppercase;">Status</span>
                    <div style="font-weight: 700; color: ${isOn ? 'var(--accent-bio)' : 'var(--text-muted)'}">${isOn ? 'AKTIV' : 'STANDBY'}</div>
                </div>
            </div>
        `;
    } else if (device.category === 'sensor') {
        const temp = device.temperature !== undefined ? device.temperature.toFixed(1) : '—';
        const hum = device.humidity !== undefined ? device.humidity.toFixed(0) : '—';
        
        cardContent = `
            <div class="card-top">
                <div class="device-info">
                    <span class="device-type-icon">🌡️</span>
                    <div class="device-title-wrap">
                        <h3 class="device-name">${escapeHtml(device.name)}</h3>
                        <span class="device-meta">${device.mac || 'BLE'}</span>
                    </div>
                </div>
                ${isOnline ? '<span class="status-pill online">Live</span>' : '<span class="status-pill offline">Offline</span>'}
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
                ${isOnline ? '<span class="status-pill online">Online</span>' : '<span class="status-pill offline">Offline</span>'}
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
});
