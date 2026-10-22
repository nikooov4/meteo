const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { runInNewContext } = require('node:vm');

const html = readFileSync(join(__dirname, '../web/map_viewer.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

async function createViewer(width = 1200) {
  const elements = new Map();
  const element = name => {
    if (!elements.has(name)) elements.set(name, {
      style: {}, dataset: {}, value: '0', textContent: '', hidden: false, attributes: new Map(),
      setAttribute(key, value) { this.attributes.set(key, value); },
      appendChild() {}, replaceChildren() {}, addEventListener() {},
    });
    return elements.get(name);
  };
  const origin = '2023-01-01T06:00:00+00:00';
  const end = '2023-01-02T06:00:00+00:00';
  const info = {
    bbox: [-180, 180, -90, 90], intervals: [[origin, '2023-01-01T07:00:00+00:00']],
    member: 0, origin: 'original', label: 'ERA5 LSP', grid_shape: [1, 1],
    archive_api: '/map-archive', manifest_sha256: 'control', downloads_available: true,
    initial_selection: { first_hour: 0, hours: 24, member: 0, start_utc: origin, end_utc: end },
  };
  const catalog = {
    kind: 'era5', manifest_sha256: 'control', streaming: false,
    grid_shape: [1, 1], frame_bytes: 4, data_bytes: 96, file_count: 1,
    available_hours: 24, gap_hours: 0, available_ranges: [], color_max_mm: 50,
    members: [{ member: 0, hours: 24, start_utc: origin, end_utc: end }],
  };
  const timers = new Map(), held = new Set(), pending = new Map(), displayed = [];
  const stage = element('map-stage'), plot = { style: {} };
  stage.clientWidth = width;
  element('speed').value = '250';
  element('play').setAttribute('aria-pressed', 'false');
  let timerId = 0, resize;
  const document = {
    hidden: false, fullscreenEnabled: false,
    getElementById: element, querySelector: () => element('viewer'), querySelectorAll: () => [],
    createElement: () => ({ value: '', textContent: '' }), addEventListener() {},
  };
  const window = {};
  runInNewContext(script.replace('__MAP_INFO_JSON__', JSON.stringify(info)), {
    window, document, URLSearchParams, AbortController, DOMException, Float32Array,
    setTimeout(callback, delay) { const handle = ++timerId; timers.set(handle, { callback, delay }); return handle; },
    clearTimeout(handle) { timers.delete(handle); },
    ResizeObserver: class { constructor(callback) { resize = callback; } observe() {} },
    Plotly: {
      async relayout() {},
      async update(target, data) { displayed.push(data.z[0][0][0]); },
    },
    async fetch(url) {
      if (url.endsWith('/catalog')) return { ok: true, json: async () => catalog };
      const hour = Number(new URL(url, 'http://localhost').searchParams.get('hour'));
      const response = {
        ok: true, arrayBuffer: async () => new Float32Array([hour]).buffer,
        headers: { get: name => name === 'X-Data-Available' ? 'true' : origin },
      };
      if (held.has(hour)) return new Promise((resolve, reject) => {
        pending.set(hour, { resolve: () => resolve(response), reject });
      });
      return response;
    },
  });
  window.initMeteoMap(plot);
  await settle();
  assert.equal(element('map-status').textContent, '');
  assert.equal(displayed.at(-1), 0);
  return {
    plot, stage, displayed, pending, held, timers,
    get playing() { return element('play').attributes.get('aria-pressed') === 'true'; },
    get error() { return element('map-status').textContent; },
    clickPlay() { element('play').onclick(); },
    async seek(hour) { element('timeline').value = String(hour); await element('timeline').oninput(); await settle(); },
    async tick() {
      assert.equal(timers.size, 1);
      const [handle, timer] = timers.entries().next().value;
      timers.delete(handle);
      await timer.callback(); await settle();
    },
    async resize(nextWidth) { stage.clientWidth = nextWidth; await resize(); await settle(); },
  };
}

test('seeking while playing continues from the chosen hour with one timer', async () => {
  const viewer = await createViewer();
  viewer.clickPlay();
  await viewer.seek(10);
  assert.equal(viewer.playing, true);
  assert.equal(viewer.displayed.at(-1), 10);
  assert.equal(viewer.timers.size, 1);
  await viewer.tick();
  assert.equal(viewer.displayed.at(-1), 11);
  assert.equal(viewer.playing, true);
});

test('seeking while paused does not start playback', async () => {
  const viewer = await createViewer();
  await viewer.seek(8);
  assert.equal(viewer.displayed.at(-1), 8);
  assert.equal(viewer.playing, false);
  assert.equal(viewer.timers.size, 0);
});

test('pausing during a slow seek prevents playback from restarting', async () => {
  const viewer = await createViewer();
  viewer.clickPlay(); viewer.held.add(6);
  const seeking = viewer.seek(6);
  await settle(); viewer.clickPlay();
  viewer.pending.get(6).resolve(); await seeking;
  assert.equal(viewer.displayed.at(-1), 6);
  assert.equal(viewer.playing, false);
  assert.equal(viewer.timers.size, 0);
});

test('rapid seeks ignore the late older frame and resume only the newest seek', async () => {
  const viewer = await createViewer();
  viewer.clickPlay(); viewer.held.add(3);
  const olderSeek = viewer.seek(3);
  await settle(); await viewer.seek(7);
  viewer.pending.get(3).resolve(); await olderSeek;
  assert.equal(viewer.displayed.at(-1), 7);
  assert.equal(viewer.timers.size, 1);
  await viewer.tick();
  assert.equal(viewer.displayed.at(-1), 8);
});

test('a late failure from an obsolete playback tick cannot pause a new seek', async () => {
  const viewer = await createViewer();
  viewer.clickPlay(); viewer.held.add(1);
  const olderTick = viewer.tick();
  await settle(); await viewer.seek(7);
  viewer.pending.get(1).reject(new Error('obsolete request failed')); await olderTick;
  assert.equal(viewer.playing, true);
  assert.equal(viewer.error, '');
  assert.equal(viewer.timers.size, 1);
  await viewer.tick();
  assert.equal(viewer.displayed.at(-1), 8);
});

test('a current seek error stops playback instead of scheduling more requests', async () => {
  const viewer = await createViewer();
  viewer.clickPlay(); viewer.held.add(4);
  const seeking = viewer.seek(4);
  await settle(); viewer.pending.get(4).reject(new Error('current request failed')); await seeking;
  assert.equal(viewer.playing, false);
  assert.equal(viewer.timers.size, 0);
  assert.match(viewer.error, /current request failed/);
});

test('the map fills the container width and preserves geographic proportions on resize', async () => {
  const viewer = await createViewer(1200);
  assert.equal(viewer.plot.style.width, '1200px');
  assert.equal(viewer.stage.style.height, '628px');
  for (const width of [640, 360, 2480]) {
    await viewer.resize(width);
    assert.equal(viewer.plot.style.width, width + 'px');
    assert.equal(Number.parseFloat(viewer.plot.style.height), Math.round((width - 76) / 2 + 66));
  }
});

test('playback controls remain below the larger map', () => {
  assert.ok(html.indexOf('<nav class="controls"') > html.indexOf('<section id="map-stage"'));
  assert.doesNotMatch(html, /\.controls\s*\{[^}]*position:\s*(sticky|fixed)/);
  assert.doesNotMatch(html, /\.viewer\s*\{[^}]*max-width:/);
});
