/* Node.js unit tests for report.html */
/* Run: node web/tests/test-report-node.js */

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

/* ========================================
   Test 1: report.html file exists
   ======================================== */
var reportPath = path.join(__dirname, '..', 'report.html');
var reportHtml = fs.readFileSync(reportPath, 'utf8');
assert('report.html exists and is non-empty', reportHtml.length > 0);

/* ========================================
   Test 2: HTML structure
   ======================================== */
assert('has DOCTYPE', reportHtml.indexOf('<!DOCTYPE html>') >= 0);
assert('has lang=ru', reportHtml.indexOf('lang="ru"') >= 0);
assert('has charset UTF-8', reportHtml.indexOf('charset="UTF-8"') >= 0);
assert('has viewport meta', reportHtml.indexOf('viewport') >= 0);
assert('has title with Report', reportHtml.indexOf('<title>') >= 0 && reportHtml.indexOf('Report') >= 0);
assert('links style.css', reportHtml.indexOf('href="style.css"') >= 0);
assert('loads Vue 3 from CDN', reportHtml.indexOf('vue@3') >= 0 || reportHtml.indexOf('vue.global.prod.js') >= 0);
assert('loads marked.js from CDN', reportHtml.indexOf('marked/marked.min.js') >= 0 || reportHtml.indexOf('marked.min.js') >= 0);
assert('loads api.js', reportHtml.indexOf('src="api.js"') >= 0);
assert('loads components.js', reportHtml.indexOf('src="components.js"') >= 0);

/* ========================================
   Test 3: Vue app setup
   ======================================== */
assert('uses Vue.createApp', reportHtml.indexOf('Vue.createApp') >= 0);
assert('uses setup function (Composition API)', reportHtml.indexOf('setup:') >= 0 || reportHtml.indexOf('setup(') >= 0);
assert('calls registerComponents', reportHtml.indexOf('registerComponents(app)') >= 0);
assert('mounts on #app', reportHtml.indexOf("app.mount('#app')") >= 0 || reportHtml.indexOf('app.mount("#app")') >= 0);
assert('calls registerComponents before mount',
  reportHtml.indexOf('registerComponents(app)') < reportHtml.indexOf("app.mount('#app')"));

/* ========================================
   Test 4: Template elements
   ======================================== */
assert('has app-sidebar with active=report', reportHtml.indexOf('app-sidebar') >= 0 && reportHtml.indexOf('active="report"') >= 0);
assert('has page-title WEEKLY_REPORT', reportHtml.indexOf('WEEKLY_REPORT') >= 0);
assert('has REGENERATE button', reportHtml.indexOf('REGENERATE') >= 0);
assert('has COPY_MARKDOWN button', reportHtml.indexOf('COPY_MARKDOWN') >= 0);
assert('has cmd-button components', reportHtml.indexOf('cmd-button') >= 0);
assert('has loading state', reportHtml.indexOf('LOADING') >= 0);
assert('has report-content div', reportHtml.indexOf('report-content') >= 0);
assert('uses v-html for rendered markdown', reportHtml.indexOf('v-html') >= 0);
assert('has COPIED success text', reportHtml.indexOf('COPIED') >= 0);
assert('has v-cloak on #app', reportHtml.indexOf('v-cloak') >= 0);

/* ========================================
   Test 4b: Two-column layout elements
   ======================================== */
assert('has report-layout container', reportHtml.indexOf('report-layout') >= 0);
assert('has report-list-panel', reportHtml.indexOf('report-list-panel') >= 0);
assert('has report-detail-panel', reportHtml.indexOf('report-detail-panel') >= 0);
assert('has report-list-item class', reportHtml.indexOf('report-list-item') >= 0);
assert('has report-list-scroll', reportHtml.indexOf('report-list-scroll') >= 0);
assert('has report-detail-scroll', reportHtml.indexOf('report-detail-scroll') >= 0);
assert('has report-detail-filename', reportHtml.indexOf('report-detail-filename') >= 0);
assert('has empty state for no reports', reportHtml.indexOf('No reports available') >= 0);
assert('has empty state for no selection', reportHtml.indexOf('Select a report from the list') >= 0);
assert('has report-list-header REPORTS', reportHtml.indexOf('REPORTS') >= 0);
assert('does NOT have reportFilename display in header', reportHtml.indexOf('reportFilename') === -1 || reportHtml.indexOf('selectedFilename') >= 0);

