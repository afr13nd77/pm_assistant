/* Node.js unit tests for components.js */
/* Run: node web/tests/test-components-node.js */

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

/* Load components.js in a sandboxed context */
var compCode = fs.readFileSync(path.join(__dirname, '..', 'components.js'), 'utf8');
var _mockStorage = {};
var sandbox = {
  console: console,
  localStorage: {
    getItem: function(k) { return _mockStorage[k] || null; },
    setItem: function(k, v) { _mockStorage[k] = v; },
    removeItem: function(k) { delete _mockStorage[k]; }
  },
  document: {
    documentElement: { classList: { add: function() {}, remove: function() {} }, style: {} },
    body: { classList: { add: function() {}, remove: function() {} }, appendChild: function() {} },
    head: { appendChild: function() {} },
    getElementById: function() { return null; },
    querySelector: function() { return null; },
    querySelectorAll: function() { return []; },
    createElement: function() { return { className: '' }; }
  },
  Promise: Promise,
  AbortController: function() { this.signal = {}; this.abort = function() {}; }
};
vm.createContext(sandbox);
vm.runInContext(compCode, sandbox);

/* Test registerComponents exists */
assert('registerComponents is function', typeof sandbox.registerComponents === 'function');

/* Create a mock Vue app to track component registrations */
var registeredComponents = {};
var mockApp = {
  component: function(name, definition) {
    registeredComponents[name] = definition;
  }
};

sandbox.registerComponents(mockApp);

/* Test all 6 components are registered */
var expectedComponents = [
  'app-sidebar',
  'note-card',
  'epic-card',
  'progress-bar',
  'metric-box',
  'cmd-button'
];

var regCount = Object.keys(registeredComponents).length;
assert('at least 6 components registered', regCount >= 6, 'got ' + regCount);

for (var i = 0; i < expectedComponents.length; i++) {
  var name = expectedComponents[i];
  assert(name + ' is registered', registeredComponents[name] !== undefined);
}

/* Test AppSidebar */
(function() {
  var comp = registeredComponents['app-sidebar'];
  assert('app-sidebar has props.active', comp.props && comp.props.active !== undefined);
  assert('app-sidebar props.active type is String', comp.props.active.type.name === 'String');
  assert('app-sidebar has template', typeof comp.template === 'string');
  assert('app-sidebar template has sidebar class', comp.template.indexOf('sidebar') >= 0);
  assert('app-sidebar template has sidebar-logo', comp.template.indexOf('sidebar-logo') >= 0);
  assert('app-sidebar logo underscore has accent class', comp.template.indexOf('class="accent"') >= 0);
  assert('app-sidebar template has nav-link class', comp.template.indexOf('nav-link') >= 0);
  assert('app-sidebar template has nav-divider', comp.template.indexOf('nav-divider') >= 0);
  /* Links are generated via computed.links(), check they exist in the computed function */
  var linksResult = comp.computed.links();
  var linkHrefs = linksResult.map(function(l) { return l.href; });
  assert('app-sidebar computed has board.html link', linkHrefs.indexOf('board.html') >= 0);
  assert('app-sidebar computed has roadmap.html link', linkHrefs.indexOf('roadmap.html') >= 0);
  assert('app-sidebar computed has timeline.html link', linkHrefs.indexOf('timeline.html') >= 0);
  assert('app-sidebar computed has report.html link', linkHrefs.indexOf('report.html') >= 0);
  assert('app-sidebar template links to settings.html', comp.template.indexOf('settings.html') >= 0);
})();

