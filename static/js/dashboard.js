/**
 * dashboard.js
 * New Dashboard Logic
 */

window.loadDashboard = async function() {
    try {
        const res = await API.get('/api/dashboard');
        if (res.success) {
            renderStatusBar(res);
            renderTents(res.tents);
            
            // Show unassigned devices if they exist
            const unassignedCount = res.unassigned_count || 0;
            if (unassignedCount > 0) {
                const devRes = await API.get('/api/devices');
                if (devRes.success) {
                    const unassigned = devRes.data.filter(d => !d.tent_id);
                    renderUnassignedDevices(unassigned);
                }
            } else {
                const unSection = document.getElementById('unassignedSection');
                if (unSection) unSection.style.display = 'none';
            }

            renderEnergyWidget(res.energy);
            renderWarningsWidget(res.warnings);
            renderGrowthWidget(res.tents);
            renderJournal(res.journal_recent);
            renderAdvisorHints(res.advisor_hints);
            
            if (typeof checkSystemStatus === 'function') {
                checkSystemStatus();
            }
        }
    } catch (err) {
        console.error("Dashboard Load Error:", err);
    }
}

function renderStatusBar(data) {
    const isOk = data.warnings && data.warnings.length === 0;
    const bar = document.querySelector('.dash-statusbar');
    if (!bar) return;
    
    // Wir setzen das identische Layout wie global-tent-stats
    bar.className = 'glass tent-stats-card dash-statusbar';
    bar.style.padding = '24px 32px';
    
    const now = new Date();
    const unassignedCount = data.unassigned_count || 0;
    
    bar.innerHTML = `
        <div class="tent-stat-block">
            <span class="label">⚡ GESAMTLEISTUNG</span>
            <span class="value" style="color: var(--accent-sun)">${data.energy.watts_now} <span style="font-size:0.9rem">W</span></span>
            <span class="sub">${data.energy.kwh_today} kWh heute</span>
        </div>
        <div class="divider"></div>
        <div class="tent-stat-block">
            <span class="label">✅ STATUS</span>
            <span class="value" style="font-size: 2.2rem;"><span style="color: ${isOk ? 'var(--text-primary)' : 'var(--warn-red)'}">${data.tents.length}</span> <span style="font-size:0.9rem; color:var(--text-muted)">Zelte</span></span>
            <div class="ratio-bar" style="height: 4px; background: rgba(255,255,255,0.1); margin-top: 8px; border-radius: 2px;">
                <div class="online" style="width:${isOk ? '100%' : '50%'}; background: ${isOk ? 'var(--accent-bio)' : 'var(--warn-red)'}; height: 100%; border-radius: 2px;"></div>
            </div>
        </div>
        <div class="divider"></div>
        <div class="tent-stat-block">
            <span class="label">🔌 GERÄTE</span>
            <span class="value" style="color: ${unassignedCount > 0 ? 'var(--warn-amber)' : 'inherit'}">${unassignedCount}</span>
            <span class="sub">${unassignedCount > 0 ? '<span style="color:var(--warn-amber)">Nicht zugewiesen</span>' : 'Zugewiesen'}</span>
        </div>
        <div class="divider"></div>
        <div class="tent-stat-block">
            <span class="label">⚠️ WARNUNGEN</span>
            <span class="value" style="color: ${data.warnings.length > 0 ? 'var(--warn-red)' : 'var(--text-muted)'}">${data.warnings.length}</span>
            <span class="sub">${data.warnings.length > 0 ? 'Aktive Fehler' : 'Alles OK'}</span>
        </div>
        <div class="divider"></div>
        <div class="tent-stat-block">
            <span class="label"> Letztes Update</span>
            <span class="value" style="font-size: 1.1rem">${now.toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'})}</span>
            <span class="sub" style="display:flex; align-items:center; gap:4px;"><span class="status-dot" style="position:static; width:6px; height:6px; background:var(--accent-bio); border-radius:50%;"></span> Synchron</span>
        </div>
    `;
}

function renderSegBar(value, min, max, warn, crit) {
    if (value === null || value === undefined) return '<div class="seg-bar">' + '<span></span>'.repeat(20) + '</div>';
    
    const segments = 20;
    const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
    const filledSegments = Math.round((pct / 100) * segments);
    
    let html = '<div class="seg-bar">';
    for (let i = 0; i < segments; i++) {
        if (i < filledSegments) {
            if (value >= crit) html += '<span class="fill-crit"></span>';
            else if (value >= warn) html += '<span class="fill-warn"></span>';
            else html += '<span class="fill-ok"></span>';
        } else {
            html += '<span></span>';
        }
    }
    html += '</div>';
    return html;
}

function formatCountdown(seconds) {
    if (!seconds) return "00:00";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
}

