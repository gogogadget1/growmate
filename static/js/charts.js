/**
 * GrowMate – Charts Modul
 * Chart.js basierte Diagramme für Temperatur, Feuchtigkeit, Energie und Pflanzenhöhe.
 */

// ─── Chart Instanzen ────────────────────────────────────────────────
const charts = {};

// ─── Gemeinsame Chart-Optionen ──────────────────────────────────────

const chartDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
        intersect: false,
        mode: 'index',
    },
    plugins: {
        legend: {
            display: true,
            position: 'top',
            labels: {
                color: 'rgba(200, 230, 201, 0.7)',
                font: { family: 'Inter', size: 12 },
                padding: 16,
                usePointStyle: true,
                pointStyleWidth: 10,
            },
        },
        tooltip: {
            backgroundColor: 'rgba(10, 18, 14, 0.95)',
            titleColor: '#e8f5e9',
            bodyColor: 'rgba(200, 230, 201, 0.8)',
            borderColor: 'rgba(76, 175, 80, 0.3)',
            borderWidth: 1,
            cornerRadius: 8,
            padding: 12,
            titleFont: { family: 'Inter', weight: '600' },
            bodyFont: { family: 'Inter' },
        },
    },
    scales: {
        x: {
            type: 'time',
            time: {
                displayFormats: {
                    minute: 'HH:mm',
                    hour: 'HH:mm',
                    day: 'dd.MM',
                },
                tooltipFormat: 'dd.MM.yyyy HH:mm',
            },
            grid: {
                color: 'rgba(76, 175, 80, 0.06)',
                drawBorder: false,
            },
            ticks: {
                color: 'rgba(200, 230, 201, 0.4)',
                font: { family: 'Inter', size: 11 },
                maxTicksLimit: 10,
            },
        },
        y: {
            grid: {
                color: 'rgba(76, 175, 80, 0.06)',
                drawBorder: false,
            },
            ticks: {
                color: 'rgba(200, 230, 201, 0.4)',
                font: { family: 'Inter', size: 11 },
            },
        },
    },
};

// ─── Dashboard Mini-Charts ──────────────────────────────────────────

async function loadDashboardCharts() {
    const res = await API.get('/api/sensors/history?hours=24');
    if (!res.success || !res.data) return;

    const data = res.data;

    // Gruppiere nach Sensor
    const sensors = {};
    data.forEach(r => {
        if (!sensors[r.sensor_name]) sensors[r.sensor_name] = [];
        sensors[r.sensor_name].push(r);
    });

    const sensorNames = Object.keys(sensors);
    const colors = ['#ff7043', '#42a5f5', '#66bb6a', '#ffa726', '#ab47bc'];

    // ─── Temperatur Mini-Chart ─────────────────────────────────
    createOrUpdateChart('chart-temp-mini', {
        type: 'line',
        data: {
            datasets: sensorNames.map((name, i) => ({
                label: name,
                data: sensors[name].map(r => ({
                    x: new Date(r.timestamp),
                    y: parseFloat(r.temperature) || 0,
                })),
                borderColor: colors[i % colors.length],
                backgroundColor: colors[i % colors.length] + '15',
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                borderWidth: 2,
            })),
        },
        options: {
            ...chartDefaults,
            plugins: {
                ...chartDefaults.plugins,
                legend: { ...chartDefaults.plugins.legend, display: sensorNames.length > 1 },
            },
            scales: {
                ...chartDefaults.scales,
                y: {
                    ...chartDefaults.scales.y,
                    title: { display: true, text: '°C', color: 'rgba(200,230,201,0.4)', font: { family: 'Inter' } },
                },
            },
        },
    });

    // ─── Feuchtigkeit Mini-Chart ───────────────────────────────
    createOrUpdateChart('chart-hum-mini', {
        type: 'line',
        data: {
            datasets: sensorNames.map((name, i) => ({
                label: name,
                data: sensors[name].map(r => ({
                    x: new Date(r.timestamp),
                    y: parseFloat(r.humidity) || 0,
                })),
                borderColor: '#42a5f5',
                backgroundColor: '#42a5f515',
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                borderWidth: 2,
            })),
        },
        options: {
            ...chartDefaults,
            plugins: {
                ...chartDefaults.plugins,
                legend: { ...chartDefaults.plugins.legend, display: sensorNames.length > 1 },
            },
            scales: {
                ...chartDefaults.scales,
                y: {
                    ...chartDefaults.scales.y,
                    title: { display: true, text: '%', color: 'rgba(200,230,201,0.4)', font: { family: 'Inter' } },
                    min: 0,
                    max: 100,
                },
            },
        },
    });
}

