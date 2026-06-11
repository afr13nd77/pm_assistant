/* Node.js unit tests for roadmap.html */
/* Run: node web/tests/test-roadmap-node.js */

var fs = require('fs');
var path = require('path');

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

/* Load roadmap.html */
var htmlPath = path.join(__dirname, '..', 'roadmap.html');
var html = fs.readFileSync(htmlPath, 'utf8');

/* ========================================
   Section 1: HTML STRUCTURE
   ======================================== */
console.log('\n// 1. HTML STRUCTURE');

assert('file exists and is non-empty', html.length > 0);
assert('has DOCTYPE', html.indexOf('<!DOCTYPE html>') >= 0);
assert('lang is ru', html.indexOf('lang="ru"') >= 0);
assert('has UTF-8 charset', html.indexOf('charset="UTF-8"') >= 0);
assert('has viewport meta', html.indexOf('name="viewport"') >= 0);
assert('title contains PM Board', html.indexOf('<title>PM Board') >= 0);
assert('title contains Roadmap', html.indexOf('Roadmap</title>') >= 0);
assert('links style.css', html.indexOf('href="style.css"') >= 0);

/* ========================================
   Section 2: SCRIPT INCLUDES
   ======================================== */
console.log('\n// 2. SCRIPT INCLUDES');

assert('includes Vue 3 CDN', html.indexOf('unpkg.com/vue@3') >= 0);
assert('includes marked.js CDN', html.indexOf('cdn.jsdelivr.net/npm/marked') >= 0);
assert('includes api.js', html.indexOf('src="api.js"') >= 0);
assert('includes components.js', html.indexOf('src="components.js"') >= 0);
assert('Vue loaded before api.js', html.indexOf('vue@3') < html.indexOf('src="api.js"'));
assert('api.js loaded before components.js', html.indexOf('src="api.js"') < html.indexOf('src="components.js"'));

/* ========================================
   Section 3: APP SIDEBAR
   ======================================== */
console.log('\n// 3. APP SIDEBAR');

assert('has app-sidebar component', html.indexOf('<app-sidebar') >= 0);
assert('app-sidebar active is roadmap', html.indexOf('active="roadmap"') >= 0);

/* ========================================
   Section 4: PAGE LAYOUT
   ======================================== */
console.log('\n// 4. PAGE LAYOUT');

assert('has div#app', html.indexOf('id="app"') >= 0);
assert('has page-content class', html.indexOf('class="page-content"') >= 0);
assert('page title contains PRODUCT_ROADMAP', html.indexOf('PRODUCT_ROADMAP') >= 0);
assert('page title contains Content System', html.indexOf('Content System') >= 0);
assert('has refresh icon with @click="loadEpics"', html.indexOf('@click="loadEpics"') >= 0);
assert('refresh icon is in page-header area',
  html.indexOf('class="refresh-icon"') >= 0 &&
  html.indexOf('class="refresh-icon"') > html.indexOf('class="page-header"'));

/* ========================================
   Section 5: LOADING / ERROR STATES
   ======================================== */
console.log('\n// 5. LOADING / ERROR STATES');

assert('has loading div with v-if="loading"', html.indexOf('v-if="loading"') >= 0);
assert('loading text is LOADING...', html.indexOf('LOADING...') >= 0);
assert('has error div with v-if="error"', html.indexOf('v-if="error"') >= 0);
assert('error uses empty-state class', html.indexOf('class="empty-state">{{ error }}') >= 0);

/* ========================================
   Section 6: STATUS_COLUMN_MAP
   ======================================== */
console.log('\n// 6. STATUS_COLUMN_MAP');