function renderTents(tents) {
    const grid = document.getElementById('tentGrid');
    if (!grid) return;
    
    grid.innerHTML = ''; // Vor dem Rendern leeren
    
    if (!tents || tents.length === 0) {
        grid.innerHTML = `<div class="dash-widget"><div class="empty-state">Keine Zelte konfiguriert.</div></div>`;
        return;
    }
    
    let html = '';
    tents.forEach(tent => {
        const tempBar = renderSegBar(tent.sensors.temp, 15, 35, 28, 30);
        const humBar = renderSegBar(tent.sensors.rlf, 30, 90, 70, 80);
        const vpdBar = renderSegBar(tent.sensors.vpd, 0.4, 2.0, 1.4, 1.6);
        const co2Bar = renderSegBar(tent.sensors.co2 || 400, 300, 2000, 1200, 1500);
        
        const lightPct = tent.light.is_on ? 100 : 0;
        const nextLight = tent.light.next_change_seconds > 0 ? `Wechsel in ${formatCountdown(tent.light.next_change_seconds)}` : 'Manuell / Dauerlicht';
        
        const canvasId = `sparkline-${tent.id}`;

        html += `
            <div class="glass tent-card-hero">
                <div class="tc-header">
                    <div>
                        <h3 class="tc-title">🌱 ${escapeHtml(tent.name)}</h3>
                        <div class="tc-subtitle" style="color:var(--text-muted); font-weight:500;">${escapeHtml(tent.strain)} • ${escapeHtml(tent.phase)}</div>
                    </div>
                    <div class="tc-badge">Tag ${tent.day_current} / ${tent.day_total}</div>
                </div>
                
                <div class="tc-metrics" style="background: rgba(0,0,0,0.2); padding: 16px; border-radius: 12px; margin-bottom:24px;">
                    <div class="tc-metric-item">
                        <div class="tc-metric-label">Temperatur</div>
                        <div class="tc-metric-val" style="color:var(--accent-heat)">${tent.sensors.temp !== null ? tent.sensors.temp.toFixed(1) : '--'} <span class="tc-metric-unit">°C</span></div>
                        ${tempBar}
                    </div>
                    <div class="tc-metric-item">
                        <div class="tc-metric-label">Luftfeuchte</div>
                        <div class="tc-metric-val" style="color:var(--accent-water)">${tent.sensors.rlf !== null ? tent.sensors.rlf.toFixed(1) : '--'} <span class="tc-metric-unit">%</span></div>
                        ${humBar}
                    </div>
                    <div class="tc-metric-item">
                        <div class="tc-metric-label">VPD</div>
                        <div class="tc-metric-val" style="color:var(--accent-bio)">${tent.sensors.vpd !== null ? tent.sensors.vpd.toFixed(2) : '--'} <span class="tc-metric-unit">kPa</span></div>
                        ${vpdBar}
                    </div>
                    <div class="tc-metric-item">
                        <div class="tc-metric-label">CO2</div>
                        <div class="tc-metric-val">${tent.sensors.co2 !== null ? tent.sensors.co2 : '--'} <span class="tc-metric-unit">ppm</span></div>
                        ${co2Bar}
                    </div>
                </div>
                
                <div class="tc-light">
                    <div class="tc-light-header">
                        <span style="font-weight:600; font-size:0.8rem; text-transform:uppercase; letter-spacing:0.06em;">Lichtzyklus</span>
                        <span class="${tent.light.is_on ? 'tc-light-active' : 'tc-light-inactive'}">${tent.light.is_on ? 'AN' : 'AUS'} • ${nextLight}</span>
                    </div>
                    <div class="light-strip">
                        <div class="${tent.light.is_on ? 'light-on' : 'light-off'}" style="width: ${lightPct}%"></div>
                    </div>
                </div>
                
                <div class="tc-sparkline">
                    <canvas id="${canvasId}"></canvas>
                </div>
                
                <div class="advisor-chip">
                    ⚡ ${escapeHtml(tent.advisor_hint || 'System läuft normal.')}
                </div>
            </div>
        `;
    });
    
    grid.innerHTML = html;
    
    // Draw sparklines for each tent (mocking logic since API doesn't specify which device)
    setTimeout(() => {
        tents.forEach(tent => {
            drawSparkline(`sparkline-${tent.id}`, tent.id);
        });
    }, 100);
}

