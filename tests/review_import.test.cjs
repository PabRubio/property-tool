const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/assets/review.js'), 'utf8');
const brief = {schema_version: 2, inputs: {
  enquiry: {kind: 'area', area: 'Manchester', budget: 250000, terms_accepted: true},
  investor: {name: 'Example investor', email: 'investor@example.com'},
  property: {}, assumptions: {},
}};

async function dashboard() {
  const elements = new Map(), requests = [], records = [], warnings = [], alerts = [];
  let failure = null, ready = false;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, value: '', textContent: '', innerHTML: '', files: [], hidden: false, disabled: false,
      handlers: {}, classList: {add() {}, remove() {}, toggle() {}},
      addEventListener(name, handler) { this.handlers[name] = handler; },
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; },
      closest() { return element(id + '-zone'); },
      click() { this.clicked = true; },
    });
    return elements.get(id);
  }
  const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
  const fetch = async (url, options = {}) => {
    if (url === '/api/config') return response({token: 'local-token', default_provider: 'none'});
    if (url === '/api/records' && options.method === 'POST') {
      const payload = JSON.parse(options.body);
      requests.push({payload, headers: options.headers});
      if (failure) return response({error: failure}, 400);
      const record = {id: 'a'.repeat(32), revision: 1, status: 'needs_follow_up', mode: 'manual',
        inputs: payload.inputs, photos: [], artifacts: {}, analysis: null, approval: null};
      records.push(record);
      return response(record, 201);
    }
    if (url === '/api/records') return response({records: records.map(r => ({
      id: r.id, address: r.inputs.enquiry.area, postcode: 'Area enquiry', status: r.status,
    }))});
    const record = records.find(r => url === '/api/records/' + r.id);
    assert.ok(record, 'Unexpected request: ' + url);
    return response(record);
  };
  vm.runInNewContext(source, {
    document: {getElementById: element, querySelectorAll: () => [], hidden: false},
    window: {addEventListener() {}, alert: text => alerts.push(text)}, history: {replaceState() {}}, location: {search: ''},
    localStorage: {getItem() { return null; }, setItem() {}, removeItem() {}},
    fetch, File, FormData, URL, URLSearchParams, setTimeout, clearTimeout,
    setInterval() { ready = true; return 0; }, console: {warn: text => warnings.push(text)},
  });
  for (let i = 0; i < 50 && !ready; i++) await new Promise(resolve => setTimeout(resolve, 5));
  assert.ok(ready, 'Dashboard must finish loading');
  return {
    element, requests, records, warnings, alerts,
    reject(message) { failure = message; },
    async upload(contents, size) {
      const input = element('brief-file');
      input.files = contents === undefined ? [] : [{size: size ?? Buffer.byteLength(contents), text: async () => contents}];
      input.value = 'investor-brief.json';
      assert.equal(typeof input.handlers.change, 'function', 'Dashboard must accept a selected brief file');
      await input.handlers.change({preventDefault() {}});
    },
  };
}

test('the plus opens the file picker even with no submissions', async () => {
  const ui = await dashboard();
  assert.equal(ui.element('submissions-title').hidden, false);
  assert.equal(ui.element('import-brief').disabled, false);
  assert.equal(typeof ui.element('import-brief').handlers.click, 'function');
  ui.element('import-brief').handlers.click();
  assert.equal(ui.element('brief-file').clicked, true);
});

test('an exported brief is submitted through the local API and opened', async () => {
  const ui = await dashboard();
  await ui.upload(JSON.stringify({...brief, mode: 'demo', artifacts: {pdf: 'untrusted.pdf'}}));
  assert.equal(ui.requests.length, 1);
  assert.deepEqual(ui.requests[0].payload, {inputs: brief.inputs});
  assert.equal(ui.requests[0].headers['X-Local-Token'], 'local-token');
  assert.equal(ui.element('record-title').textContent, 'Manchester');
  assert.equal(ui.element('area-panel').hidden, false);
  assert.deepEqual(ui.alerts, []);
  assert.equal(ui.element('brief-file').value, '');
  assert.equal(ui.element('import-brief').disabled, false);
});

test('invalid JSON and unsupported exports are explained without creating records', async () => {
  for (const contents of ['{broken', 'null', '[]', '{}', JSON.stringify({...brief, schema_version: 99}),
    JSON.stringify({...brief, inputs: null}), JSON.stringify({...brief, inputs: []})]) {
    const ui = await dashboard();
    await ui.upload(contents);
    assert.equal(ui.requests.length, 0);
    assert.equal(ui.alerts.length, 1);
    assert.match(ui.alerts[0], /JSON|brief|version/i);
    assert.equal(ui.element('brief-file').value, '');
    assert.equal(ui.element('import-brief').disabled, false);
  }
});

test('oversized files are rejected before reading or posting', async () => {
  const ui = await dashboard();
  await ui.upload(JSON.stringify(brief), 1024 * 1024 + 1);
  assert.equal(ui.requests.length, 0);
  assert.match(ui.alerts[0], /1 MB/);
});

test('server validation errors are visible and a corrected file can be retried', async () => {
  const ui = await dashboard();
  ui.reject('Contact email is required');
  await ui.upload(JSON.stringify(brief));
  assert.equal(ui.records.length, 0);
  assert.deepEqual(ui.alerts, ['Contact email is required']);
  ui.reject(null);
  await ui.upload(JSON.stringify(brief));
  assert.equal(ui.records.length, 1);
  assert.equal(ui.alerts.length, 1);
});

test('cancelling the picker creates no record or error', async () => {
  const ui = await dashboard();
  await ui.upload(undefined);
  assert.equal(ui.requests.length, 0);
  assert.deepEqual(ui.alerts, []);
});