assert('STATUS_COLUMN_MAP is defined', html.indexOf('var STATUS_COLUMN_MAP') >= 0);
assert('map has backlog key', html.indexOf("'backlog': 'backlog'") >= 0);
assert('map has todo key', html.indexOf("'todo': 'todo'") >= 0);
assert('map has open key', html.indexOf("'open': 'todo'") >= 0);
assert('map has draft key', html.indexOf("'draft': 'todo'") >= 0);
assert('map has in-progress key', html.indexOf("'in-progress': 'inprogress'") >= 0);
assert('map has in-review key', html.indexOf("'in-review': 'inprogress'") >= 0);
assert('map has code-review key', html.indexOf("'code-review': 'inprogress'") >= 0);
assert('map has in-testing key', html.indexOf("'in-testing': 'inprogress'") >= 0);
assert('map has deploy key', html.indexOf("'deploy': 'inprogress'") >= 0);
assert('map has staging key', html.indexOf("'staging': 'inprogress'") >= 0);
assert('map has done key', html.indexOf("'done': 'done'") >= 0);
assert('map has closed key', html.indexOf("'closed': 'done'") >= 0);
assert('map has resolved key', html.indexOf("'resolved': 'done'") >= 0);
assert('getColumn function is defined', html.indexOf('function getColumn') >= 0);
assert('map has development key', html.indexOf("'development': 'inprogress'") >= 0 || html.indexOf("'development':'inprogress'") >= 0);
assert('map has ready-for-development key', html.indexOf("'ready-for-development': 'todo'") >= 0 || html.indexOf("'ready-for-development':'todo'") >= 0);
assert('map has в-работе. key', html.indexOf("'в-работе.': 'inprogress'") >= 0);
assert('map has бэклог/идеи key', html.indexOf("'бэклог/идеи': 'backlog'") >= 0);

/* ========================================
   Section 7: FOUR COLUMNS
   ======================================== */
console.log('\n// 7. FOUR COLUMNS');

assert('has roadmap-grid container', html.indexOf('class="roadmap-grid"') >= 0);
assert('roadmap-grid shown when not loading', html.indexOf('class="roadmap-grid" v-if="!loading"') >= 0);

/* Section labels */
assert('has BACKLOG section-label', html.indexOf('class="section-label">BACKLOG</div>') >= 0);
assert('has TODO section-label', html.indexOf('class="section-label">TODO</div>') >= 0);
assert('has IN PROGRESS section-label', html.indexOf('class="section-label">IN PROGRESS</div>') >= 0);
assert('has DONE section-label', html.indexOf('class="section-label">DONE</div>') >= 0);

/* Count section-label occurrences inside the roadmap-grid area */
var gridStart = html.indexOf('class="roadmap-grid"');
var gridEnd = html.indexOf('</main>');
var gridHtml = html.substring(gridStart, gridEnd);
var sectionLabelCount = (gridHtml.match(/class="section-label">/g) || []).length;
assert('exactly 4 section-labels in roadmap-grid', sectionLabelCount === 4, 'got ' + sectionLabelCount);

/* v-for on visible arrays */
assert('v-for on visibleBacklog', html.indexOf('v-for="epic in visibleBacklog"') >= 0);
assert('v-for on visibleTodo', html.indexOf('v-for="epic in visibleTodo"') >= 0);
assert('v-for on visibleInprogress', html.indexOf('v-for="epic in visibleInprogress"') >= 0);
assert('v-for on visibleDone', html.indexOf('v-for="epic in visibleDone"') >= 0);

/* Show more buttons reference full arrays */
assert('show more references backlogEpics', html.indexOf('backlogEpics.length') >= 0);
assert('show more references todoEpics', html.indexOf('todoEpics.length') >= 0);
assert('show more references inprogressEpics', html.indexOf('inprogressEpics.length') >= 0);
assert('show more references doneEpics', html.indexOf('doneEpics.length') >= 0);

/* Empty states */
var noEpicsCount = (gridHtml.match(/No epics/g) || []).length;
assert('4 "No epics" empty states in grid', noEpicsCount === 4, 'got ' + noEpicsCount);

/* ========================================
   Section 8: EPIC CARDS
   ======================================== */
console.log('\n// 8. EPIC CARDS');