/* ========================================
   Test 5: Data properties exist in setup
   ======================================== */
assert('has reports ref', reportHtml.indexOf("var reports = Vue.ref") >= 0);
assert('has selectedFilename ref', reportHtml.indexOf("var selectedFilename = Vue.ref") >= 0);
assert('has reportContent ref', reportHtml.indexOf("var reportContent = Vue.ref") >= 0);
assert('has loading ref', reportHtml.indexOf("var loading = Vue.ref") >= 0);
assert('has loadingContent ref', reportHtml.indexOf("var loadingContent = Vue.ref") >= 0);
assert('has regenerating ref', reportHtml.indexOf("var regenerating = Vue.ref") >= 0);
assert('has error ref', reportHtml.indexOf("var error = Vue.ref") >= 0);
assert('has copySuccess ref', reportHtml.indexOf("var copySuccess = Vue.ref") >= 0);

/* ========================================
   Test 6: Methods exist
   ======================================== */
assert('has loadReports method', reportHtml.indexOf('function loadReports') >= 0);
assert('has selectReport method', reportHtml.indexOf('function selectReport') >= 0);
assert('has regenerate method', reportHtml.indexOf('function regenerate') >= 0);
assert('has copyMarkdown method', reportHtml.indexOf('function copyMarkdown') >= 0);
assert('has renderMarkdown method', reportHtml.indexOf('function renderMarkdown') >= 0);
assert('has formatDate method', reportHtml.indexOf('function formatDate') >= 0);
assert('does NOT have renderMarkdownToHtml function', reportHtml.indexOf('function renderMarkdownToHtml') === -1);
assert('does NOT have applyInline function', reportHtml.indexOf('function applyInline') === -1);

/* ========================================
   Test 7: API calls
   ======================================== */
assert('calls api.reports()', reportHtml.indexOf('api.reports()') >= 0);
assert('calls api.reportByFilename()', reportHtml.indexOf('api.reportByFilename(') >= 0);
assert('calls api.regenerate()', reportHtml.indexOf('api.regenerate()') >= 0);
assert('uses navigator.clipboard.writeText', reportHtml.indexOf('navigator.clipboard.writeText') >= 0);

/* ========================================
   Test 8: Lifecycle
   ======================================== */
assert('uses onMounted', reportHtml.indexOf('onMounted') >= 0);
assert('onMounted calls loadReports', reportHtml.indexOf('loadReports()') >= 0);

/* ========================================
   Test 9: Console logging
   ======================================== */
var logMatches = reportHtml.match(/console\.log/g);
assert('has console.log calls (>= 5)', logMatches && logMatches.length >= 5, 'got ' + (logMatches ? logMatches.length : 0));
var errorLogMatches = reportHtml.match(/console\.error/g);
assert('has console.error calls (>= 2)', errorLogMatches && errorLogMatches.length >= 2, 'got ' + (errorLogMatches ? errorLogMatches.length : 0));

/* ========================================
   Test 10: Report-specific CSS
   ======================================== */