/* Test NoteCard */
(function() {
  var comp = registeredComponents['note-card'];
  assert('note-card has props.type', comp.props && comp.props.type !== undefined);
  assert('note-card has props.title', comp.props && comp.props.title !== undefined);
  assert('note-card has props.tags', comp.props && comp.props.tags !== undefined);
  assert('note-card has props.date', comp.props && comp.props.date !== undefined);
  assert('note-card has props.status', comp.props && comp.props.status !== undefined);
  assert('note-card props.tags type is Array', comp.props.tags.type.name === 'Array');
  assert('note-card emits click', comp.emits && comp.emits.indexOf('click') >= 0);
  assert('note-card has template', typeof comp.template === 'string');
  assert('note-card template has card-clip class', comp.template.indexOf('card-clip') >= 0);
  /* Test computed.cardClass for design system card type stripe */
  assert('note-card has computed.cardClass', typeof comp.computed.cardClass === 'function');
  assert('note-card cardClass MEETING_SUMMARY -> card-meeting', comp.computed.cardClass.call({ type: 'MEETING_SUMMARY' }) === 'card-meeting');
  assert('note-card cardClass IDEA_CAPTURE -> card-idea', comp.computed.cardClass.call({ type: 'IDEA_CAPTURE' }) === 'card-idea');
  assert('note-card cardClass JIRA_DRAFT -> card-jira', comp.computed.cardClass.call({ type: 'JIRA_DRAFT' }) === 'card-jira');
  assert('note-card cardClass SYNTHESIS -> card-synthesis', comp.computed.cardClass.call({ type: 'SYNTHESIS' }) === 'card-synthesis');
  assert('note-card cardClass unknown -> empty', comp.computed.cardClass.call({ type: 'UNKNOWN' }) === '');
  assert('note-card cardClass empty -> empty', comp.computed.cardClass.call({ type: '' }) === '');
  assert('note-card template binds clipBorderClass', comp.template.indexOf('clipBorderClass') >= 0);
  assert('note-card template has card-stage', comp.template.indexOf('card-stage') >= 0);
  assert('note-card template has card-title', comp.template.indexOf('card-title') >= 0);
  assert('note-card template has card-meta', comp.template.indexOf('card-meta') >= 0);
  assert('note-card template has card-date', comp.template.indexOf('card-date') >= 0);
})();

/* Test EpicCard */
(function() {
  var comp = registeredComponents['epic-card'];
  assert('epic-card has props.id', comp.props && comp.props.id !== undefined);
  assert('epic-card has props.title', comp.props && comp.props.title !== undefined);
  assert('epic-card has props.horizon', comp.props && comp.props.horizon !== undefined);
  assert('epic-card has props.priority', comp.props && comp.props.priority !== undefined);
  assert('epic-card has props.progress', comp.props && comp.props.progress !== undefined);
  assert('epic-card has props.prd_status', comp.props && comp.props.prd_status !== undefined);
  assert('epic-card has props.tickets', comp.props && comp.props.tickets !== undefined);
  assert('epic-card has props.tags', comp.props && comp.props.tags !== undefined);
  assert('epic-card props.progress type is Number', comp.props.progress.type.name === 'Number');
  assert('epic-card emits click', comp.emits && comp.emits.indexOf('click') >= 0);
  assert('epic-card has template', typeof comp.template === 'string');
  assert('epic-card template has progress-wrap', comp.template.indexOf('progress-wrap') >= 0);
  assert('epic-card template has progress-fill', comp.template.indexOf('progress-fill') >= 0);
  assert('epic-card template references clipBorderClass', comp.template.indexOf('clipBorderClass') >= 0);

  /* Test computed.priorityClass (DS: card-p1/p2/p3) */
  var ctx1 = { priority: 'p1' };
  assert('epic-card p1 -> card-p1', comp.computed.priorityClass.call(ctx1) === 'card-p1');
  var ctx2 = { priority: 'p2' };
  assert('epic-card p2 -> card-p2', comp.computed.priorityClass.call(ctx2) === 'card-p2');
  var ctx3 = { priority: 'p3' };
  assert('epic-card p3 -> card-p3', comp.computed.priorityClass.call(ctx3) === 'card-p3');

  /* Test computed.fillColor (DS: fill-low/mid/high) */
  assert('epic-card 85% -> fill-high', comp.computed.fillColor.call({ progress: 85 }) === 'fill-high');
  assert('epic-card 80% -> fill-high', comp.computed.fillColor.call({ progress: 80 }) === 'fill-high');
  assert('epic-card 60% -> fill-mid', comp.computed.fillColor.call({ progress: 60 }) === 'fill-mid');
  assert('epic-card 40% -> fill-mid', comp.computed.fillColor.call({ progress: 40 }) === 'fill-mid');
  assert('epic-card 20% -> fill-low', comp.computed.fillColor.call({ progress: 20 }) === 'fill-low');
  assert('epic-card 0% -> fill-low', comp.computed.fillColor.call({ progress: 0 }) === 'fill-low');
})();

