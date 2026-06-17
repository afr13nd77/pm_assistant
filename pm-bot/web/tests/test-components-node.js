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

/* ========================================
   Test capture-terminal component (BL-137 T-08)
   ======================================== */
(function() {
  var comp = registeredComponents['capture-terminal'];
  assert('capture-terminal is registered', comp !== undefined);

  /* Props */
  assert('capture-terminal has props.layout', comp.props && comp.props.layout !== undefined);
  assert('capture-terminal props.layout default is drawer', comp.props.layout.default === 'drawer');
  assert('capture-terminal props.layout type is String', comp.props.layout.type.name === 'String');
  assert('capture-terminal has props.open', comp.props && comp.props.open !== undefined);
  assert('capture-terminal props.open default is true', comp.props.open.default === true);
  assert('capture-terminal props.open type is Boolean', comp.props.open.type.name === 'Boolean');

  /* Emits */
  assert('capture-terminal emits close', comp.emits && comp.emits.indexOf('close') >= 0);
  assert('capture-terminal emits captured', comp.emits && comp.emits.indexOf('captured') >= 0);
  assert('capture-terminal emits imported', comp.emits && comp.emits.indexOf('imported') >= 0);

  /* Data */
  var dataFn = comp.data;
  assert('capture-terminal data is a function', typeof dataFn === 'function');
  var data = dataFn();
  assert('capture-terminal data.mode is simple', data.mode === 'simple');
  assert('capture-terminal data.chatMessages is array', Array.isArray(data.chatMessages));
  assert('capture-terminal data.captureText is empty', data.captureText === '');
  assert('capture-terminal data.captureType is idea', data.captureType === 'idea');
  assert('capture-terminal data.capturing is false', data.capturing === false);
  assert('capture-terminal data.extType is idea', data.extType === 'idea');
  assert('capture-terminal data.extText is empty', data.extText === '');
  assert('capture-terminal data.extSaving is false', data.extSaving === false);
  assert('capture-terminal data.extSaveOk is false', data.extSaveOk === false);
  assert('capture-terminal data.jiraActive is false', data.jiraActive === false);
  assert('capture-terminal data.projects is array', Array.isArray(data.projects));
  assert('capture-terminal data.projectsLoading is false', data.projectsLoading === false);
  assert('capture-terminal data.selectedProject is null', data.selectedProject === null);
  assert('capture-terminal data.recentProjectKeys is array', Array.isArray(data.recentProjectKeys));
  assert('capture-terminal data.projectSearch is empty', data.projectSearch === '');
  assert('capture-terminal data.projectDropOpen is false', data.projectDropOpen === false);
  assert('capture-terminal data.issueTypes is array', Array.isArray(data.issueTypes));
  assert('capture-terminal data.tickets is array', Array.isArray(data.tickets));
  assert('capture-terminal data.ticketsLoading is false', data.ticketsLoading === false);
  assert('capture-terminal data.typeFilter is empty', data.typeFilter === '');
  assert('capture-terminal data.statusFilter is empty', data.statusFilter === '');
  assert('capture-terminal data.selectedTicketIds is array', Array.isArray(data.selectedTicketIds));
  assert('capture-terminal data.directKey is empty', data.directKey === '');
  assert('capture-terminal data.importing is false', data.importing === false);
  assert('capture-terminal data.importResult is null', data.importResult === null);

  /* Computed: previewTitle */
  assert('capture-terminal has computed.previewTitle', typeof comp.computed.previewTitle === 'function');
  assert('previewTitle empty when no text', comp.computed.previewTitle.call({ extText: '' }) === '');
  assert('previewTitle empty when short text', comp.computed.previewTitle.call({ extText: 'ab' }) === '');
  assert('previewTitle returns first line', comp.computed.previewTitle.call({ extText: 'Hello world\nSecond line' }) === 'Hello world');
  assert('previewTitle truncates at 60 chars', comp.computed.previewTitle.call({ extText: 'A'.repeat(80) }).length === 60);

  /* Computed: previewBody */
  assert('capture-terminal has computed.previewBody', typeof comp.computed.previewBody === 'function');
  assert('previewBody empty when no text', comp.computed.previewBody.call({ extText: '' }) === '');
  assert('previewBody empty when single line', comp.computed.previewBody.call({ extText: 'Hello world' }) === '');
  assert('previewBody returns remainder', comp.computed.previewBody.call({ extText: 'Line 1\nLine 2\nLine 3' }) === 'Line 2\nLine 3');
  assert('previewBody truncates at 200 chars', comp.computed.previewBody.call({ extText: 'Title\n' + 'B'.repeat(300) }).length === 200);

  /* Computed: filteredProjects */
  assert('capture-terminal has computed.filteredProjects', typeof comp.computed.filteredProjects === 'function');
  var mockProjects = [
    { key: 'SUP', name: 'Support' },
    { key: 'DEV', name: 'Development' },
    { key: 'GO', name: 'Go Project' }
  ];
  assert('filteredProjects returns null when no search', comp.computed.filteredProjects.call({ projectSearch: '', projects: mockProjects }) === null);
  var filtered = comp.computed.filteredProjects.call({ projectSearch: 'sup', projects: mockProjects });
  assert('filteredProjects filters by key', filtered.length === 1 && filtered[0].key === 'SUP');
  var filtered2 = comp.computed.filteredProjects.call({ projectSearch: 'dev', projects: mockProjects });
  assert('filteredProjects filters by name', filtered2.length === 1 && filtered2[0].key === 'DEV');

  /* Computed: filteredTickets */
  assert('capture-terminal has computed.filteredTickets', typeof comp.computed.filteredTickets === 'function');
  var mockTickets = [
    { key: 'SUP-1', type: 'Bug', status: 'To Do' },
    { key: 'SUP-2', type: 'Story', status: 'In Progress' },
    { key: 'SUP-3', type: 'Bug', status: 'In Progress' }
  ];
  var allTickets = comp.computed.filteredTickets.call({ tickets: mockTickets, typeFilter: '', statusFilter: '' });
  assert('filteredTickets returns all when no filter', allTickets.length === 3);
  var typeFiltered = comp.computed.filteredTickets.call({ tickets: mockTickets, typeFilter: 'Bug', statusFilter: '' });
  assert('filteredTickets filters by type', typeFiltered.length === 2);
  var statusFiltered = comp.computed.filteredTickets.call({ tickets: mockTickets, typeFilter: '', statusFilter: 'In Progress' });
  assert('filteredTickets filters by status', statusFiltered.length === 2);
  var bothFiltered = comp.computed.filteredTickets.call({ tickets: mockTickets, typeFilter: 'Bug', statusFilter: 'In Progress' });
  assert('filteredTickets filters by both', bothFiltered.length === 1 && bothFiltered[0].key === 'SUP-3');

  /* Computed: selectedCount */
  assert('capture-terminal has computed.selectedCount', typeof comp.computed.selectedCount === 'function');
  assert('selectedCount with empty', comp.computed.selectedCount.call({ selectedTicketIds: [] }) === 0);
  assert('selectedCount with items', comp.computed.selectedCount.call({ selectedTicketIds: ['A', 'B'] }) === 2);

  /* Computed: canSave */
  assert('capture-terminal has computed.canSave', typeof comp.computed.canSave === 'function');
  assert('canSave true when text and not saving', comp.computed.canSave.call({ extText: 'hello', extSaving: false }) === true);
  assert('canSave false when empty', comp.computed.canSave.call({ extText: '', extSaving: false }) === false);
  assert('canSave false when saving', comp.computed.canSave.call({ extText: 'hello', extSaving: true }) === false);
  assert('canSave false when whitespace only', comp.computed.canSave.call({ extText: '   ', extSaving: false }) === false);

  /* Computed: canImport */
  assert('capture-terminal has computed.canImport', typeof comp.computed.canImport === 'function');
  assert('canImport true when selected and not importing', comp.computed.canImport.call({ selectedTicketIds: ['X'], importing: false }) === true);
  assert('canImport false when none selected', comp.computed.canImport.call({ selectedTicketIds: [], importing: false }) === false);
  assert('canImport false when importing', comp.computed.canImport.call({ selectedTicketIds: ['X'], importing: true }) === false);

  /* Computed: recentProjects and otherProjects */
  assert('capture-terminal has computed.recentProjects', typeof comp.computed.recentProjects === 'function');
  assert('capture-terminal has computed.otherProjects', typeof comp.computed.otherProjects === 'function');
  var ctx = { recentProjectKeys: ['SUP'], projects: mockProjects };
  var recent = comp.computed.recentProjects.call(ctx);
  assert('recentProjects returns matching', recent.length === 1 && recent[0].key === 'SUP');
  var other = comp.computed.otherProjects.call(ctx);
  assert('otherProjects returns non-matching', other.length === 2);

  /* Computed: sessionDate */
  assert('capture-terminal has computed.sessionDate', typeof comp.computed.sessionDate === 'function');
  var dateStr = comp.computed.sessionDate.call({});
  assert('sessionDate format DD.MM.YYYY', /^\d{2}\.\d{2}\.\d{4}$/.test(dateStr));

  /* Methods existence */
  assert('capture-terminal has method initMode', typeof comp.methods.initMode === 'function');
  assert('capture-terminal has method setExtType', typeof comp.methods.setExtType === 'function');
  assert('capture-terminal has method activateJira', typeof comp.methods.activateJira === 'function');
  assert('capture-terminal has method saveCapture', typeof comp.methods.saveCapture === 'function');
  assert('capture-terminal has method resetCapture', typeof comp.methods.resetCapture === 'function');
  assert('capture-terminal has method loadProjects', typeof comp.methods.loadProjects === 'function');
  assert('capture-terminal has method selectProject', typeof comp.methods.selectProject === 'function');
  assert('capture-terminal has method clearProject', typeof comp.methods.clearProject === 'function');
  assert('capture-terminal has method loadTickets', typeof comp.methods.loadTickets === 'function');
  assert('capture-terminal has method toggleTicket', typeof comp.methods.toggleTicket === 'function');
  assert('capture-terminal has method isTicketSelected', typeof comp.methods.isTicketSelected === 'function');
  assert('capture-terminal has method importSelected', typeof comp.methods.importSelected === 'function');
  assert('capture-terminal has method handleExtKeydown', typeof comp.methods.handleExtKeydown === 'function');
  assert('capture-terminal has method simpleCapture', typeof comp.methods.simpleCapture === 'function');
  assert('capture-terminal has method simpleKeydown', typeof comp.methods.simpleKeydown === 'function');
  assert('capture-terminal has method onProjectInputFocus', typeof comp.methods.onProjectInputFocus === 'function');
  assert('capture-terminal has method onProjectInputBlur', typeof comp.methods.onProjectInputBlur === 'function');
  assert('capture-terminal has method onFilterChange', typeof comp.methods.onFilterChange === 'function');

  /* Method: setExtType */
  var ctx2 = { extType: 'idea', jiraActive: true };
  comp.methods.setExtType.call(ctx2, 'task');
  assert('setExtType sets type', ctx2.extType === 'task');
  assert('setExtType deactivates jira', ctx2.jiraActive === false);

  /* Method: activateJira */
  var loadProjectsCalled = false;
  var ctx3 = { jiraActive: false, projects: [], loadProjects: function() { loadProjectsCalled = true; } };
  comp.methods.activateJira.call(ctx3);
  assert('activateJira sets jiraActive true', ctx3.jiraActive === true);
  assert('activateJira loads projects when empty', loadProjectsCalled === true);

  /* Method: activateJira when projects exist */
  var loadProjectsCalled2 = false;
  var ctx4 = { jiraActive: false, projects: [{ key: 'A', name: 'A' }], loadProjects: function() { loadProjectsCalled2 = true; } };
  comp.methods.activateJira.call(ctx4);
  assert('activateJira does not reload when projects exist', loadProjectsCalled2 === false);

  /* Method: resetCapture */
  var ctx5 = { extText: 'some text' };
  comp.methods.resetCapture.call(ctx5);
  assert('resetCapture clears text', ctx5.extText === '');

  /* Method: toggleTicket */
  var ctx6 = { selectedTicketIds: [] };
  comp.methods.toggleTicket.call(ctx6, 'SUP-1');
  assert('toggleTicket adds key', ctx6.selectedTicketIds.indexOf('SUP-1') >= 0);
  comp.methods.toggleTicket.call(ctx6, 'SUP-1');
  assert('toggleTicket removes key', ctx6.selectedTicketIds.indexOf('SUP-1') === -1);

  /* Method: isTicketSelected */
  assert('isTicketSelected true', comp.methods.isTicketSelected.call({ selectedTicketIds: ['X'] }, 'X') === true);
  assert('isTicketSelected false', comp.methods.isTicketSelected.call({ selectedTicketIds: ['X'] }, 'Y') === false);

  /* Method: clearProject */
  var ctx7 = {
    selectedProject: { key: 'A' }, projectSearch: 'A', tickets: [1],
    issueTypes: ['Bug'], typeFilter: 'Bug', statusFilter: 'Done', selectedTicketIds: ['X']
  };
  comp.methods.clearProject.call(ctx7);
  assert('clearProject resets selectedProject', ctx7.selectedProject === null);
  assert('clearProject resets projectSearch', ctx7.projectSearch === '');
  assert('clearProject resets tickets', ctx7.tickets.length === 0);
  assert('clearProject resets issueTypes', ctx7.issueTypes.length === 0);
  assert('clearProject resets typeFilter', ctx7.typeFilter === '');
  assert('clearProject resets statusFilter', ctx7.statusFilter === '');
  assert('clearProject resets selectedTicketIds', ctx7.selectedTicketIds.length === 0);

  /* Method: initMode reads from localStorage */
  _mockStorage['pm_capture_mode'] = 'extended';
  _mockStorage['pm_jira_recent_projects'] = '["SUP","DEV"]';
  var ctx8 = { mode: 'simple', recentProjectKeys: [] };
  comp.methods.initMode.call(ctx8);
  assert('initMode reads mode from localStorage', ctx8.mode === 'extended');
  assert('initMode reads recentProjectKeys from localStorage', ctx8.recentProjectKeys.length === 2 && ctx8.recentProjectKeys[0] === 'SUP');
  // Restore
  _mockStorage['pm_capture_mode'] = 'simple';
  delete _mockStorage['pm_jira_recent_projects'];

  /* Method: onFilterChange */
  var loadTicketsCalled = false;
  var ctx9 = { selectedTicketIds: ['X', 'Y'], loadTickets: function() { loadTicketsCalled = true; } };
  comp.methods.onFilterChange.call(ctx9);
  assert('onFilterChange clears selection', ctx9.selectedTicketIds.length === 0);
  assert('onFilterChange triggers loadTickets', loadTicketsCalled === true);

  /* Template */
  assert('capture-terminal has template', typeof comp.template === 'string');

  /* Simple mode template checks */
  assert('template has simple mode v-if', comp.template.indexOf('mode === \'simple\'') >= 0);
  assert('template has CAPTURE_TERMINAL header', comp.template.indexOf('CAPTURE_TERMINAL') >= 0);
  assert('template has capture-messages class', comp.template.indexOf('capture-messages') >= 0);
  assert('template has type-selector', comp.template.indexOf('type-selector') >= 0);
  assert('template has IDEA button', comp.template.indexOf('IDEA') >= 0);
  assert('template has TASK button', comp.template.indexOf('TASK') >= 0);
  assert('template has MEETING button', comp.template.indexOf('MEETING') >= 0);
  assert('template has JIRA_IMPORT button', comp.template.indexOf('JIRA_IMPORT') >= 0);
  assert('template has cp-textarea', comp.template.indexOf('cp-textarea') >= 0);
  assert('template has cmd-button for simple mode', comp.template.indexOf('cmd-button') >= 0);
  assert('template has Ctrl+Enter hint', comp.template.indexOf('Ctrl+Enter') >= 0);

  /* Simple mode inline layout */
  assert('template has QUICK CAPTURE', comp.template.indexOf('QUICK CAPTURE') >= 0);
  assert('template has cp-input for inline', comp.template.indexOf('cp-input') >= 0);

  /* Extended mode template checks */
  assert('template has extended mode v-if', comp.template.indexOf('mode === \'extended\'') >= 0);
  assert('template has ct-header class', comp.template.indexOf('ct-header') >= 0);
  assert('template has ct-type-bar', comp.template.indexOf('ct-type-bar') >= 0);
  assert('template has ct-chip class', comp.template.indexOf('ct-chip') >= 0);
  assert('template has ct-textarea', comp.template.indexOf('ct-textarea') >= 0);
  assert('template has ct-preview', comp.template.indexOf('ct-preview') >= 0);
  assert('template has ct-dest-row', comp.template.indexOf('ct-dest-row') >= 0);
  assert('template has ct-footer', comp.template.indexOf('ct-footer') >= 0);
  assert('template has ct-btn-primary', comp.template.indexOf('ct-btn-primary') >= 0);
  assert('template has ct-btn-ghost', comp.template.indexOf('ct-btn-ghost') >= 0);

  /* Jira panel template checks */
  assert('template has ct-jira-body', comp.template.indexOf('ct-jira-body') >= 0);
  assert('template has ct-proj-wrap', comp.template.indexOf('ct-proj-wrap') >= 0);
  assert('template has ct-proj-input', comp.template.indexOf('ct-proj-input') >= 0);
  assert('template has ct-proj-drop', comp.template.indexOf('ct-proj-drop') >= 0);
  assert('template has ct-filter-row', comp.template.indexOf('ct-filter-row') >= 0);
  assert('template has ct-or-divider', comp.template.indexOf('ct-or-divider') >= 0);
  assert('template has ct-id-input', comp.template.indexOf('ct-id-input') >= 0);
  assert('template has ct-ticket-list', comp.template.indexOf('ct-ticket-list') >= 0);
  assert('template has ct-ticket-item', comp.template.indexOf('ct-ticket-item') >= 0);
  assert('template has ct-sel-row', comp.template.indexOf('ct-sel-row') >= 0);

  /* Tabler icon classes */
  assert('template has ti-bulb icon', comp.template.indexOf('ti ti-bulb') >= 0);
  assert('template has ti-checkbox icon', comp.template.indexOf('ti ti-checkbox') >= 0);
  assert('template has ti-users icon', comp.template.indexOf('ti ti-users') >= 0);
  assert('template has ti-brand-jira icon', comp.template.indexOf('ti ti-brand-jira') >= 0);
  assert('template has ti-device-floppy icon', comp.template.indexOf('ti ti-device-floppy') >= 0);
  assert('template has ti-download icon', comp.template.indexOf('ti ti-download') >= 0);
  assert('template has ti-x close icon', comp.template.indexOf('ti ti-x') >= 0);
  assert('template has ti-pencil icon', comp.template.indexOf('ti ti-pencil') >= 0);
  assert('template has ti-database icon', comp.template.indexOf('ti ti-database') >= 0);
  assert('template has ti-folder icon', comp.template.indexOf('ti ti-folder') >= 0);
  assert('template has ti-book icon', comp.template.indexOf('ti ti-book') >= 0);
  assert('template has ti-circle-check icon', comp.template.indexOf('ti ti-circle-check') >= 0);
  assert('template has ti-folder-open icon', comp.template.indexOf('ti ti-folder-open') >= 0);
  assert('template has ti-square icon', comp.template.indexOf('ti ti-square') >= 0);
  assert('template has ti-square-check icon', comp.template.indexOf('ti ti-square-check') >= 0);
  assert('template has ti-external-link icon', comp.template.indexOf('ti ti-external-link') >= 0);
  assert('template has ti-user icon', comp.template.indexOf('ti ti-user') >= 0);
  assert('template has ti-clock icon', comp.template.indexOf('ti ti-clock') >= 0);
  assert('template has ti-tag icon', comp.template.indexOf('ti ti-tag') >= 0);

  /* Mounted and Watch */
  assert('capture-terminal has mounted hook', typeof comp.mounted === 'function');
  assert('capture-terminal has watch.open', typeof comp.watch.open === 'function');

  /* ES5 compliance checks */
  var compStr = JSON.stringify(comp.methods);
  assert('no arrow functions in methods', compStr.indexOf('=>') === -1);

  /* No Set() usage -- selectedTicketIds should be array */
  assert('selectedTicketIds is plain array (no Set)', Array.isArray(data.selectedTicketIds) && typeof data.selectedTicketIds.push === 'function');
})();