assert('has .report-content CSS', reportHtml.indexOf('.report-content {') >= 0 || reportHtml.indexOf('.report-content{') >= 0);
assert('has .report-content h1 CSS', reportHtml.indexOf('.report-content h1') >= 0);
assert('has .report-content h2 CSS', reportHtml.indexOf('.report-content h2') >= 0);
assert('has .report-content h3 CSS', reportHtml.indexOf('.report-content h3') >= 0);
assert('has .report-content ul CSS', reportHtml.indexOf('.report-content ul') >= 0);
assert('has .report-content li CSS', reportHtml.indexOf('.report-content li') >= 0);
assert('has .report-content p CSS', reportHtml.indexOf('.report-content p') >= 0);
assert('has .report-content strong CSS', reportHtml.indexOf('.report-content strong') >= 0);
assert('has .report-content hr CSS', reportHtml.indexOf('.report-content hr') >= 0);
assert('has .report-content code CSS', reportHtml.indexOf('.report-content code') >= 0);
assert('has .report-content pre CSS', reportHtml.indexOf('.report-content pre') >= 0);
assert('has .report-content blockquote CSS', reportHtml.indexOf('.report-content blockquote') >= 0);
assert('has .report-content table CSS', reportHtml.indexOf('.report-content table') >= 0);
assert('has .report-content a CSS', reportHtml.indexOf('.report-content a') >= 0);
assert('has .report-content ol CSS', reportHtml.indexOf('.report-content ol') >= 0);
assert('has .report-content .contains-task-list CSS', reportHtml.indexOf('.report-content .contains-task-list') >= 0);
assert('CSS uses var(--cyan)', reportHtml.indexOf('var(--cyan)') >= 0);
assert('CSS uses var(--yellow)', reportHtml.indexOf('var(--yellow)') >= 0);
assert('CSS uses var(--card)', reportHtml.indexOf('var(--card)') >= 0);
assert('CSS uses var(--border)', reportHtml.indexOf('var(--border)') >= 0);

/* ========================================
   Test 10b: Two-column layout CSS
   ======================================== */
assert('has .report-layout CSS', reportHtml.indexOf('.report-layout') >= 0);
assert('has .report-list-panel CSS', reportHtml.indexOf('.report-list-panel') >= 0);
assert('has .report-list-item CSS', reportHtml.indexOf('.report-list-item {') >= 0);
assert('has .report-list-item:hover CSS', reportHtml.indexOf('.report-list-item:hover') >= 0);
assert('has .report-list-item.active CSS', reportHtml.indexOf('.report-list-item.active') >= 0);
assert('has .report-date CSS', reportHtml.indexOf('.report-date') >= 0);
assert('has .report-title CSS', reportHtml.indexOf('.report-title') >= 0);
assert('has .report-detail-panel CSS', reportHtml.indexOf('.report-detail-panel') >= 0);
assert('has .report-detail-empty CSS', reportHtml.indexOf('.report-detail-empty') >= 0);
assert('report-list-panel width is 280px', reportHtml.indexOf('width: 280px') >= 0);
assert('report-list-item has cyan active border', reportHtml.indexOf('border-left-color: var(--cyan)') >= 0);
assert('CSS uses var(--text-muted)', reportHtml.indexOf('var(--text-muted)') >= 0);
assert('CSS uses var(--text-body)', reportHtml.indexOf('var(--text-body)') >= 0);

/* ========================================
   Test 11: Error handling
   ======================================== */
assert('has .catch for API calls', reportHtml.indexOf('.catch') >= 0);
assert('sets error on load failure', reportHtml.indexOf('Failed to load report') >= 0);
assert('sets error on regenerate failure', reportHtml.indexOf('Failed to regenerate report') >= 0);
assert('handles AbortError gracefully', reportHtml.indexOf("err.name === 'AbortError'") >= 0);

/* ========================================
   Test 12: Copy success timeout (2 seconds)
   ======================================== */
assert('copySuccess resets after timeout', reportHtml.indexOf('setTimeout') >= 0);
assert('timeout is 2000ms', reportHtml.indexOf('2000') >= 0);

/* ========================================
   Test 13: Frontmatter stripping
   ======================================== */
assert('has stripFrontmatter function', reportHtml.indexOf('stripFrontmatter') >= 0);

/* ========================================
   Test 14: Extract and test stripFrontmatter function (marked.js migration)
   ======================================== */
