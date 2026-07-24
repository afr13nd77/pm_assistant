/* Node.js unit tests for today.html, style-today.css, sidebar (components.js), api.js */
/* Run: node pm-bot/web/tests/test-today-node.js */

var fs = require('fs');
var path = require('path');

var WEB = path.resolve(__dirname, '..');
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

/* ================================================================
   1. today.html structure
   ================================================================ */
console.log('\n--- today.html structure ---');

var todayHtml = fs.readFileSync(path.join(WEB, 'today.html'), 'utf8');

assert('today.html exists and is not empty', todayHtml.length > 0);

assert('contains <app-sidebar active="today"',
  todayHtml.indexOf('active="today"') >= 0);

assert('contains <capture-terminal',
  todayHtml.indexOf('<capture-terminal') >= 0);

assert('links style-today.css',
  todayHtml.indexOf('style-today.css') >= 0);

assert('links api.js',
  todayHtml.indexOf('api.js') >= 0);

assert('links components.js',
  todayHtml.indexOf('components.js') >= 0);

assert('has FOUC prevention script (localStorage pm_theme)',
  todayHtml.indexOf("localStorage.getItem('pm_theme')") >= 0);

assert('has Vue mount div id="app"',
  todayHtml.indexOf('id="app"') >= 0);

assert('has theme-matrix class on html',
  todayHtml.indexOf('class="theme-matrix"') >= 0);

assert('has id="theme-css" on stylesheet link',
  todayHtml.indexOf('id="theme-css"') >= 0);

assert('loads Vue 3 from CDN',
  todayHtml.indexOf('vue@3') >= 0 || todayHtml.indexOf('vue.global') >= 0);

assert('calls registerComponents(app)',
  todayHtml.indexOf('registerComponents(app)') >= 0);

assert('mounts Vue app with app.mount',
  todayHtml.indexOf("app.mount('#app')") >= 0);

/* ================================================================
   2. style-today.css
   ================================================================ */
console.log('\n--- style-today.css ---');

var todayCss = fs.readFileSync(path.join(WEB, 'style-today.css'), 'utf8');

assert('style-today.css exists and is not empty', todayCss.length > 0);

/* Key layout classes */
assert('has .today-content class',
  todayCss.indexOf('.today-content') >= 0);

assert('has .today-topbar class',
  todayCss.indexOf('.today-topbar') >= 0);

assert('has .today-metrics class',
  todayCss.indexOf('.today-metrics') >= 0);

assert('has .focus-card class',
  todayCss.indexOf('.focus-card') >= 0);

assert('has .panel class',
  todayCss.indexOf('.panel') >= 0);

assert('has .meeting class',
  todayCss.indexOf('.meeting') >= 0);

assert('has .todo-row class',
  todayCss.indexOf('.todo-row') >= 0);

assert('has .news-grid class',
  todayCss.indexOf('.news-grid') >= 0);

/* Responsive breakpoints */
assert('has @media (max-width: 1200px)',
  todayCss.indexOf('@media (max-width: 1200px)') >= 0);

assert('has @media (max-width: 820px)',
  todayCss.indexOf('@media (max-width: 820px)') >= 0);

assert('has @media (max-width: 560px)',
  todayCss.indexOf('@media (max-width: 560px)') >= 0);

/* Drawer / modal / toast (today-scoped variants) */
assert('has drawer class (today-drawer)',
  todayCss.indexOf('.today-drawer') >= 0);

assert('has drawer-overlay class',
  todayCss.indexOf('.today-drawer-overlay') >= 0);

assert('has modal class (today-modal)',
  todayCss.indexOf('.today-modal') >= 0);

assert('has modal-overlay class',
  todayCss.indexOf('.today-modal-overlay') >= 0);

assert('has toast class (today-toast)',
  todayCss.indexOf('.today-toast') >= 0);

/* Additional panel/detail classes */
assert('has .split-row class',
  todayCss.indexOf('.split-row') >= 0);

assert('has .bottom-row class',
  todayCss.indexOf('.bottom-row') >= 0);

assert('has .digest-row class',
  todayCss.indexOf('.digest-row') >= 0);

assert('has .meeting-dot class',
  todayCss.indexOf('.meeting-dot') >= 0);

assert('has .meeting-time class',
  todayCss.indexOf('.meeting-time') >= 0);

assert('has .meeting-title class',
  todayCss.indexOf('.meeting-title') >= 0);

assert('has .news-row class',
  todayCss.indexOf('.news-row') >= 0);

assert('has .news-title class',
  todayCss.indexOf('.news-title') >= 0);

/* ================================================================
   3. Sidebar groups (components.js)
   ================================================================ */
console.log('\n--- Sidebar groups (components.js) ---');

var compJs = fs.readFileSync(path.join(WEB, 'components.js'), 'utf8');

assert('components.js contains app-sidebar registration',
  compJs.indexOf("'app-sidebar'") >= 0);

assert('components.js has workday group',
  compJs.indexOf("'workday'") >= 0);

assert('components.js has knowledge group',
  compJs.indexOf("'knowledge'") >= 0);

assert('components.js has monitoring group',
  compJs.indexOf("'monitoring'") >= 0);