assert('epic-card has :key="epic.id"', html.indexOf(':key="epic.id"') >= 0);
assert('epic-card binds :id', html.indexOf(':id="epic.id"') >= 0);
assert('epic-card binds :title', html.indexOf(':title="epic.title"') >= 0);
assert('epic-card binds :priority', html.indexOf(':priority="epic.priority"') >= 0);
assert('epic-card binds :progress', html.indexOf(':progress="epic.progress"') >= 0);
assert('epic-card binds :prd_status', html.indexOf(':prd_status="epic.prd_status"') >= 0);
assert('epic-card binds :tickets', html.indexOf(':tickets="epic.tickets || []"') >= 0);
assert('epic-card has @click="selectEpic(epic)"', html.indexOf('@click="selectEpic(epic)"') >= 0);

/* ========================================
   Section 9: METRICS
   ======================================== */
console.log('\n// 9. METRICS');

assert('has metrics-grid container', html.indexOf('class="metrics-grid"') >= 0);
assert('has TOTAL metric-box', html.indexOf('label="TOTAL"') >= 0);
assert('TOTAL binds totalCount', html.indexOf(':value="totalCount"') >= 0);
assert('TOTAL color is cyan', html.indexOf('label="TOTAL" :value="totalCount" color="cyan"') >= 0);
assert('has BACKLOG metric-box', html.indexOf('label="BACKLOG"') >= 0);
assert('BACKLOG binds backlogCount', html.indexOf(':value="backlogCount"') >= 0);
assert('BACKLOG color is yellow', html.indexOf('label="BACKLOG" :value="backlogCount" color="yellow"') >= 0);
assert('has IN_PROGRESS metric-box', html.indexOf('label="IN_PROGRESS"') >= 0);
assert('IN_PROGRESS binds inProgressCount', html.indexOf(':value="inProgressCount"') >= 0);
assert('IN_PROGRESS color is magenta', html.indexOf('label="IN_PROGRESS" :value="inProgressCount" color="magenta"') >= 0);
assert('has DONE metric-box', html.indexOf('label="DONE"') >= 0);
assert('DONE binds doneCount', html.indexOf(':value="doneCount"') >= 0);
assert('DONE color is green', html.indexOf('label="DONE" :value="doneCount" color="green"') >= 0);

/* 4 metric-box components */
var metricBoxCount = (html.match(/<metric-box /g) || []).length;
assert('exactly 4 metric-box components', metricBoxCount === 4, 'got ' + metricBoxCount);

/* ========================================
   Section 10: DOMAIN TABS
   ======================================== */
console.log('\n// 10. DOMAIN TABS');

assert('has domain-tabs container', html.indexOf('class="domain-tabs"') >= 0);
assert('has ALL button in domain-tabs', html.indexOf('>ALL</button>') >= 0);
assert('has v-for on domains', html.indexOf('v-for="d in domains"') >= 0);

/* ========================================
   Section 11: DRAWER (epic mode)
   ======================================== */
console.log('\n// 11. DRAWER (epic mode)');

assert('has task-drawer class', html.indexOf('class="task-drawer"') >= 0);
assert('drawer toggles open via drawerOpen', html.indexOf('drawerOpen') >= 0);
assert('close button with closeDrawer', html.indexOf('@click="closeDrawer"') >= 0);
assert('drawer close button has [x] text', html.indexOf('[&times;]') >= 0);

/* Epic drawer meta labels */
assert('drawer shows epic status', html.indexOf('drawerEpic.status') >= 0);
assert('drawer does NOT show horizon', html.indexOf('horizon') < 0);
assert('drawer shows epic title', html.indexOf('drawerEpic.title') >= 0);
assert('drawer shows epic priority', html.indexOf('drawerEpic.priority') >= 0);
assert('drawer shows epic progress', html.indexOf('drawerEpic.progress') >= 0);
assert('drawer shows epic domain', html.indexOf('drawerEpic.domain') >= 0);
assert('drawer shows epic prd_status', html.indexOf('drawerEpic.prd_status') >= 0);
assert('drawer shows confluence link', html.indexOf('drawerEpic.confluence_link') >= 0);

