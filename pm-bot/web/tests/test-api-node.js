/* Node.js unit tests for api.js */
/* Run: node web/tests/test-api-node.js */

var fs = require('fs');
var path = require('path');
var vm = require('vm');

var passed = 0;
var failed = 0;

function assert(name, condition, detail) {
  if (condition) {
    passed++;
    console.log('[PASS] ' + name);
  } else {
    failed++;
    console.log('[FAIL] ' + name + (detail ? ' -- ' + detail : ''));
  }
}

/* Mock sessionStorage for domain caching tests */
var _mockSessionData = {};
var mockSessionStorage = {
  getItem: function(k) { return _mockSessionData[k] || null; },
  setItem: function(k, v) { _mockSessionData[k] = String(v); },
  removeItem: function(k) { delete _mockSessionData[k]; },
  clear: function() { _mockSessionData = {}; }
};

/* Mock AbortController */
function MockAbortController() {
  this.signal = { aborted: false };
  this.abort = function() { this.signal.aborted = true; };
}

/* Load api.js in a sandboxed context */
var apiCode = fs.readFileSync(path.join(__dirname, '..', 'api.js'), 'utf8');
var sandbox = {
  fetch: function() { return Promise.resolve({ ok: true, json: function() { return {}; } }); },
  JSON: JSON,
  console: { log: function() {}, error: function() {} },
  Promise: Promise,
  encodeURIComponent: encodeURIComponent,
  Date: Date,
  parseInt: parseInt,
  String: String,
  AbortController: MockAbortController,
  sessionStorage: mockSessionStorage
};
vm.createContext(sandbox);
vm.runInContext(apiCode, sandbox);

/* Test API base URL */
assert('API base URL is correct', sandbox.API === 'http://localhost:8000/api/v1');

/* Test api object exists and has all methods */
assert('api object exists', typeof sandbox.api === 'object');
assert('api.ideas is function', typeof sandbox.api.ideas === 'function');
assert('api.meetings is function', typeof sandbox.api.meetings === 'function');
assert('api.tasks is function', typeof sandbox.api.tasks === 'function');
assert('api.epics is function', typeof sandbox.api.epics === 'function');
assert('api.timeline is function', typeof sandbox.api.timeline === 'function');
assert('api.reports is function', typeof sandbox.api.reports === 'function');
assert('api.reportByFilename is function', typeof sandbox.api.reportByFilename === 'function');
assert('api.capture is function', typeof sandbox.api.capture === 'function');
assert('api.regenerate is function', typeof sandbox.api.regenerate === 'function');
assert('api.pipeline is function', typeof sandbox.api.pipeline === 'function');

/* Test apiFetch is function */
assert('apiFetch is function', typeof sandbox.apiFetch === 'function');

/* Test api.domains.invalidate exists (P0-2) */
assert('api.domains.invalidate is function', typeof sandbox.api.domains.invalidate === 'function');

/* Test api methods count (13 total: ideas, meetings, tasks, epics, domains, timeline, reports, reportByFilename, capture, regenerate, pipeline, jiraImport, taskByKey) */
var methodCount = Object.keys(sandbox.api).length;
assert('api has 13 methods', methodCount === 13, 'got ' + methodCount);

/* Test that fetch is called with correct URLs */
var fetchCalls = [];
sandbox.fetch = function(url, opts) {
  fetchCalls.push({ url: url, opts: opts || {} });
  return Promise.resolve({
    ok: true,
    json: function() { return Promise.resolve([]); }
  });
};
vm.runInContext(apiCode, sandbox);

/* Test ideas call */
fetchCalls = [];
sandbox.api.ideas().then(function() {
  assert('api.ideas calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/ideas');
  assert('api.ideas uses GET', !fetchCalls[0].opts.method || fetchCalls[0].opts.method === 'GET');
  assert('api.ideas passes signal in opts', fetchCalls[0].opts.signal !== undefined);

  /* Test meetings with default days */
  fetchCalls = [];
  return sandbox.api.meetings();
}).then(function() {
  assert('api.meetings default URL has days=14', fetchCalls[0].url === 'http://localhost:8000/api/v1/meetings?days=14');

  /* Test meetings with custom days */
  fetchCalls = [];
  return sandbox.api.meetings(7);
}).then(function() {
  assert('api.meetings(7) URL has days=7', fetchCalls[0].url === 'http://localhost:8000/api/v1/meetings?days=7');

  /* Test tasks */
  fetchCalls = [];
  return sandbox.api.tasks();
}).then(function() {
  assert('api.tasks calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/tasks');

  /* Test epics */
  fetchCalls = [];
  return sandbox.api.epics();
}).then(function() {
  assert('api.epics calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/epics');

  /* Test domains (P0-2: first call should hit the API, not cache) */
  fetchCalls = [];
  sandbox.api.domains.invalidate(); // ensure cache is clear
  return sandbox.api.domains();
}).then(function() {
  assert('api.domains calls correct URL on first call', fetchCalls[0].url === 'http://localhost:8000/api/v1/domains');

  /* Test domains cache: second call should NOT hit the API */
  fetchCalls = [];
  return sandbox.api.domains();
}).then(function() {
  assert('api.domains returns cached on second call (no fetch)', fetchCalls.length === 0, 'fetch was called ' + fetchCalls.length + ' times');

  /* Test domains.invalidate clears cache */
  sandbox.api.domains.invalidate();
  fetchCalls = [];
  return sandbox.api.domains();
}).then(function() {
  assert('api.domains fetches after invalidate', fetchCalls.length === 1);

  /* Test timeline */
  fetchCalls = [];
  return sandbox.api.timeline('CONT-412');
}).then(function() {
  assert('api.timeline calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/timeline/CONT-412');

  /* Test reports list */
  fetchCalls = [];
  return sandbox.api.reports();
}).then(function() {
  assert('api.reports calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/reports');

  /* Test reportByFilename */
  fetchCalls = [];
  return sandbox.api.reportByFilename('weekly-2026-05-03.md');
}).then(function() {
  assert('api.reportByFilename calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/reports/weekly-2026-05-03.md');

  /* Test capture */
  fetchCalls = [];
  return sandbox.api.capture('idea', 'test idea');
}).then(function() {
  assert('api.capture calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/capture');
  assert('api.capture uses POST', fetchCalls[0].opts.method === 'POST');
  assert('api.capture sets Content-Type', fetchCalls[0].opts.headers['Content-Type'] === 'application/json');
  var body = JSON.parse(fetchCalls[0].opts.body);
  assert('api.capture body has type', body.type === 'idea');
  assert('api.capture body has text', body.text === 'test idea');

  /* Test regenerate */
  fetchCalls = [];
  return sandbox.api.regenerate();
}).then(function() {
  assert('api.regenerate calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/report/regenerate');
  assert('api.regenerate uses POST', fetchCalls[0].opts.method === 'POST');

  /* Test pipeline */
  fetchCalls = [];
  return sandbox.api.pipeline();
}).then(function() {
  assert('api.pipeline calls correct URL', fetchCalls[0].url === 'http://localhost:8000/api/v1/pipeline');

  /* Summary */
  console.log('\n// SUMMARY: ' + passed + '/' + (passed + failed) + ' passed');
  if (failed > 0) process.exit(1);
}).catch(function(err) {
  console.error('[ERROR] ' + err.message);
  process.exit(1);
});