assert('components.js has system group',
  compJs.indexOf("'system'") >= 0);

assert('components.js has systemCollapsed: true',
  compJs.indexOf('systemCollapsed: true') >= 0);

assert('components.js has today nav item',
  compJs.indexOf("'today'") >= 0);

assert('components.js has KNOWLEDGE OVERVIEW label',
  compJs.indexOf('KNOWLEDGE OVERVIEW') >= 0);

assert('components.js has WORK QUEUE label',
  compJs.indexOf('WORK QUEUE') >= 0);

assert('components.js has DIAGNOSTICS label',
  compJs.indexOf('DIAGNOSTICS') >= 0);

assert('components.js has registerComponents function',
  compJs.indexOf('function registerComponents') >= 0);

/* ================================================================
   4. api.js functions
   ================================================================ */
console.log('\n--- api.js functions ---');

var apiJs = fs.readFileSync(path.join(WEB, 'api.js'), 'utf8');

assert('api.js has todayDigest function',
  apiJs.indexOf('todayDigest:') >= 0 || apiJs.indexOf('todayDigest :') >= 0);

assert('api.js has todayMeetings function',
  apiJs.indexOf('todayMeetings:') >= 0 || apiJs.indexOf('todayMeetings :') >= 0);

assert('api.js has todayNews function',
  apiJs.indexOf('todayNews:') >= 0 || apiJs.indexOf('todayNews :') >= 0);

assert('api.js has todos function',
  apiJs.indexOf('todos:') >= 0 || apiJs.indexOf('todos :') >= 0);

assert('api.js has todoCreate function',
  apiJs.indexOf('todoCreate:') >= 0 || apiJs.indexOf('todoCreate :') >= 0);

assert('api.js has todoUpdate function',
  apiJs.indexOf('todoUpdate:') >= 0 || apiJs.indexOf('todoUpdate :') >= 0);

assert('api.js has todayLatestReport function',
  apiJs.indexOf('todayLatestReport:') >= 0 || apiJs.indexOf('todayLatestReport :') >= 0);

/* Verify API paths used by today page */
assert('api.js todayDigest calls /today/digest',
  apiJs.indexOf('/today/digest') >= 0);

assert('api.js todayMeetings calls /today/meetings',
  apiJs.indexOf('/today/meetings') >= 0);

assert('api.js todayNews calls /today/news',
  apiJs.indexOf('/today/news') >= 0);

assert('api.js todos calls /todos',
  apiJs.indexOf("'/todos'") >= 0 || apiJs.indexOf('"/todos"') >= 0);

assert('api.js todoCreate uses POST method',
  apiJs.indexOf("method: 'POST'") >= 0);

assert('api.js todoUpdate uses PATCH method',
  apiJs.indexOf("method: 'PATCH'") >= 0);

assert('api.js todayLatestReport calls /reports',
  apiJs.indexOf("'/reports'") >= 0 || apiJs.indexOf('"/reports"') >= 0);

/* ================================================================
   5. today.html Vue app data & methods
   ================================================================ */
console.log('\n--- today.html Vue app data & methods ---');

assert('today.html has digest data property',
  todayHtml.indexOf('digest:') >= 0);

assert('today.html has todos data property',
  todayHtml.indexOf('todos:') >= 0);

assert('today.html has meetings data property',
  todayHtml.indexOf('meetings:') >= 0);

assert('today.html has news data property',
  todayHtml.indexOf('news:') >= 0);

assert('today.html has latestReport data property',
  todayHtml.indexOf('latestReport:') >= 0);

assert('today.html has refreshAll method',
  todayHtml.indexOf('refreshAll:') >= 0);

assert('today.html has loadDigest method',
  todayHtml.indexOf('loadDigest:') >= 0);

assert('today.html has loadTodos method',
  todayHtml.indexOf('loadTodos:') >= 0);

assert('today.html has loadMeetings method',
  todayHtml.indexOf('loadMeetings:') >= 0);

assert('today.html has loadNews method',
  todayHtml.indexOf('loadNews:') >= 0);

assert('today.html has openDrawer method',
  todayHtml.indexOf('openDrawer:') >= 0);

assert('today.html has closeDrawer method',
  todayHtml.indexOf('closeDrawer:') >= 0);

assert('today.html has showToast method',
  todayHtml.indexOf('showToast:') >= 0);

assert('today.html has toggleTodo method',
  todayHtml.indexOf('toggleTodo:') >= 0);

assert('today.html uses Promise.allSettled for parallel loading',
  todayHtml.indexOf('Promise.allSettled') >= 0);

assert('today.html has formattedDate computed',
  todayHtml.indexOf('formattedDate:') >= 0);

assert('today.html has meetingsCount computed',
  todayHtml.indexOf('meetingsCount:') >= 0);

assert('today.html has todosCount computed',
  todayHtml.indexOf('todosCount:') >= 0);

assert('today.html has urgentCount computed',
  todayHtml.indexOf('urgentCount:') >= 0);

/* Summary */
console.log('\n// SUMMARY: ' + passed + '/' + (passed + failed) + ' passed');
if (failed > 0) {
  process.exit(1);
}
