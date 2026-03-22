/**
 * GrowMate – Pflanzentagebuch & Pflanzenverwaltung
 * CRUD mit 2-Spalten Layout und Archivierungsfunktion.
 */

// ─── Tagebuch & Pflanzen laden ───────────────────────────────────────

async function loadDiary() {
    const container = document.getElementById('diary-entries');
    const plantListContainer = document.getElementById('diary-plant-list');
    const filter = document.getElementById('diary-filter').value;
    const plantFilter = document.getElementById('diary-plant-filter').value;
    const showArchived = document.getElementById('toggle-show-archived').checked;

    // Lade Pflanzen für die linke Sidebar
    loadPlantSidebar(showArchived);

    container.innerHTML = '<div class="spinner"></div>';

    let url = `/api/diary?show_archived=${showArchived}&`;
    if (filter) url += `type=${encodeURIComponent(filter)}&`;
    if (plantFilter) url += `plant=${encodeURIComponent(plantFilter)}&`;

    const res = await API.get(url);

    if (res.success && res.data && res.data.length > 0) {
        container.innerHTML = res.data.map(renderDiaryEntry).join('');
        bindEntryEvents(container);
    } else {
        container.innerHTML = '<div class="empty-state">Noch keine Einträge vorhanden.</div>';
    }
}

async function loadPlantSidebar(showArchived = false) {
    const container = document.getElementById('diary-plant-list');
    const filterSelect = document.getElementById('diary-plant-filter');
    const datalist = document.getElementById('known-plants');
    
    const res = await API.get(`/api/plants?show_archived=${showArchived}`);
    
    if (res.success && res.data) {
        const plants = res.data;
        
        // Sidebar Liste
        container.innerHTML = plants.map(plant => `
            <div class="diary-plant-card ${plant.is_archived ? 'archived' : ''}">
                <div class="plant-info">
                    <h4>${escapeHtml(plant.name)}</h4>
                    <p>${escapeHtml(plant.description || 'Keine Beschreibung')}</p>
                </div>
                <button class="btn btn-icon btn-sm" onclick="togglePlantArchive(${plant.id}, ${plant.is_archived})" 
                        title="${plant.is_archived ? 'Dearchivieren' : 'Archivieren'}">
                    ${plant.is_archived ? '📤' : '📥'}
                </button>
            </div>
        `).join('') || '<p class="text-muted">Keine Pflanzen angelegt.</p>';

        // Filter Dropdown
        const currentFilter = filterSelect.value;
        filterSelect.innerHTML = '<option value="">Alle Pflanzen</option>' + 
            plants.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('');
        filterSelect.value = currentFilter;

        // Datalist für Modal
        if (datalist) {
            datalist.innerHTML = plants.map(p => `<option value="${escapeHtml(p.name)}">`).join('');
        }
    }
}

// ─── Pflanzen-Archivierung ───────────────────────────────────────────

async function togglePlantArchive(plantId, currentStatus) {
    const password = prompt("Bitte Passwort eingeben:");
    if (!password) return;

    const res = await API.put(`/api/plants/${plantId}/archive`, 
        { is_archived: !currentStatus }, 
        { 'X-Plant-Password': password }
    );

    if (res.success) {
        showToast(`Pflanze erfolgreich ${currentStatus ? 'reaktiviert' : 'archiviert'}`, 'success');
        loadDiary();
    } else {
        showToast(res.message || "Fehler beim Archivieren", "error");
    }
}

// ─── Neuer Eintrag / Modal Logic ─────────────────────────────────────

function openDiaryModal(type = 'default', entry = null) {
    const modal = document.getElementById('modal-diary');
    const form = document.getElementById('form-diary');
    const title = document.getElementById('diary-modal-title');
    
    form.reset();
    document.getElementById('diary-edit-id').value = '';
    document.getElementById('diary-date').value = new Date().toISOString().split('T')[0];
    
    // Sichtbarkeit der Felder steuern
    const allRows = form.querySelectorAll('.form-row, .form-group');
    allRows.forEach(row => row.style.display = '');

    if (type === 'care') {
        title.textContent = '🌱 Pflanzen-Pflege';
        document.getElementById('diary-type').value = 'Pflege';
        // Verberge Wasser-spezifische Felder
        document.getElementById('diary-water').closest('.form-group').style.display = 'none';
        document.getElementById('diary-ph').closest('.form-group').style.display = 'none';
    } else if (type === 'water') {
        title.textContent = '💧 Bewässerung';
        document.getElementById('diary-type').value = 'Bewässerung';
        // Verberge Höhe/Phase/Gesundheit
        document.getElementById('diary-height').closest('.form-group').style.display = 'none';
        document.getElementById('diary-phase').closest('.form-group').style.display = 'none';
        document.getElementById('diary-health').closest('.form-group').style.display = 'none';
    } else {
        title.textContent = entry ? 'Eintrag bearbeiten' : 'Neuer Eintrag';
    }

    if (entry) {
        document.getElementById('diary-edit-id').value = entry.id;
        document.getElementById('diary-date').value = entry.entry_date;
        document.getElementById('diary-type').value = entry.entry_type;
        document.getElementById('diary-title').value = entry.title;
        document.getElementById('diary-plant').value = entry.plant_name;
        document.getElementById('diary-content').value = entry.content;
        document.getElementById('diary-height').value = entry.plant_height_cm;
        document.getElementById('diary-phase').value = entry.plant_phase;
        document.getElementById('diary-health').value = entry.health_status;
        document.getElementById('diary-water').value = entry.water_amount_ml;
        document.getElementById('diary-ph').value = entry.ph_value;
    }

    modal.classList.add('active');
}

