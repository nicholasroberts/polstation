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
function render(data) {
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
    card.querySelector('.badge').textContent = {live:'● Live · demo', stale:'Stale · demo', disconnected:'Disconnected'}[camera.state];
    card.querySelector('.model').textContent = `${camera.model} · simulated source`;
    card.querySelector('.exposure').textContent = `${(camera.exposure_us / 1000).toFixed(1)} ms`;
    card.querySelector('.gain').textContent = `${camera.gain_db.toFixed(1)} dB`;
    card.querySelector('.age').textContent = camera.age_seconds === null ? '—' : `${camera.age_seconds.toFixed(1)} s`;
    card.querySelector('.frame').textContent = camera.frame_number === null ? '—' : String(camera.frame_number).padStart(6, '0');
    card.querySelector('time').textContent = camera.captured_at_utc ? new Date(camera.captured_at_utc).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC') : 'No frame available';
    const img = card.querySelector('img');
    img.hidden = !camera.preview_svg;
    img.style.display = camera.preview_svg ? 'block' : 'none';
    // SVG is displayed as an image, never injected into the document DOM.
    if (camera.preview_svg) img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(camera.preview_svg)}`;
    else img.removeAttribute('src');
    const overlay = card.querySelector('.overlay');
    overlay.hidden = camera.state === 'live';
    overlay.textContent = camera.state === 'stale' ? 'Stale frame · simulated interruption' : 'No preview · simulated disconnect';
  });
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
    if (data.mode !== 'demo' || !Array.isArray(data.cameras)) throw new Error('Invalid demo response');
    render(data);
    lastSuccess = Date.now();
    error.hidden = true;
    document.querySelector('#connection').textContent = scenario.value === 'live' ? 'Three simulated feeds · refreshing every second' : 'Fault demonstration · camera 2 frozen, camera 3 disconnected';
  } catch (_) {
    if (ticket === sequence) markUnavailable('Cannot reach the demo source. Displayed frames are no longer live. Reconnecting automatically…');
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