/* Test ProgressBar */
(function() {
  var comp = registeredComponents['progress-bar'];
  assert('progress-bar has props.value', comp.props && comp.props.value !== undefined);
  assert('progress-bar has props.color', comp.props && comp.props.color !== undefined);
  assert('progress-bar props.value type is Number', comp.props.value.type.name === 'Number');
  assert('progress-bar has template', typeof comp.template === 'string');
  assert('progress-bar template has progress-wrap', comp.template.indexOf('progress-wrap') >= 0);

  /* Test computed.fillClass (DS: fill-low/mid/high) */
  assert('progress-bar default color is mid', comp.props.color.default === 'mid');
  assert('progress-bar fillClass mid', comp.computed.fillClass.call({ color: 'mid' }) === 'fill-mid');
  assert('progress-bar fillClass low', comp.computed.fillClass.call({ color: 'low' }) === 'fill-low');
  assert('progress-bar fillClass high', comp.computed.fillClass.call({ color: 'high' }) === 'fill-high');

  /* Test computed.clampedValue */
  assert('progress-bar clamps 60', comp.computed.clampedValue.call({ value: 60 }) === 60);
  assert('progress-bar clamps -10 to 0', comp.computed.clampedValue.call({ value: -10 }) === 0);
  assert('progress-bar clamps 150 to 100', comp.computed.clampedValue.call({ value: 150 }) === 100);
})();

/* Test MetricBox */
(function() {
  var comp = registeredComponents['metric-box'];
  assert('metric-box has props.label', comp.props && comp.props.label !== undefined);
  assert('metric-box has props.value', comp.props && comp.props.value !== undefined);
  assert('metric-box has props.color', comp.props && comp.props.color !== undefined);
  assert('metric-box has template', typeof comp.template === 'string');
  assert('metric-box template has metric class', comp.template.indexOf('class="metric"') >= 0);
  assert('metric-box template has metric-label', comp.template.indexOf('metric-label') >= 0);
  assert('metric-box template has metric-value', comp.template.indexOf('metric-value') >= 0);

  /* DS: no colorStyle computed; uses class-based .metric-{color} */
  assert('metric-box has no colorStyle computed', comp.computed === undefined || comp.computed.colorStyle === undefined);
  assert('metric-box template uses metric- class for color', comp.template.indexOf("'metric-value metric-'") >= 0);
  /* DS: // prefix comes from CSS ::before, not hardcoded in template */
  assert('metric-box template has no hardcoded // prefix', comp.template.indexOf('// {{ label }}') === -1);
  assert('metric-box template has {{ label }}', comp.template.indexOf('{{ label }}') >= 0);
})();

/* Test CmdButton */
(function() {
  var comp = registeredComponents['cmd-button'];
  assert('cmd-button has props.label', comp.props && comp.props.label !== undefined);
  assert('cmd-button has props.color', comp.props && comp.props.color !== undefined);
  assert('cmd-button has props.loading', comp.props && comp.props.loading !== undefined);
  assert('cmd-button props.loading type is Boolean', comp.props.loading.type.name === 'Boolean');
  assert('cmd-button emits click', comp.emits && comp.emits.indexOf('click') >= 0);
  assert('cmd-button has template', typeof comp.template === 'string');
  /* cmd-btn is in computed.btnClass, not in template literal (uses :class="btnClass") */
  assert('cmd-button computed btnClass contains cmd-btn', comp.computed.btnClass.call({ color: 'cyan' }).indexOf('cmd-btn') >= 0);

  /* Test computed.btnClass (DS: cmd-btn cmd-btn-{color}) */
  assert('cmd-button btnClass cyan', comp.computed.btnClass.call({ color: 'cyan' }) === 'cmd-btn cmd-btn-cyan');
  assert('cmd-button btnClass magenta', comp.computed.btnClass.call({ color: 'magenta' }) === 'cmd-btn cmd-btn-magenta');
  assert('cmd-button btnClass green', comp.computed.btnClass.call({ color: 'green' }) === 'cmd-btn cmd-btn-green');

  /* Test computed.displayLabel */
  assert('cmd-button displayLabel normal', comp.computed.displayLabel.call({ loading: false, label: 'TEST' }) === '[ TEST ]');
  assert('cmd-button displayLabel loading', comp.computed.displayLabel.call({ loading: true, label: 'TEST' }) === '[ ... ]');
})();