(function() {
  /* Verify removed functions are absent from the HTML source */
  assert('renderMarkdownToHtml is NOT defined in HTML', reportHtml.indexOf('function renderMarkdownToHtml') === -1);
  assert('applyInline is NOT defined in HTML', reportHtml.indexOf('function applyInline') === -1);

  /* Extract only the stripFrontmatter function (now directly followed by var app) */
  var fnMatch = reportHtml.match(/function stripFrontmatter[\s\S]*?(?=\n\s*var app)/);
  if (!fnMatch) {
    assert('stripFrontmatter function extractable', false, 'could not extract stripFrontmatter from HTML');
    return;
  }

  var sandbox = {
    console: { log: function() {}, error: function() {} }
  };
  vm.createContext(sandbox);
  vm.runInContext(fnMatch[0], sandbox);

  /* Test stripFrontmatter */
  assert('stripFrontmatter is function', typeof sandbox.stripFrontmatter === 'function');

  /* With frontmatter */
  var withFm = '---\ndate: 2026-04-27\nweek: 18\n---\n# Report\nContent here';
  var stripped = sandbox.stripFrontmatter(withFm);
  assert('stripFrontmatter removes frontmatter', stripped.indexOf('date:') === -1);
  assert('stripFrontmatter keeps content', stripped.indexOf('# Report') >= 0);
  assert('stripFrontmatter keeps body', stripped.indexOf('Content here') >= 0);

  /* Without frontmatter */
  var withoutFm = '# Report\nContent here';
  var result = sandbox.stripFrontmatter(withoutFm);
  assert('stripFrontmatter passes through without frontmatter', result.indexOf('# Report') >= 0);

  /* Empty input */
  assert('stripFrontmatter handles empty string', sandbox.stripFrontmatter('') === '');
  assert('stripFrontmatter handles null', sandbox.stripFrontmatter(null) === '');
})();

/* ========================================
   Test 14b: marked.js integration assertions
   ======================================== */
assert('marked.min.js CDN script is present', reportHtml.indexOf('marked/marked.min.js') >= 0 || reportHtml.indexOf('marked.min.js') >= 0);
assert('marked.use( configuration is present', reportHtml.indexOf('marked.use(') >= 0);
assert('marked.parse( is used in renderMarkdown', reportHtml.indexOf('marked.parse(') >= 0);
assert('marked.Renderer is instantiated', reportHtml.indexOf('new marked.Renderer') >= 0 || reportHtml.indexOf('marked.Renderer()') >= 0);
assert('marked.version log is present', reportHtml.indexOf('marked.version') >= 0);

/* ========================================
   Test 15: Regenerating state
   ======================================== */
assert('regenerating state used in button :loading', reportHtml.indexOf(':loading="regenerating"') >= 0);
assert('regenerating set to true before call', reportHtml.indexOf('regenerating.value = true') >= 0);
assert('regenerating set to false after call', reportHtml.indexOf('regenerating.value = false') >= 0);

/* ========================================
   Test 16: Color scheme for buttons
   ======================================== */
assert('REGENERATE button is magenta', reportHtml.indexOf('label="REGENERATE" color="magenta"') >= 0);
assert('COPY_MARKDOWN button is cyan', reportHtml.indexOf('label="COPY_MARKDOWN" color="cyan"') >= 0);

/* ========================================
   Test 17: Regenerate flow reloads list and auto-selects
   ======================================== */
assert('regenerate reloads report list', reportHtml.indexOf('api.reports()') >= 0);
assert('regenerate auto-selects new report', reportHtml.indexOf('selectReport(newFilename)') >= 0 || reportHtml.indexOf('selectReport(list[0].filename)') >= 0);

/* ========================================
   Test 18: Theme detection script
   ======================================== */
assert('has matrix theme applied', reportHtml.indexOf('theme-matrix') >= 0);
assert('has matrix CSS loaded', reportHtml.indexOf('style-matrix.css') >= 0);

/* ========================================
   Summary
   ======================================== */
console.log('\n// SUMMARY: ' + passed + '/' + (passed + failed) + ' passed');
if (failed > 0) {
  process.exit(1);
}
