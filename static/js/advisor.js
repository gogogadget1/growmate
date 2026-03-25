async function loadAdvisor() {
    const container = document.getElementById('advisor-tips');
    if (!container) return;

    // Wir laden die Historie parallel
    loadAdvisorHistory();

    try {
        const res = await API.get('/api/analysis');
        if (res.success && res.data) {
            if (res.data.length === 0) {
                container.innerHTML = '<p class="text-muted">Aktuell keine besonderen Hinweise. Deine Pflanzen scheinen sich wohlzufühlen!</p>';
                return;
            }

            container.innerHTML = res.data.map(tip => `
                <div class="advisor-tip ${tip.type === 'warning' ? 'warning' : ''}">
                    <h4>${tip.type === 'warning' ? '🚨' : (tip.title.includes('🤖') ? '' : '💡')} ${escapeHtml(tip.title)}</h4>
                    <p>${escapeHtml(tip.message)}</p>
                    ${tip.scientific_ref ? `<span class="scientific-ref">${escapeHtml(tip.scientific_ref)}</span>` : ''}
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="text-danger">Fehler beim Laden der Analyse.</p>';
        }
    } catch (e) {
        console.error("Advisor Error:", e);
        container.innerHTML = '<p class="text-danger">Systemfehler bei der Analyse.</p>';
    }
}

async function loadAdvisorHistory() {
    const feed = document.getElementById('advisor-history-feed');
    if (!feed) return;

    try {
        const res = await API.get('/api/analysis/history?limit=10');
        if (res.success && res.data) {
            if (res.data.length === 0) {
                feed.innerHTML = '<p class="text-muted text-sm">Noch keine historischen Daten verfügbar. Erster Check läuft...</p>';
                return;
            }

            feed.innerHTML = res.data.map(entry => {
                const tips = entry.results || [];
                const warningCount = tips.filter(t => t.type === 'warning').length;
                const aiCount = tips.filter(t => t.title.includes('🤖')).length;
                
                let summary = tips.length > 0 
                    ? `${tips.length} Erkenntnisse gefunden.`
                    : "Alle Systeme im grünen Bereich.";
                
                return `
                    <div class="history-item ${tips.length === 0 ? 'no-findings' : ''}">
                        <div class="history-header">
                            <span class="history-time">${formatTimestamp(entry.timestamp)}</span>
                            <div>
                                ${warningCount > 0 ? `<span class="history-tip-badge" style="background:var(--danger)">${warningCount} Warnung${warningCount > 1 ? 'en' : ''}</span>` : ''}
                                ${aiCount > 0 ? `<span class="history-tip-badge" style="background:var(--info)">AI</span>` : ''}
                            </div>
                        </div>
                        <div class="history-summary">${summary}</div>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        console.error("History Load Error:", e);
    }
}

let advisorInterval = null;

function startAdvisorPolling() {
    if (advisorInterval) clearInterval(advisorInterval);
    advisorInterval = setInterval(() => {
        if (GrowMate.currentPage === 'advisor') {
            loadAdvisor();
        }
    }, 60000); // Alle 60 Sekunden aktualisieren
}

// Initiale Load wenn die Seite direkt mit Hash aufgerufen wurde
document.addEventListener('DOMContentLoaded', () => {
    if (window.location.hash === '#advisor') {
        setTimeout(() => {
            if (typeof navigateTo === 'function') navigateTo('advisor');
        }, 100);
    }
});