/* JIRA_TICKETS section */
assert('has JIRA_TICKETS section title', html.indexOf('JIRA_TICKETS') >= 0);

/* Content sections */
assert('has GOAL section', html.indexOf('>GOAL</div>') >= 0);
assert('has SCOPE section', html.indexOf('>SCOPE</div>') >= 0);
assert('has ACCEPTANCE_CRITERIA section', html.indexOf('>ACCEPTANCE_CRITERIA</div>') >= 0);

/* ========================================
   Section 12: DRAWER (task mode)
   ======================================== */
console.log('\n// 12. DRAWER (task mode)');

assert('task drawer shows task title', html.indexOf('drawerTask.title') >= 0);
assert('task drawer shows task date', html.indexOf('drawerTask.date') >= 0);
assert('task drawer shows task status', html.indexOf('drawerTask.status') >= 0);
assert('task drawer shows task type', html.indexOf('drawerTask.type') >= 0);
assert('task drawer shows task domain', html.indexOf('drawerTask.domain') >= 0);
assert('task drawer shows task priority', html.indexOf('drawerTask.priority') >= 0);
assert('task drawer shows story_points', html.indexOf('drawerTask.story_points') >= 0);
assert('task drawer shows jira_key', html.indexOf('drawerTask.jira_key') >= 0);
assert('back button calls backToEpic', html.indexOf('@click="backToEpic"') >= 0);
assert('task drawer has jira-create-section', html.indexOf('<jira-create-section') >= 0);

/* ========================================
   Section 13: VUE LOGIC
   ======================================== */
console.log('\n// 13. VUE LOGIC');

/* Composition API setup */
assert('uses setup function', html.indexOf('setup:') >= 0 || html.indexOf('setup(') >= 0);

/* Reactive refs */
assert('declares epics ref as Vue.ref([])', html.indexOf('Vue.ref([])') >= 0);
assert('declares loading ref as Vue.ref(true)', html.indexOf('Vue.ref(true)') >= 0);
assert('declares error ref as Vue.ref(null)', html.indexOf('Vue.ref(null)') >= 0);

/* Computed properties - column filters */
assert('backlogEpics computed defined', html.indexOf('var backlogEpics = Vue.computed') >= 0);
assert('todoEpics computed defined', html.indexOf('var todoEpics = Vue.computed') >= 0);
assert('inprogressEpics computed defined', html.indexOf('var inprogressEpics = Vue.computed') >= 0);
assert('doneEpics computed defined', html.indexOf('var doneEpics = Vue.computed') >= 0);

/* Visible slices */
assert('visibleBacklog computed defined', html.indexOf('var visibleBacklog = Vue.computed') >= 0);
assert('visibleTodo computed defined', html.indexOf('var visibleTodo = Vue.computed') >= 0);
assert('visibleInprogress computed defined', html.indexOf('var visibleInprogress = Vue.computed') >= 0);
assert('visibleDone computed defined', html.indexOf('var visibleDone = Vue.computed') >= 0);

/* Metric computeds */
assert('totalCount computed defined', html.indexOf('var totalCount = Vue.computed') >= 0);
assert('backlogCount computed defined', html.indexOf('var backlogCount = Vue.computed') >= 0);
assert('inProgressCount computed defined', html.indexOf('var inProgressCount = Vue.computed') >= 0);
assert('doneCount computed defined', html.indexOf('var doneCount = Vue.computed') >= 0);

/* Methods */
assert('loadEpics function defined', html.indexOf('function loadEpics') >= 0 || html.indexOf('loadEpics =') >= 0);
assert('selectEpic function defined', html.indexOf('function selectEpic') >= 0);
assert('closeDrawer function defined', html.indexOf('function closeDrawer') >= 0);
assert('showMore function defined', html.indexOf('function showMore') >= 0);
assert('selectDomain function defined', html.indexOf('function selectDomain') >= 0);