/* Test CSS file exists and has design system variables & classes */
(function() {
  var cssPath = path.join(__dirname, '..', 'style.css');
  var cssContent = fs.readFileSync(cssPath, 'utf8');
  assert('style.css exists and is non-empty', cssContent.length > 0);
  /* DS tokens */
  assert('style.css has --bg variable', cssContent.indexOf('--bg:') >= 0);
  assert('style.css has --cyan variable', cssContent.indexOf('--cyan:') >= 0);
  assert('style.css has --magenta variable', cssContent.indexOf('--magenta:') >= 0);
  assert('style.css has --green variable', cssContent.indexOf('--green:') >= 0);
  assert('style.css has --yellow variable', cssContent.indexOf('--yellow:') >= 0);
  assert('style.css has --purple variable', cssContent.indexOf('--purple:') >= 0);
  assert('style.css has --amber variable', cssContent.indexOf('--amber:') >= 0);
  assert('style.css has --text-primary variable', cssContent.indexOf('--text-primary:') >= 0);
  assert('style.css has --text-body variable', cssContent.indexOf('--text-body:') >= 0);
  assert('style.css has --text-muted variable', cssContent.indexOf('--text-muted:') >= 0);
  assert('style.css has --font variable', cssContent.indexOf('--font:') >= 0);
  assert('style.css has Share Tech Mono font', cssContent.indexOf('Share Tech Mono') >= 0);
  /* DS layout classes */
  assert('style.css has .sidebar', cssContent.indexOf('.sidebar') >= 0);
  assert('style.css has .card', cssContent.indexOf('.card') >= 0);
  assert('style.css has .tag', cssContent.indexOf('.tag') >= 0);
  assert('style.css has .progress-bar', cssContent.indexOf('.progress-bar') >= 0);
  assert('style.css has .metric', cssContent.indexOf('.metric') >= 0);
  assert('style.css has .cmd-btn', cssContent.indexOf('.cmd-btn') >= 0);
  assert('style.css has .detail-panel', cssContent.indexOf('.detail-panel') >= 0);
  assert('style.css has .capture-panel', cssContent.indexOf('.capture-panel') >= 0);
  assert('style.css has .loading', cssContent.indexOf('.loading') >= 0);
  assert('style.css has .empty-state', cssContent.indexOf('.empty-state') >= 0);
  assert('style.css has .kanban-grid', cssContent.indexOf('.kanban-grid') >= 0);
  assert('style.css has .text-page-title', cssContent.indexOf('.text-page-title') >= 0);
  assert('style.css has .btn-row', cssContent.indexOf('.btn-row') >= 0);
  assert('style.css has .status-bar', cssContent.indexOf('.status-bar') >= 0);
  /* DS card priority classes */
  assert('style.css has card-p1/p2/p3', cssContent.indexOf('.card-p1') >= 0 && cssContent.indexOf('.card-p2') >= 0 && cssContent.indexOf('.card-p3') >= 0);
  /* DS progress fill classes */
  assert('style.css has fill-low/mid/high', cssContent.indexOf('.fill-low') >= 0 && cssContent.indexOf('.fill-mid') >= 0 && cssContent.indexOf('.fill-high') >= 0);
  /* DS tag classes */
  assert('style.css has tag-idea/prd/jira/done/blocked',
    cssContent.indexOf('.tag-idea') >= 0 && cssContent.indexOf('.tag-prd') >= 0 &&
    cssContent.indexOf('.tag-jira') >= 0 && cssContent.indexOf('.tag-done') >= 0 &&
    cssContent.indexOf('.tag-blocked') >= 0
  );
  /* DS button color classes */
  assert('style.css has .cmd-btn-cyan', cssContent.indexOf('.cmd-btn-cyan') >= 0);
  assert('style.css has .cmd-btn-magenta', cssContent.indexOf('.cmd-btn-magenta') >= 0);
  assert('style.css has .cmd-btn-green', cssContent.indexOf('.cmd-btn-green') >= 0);
  /* DS metric color classes */
  assert('style.css has .metric-cyan', cssContent.indexOf('.metric-cyan') >= 0);
  assert('style.css has .metric-label::before', cssContent.indexOf('.metric-label::before') >= 0);
  /* DS card type stripe classes */
  assert('style.css has .card-meeting', cssContent.indexOf('.card-meeting') >= 0);
  assert('style.css has .card-idea', cssContent.indexOf('.card-idea') >= 0);
  assert('style.css has .card-jira', cssContent.indexOf('.card-jira') >= 0);
  assert('style.css has .card-synthesis', cssContent.indexOf('.card-synthesis') >= 0);
  /* DS sidebar logo accent */
  assert('style.css has .sidebar-logo .accent', cssContent.indexOf('.sidebar-logo .accent') >= 0);
})();

