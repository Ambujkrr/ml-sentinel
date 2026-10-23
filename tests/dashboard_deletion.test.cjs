// Run with: node --test tests/dashboard_deletion.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(require('node:path').join(__dirname, '../app/web/dashboard.js'), 'utf8');

function dashboard() {
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) elements.set(selector, {
      textContent: '', innerHTML: '', hidden: false, disabled: false, checked: false,
      handlers: {}, attributes: {}, children: [],
      addEventListener(type, handler) { this.handlers[type] = handler; },
      replaceChildren() { this.children = []; },
      appendChild(child) { this.children.push(child); },
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this.attributes[key]; },
      showModal() { this.open = true; },
      close() { this.open = false; this.handlers.close?.(); },
      classList: { toggle() {} },
    });
    return elements.get(selector);
  };
  const context = vm.createContext({
    document: { querySelector: element, addEventListener() {}, createElement: () => ({}) },
    setTimeout() {}, clearTimeout() {},
  });
  // Skip only automatic startup requests; execute the real rendering and handlers.
  vm.runInContext(source.slice(0, source.indexOf('// Metadata is read-only.')), context);
  const run = (code) => vm.runInContext(code, context);
  run(`state.datasets = [
    { id: 'first-id', name: 'Duplicate <name>', dataset_type: 'reference' },
    { id: 'second-id', name: 'Duplicate <name>', dataset_type: 'reference' }
  ];`);
  return { element, run, context };
}

test('Actions keeps reports public and only administrators see distinct ID deletion targets', () => {
  const { element, run } = dashboard();
  run('renderDatasets()');
  assert.match(element('#dataset-list').innerHTML, /ACTIONS/);
  assert.match(element('#dataset-list').innerHTML, /data-profile="first-id"/);
  assert.doesNotMatch(element('#dataset-list').innerHTML, /data-delete/);
  run('state.admin.authenticated = true; renderDatasets()');
  assert.match(element('#dataset-list').innerHTML, /data-delete="first-id"/);
  assert.match(element('#dataset-list').innerHTML, /data-delete="second-id"/);
  assert.match(element('#dataset-list').innerHTML, /Duplicate &lt;name&gt;/);
  run("state.demo = {model_id: 'demo'}; state.modelId = 'demo'; renderDatasets()");
  assert.doesNotMatch(element('#dataset-list').innerHTML, /data-delete/);
  assert.match(element('#dataset-list').innerHTML, /Protected demo/);
});

test('preview identifies the exact record; cancel sends no DELETE', async () => {
  const { element, run, context } = dashboard();
  const requests = [];
  context.fetch = async (path, options) => {
    requests.push([path, options]);
    return { ok: true, json: async () => ({ dataset_id: 'second-id', name: 'Duplicate <name>', removes: ['CSV'] }) };
  };
  run('state.admin.authenticated = true');
  await run("confirmDatasetDeletion('second-id')");
  assert.equal(element('#delete-dataset-id').textContent, 'second-id');
  assert.equal(element('#delete-dataset-name').textContent, 'Duplicate <name>');
  assert.equal(element('#delete-dialog').open, true);
  element('#delete-cancel').handlers.click();
  assert.equal(run('state.pendingDelete'), null);
  assert.equal(requests.length, 1);
  assert.match(requests[0][0], /second-id\/deletion-preview$/);
});

for (const failure of [false, true]) test(`confirmed deletion refreshes and shows ${failure ? 'error' : 'success'}`, async () => {
  const { element, run, context } = dashboard();
  let complete;
  const response = new Promise((resolve) => { complete = resolve; });
  const requests = [];
  context.fetch = (path, options) => { requests.push([path, options]); return response; };
  run(`state.pendingDelete = {dataset_id: 'second-id', name: 'Duplicate'};
    globalThis.refreshed = 0; loadAdminStatus = async () => {};
    refresh = async () => { globalThis.refreshed++; return true; };`);
  element('#delete-confirm').checked = true;
  const submission = element('#delete-form').handlers.submit({ preventDefault() {} });
  assert.equal(element('#delete-submit').disabled, true);
  assert.equal(element('#delete-submit').textContent, 'Deleting…');
  assert.equal(requests[0][0], '/datasets/second-id');
  assert.equal(requests[0][1].method, 'DELETE');
  assert.equal(requests[0][1].headers['X-Admin-Action'], 'dataset-delete');
  complete({ ok: !failure, json: async () => failure ? {detail: 'Dataset is used by monitoring comparisons'} : {} });
  await submission;
  assert.equal(run('globalThis.refreshed'), 1);
  assert.equal(element('#delete-submit').disabled, false);
  assert.equal(element('#delete-submit').attributes['aria-busy'], undefined);
  assert.match(element('#flash').textContent, failure ? /used by monitoring/ : /Removed Duplicate/);
});