// ─── Hilfsfunktionen ─────────────────────────────────────────────────

function renderDiaryEntry(entry) {
    return `
        <div class="card glass diary-entry">
            <div class="diary-entry-header">
                <span class="diary-entry-type type-${entry.entry_type.toLowerCase()}">
                    ${getTypeEmoji(entry.entry_type)} ${entry.entry_type}
                </span>
                <span class="diary-entry-date">${formatDate(entry.entry_date)}</span>
            </div>
            <div class="diary-entry-title">
                ${escapeHtml(entry.title)}
                <span class="plant-tag">🌱 ${escapeHtml(entry.plant_name)}</span>
            </div>
            <div class="diary-entry-metrics">
                ${entry.plant_phase ? `<span>📅 ${entry.plant_phase}</span>` : ''}
                ${entry.water_amount_ml ? `<span>💧 ${entry.water_amount_ml}ml</span>` : ''}
                ${entry.plant_height_cm ? `<span>📏 ${entry.plant_height_cm}cm</span>` : ''}
            </div>
            ${entry.content ? `<div class="diary-entry-content">${escapeHtml(entry.content)}</div>` : ''}
            <div class="diary-entry-footer">
                <button class="btn btn-outline btn-sm btn-edit-entry" data-id="${entry.id}">✏️</button>
                <button class="btn btn-danger btn-sm btn-delete-entry" data-id="${entry.id}">🗑️</button>
            </div>
        </div>
    `;
}

function bindEntryEvents(container) {
    container.querySelectorAll('.btn-edit-entry').forEach(btn => {
        btn.addEventListener('click', async () => {
            const res = await API.get(`/api/diary/${btn.dataset.id}`);
            if (res.success) openDiaryModal('edit', res.data);
        });
    });
    container.querySelectorAll('.btn-delete-entry').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (confirm("Möchtest du diesen Tagebucheintrag wirklich unwiderruflich löschen?")) {
                const res = await API.delete(`/api/diary/${btn.dataset.id}`);
                if (res.success) { loadDiary(); showToast("Eintrag gelöscht", "success"); }
            }
        });
    });
}

// ─── Initialisierung ─────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Tagebuch-Buttons
    document.getElementById('btn-new-plant-care')?.addEventListener('click', () => openDiaryModal('care'));
    document.getElementById('btn-new-water')?.addEventListener('click', () => openDiaryModal('water'));
    document.getElementById('btn-new-note')?.addEventListener('click', () => openDiaryModal('default'));

    // Filter und Toggle
    document.getElementById('diary-filter')?.addEventListener('change', loadDiary);
    document.getElementById('diary-plant-filter')?.addEventListener('change', loadDiary);
    document.getElementById('toggle-show-archived')?.addEventListener('change', loadDiary);

    // Modal schliessen
    document.getElementById('modal-close-diary')?.addEventListener('click', () => document.getElementById('modal-diary').classList.remove('active'));
    document.getElementById('btn-cancel-diary')?.addEventListener('click', () => document.getElementById('modal-diary').classList.remove('active'));

    // Formular speichern
    document.getElementById('form-diary')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const editId = document.getElementById('diary-edit-id').value;
        const data = {
            entry_date: document.getElementById('diary-date').value,
            entry_type: document.getElementById('diary-type').value,
            title: document.getElementById('diary-title').value,
            plant_name: document.getElementById('diary-plant').value,
            content: document.getElementById('diary-content').value,
            plant_height_cm: document.getElementById('diary-height').value || null,
            plant_phase: document.getElementById('diary-phase').value || null,
            health_status: document.getElementById('diary-health').value || null,
            water_amount_ml: document.getElementById('diary-water').value || null,
            ph_value: document.getElementById('diary-ph').value || null
        };
        const res = editId ? await API.put(`/api/diary/${editId}`, data) : await API.post('/api/diary', data);
        if (res.success) {
            document.getElementById('modal-diary').classList.remove('active');
            loadDiary();
            showToast("Erfolgreich gespeichert", "success");
        }
    });

    // Neue Pflanze anlegen (Settings)
    document.getElementById('form-add-plant')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = {
            name: document.getElementById('new-plant-name').value,
            description: document.getElementById('new-plant-desc').value
        };
        const res = await API.post('/api/plants', data);
        if (res.success) {
            showToast("Pflanze angelegt", "success");
            e.target.reset();
            loadDiary(); // Refresh sidebar/datalist
        }
    });

    loadDiary();
});