// ─── History Page Charts ────────────────────────────────────────────

async function loadHistoryCharts() {
    const hours = parseInt(document.getElementById('history-timerange').value) || 24;

    await Promise.all([
        loadTempHistory(hours),
        loadHumHistory(hours),
        loadEnergyHistory(hours),
        loadPlantHeightChart(),
    ]);
}

async function loadTempHistory(hours) {
    const res = await API.get(`/api/sensors/history?hours=${hours}`);
    if (!res.success || !res.data) return;

    const sensors = groupBySensor(res.data);
    const sensorNames = Object.keys(sensors);
    const colors = ['#ff7043', '#e53935', '#ff8a65', '#d84315', '#bf360c'];

    createOrUpdateChart('chart-temp-history', {
        type: 'line',
        data: {
            datasets: sensorNames.map((name, i) => ({
                label: name,
                data: sensors[name].map(r => ({ x: new Date(r.timestamp), y: parseFloat(r.temperature) || 0 })),
                borderColor: colors[i % colors.length],
                backgroundColor: colors[i % colors.length] + '10',
                fill: true,
                tension: 0.3,
                pointRadius: 1,
                pointHoverRadius: 5,
                borderWidth: 2,
            })),
        },
        options: {
            ...chartDefaults,
            scales: {
                ...chartDefaults.scales,
                y: {
                    ...chartDefaults.scales.y,
                    title: { display: true, text: 'Temperatur (°C)', color: 'rgba(200,230,201,0.5)', font: { family: 'Inter' } },
                },
            },
        },
    });
}

async function loadHumHistory(hours) {
    const res = await API.get(`/api/sensors/history?hours=${hours}`);
    if (!res.success || !res.data) return;

    const sensors = groupBySensor(res.data);
    const sensorNames = Object.keys(sensors);
    const colors = ['#42a5f5', '#1e88e5', '#64b5f6', '#1565c0', '#0d47a1'];

    createOrUpdateChart('chart-hum-history', {
        type: 'line',
        data: {
            datasets: sensorNames.map((name, i) => ({
                label: name,
                data: sensors[name].map(r => ({ x: new Date(r.timestamp), y: parseFloat(r.humidity) || 0 })),
                borderColor: colors[i % colors.length],
                backgroundColor: colors[i % colors.length] + '10',
                fill: true,
                tension: 0.3,
                pointRadius: 1,
                pointHoverRadius: 5,
                borderWidth: 2,
            })),
        },
        options: {
            ...chartDefaults,
            scales: {
                ...chartDefaults.scales,
                y: {
                    ...chartDefaults.scales.y,
                    title: { display: true, text: 'Feuchtigkeit (%)', color: 'rgba(200,230,201,0.5)', font: { family: 'Inter' } },
                    min: 0,
                    max: 100,
                },
            },
        },
    });
}

