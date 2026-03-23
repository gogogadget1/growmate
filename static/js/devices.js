/**
 * GrowMate – Geräte-Verwaltung
 * Steckdosen ein-/ausschalten, Geräte hinzufügen/entfernen.
 */

// ─── Geräte laden ───────────────────────────────────────────────────

async function loadDevices() {
    const container = document.getElementById('device-cards');
    container.innerHTML = `
        <div class="card glass loading-card">
            <div class="card-body center">
                <div class="spinner"></div>
                <p>Lade Geräte...</p>
            </div>
        </div>
    `;

    const [res, configsRes] = await Promise.all([
        API.get('/api/devices'),
        API.get('/api/devices/config')
    ]);

    const configs = {};
    if (configsRes.success) {
        configsRes.data.forEach(c => configs[c.device_name] = c);
    }

    if (res.success && res.data && res.data.length > 0) {
        container.innerHTML = res.data.map((device, index) => {
            const config = configs[device.name] || {};
            if (device.type === 'tapo_plug') {
                return renderPlugCard(device, index, config);
            } else if (device.type === 'govee_ble') {
                return renderSensorDeviceCard(device);
            } else {
                return renderGenericDeviceCard(device);
            }
        }).join('');

        // Config-Safe-Events binden
        container.querySelectorAll('.btn-save-device-config').forEach(btn => {
            btn.addEventListener('click', handleSaveDeviceConfig);
        });

        // Toggle-Events binden
        container.querySelectorAll('.device-toggle').forEach(toggle => {
            toggle.addEventListener('change', handleToggle);
        });

        // Events binden
        container.querySelectorAll('.btn-remove-device').forEach(btn => {
            btn.addEventListener('click', handleRemoveDevice);
        });
        container.querySelectorAll('.btn-rename-device').forEach(btn => {
            btn.addEventListener('click', handleRenameDevice);
        });
    } else {
        container.innerHTML = `
            <div class="card glass">
                <div class="card-body center">
                    <div class="empty-state">
                        <span class="empty-icon">🔌</span>
                        <span class="empty-text">Keine Geräte konfiguriert. Füge dein erstes Gerät hinzu!</span>
                    </div>
                </div>
            </div>
        `;
    }
}

function renderPlugCard(device, index, config = {}) {
    const isOnline = device.online !== false;
    const isOn = device.device_on === true;
    const ppfd = config.ppfd_value || 0;
    const isLight = config.is_growth_light === 1 || config.is_growth_light === true;

    return `
        <div class="card glass device-card sensor-card" data-device-name="${escapeHtml(device.name)}">
            <div class="card-body">
                <div class="device-header">
                    <div>
                        <div class="device-name">🔌 ${escapeHtml(device.name)}</div>
                        <div class="device-ip">${device.ip || '—'}</div>
                    </div>
                    <label class="toggle-switch" title="${isOn ? 'Ausschalten' : 'Einschalten'}">
                        <input type="checkbox"
                               class="device-toggle"
                               data-ip="${device.ip}"
                               data-name="${escapeHtml(device.name)}"
                               ${isOn ? 'checked' : ''}
                               ${!isOnline ? 'disabled' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <div class="device-status">
                    ${isOnline
                        ? `<span class="online">● Online</span> – ${isOn ? '🟢 Eingeschaltet' : '⚫ Ausgeschaltet'}`
                        : `<span class="offline">● Offline</span>`
                    }
                </div>

                <div class="device-config-extra" style="margin: 15px 0; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 8px; border: 1px solid var(--border-color);">
                    <div style="font-size: 0.8rem; font-weight: 700; margin-bottom: 8px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px;">Wissenschaftliche Config</div>
                    <div style="display: flex; align-items: center; gap: 15px; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 8px; font-size: 0.85rem; cursor: pointer;">
                            <input type="checkbox" class="config-is-light" ${isLight ? 'checked' : ''} style="accent-color: var(--accent);">
                            <span>Wachstumslicht</span>
                        </label>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 0.85rem;">PPFD:</span>
                            <input type="number" class="config-ppfd" value="${ppfd}" min="0" max="3000" style="width: 70px; background: var(--bg-input); border: 1px solid var(--border-color); color: white; border-radius: 4px; padding: 2px 5px; font-size: 0.85rem;">
                            <button class="btn btn-sm btn-outline btn-save-device-config" data-name="${escapeHtml(device.name)}" style="padding: 2px 8px;">💾</button>
                        </div>
                    </div>
                </div>

                ${device.power_w !== undefined ? `
                <div class="device-energy">
                    <div class="device-energy-item">
                        <div class="energy-val">${device.power_w !== null ? device.power_w.toFixed(1) : '—'} W</div>
                        <div class="energy-lbl">Aktuell</div>
                    </div>
                    <div class="device-energy-item">
                        <div class="energy-val">${device.energy_today_wh ? (device.energy_today_wh / 1000).toFixed(2) : '—'} kWh</div>
                        <div class="energy-lbl">Heute</div>
                    </div>
                </div>
                ` : ''}

                <div class="device-actions" style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 15px;">
                    <button class="btn btn-outline btn-icon btn-rename-device"
                            data-name="${escapeHtml(device.name)}" title="Umbenennen">✏️</button>
                    <button class="btn btn-danger btn-icon btn-remove-device"
                            data-name="${escapeHtml(device.name)}" title="Gerät entfernen">🗑️</button>
                </div>
            </div>
        </div>
    `;
}