function renderUnassignedDevices(devices) {
    const grid = document.getElementById('unassignedSection');
    const container = document.getElementById('unassignedGrid');
    if (!grid || !container) return;
    
    if (!devices || devices.length === 0) {
        grid.style.display = 'none';
        return;
    }
    
    grid.style.display = 'block';
    container.innerHTML = devices.map(d => {
        const isOnline = d.online !== false;
        const icon = d.category === 'sensor' ? '🌡️' : '🔌';
        const val = d.power_w ? `${d.power_w.toFixed(1)}W` : (d.temperature ? `${d.temperature.toFixed(1)}°C` : 'Bereit');
        
        return `
            <div class="glass mini-card" style="padding: 12px; display:flex; align-items:center; gap:12px; min-width:180px;">
                <span style="font-size:1.2rem;">${icon}</span>
                <div style="flex:1; overflow:hidden;">
                    <div style="font-size:0.85rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(d.name)}</div>
                    <div style="font-size:0.75rem; color:var(--text-muted); display:flex; justify-content:space-between;">
                        <span>${escapeHtml(d.type)}</span>
                        <span style="color:${isOnline ? 'var(--accent-bio)' : 'var(--warn-red)'}">${val}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function drawSparkline(canvasId, tentId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    
    // Wir mocken den Graphen als Platzhalter für "Mini Chart.js Line-Chart letzte 24h"
    const fakeData = Array.from({length: 24}, () => 20 + Math.random() * 5);
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: fakeData.map((_, i) => `${i}h`),
            datasets: [{
                data: fakeData,
                borderColor: '#2dff7e',
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false, min: 15, max: 30 } },
            layout: { padding: 0 }
        }
    });
}

function renderEnergyWidget(energy) {
    const w = document.getElementById('widget-energy');
    if (!w) return;
    w.className = "glass dash-widget";
    w.innerHTML = `
        <div class="widget-title">⚡ Energieverbrauch</div>
        <div style="font-family:'Space Grotesk',sans-serif; font-size:2rem; font-weight:800; color:var(--accent-sun); margin-top:8px;">
            ${energy.watts_now} <span style="font-size:1rem; color:var(--text-muted)">W</span>
        </div>
        <div style="font-size:0.9rem; color:var(--text-muted); margin-top:4px;">
            Heute: ${energy.kwh_today} kWh
        </div>
    `;
}

function renderWarningsWidget(warnings) {
    const w = document.getElementById('widget-warnings');
    if (!w) return;
    w.className = "glass dash-widget";
    if (!warnings || warnings.length === 0) {
        w.innerHTML = `
            <div class="widget-title" style="color:var(--text-muted)">⚠️ Systemwarnungen</div>
            <div style="color:var(--text-muted); margin-top:16px;">
                Keine Systemwarnungen aktiv. Alles im grünen Bereich.
            </div>
        `;
        return;
    }
    
    let html = `<div class="widget-title" style="color:var(--warn-red)">⚠️ Meldungen (${warnings.length})</div>`;
    html += `<ul style="margin: 16px 0 0 0; padding-left: 20px; font-size:0.9rem; color:var(--text-primary);">`;
    warnings.forEach(warn => {
        html += `<li style="margin-bottom:8px;">${escapeHtml(warn.message || warn)}</li>`;
    });
    html += `</ul>`;
    w.innerHTML = html;
}

function renderGrowthWidget(tents) {
    const w = document.getElementById('widget-growth');
    if (!w) return;
    w.className = "glass dash-widget";
    let html = `<div class="widget-title">🌿 Zyklus-Fortschritt</div>`;
    
    if (!tents || tents.length === 0) {
        html += `<div style="color:var(--text-dim); margin-top:16px;">Keine Zelte konfiguriert.</div>`;
    } else {
        html += `<div style="display:flex; flex-direction:column; gap:16px; margin-top:16px;">`;
        tents.forEach(tent => {
            const pct = tent.day_total > 0 ? Math.min(100, (tent.day_current / tent.day_total) * 100) : 0;
            html += `
                <div class="growth-row">
                    <div class="growth-header">
                        <span>${escapeHtml(tent.name)}</span>
                        <span style="font-family:'Space Grotesk',sans-serif; font-weight:700;">${tent.day_current} // ${tent.day_total}</span>
                    </div>
                    <div class="growth-progress">
                        <div class="growth-progress-fill" style="width: ${pct}%"></div>
                    </div>
                </div>
            `;
        });
        html += `</div>`;
    }
    
    w.innerHTML = html;
}

function renderJournal(entries) {
    const strip = document.getElementById('journalStrip');
    if (!strip) return;
    
    strip.innerHTML = ''; // Vor dem Rendern leeren
    let html = '';
    entries.forEach(e => {
        html += `
            <div class="glass journal-entry" style="padding: 16px; display:flex; gap:16px;">
                <div class="journal-icon">${e.icon}</div>
                <div class="journal-content">
                    <div class="journal-time">${escapeHtml(e.time)}</div>
                    <div class="journal-text">${escapeHtml(e.text)}</div>
                </div>
            </div>
        `;
    });
    
    strip.innerHTML = html;
}

function renderAdvisorHints(hints) {
    const strip = document.getElementById('advisorStrip');
    if (!strip) return;
    
    strip.innerHTML = ''; // Vor dem Rendern leeren
    let html = '';
    hints.forEach(h => {
        html += `
            <div class="glass journal-entry" style="padding: 16px; display:flex; gap:16px; border-left: 3px solid var(--accent-bio);">
                <div class="journal-icon" style="background: rgba(45,255,126,0.1);">🧠</div>
                <div class="journal-content">
                    <div class="journal-time">${escapeHtml(h.time)}</div>
                    <div class="journal-text">${escapeHtml(h.text)}</div>
                </div>
            </div>
        `;
    });
    
    strip.innerHTML = html;
}

document.addEventListener('DOMContentLoaded', () => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'dashboard' || hash === '') {
        window.loadDashboard();
    }
});