async function loadEnergyHistory(hours) {
    const res = await API.get(`/api/energy/history?hours=${hours}`);
    if (!res.success || !res.data) return;

    const devices = {};
    res.data.forEach(r => {
        if (!devices[r.device_name]) devices[r.device_name] = [];
        devices[r.device_name].push(r);
    });

    const deviceNames = Object.keys(devices);
    const colors = ['#ffa726', '#ff9800', '#ffb74d', '#f57c00', '#e65100'];

    createOrUpdateChart('chart-energy-history', {
        type: 'line',
        data: {
            datasets: deviceNames.map((name, i) => ({
                label: name,
                data: devices[name].map(r => ({ x: new Date(r.timestamp), y: parseFloat(r.power_w) || 0 })),
                borderColor: colors[i % colors.length],
                backgroundColor: colors[i % colors.length] + '10',
                fill: true,
                tension: 0.3,
                pointRadius: 1,
                pointHoverRadius: 5,
                borderWidth: 2,
            })),
        },
        options: {
            ...chartDefaults,
            scales: {
                ...chartDefaults.scales,
                y: {
                    ...chartDefaults.scales.y,
                    title: { display: true, text: 'Leistung (W)', color: 'rgba(200,230,201,0.5)', font: { family: 'Inter' } },
                    beginAtZero: true,
                },
            },
        },
    });
}

async function loadPlantHeightChart() {
    const res = await API.get('/api/diary/heights');
    if (!res.success || !res.data || res.data.length === 0) {
        // Leeres Chart oder Hinweis anzeigen
        createOrUpdateChart('chart-plant-height', {
            type: 'line',
            data: { datasets: [] },
            options: {
                ...chartDefaults,
                plugins: {
                    ...chartDefaults.plugins,
                    legend: { display: false },
                },
            },
        });
        return;
    }

    const plants = {};
    res.data.forEach(r => {
        const name = r.plant_name || 'Allgemein';
        if (!plants[name]) plants[name] = [];
        plants[name].push({
            x: new Date(r.entry_date + 'T00:00:00'),
            y: parseFloat(r.plant_height_cm) || 0,
        });
    });

    const colors = ['#ab47bc', '#4db6ac', '#ffb74d', '#64b5f6', '#f06292', '#aed581'];
    const datasets = Object.keys(plants).sort().map((name, i) => {
        const c = colors[i % colors.length];
        return {
            label: name,
            data: plants[name],
            borderColor: c,
            backgroundColor: c + '15',
            fill: true,
            tension: 0.3,
            pointRadius: 4,
            pointHoverRadius: 7,
            pointBackgroundColor: c,
            borderWidth: 2,
        };
    });

    createOrUpdateChart('chart-plant-height', {
        type: 'line',
        data: { datasets: datasets },
        options: {
            ...chartDefaults,
            scales: {
                x: {
                    ...chartDefaults.scales.x,
                    time: {
                        ...chartDefaults.scales.x.time,
                        unit: 'day',
                        displayFormats: { day: 'dd.MM' },
                    },
                },
                y: {
                    ...chartDefaults.scales.y,
                    title: { display: true, text: 'Höhe (cm)', color: 'rgba(200,230,201,0.5)', font: { family: 'Inter' } },
                    beginAtZero: true,
                },
            },
            plugins: {
                ...chartDefaults.plugins,
                legend: { display: true, position: 'top', labels: { color: 'rgba(255,255,255,0.7)', font: { family: 'Inter' } } },
            },
        },
    });
}

// ─── Helpers ────────────────────────────────────────────────────────

function createOrUpdateChart(canvasId, config) {
    // Sicherheits-Zerstörung bestehender Instanzen
    if (window.myChartInstance) {
        window.myChartInstance.destroy();
    }
    if (charts[canvasId]) {
        charts[canvasId].destroy();
    }
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    const chartInstance = new Chart(ctx.getContext('2d'), config);
    charts[canvasId] = chartInstance;
    window.myChartInstance = chartInstance; // Globaler Ref für Debugging/User-Wunsch
}

function groupBySensor(data) {
    const sensors = {};
    data.forEach(r => {
        if (!sensors[r.sensor_name]) sensors[r.sensor_name] = [];
        sensors[r.sensor_name].push(r);
    });
    return sensors;
}

// ─── Event Listeners ────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('btn-refresh-history');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            refreshBtn.classList.add('spinning');
            loadHistoryCharts().finally(() => {
                setTimeout(() => refreshBtn.classList.remove('spinning'), 500);
            });
        });
    }
});
