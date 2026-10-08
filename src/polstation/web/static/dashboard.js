'use strict';
const cards = new Map();
const scenario = document.querySelector('#scenario');
const error = document.querySelector('#error');
let sequence = 0;
let lastSuccess = 0;
let activeController;

function markUnavailable(message) {
  error.hidden = false;
  error.textContent = message;
  document.querySelector('#connection').textContent = 'Preview connection unavailable';
  cards.forEach(card => {
    card.dataset.state = 'unavailable';
    card.querySelector('.badge').textContent = 'Unavailable';
    card.querySelector('.age').textContent = 'Unknown';
    card.querySelector('.overlay').hidden = false;
    card.querySelector('.overlay').textContent = card.querySelector('img').getAttribute('src') ? 'Preview unavailable · last image retained' : 'Preview unavailable · no image received';
  });
}
function renderPolarization(data, hardware) {
  const section = document.querySelector('#polarization');
  section.hidden = !hardware;
  if (!hardware) return;
  const polarization = data.polarization || {state: 'unavailable', error: 'No polarization preview received'};
  const live = polarization.state === 'live';
  const warning = document.querySelector('#polarization-warning');
  warning.textContent = polarization.relative_sensitivity_corrected
    ? `Sequential camera frames · spatially unregistered · temporally unsynchronized · relative sensitivity normalized (${polarization.calibration_id || 'calibration ID unavailable'}) · dark/flat uncorrected`
    : 'Sequential camera frames · spatially unregistered · temporally unsynchronized · radiometrically uncalibrated';
  document.querySelector('#polarization-status').textContent = live ? 'Diagnostic maps updating' : polarization.state === 'stale' ? 'Derived maps are stale' : polarization.error || 'Derived maps unavailable';
  for (const [kind, label] of [['dolp', 'DoLP'], ['aop', 'AoP']]) {
    const image = document.querySelector(`#${kind}-preview`);
    const legend = document.querySelector(`#${kind}-legend`);
    const preview = polarization[`${kind}_preview_png`];
    const scale = polarization[`${kind}_legend_png`];
    if (preview) image.src = `data:image/png;base64,${preview}`;
    else image.removeAttribute('src');
    if (scale) legend.src = `data:image/png;base64,${scale}`;
    else legend.removeAttribute('src');
    image.hidden = !preview;
    legend.hidden = !scale;
    const overlay = image.parentElement.querySelector('.derived-overlay');
    overlay.hidden = live;
    overlay.textContent = polarization.state === 'stale' ? `${label} preview is stale` : `${label} unavailable · ${polarization.error || 'waiting for configured camera frames'}`;
  }
}
function displayNumber(value, digits, unit) {
  return Number.isFinite(value) ? `${value.toFixed(digits)} ${unit}` : '—';
}
function sensorBadge(card, sensor, fault = false) {
  const badge = card.querySelector('.sensor-badge');
  card.dataset.state = fault ? 'fault' : sensor.state;
  badge.textContent = fault ? 'Fault reported' : sensor.state === 'live' ? '● Live' : sensor.state === 'stale' ? 'Stale' : 'Unavailable';
}
function sampleAge(sensor) {
  return Number.isFinite(sensor.age_seconds) ? `Sample age · ${sensor.age_seconds.toFixed(1)} s` : 'No current sample';
}
function renderSensors(data, hardware) {
  const section = document.querySelector('#telemetry');
  section.hidden = !hardware;
  if (!hardware) return;
  const sensors = data.sensors || {};
  const environment = sensors.bme280 || {state: 'unavailable', values: {}};
  const controller = sensors.epever || {state: 'unavailable', values: {}};
  const env = environment.values || {};
  const power = controller.values || {};
  const environmentCard = document.querySelector('#environment-card');
  sensorBadge(environmentCard, environment);
  document.querySelector('#env-temperature').textContent = displayNumber(env.temperature_c, 1, '°C');
  document.querySelector('#env-humidity').textContent = displayNumber(env.humidity_percent, 1, '%RH');
  document.querySelector('#env-pressure').textContent = displayNumber(env.pressure_hpa, 1, 'hPa');
  document.querySelector('#environment-age').textContent = sampleAge(environment);

  const fault = power.controller_fault === true;
  for (const id of ['solar-card', 'battery-card', 'power-card']) sensorBadge(document.querySelector(`#${id}`), controller, fault);
  document.querySelector('#pv-power').textContent = displayNumber(power.pv_power_w, 1, 'W');
  document.querySelector('#pv-voltage').textContent = displayNumber(power.pv_voltage_v, 2, 'V');
  document.querySelector('#pv-current').textContent = displayNumber(power.pv_current_a, 2, 'A');
  document.querySelector('#charge-stage').textContent = power.charging_stage || '—';
  document.querySelector('#pv-state').textContent = power.pv_input_state || '—';
  document.querySelector('#battery-soc').textContent = displayNumber(power.battery_soc_percent, 0, '%');
  document.querySelector('#battery-voltage').textContent = displayNumber(power.battery_voltage_v, 2, 'V');
  document.querySelector('#battery-current').textContent = displayNumber(power.battery_net_current_a, 2, 'A');
  document.querySelector('#battery-temperature').textContent = displayNumber(power.battery_temperature_c, 1, '°C');
  document.querySelector('#battery-state').textContent = power.battery_voltage_state || '—';
  document.querySelector('#load-power').textContent = displayNumber(power.load_power_w, 1, 'W');
  document.querySelector('#load-current').textContent = displayNumber(power.load_current_a, 2, 'A');
  document.querySelector('#controller-temperature').textContent = displayNumber(power.controller_temperature_c, 1, '°C');
  document.querySelector('#generated-today').textContent = displayNumber(power.generated_today_kwh, 2, 'kWh');
  document.querySelector('#consumed-today').textContent = displayNumber(power.consumed_today_kwh, 2, 'kWh');
  document.querySelector('#controller-age').textContent = sampleAge(controller);
  const liveCount = [environment, controller].filter(sensor => sensor.state === 'live').length;
  document.querySelector('#telemetry-status').textContent = fault ? 'MPPT controller fault reported' : `${liveCount}/2 sensor links live · read-only`;
}
function render(data) {
  const hardware = data.mode === 'hardware-preview';
  document.querySelector('#scenario-control').hidden = hardware;
  document.querySelector('#banner-title').textContent = hardware ? 'HARDWARE PREVIEW — not recording' : 'DEMO — no cameras connected';
  document.querySelector('#banner-detail').textContent = hardware ? 'Real camera frames. Sequential, unsynchronized and not saved as observations.' : 'All images and camera values are simulated. No scientific data is recorded.';
  document.querySelector('#source-label').textContent = hardware ? 'Vimba X · real cameras' : 'Simulation';
  document.querySelector('#channel-count').textContent = String(data.cameras.length).padStart(2, '0');
  document.querySelector('#footer-status').textContent = hardware ? 'Allied Vision Mako G-223B × 3 · live diagnostic' : 'Allied Vision Mako G-223B × 3 · simulated';
  renderSensors(data, hardware);
  const currentIds = new Set(data.cameras.map(camera => camera.id));
  cards.forEach((card, id) => { if (!currentIds.has(id)) { card.remove(); cards.delete(id); } });
  data.cameras.forEach((camera, index) => {
    let card = cards.get(camera.id);
    if (!card) {
      card = document.querySelector('#camera-template').content.firstElementChild.cloneNode(true);
      cards.set(camera.id, card);
      document.querySelector('#cameras').append(card);
    }
    card.dataset.state = camera.state;
    card.querySelector('.channel').textContent = `CHANNEL ${String(index + 1).padStart(2, '0')}`;
    card.querySelector('h3').textContent = camera.id.replaceAll('_', ' ');
    card.querySelector('.badge').textContent = camera.state === 'live' ? `● Live${camera.simulated ? ' · demo' : ''}` : camera.state === 'stale' ? `Stale${camera.simulated ? ' · demo' : ''}` : 'Disconnected';
    card.querySelector('.model').textContent = `${camera.model}${camera.simulated ? ' · simulated source' : ` · ${camera.pixel_format || 'format unknown'}`}`;
    card.querySelector('.exposure').textContent = Number.isFinite(camera.exposure_us) ? `${(camera.exposure_us / 1000).toFixed(1)} ms` : '—';
    card.querySelector('.gain').textContent = Number.isFinite(camera.gain_db) ? `${camera.gain_db.toFixed(1)} dB` : '—';
    card.querySelector('.age').textContent = camera.age_seconds === null ? '—' : `${camera.age_seconds.toFixed(1)} s`;
    card.querySelector('.frame').textContent = camera.frame_number === null ? '—' : String(camera.frame_number).padStart(6, '0');
    card.querySelector('time').textContent = camera.captured_at_utc ? new Date(camera.captured_at_utc).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC') : 'No frame available';
    const img = card.querySelector('img');
    // Preview payloads are displayed as images, never injected into the document DOM.
    const preview = camera.preview_svg || camera.preview_png;
    if (camera.preview_svg) img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(camera.preview_svg)}`;
    else if (camera.preview_png) img.src = `data:image/png;base64,${camera.preview_png}`;
    else img.removeAttribute('src');
    img.hidden = !preview;
    img.style.display = preview ? 'block' : 'none';
    const overlay = card.querySelector('.overlay');
    overlay.hidden = camera.state === 'live';
    overlay.textContent = camera.state === 'stale' ? 'Stale frame' : 'No current preview';
  });
  renderPolarization(data, hardware);
}
async function refresh() {
  const ticket = ++sequence;
  if (activeController) activeController.abort();
  const controller = new AbortController();
  activeController = controller;
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch(`/api/previews?scenario=${encodeURIComponent(scenario.value)}`, {signal:controller.signal, cache:'no-store'});
    if (!response.ok) throw new Error('Preview request failed');
    const data = await response.json();
    if (ticket !== sequence) return;
    if (!['demo', 'hardware-preview'].includes(data.mode) || !Array.isArray(data.cameras)) throw new Error('Invalid preview response');
    if (data.error) throw new Error(data.error);
    render(data);
    lastSuccess = Date.now();
    error.hidden = true;
    document.querySelector('#connection').textContent = data.mode === 'hardware-preview' ? `${data.cameras.length} real camera previews · sequential and unsynchronized` : scenario.value === 'live' ? 'Three simulated feeds · refreshing every second' : 'Fault demonstration · camera 2 frozen, camera 3 disconnected';
  } catch (_) {
    if (ticket === sequence) markUnavailable('Cannot reach the preview source. Displayed frames are no longer live. Reconnecting automatically…');
  } finally {
    clearTimeout(timeout);
    if (ticket === sequence) setTimeout(refresh, 1000);
  }
}
scenario.addEventListener('change', () => { if (activeController) activeController.abort(); });
setInterval(() => {
  document.querySelector('#clock').textContent = new Date().toLocaleTimeString();
  if (lastSuccess && Date.now() - lastSuccess > 5000) markUnavailable('Preview updates have stopped. Displayed frames are no longer live.');
}, 1000);
refresh();
