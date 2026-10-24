const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { runInNewContext } = require('node:vm');

const html = readFileSync(join(__dirname, '../web/map_viewer.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const settle = () => new Promise(resolve => setImmediate(resolve));

async function createViewer(width = 1200, {sourceAt = () => [{Name:'осадки.nc',Format:'NetCDF',Cells:1}], animate = false,
  fullscreenApi = 'native', reducedMotion = false} = {}) {
  const elements = new Map();
  const element = name => {
    if (!elements.has(name)) elements.set(name, {
      style: {}, dataset: {}, value: '0', textContent: '', hidden: false, attributes: new Map(),
      setAttribute(key, value) { this.attributes.set(key, value); },
      classList: { toggle() {} }, focus() {},
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
  const timers = new Map(), held = new Set(), pending = new Map(), displayed = [], exports = [], layouts = [], titles = [];
  const stage = element('map-stage'), plot = { style: {} };
  stage.clientWidth = width;
  element('speed').value = '250';
  element('play').setAttribute('aria-pressed', 'false');
  let timerId = 0, resize;
  let animationTime = 0;
  const events = new Map();
  const player = element('map-player');
  const document = {
    hidden: false, fullscreenEnabled: fullscreenApi !== 'unavailable', fullscreenElement: null, body: element('body'),
    getElementById: element, querySelector: selector => element(selector === '.controls' ? 'controls' : 'viewer'), querySelectorAll: () => [],
    createElement: () => ({ value: '', textContent: '' }), addEventListener(name, callback) { events.set(name, callback); },
    async exitFullscreen() { document.fullscreenElement = null; events.get('fullscreenchange')(); },
  };
  player.requestFullscreen = async () => {
    if (fullscreenApi === 'denied') throw new Error('Denied by embedded browser');
    document.fullscreenElement = player; events.get('fullscreenchange')();
  };
  const window = {matchMedia: () => ({matches: reducedMotion})};
  runInNewContext(script.replace('__MAP_INFO_JSON__', JSON.stringify(info)), {
    window, document, URLSearchParams, AbortController, DOMException, Float32Array,
    setTimeout(callback, delay) { const handle = ++timerId; timers.set(handle, { callback, delay }); return handle; },
    requestAnimationFrame: animate ? callback => setImmediate(() => callback(animationTime += 40)) : undefined,
    clearTimeout(handle) { timers.delete(handle); },
    ResizeObserver: class { constructor(callback) { resize = callback; } observe() {} },
    Plotly: {
      async relayout(target, layout) { layouts.push(layout); },
      async update(target, data, layout) { displayed.push(data.z[0][0][0]); if (layout['title.text']) titles.push(layout['title.text']); },
      async downloadImage(target, options) { exports.push(options); },
    },
    async fetch(url) {
      if (url.endsWith('/catalog')) return { ok: true, json: async () => catalog };
      const hour = Number(new URL(url, 'http://localhost').searchParams.get('hour'));
      const response = {
        ok: true, arrayBuffer: async () => new Float32Array([hour]).buffer,
        headers: { get: name => ({'X-Data-Available':'true','X-Cycle-UTC':origin,
          'X-Frame-Sources':encodeURIComponent(JSON.stringify(sourceAt(hour)))})[name] ?? null },
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
    get source() { return element('frame-source').textContent; },
    get hour() { return element('hour').textContent; },
    get expanded() { return element('fullscreen').attributes.get('aria-pressed') === 'true'; },
    get nativeFullscreen() { return document.fullscreenElement === player; },
    async toggleFullscreen(width, height) {
      stage.clientWidth = width; stage.clientHeight = height;
      await element('fullscreen').onclick(); await settle();
    },
    async escapeFullscreen(width) {
      stage.clientWidth = width;
      await events.get('keydown')({key:'Escape'});
      await settle();
    },
    async exportImage(format) { await element(format).onclick(); },
    exports, layouts, titles,
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

test('the caption in the map header follows the displayed frame, including mixed sources', async () => {
  const viewer = await createViewer(1200, {sourceAt: hour => hour === 7
    ? [{Name:'осадки.nc',Format:'NetCDF',Cells:3},{Name:'дополнение.grib',Format:'GRIB',Cells:1}]
    : [{Name:'резерв.tif',Format:'GeoTIFF',Cells:1}]});
  assert.match(viewer.source, /резерв\.tif · GeoTIFF/);
  viewer.held.add(3);
  const older = viewer.seek(3);
  await settle(); await viewer.seek(7);
  viewer.pending.get(3).resolve(); await older;
  assert.match(viewer.source, /осадки\.nc · NetCDF \(75%\)/);
  assert.match(viewer.source, /дополнение\.grib · GRIB \(25%\)/);
  assert.match(viewer.source, /^Кадры файла:/);
  assert.ok(html.indexOf('id="frame-source"') > html.indexOf('<section id="map-stage"'));
  assert.ok(html.indexOf('id="frame-source"') < html.indexOf('<div class="window-tools"'));
});

test('an adjacent source change blends during playback and ends at the exact new value', async () => {
  const viewer = await createViewer(1200, {animate:true, sourceAt: hour =>
    [{Name:hour === 0 ? 'first.nc' : 'next.grib',Format:hour === 0 ? 'NetCDF' : 'GRIB',Cells:1}]});
  viewer.clickPlay(); await viewer.tick();
  assert.ok(viewer.displayed.some(value => value > 0 && value < 1));
  assert.equal(viewer.displayed.at(-1), 1);
  assert.match(viewer.source, /next.grib · GRIB/);
});

test('manual seeks show exact observations immediately', async () => {
  const viewer = await createViewer(1200, {animate:true, sourceAt: hour =>
    [{Name:hour + '.nc',Format:'NetCDF',Cells:1}]});
  await viewer.seek(8);
  assert.deepEqual(viewer.displayed, [0,8]);
  viewer.clickPlay(); await viewer.seek(9);
  assert.deepEqual(viewer.displayed, [0,8,9]);
});

test('source transitions still respect the system reduced motion setting', async () => {
  const viewer = await createViewer(1200, {animate:true, reducedMotion:true, sourceAt: hour =>
    [{Name:hour + '.nc',Format:'NetCDF',Cells:1}]});
  viewer.clickPlay(); await viewer.tick();
  assert.deepEqual(viewer.displayed, [0,1]);
});

test('Google NetCDF frames advance during playback with their file caption', async () => {
  const viewer = await createViewer(1200, {sourceAt: () => [{Name:'era5-arco-lsp-20230101.nc',Format:'NetCDF',Cells:1}]});
  viewer.clickPlay();
  for (let hour=1;hour<=3;hour++) { await viewer.tick(); assert.equal(viewer.displayed.at(-1),hour); }
  assert.equal(viewer.source,'Кадры файла: era5-arco-lsp-20230101.nc · NetCDF');
});

test('PNG and JPEG export the selected hour while the map title omits the time', async () => {
  const viewer = await createViewer();
  await viewer.seek(8);
  await viewer.exportImage('png'); await viewer.exportImage('jpeg');
  assert.deepEqual(viewer.exports.map(options => options.format),['png','jpeg']);
  assert.ok(viewer.exports.every(options => options.filename.includes('2023-01-01T15-00')));
  assert.ok(viewer.titles.every(title => title === 'Осадки · LSP'));
  assert.match(viewer.hour,/2023-01-01 · 14:00–15:00 UTC/);
  assert.doesNotMatch(html,/smooth-transition|Плавная смена файлов/);
});

test('fullscreen scales the map and controls together without stretching the geographic field', async () => {
  const viewer = await createViewer();
  viewer.clickPlay(); await viewer.seek(8);
  await viewer.toggleFullscreen(1920,900);
  assert.equal(viewer.expanded,true);
  assert.equal(viewer.nativeFullscreen,true);
  assert.equal(viewer.plot.style.width,'1920px');
  assert.equal(viewer.plot.style.height,'900px');
  const layout = viewer.layouts.at(-1);
  const innerWidth = layout.width-layout['margin.l']-layout['margin.r'];
  const innerHeight = layout.height-layout['margin.t']-layout['margin.b'];
  assert.equal(innerWidth/innerHeight,2);
  assert.equal(viewer.playing,true);
  assert.equal(viewer.displayed.at(-1),8);
  await viewer.tick(); assert.equal(viewer.displayed.at(-1),9);
  await viewer.escapeFullscreen(1200);
  assert.equal(viewer.expanded,false);
  assert.equal(viewer.plot.style.width,'1200px');
  assert.equal(viewer.plot.style.height,'628px');
  assert.equal(viewer.playing,true);
  assert.equal(viewer.layouts.at(-1)['margin.l'],8);
  assert.equal(viewer.layouts.at(-1)['margin.r'],68);
  const playerHtml = html.slice(html.indexOf('<div id="map-player"'),html.indexOf('\n  <details>',html.indexOf('<div id="map-player"')));
  assert.match(playerHtml,/id="map-stage"/);
  assert.match(playerHtml,/class="controls"/);
  assert.match(playerHtml,/id="fullscreen"/);
});

test('fullscreen also fits tall viewports and exits by its button', async () => {
  const viewer = await createViewer();
  await viewer.toggleFullscreen(600,1000);
  const layout = viewer.layouts.at(-1);
  assert.equal((layout.width-layout['margin.l']-layout['margin.r'])/
    (layout.height-layout['margin.t']-layout['margin.b']),2);
  await viewer.toggleFullscreen(1200,628);
  assert.equal(viewer.expanded,false);
  assert.equal(viewer.nativeFullscreen,false);
});

test('embedded browsers can expand within the window when native fullscreen is denied or unavailable', async () => {
  for (const fullscreenApi of ['denied','unavailable']) {
    const viewer = await createViewer(1200,{fullscreenApi});
    await viewer.toggleFullscreen(1200,700);
    assert.equal(viewer.expanded,true);
    assert.equal(viewer.nativeFullscreen,false);
    assert.equal(viewer.error,'');
    await viewer.escapeFullscreen(1200);
    assert.equal(viewer.expanded,false);
    assert.equal(viewer.plot.style.height,'628px');
  }
});