async function handleSaveDeviceConfig(e) {
    const btn = e.currentTarget;
    const name = btn.dataset.name;
    const card = btn.closest('.device-card');
    const isLight = card.querySelector('.config-is-light').checked;
    const ppfd = parseInt(card.querySelector('.config-ppfd').value) || 0;

    btn.disabled = true;
    const res = await API.post('/api/devices/config', {
        device_name: name,
        ppfd_value: ppfd,
        is_growth_light: isLight
    });

    if (res.success) {
        showToast(`✅ Konfiguration für ${name} gespeichert`, 'success');
    } else {
        showToast(`❌ Fehler: ${res.message}`, 'error');
    }
    btn.disabled = false;
}

function renderSensorDeviceCard(device) {
    return `
        <div class="card glass device-card sensor-card" data-device-name="${escapeHtml(device.name)}">
            <div class="card-body">
                <div class="device-header">
                    <div>
                        <div class="device-name">📡 ${escapeHtml(device.name)}</div>
                        <div class="device-ip">${device.mac || 'BLE Sensor'}</div>
                    </div>
                </div>
                <div class="device-status">
                    <span class="online">● Bluetooth</span> – Passiver Scan
                </div>
                <div class="device-actions" style="display: flex; gap: 10px; justify-content: flex-end;">
                    <button class="btn btn-outline btn-icon btn-rename-device"
                            data-name="${escapeHtml(device.name)}" title="Umbenennen">✏️</button>
                    <button class="btn btn-danger btn-icon btn-remove-device"
                            data-name="${escapeHtml(device.name)}" title="Gerät entfernen">🗑️</button>
                </div>
            </div>
        </div>
    `;
}

function renderGenericDeviceCard(device) {
    return `
        <div class="card glass device-card sensor-card" data-device-name="${escapeHtml(device.name)}">
            <div class="card-body">
                <div class="device-header">
                    <div>
                        <div class="device-name">📱 ${escapeHtml(device.name)}</div>
                        <div class="device-ip">${device.ip || device.mac || '—'}</div>
                    </div>
                </div>
                <div class="device-status">
                    <span>${device.type}</span>
                </div>
                <div class="device-actions" style="display: flex; gap: 10px; justify-content: flex-end;">
                    <button class="btn btn-outline btn-icon btn-rename-device"
                            data-name="${escapeHtml(device.name)}" title="Umbenennen">✏️</button>
                    <button class="btn btn-danger btn-icon btn-remove-device"
                            data-name="${escapeHtml(device.name)}" title="Gerät entfernen">🗑️</button>
                </div>
            </div>
        </div>
    `;
}

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