/* Test applyPageTheme exists (matrix is the only theme) */
(function() {
  assert('applyPageTheme is function', typeof sandbox.applyPageTheme === 'function');
  assert('getCardTheme is removed', typeof sandbox.getCardTheme === 'undefined');
})();

/* Test applyPageTheme returns a Promise (P0-1) */
(function() {
  var result = sandbox.applyPageTheme();
  assert('applyPageTheme returns a Promise', result && typeof result.then === 'function');
})();

/* Test style.css no longer has html opacity transition (P0-1) */
(function() {
  var cssPath = path.join(__dirname, '..', 'style.css');
  var cssContent = fs.readFileSync(cssPath, 'utf8');
  var hasOpacityTransition = /html\s*\{\s*transition:\s*opacity/.test(cssContent);
  assert('style.css does NOT have html opacity transition', !hasOpacityTransition);
})();

/* Test HTML pages have inline matrix theme script in head (P0-1) */
(function() {
  var pages = ['board.html', 'roadmap.html', 'dashboard.html', 'settings.html', 'timeline.html', 'report.html'];
  for (var p = 0; p < pages.length; p++) {
    var pagePath = path.join(__dirname, '..', pages[p]);
    var pageContent = fs.readFileSync(pagePath, 'utf8');
    assert(pages[p] + ' has theme-matrix class', pageContent.indexOf('theme-matrix') >= 0);
    assert(pages[p] + ' loads style-matrix.css', pageContent.indexOf('style-matrix.css') >= 0);
  }
})();

/* Test index.html exists and has redirect */
(function() {
  var indexPath = path.join(__dirname, '..', 'index.html');
  var indexContent = fs.readFileSync(indexPath, 'utf8');
  assert('index.html exists', indexContent.length > 0);
  assert('index.html has meta refresh to board.html', indexContent.indexOf('url=board.html') >= 0);
})();

/* Test vendor/.gitkeep exists */
(function() {
  var gitkeepPath = path.join(__dirname, '..', 'vendor', '.gitkeep');
  assert('vendor/.gitkeep exists', fs.existsSync(gitkeepPath));
})();

/* Test style.css has theme utility classes (Phase 0) */
(function() {
  var cssPath = path.join(__dirname, '..', 'style.css');
  var cssContent = fs.readFileSync(cssPath, 'utf8');
  assert('style.css has .text-cyan', cssContent.indexOf('.text-cyan') >= 0);
  assert('style.css has .text-magenta', cssContent.indexOf('.text-magenta') >= 0);
  assert('style.css has .text-green', cssContent.indexOf('.text-green') >= 0);
  assert('style.css has .text-amber', cssContent.indexOf('.text-amber') >= 0);
  assert('style.css has .text-yellow', cssContent.indexOf('.text-yellow') >= 0);
  assert('style.css has .text-purple', cssContent.indexOf('.text-purple') >= 0);
  assert('style.css has .text-muted', cssContent.indexOf('.text-muted') >= 0);
  assert('style.css has .bg-bar-cyan', cssContent.indexOf('.bg-bar-cyan') >= 0);
  assert('style.css has .border-priority-p1', cssContent.indexOf('.border-priority-p1') >= 0);
  assert('style.css has .mr-xs', cssContent.indexOf('.mr-xs') >= 0);
  assert('style.css has .tag-sm', cssContent.indexOf('.tag-sm') >= 0);
  assert('style.css has .msg-error', cssContent.indexOf('.msg-error') >= 0);
})();

/* Test style-light.css exists and has theme overrides */
(function() {
  var lightCssPath = path.join(__dirname, '..', 'style-light.css');
  var lightCss = fs.readFileSync(lightCssPath, 'utf8');
  assert('style-light.css exists', lightCss.length > 0);
  assert('style-light.css has :root override', lightCss.indexOf(':root') >= 0);
  assert('style-light.css has --bg: #F3F1EA', lightCss.indexOf('#F3F1EA') >= 0);
  assert('style-light.css has Inter font', lightCss.indexOf('Inter') >= 0);
  assert('style-light.css has .bg-light', lightCss.indexOf('.bg-light') >= 0);
  assert('style-light.css has sidebar override', lightCss.indexOf('.sidebar') >= 0);
  assert('style-light.css has card override', lightCss.indexOf('.card') >= 0);
})();

/* Test applyPageTheme accepts theme parameter */
(function() {
  var result = sandbox.applyPageTheme('matrix');
  assert('applyPageTheme("matrix") returns Promise', result && typeof result.then === 'function');
  var result2 = sandbox.applyPageTheme('light');
  assert('applyPageTheme("light") returns Promise', result2 && typeof result2.then === 'function');
})();

/* Test HTML pages have id="theme-css" and FOUC prevention script */
(function() {
  var pages = ['board.html', 'roadmap.html', 'dashboard.html', 'settings.html', 'timeline.html', 'report.html', 'ideas.html', 'overview.html'];
  for (var p = 0; p < pages.length; p++) {
    var pagePath = path.join(__dirname, '..', pages[p]);
    var pageContent = fs.readFileSync(pagePath, 'utf8');
    assert(pages[p] + ' has id="theme-css"', pageContent.indexOf('id="theme-css"') >= 0);
    assert(pages[p] + ' has FOUC prevention script', pageContent.indexOf('pm_theme') >= 0);
  }
})();

/* Test components.js has no theme-dependent inline styles */
(function() {
  var jsPath = path.join(__dirname, '..', 'components.js');
  var jsContent = fs.readFileSync(jsPath, 'utf8');
  assert('no style="color: var(-- in components.js', jsContent.indexOf('style="color: var(--') < 0);
  assert('no :style="{color: \'var(-- in components.js', jsContent.indexOf(':style="{color: \'var(--') < 0);
  assert('no style="font-size:10px in components.js', jsContent.indexOf('style="font-size:10px') < 0);
  assert('no style="margin-right:4px in components.js', jsContent.indexOf('style="margin-right:4px') < 0);
})();

/* Test settings.html has theme toggle */
(function() {
  var settingsPath = path.join(__dirname, '..', 'settings.html');
  var settingsContent = fs.readFileSync(settingsPath, 'utf8');
  assert('settings.html has THEME section', settingsContent.indexOf('// THEME') >= 0);
  assert('settings.html has MATRIX button', settingsContent.indexOf("setTheme('matrix')") >= 0);
  assert('settings.html has LIGHT button', settingsContent.indexOf("setTheme('light')") >= 0);
})();

/* Summary */
console.log('\n// SUMMARY: ' + passed + '/' + (passed + failed) + ' passed');
if (failed > 0) {
  process.exit(1);
}
