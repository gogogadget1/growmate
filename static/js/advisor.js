/**
 * GrowMate – Ratgeber
 * Analysiert Sensordaten gegen botanische Fachdaten.
 */

async function loadAdvisor() {
    const container = document.getElementById('advisor-tips');
    if (!container) return;

    container.innerHTML = '<div class="spinner"></div>';

    try {
        const res = await API.get('/api/analysis');
        if (res.success && res.data) {
            if (res.data.length === 0) {
                container.innerHTML = '<p class="text-muted">Aktuell keine besonderen Hinweise. Deine Pflanzen scheinen sich wohlzufühlen!</p>';
                return;
            }

            container.innerHTML = res.data.map(tip => `
                <div class="advisor-tip ${tip.type === 'warning' ? 'warning' : ''}">
                    <h4>${tip.type === 'warning' ? '🚨' : '💡'} ${escapeHtml(tip.title)}</h4>
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

// Initialisierung bei Seitenwechsel
document.addEventListener('DOMContentLoaded', () => {
    // Falls die App-Navigation advisor erkennt
    window.addEventListener('hashchange', () => {
        if (window.location.hash === '#advisor') {
            loadAdvisor();
        }
    });

    if (window.location.hash === '#advisor') {
        loadAdvisor();
    }
});