/* Test ct-* CSS classes exist in style.css (BL-137) */
(function() {
  var cssPath = path.join(__dirname, '..', 'style.css');
  var cssContent = fs.readFileSync(cssPath, 'utf8');
  var ctClasses = [
    '.ct-header', '.ct-dot', '.ct-header-title', '.ct-session-badge', '.ct-close',
    '.ct-type-bar', '.ct-chip', '.ct-chip--idea', '.ct-chip--task', '.ct-chip--meet', '.ct-chip--jira',
    '.ct-capture-body', '.ct-field-label', '.ct-textarea',
    '.ct-preview', '.ct-preview-label', '.ct-preview-row', '.ct-preview-key', '.ct-preview-value',
    '.ct-jira-body', '.ct-proj-wrap', '.ct-proj-input', '.ct-proj-drop', '.ct-proj-opt',
    '.ct-filter-row', '.ct-filter', '.ct-or-divider', '.ct-id-input',
    '.ct-ticket-list', '.ct-ticket-item', '.ct-ticket-check', '.ct-card-body', '.ct-card-title',
    '.ct-badge', '.ct-status-badge', '.ct-sel-row', '.ct-dest-row', '.ct-dest-chip',
    '.ct-footer', '.ct-hint', '.ct-footer-actions', '.ct-btn-ghost', '.ct-btn-primary'
  ];
  for (var i = 0; i < ctClasses.length; i++) {
    assert('style.css has ' + ctClasses[i], cssContent.indexOf(ctClasses[i]) >= 0);
  }
})();

/* Summary */
console.log('\n// SUMMARY: ' + passed + '/' + (passed + failed) + ' passed');
if (failed > 0) {
  process.exit(1);
}