/* Lifecycle */
assert('uses Vue.onMounted', html.indexOf('Vue.onMounted') >= 0);

/* ========================================
   Section 14: SETUP RETURN
   ======================================== */
console.log('\n// 14. SETUP RETURN');

assert('setup returns epics', html.indexOf('epics: epics') >= 0);
assert('setup returns loading', html.indexOf('loading: loading') >= 0);
assert('setup returns error', html.indexOf('error: error') >= 0);
assert('setup returns backlogEpics', html.indexOf('backlogEpics: backlogEpics') >= 0);
assert('setup returns todoEpics', html.indexOf('todoEpics: todoEpics') >= 0);
assert('setup returns inprogressEpics', html.indexOf('inprogressEpics: inprogressEpics') >= 0);
assert('setup returns doneEpics', html.indexOf('doneEpics: doneEpics') >= 0);
assert('setup returns visibleBacklog', html.indexOf('visibleBacklog: visibleBacklog') >= 0);
assert('setup returns visibleTodo', html.indexOf('visibleTodo: visibleTodo') >= 0);
assert('setup returns visibleInprogress', html.indexOf('visibleInprogress: visibleInprogress') >= 0);
assert('setup returns visibleDone', html.indexOf('visibleDone: visibleDone') >= 0);
assert('setup returns totalCount', html.indexOf('totalCount: totalCount') >= 0);
assert('setup returns backlogCount', html.indexOf('backlogCount: backlogCount') >= 0);
assert('setup returns inProgressCount', html.indexOf('inProgressCount: inProgressCount') >= 0);
assert('setup returns doneCount', html.indexOf('doneCount: doneCount') >= 0);
assert('setup returns loadEpics', html.indexOf('loadEpics: loadEpics') >= 0);
assert('setup returns selectEpic', html.indexOf('selectEpic: selectEpic') >= 0);
assert('setup returns closeDrawer', html.indexOf('closeDrawer: closeDrawer') >= 0);
assert('setup returns showMore', html.indexOf('showMore: showMore') >= 0);
assert('setup returns selectDomain', html.indexOf('selectDomain: selectDomain') >= 0);

/* ========================================
   Section 15: CONSOLE LOGGING
   ======================================== */
console.log('\n// 15. CONSOLE LOGGING');

assert('logs initialization', html.indexOf("console.log('[roadmap] initializing roadmap page')") >= 0);
assert('logs loadEpics call', html.indexOf("[roadmap] loadEpics") >= 0);
assert('logs selectEpic action', html.indexOf("[roadmap] selectEpic") >= 0);
assert('logs closeDrawer action', html.indexOf("[roadmap] closeDrawer") >= 0);
assert('logs app mounted', html.indexOf("[roadmap] app mounted") >= 0);

/* ========================================
   Section 16: ERROR HANDLING
   ======================================== */
console.log('\n// 16. ERROR HANDLING');

assert('has try block', html.indexOf('try {') >= 0);
assert('has catch (err) block', html.indexOf('catch (err)') >= 0);
assert('has finally block', html.indexOf('finally {') >= 0);
assert('error.value set on failure', html.indexOf("error.value = 'Failed to load epics:") >= 0);
assert('loading set to false in finally', html.indexOf('loading.value = false') >= 0);

/* ========================================
   Section 17: REGISTER AND MOUNT
   ======================================== */
console.log('\n// 17. REGISTER AND MOUNT');

assert('calls registerComponents(app)', html.indexOf('registerComponents(app)') >= 0);
assert('calls app.mount(#app)', html.indexOf("app.mount('#app')") >= 0);

/* ========================================
   Summary
   ======================================== */
console.log('\n// SUMMARY: ' + passed + '/' + (passed + failed) + ' passed');
if (failed > 0) {
  process.exit(1);
}
