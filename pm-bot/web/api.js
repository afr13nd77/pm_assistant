/* api.js -- Fetch client for vault_api (plain JS, no Vue dependency) */

var API = 'http://localhost:8000/api/v1';

/* ----------------------------------------------------------------
   P1-1: AbortController map for request cancellation.
   Tracks in-flight requests by path so duplicate requests
   to the same path cancel the previous one.
   ---------------------------------------------------------------- */
var _currentControllers = {};

/* ----------------------------------------------------------------
   P0-2: Domain cache using sessionStorage with 60-second TTL.
   ---------------------------------------------------------------- */
var _domainsCache = null;
var _domainsCacheTs = 0;
var DOMAINS_CACHE_TTL = 60000; // 60 seconds

/**
 * Generic fetch wrapper with logging, error handling, and request cancellation.
 * @param {string} path - API path relative to API base
 * @param {object} opts - fetch options (method, headers, body, etc.)
 * @returns {Promise<any>} - parsed JSON response
 */
async function apiFetch(path, opts) {
  opts = opts || {};
  var method = opts.method || 'GET';
  console.log('[api]', method, path);

  // P1-1: Cancel any in-flight request to the same path
  if (_currentControllers[path]) {
    console.log('[api] aborting previous request to', path);
    _currentControllers[path].abort();
  }

  // Create new AbortController for this request
  var controller = new AbortController();
  _currentControllers[path] = controller;
  opts.signal = controller.signal;

  try {
    var res = await fetch(API + path, opts);
    if (!res.ok) {
      var errText = '';
      try { errText = await res.text(); } catch (_e) { /* ignore */ }
      console.error('[api] error', res.status, path, errText);
      throw new Error('API error: ' + res.status + ' ' + errText);
    }
    var data = await res.json();
    console.log('[api] success', method, path, 'items:', Array.isArray(data) ? data.length : 1);
    return data;
  } catch (err) {
    // P1-1: Don't log AbortError as a real error
    if (err.name === 'AbortError') {
      console.log('[api] request aborted', method, path);
      throw err;
    }
    console.error('[api] fetch failed', method, path, err.message);
    throw err;
  } finally {
    // Clean up controller reference if it is still ours
    if (_currentControllers[path] === controller) {
      delete _currentControllers[path];
    }
  }
}

var _jiraProjectsCache = null;
var _jiraProjectsCacheTs = 0;
var _jiraEpicsCaches = {};
var _jiraIssueTypesCaches = {};
var _JIRA_CACHE_TTL = 300000; // 5 minutes
var _jiraSearchCache = {};
var _JIRA_SEARCH_CACHE_TTL = 60000;

var api = {
  /** GET /api/v1/ideas -- ideas sorted by date, optional domain filter */
  ideas: function(domain) {
    var path = '/ideas';
    if (domain) path += '?domain=' + encodeURIComponent(domain);
    return apiFetch(path);
  },

  /** GET /api/v1/meetings?days=N -- meeting notes for the last N days */
  meetings: function(days) {
    days = days || 14;
    return apiFetch('/meetings?days=' + days);
  },

  /** GET /api/v1/tasks -- task drafts from Tasks/Drafts/, optional domain filter */
  tasks: function(domain) {
    var path = '/tasks';
    if (domain) path += '?domain=' + encodeURIComponent(domain);
    return apiFetch(path);
  },

  /** GET /api/v1/epics -- epics with progress, optional domain filter */
  epics: function(domain) {
    var path = '/epics';
    if (domain) path += '?domain=' + encodeURIComponent(domain);
    return apiFetch(path);
  },

  /**
   * GET /api/v1/domains -- domain statistics.
   * P0-2: Uses sessionStorage cache with 60-second TTL.
   */
  domains: function() {
    var now = Date.now();

    // Check in-memory cache first
    if (_domainsCache && (now - _domainsCacheTs) < DOMAINS_CACHE_TTL) {
      console.log('[api] domains: returning cached data (age: ' + (now - _domainsCacheTs) + 'ms)');
      return Promise.resolve(_domainsCache);
    }

    // Check sessionStorage fallback
    try {
      var stored = sessionStorage.getItem('pm_domains_cache');
      var storedTs = parseInt(sessionStorage.getItem('pm_domains_cache_ts') || '0', 10);
      if (stored && (now - storedTs) < DOMAINS_CACHE_TTL) {
        _domainsCache = JSON.parse(stored);
        _domainsCacheTs = storedTs;
        console.log('[api] domains: returning sessionStorage cached data (age: ' + (now - storedTs) + 'ms)');
        return Promise.resolve(_domainsCache);
      }
    } catch (e) {
      console.log('[api] domains: sessionStorage read failed, fetching fresh');
    }

    // Fetch fresh data
    return apiFetch('/domains').then(function(data) {
      _domainsCache = data;
      _domainsCacheTs = Date.now();
      try {
        sessionStorage.setItem('pm_domains_cache', JSON.stringify(data));
        sessionStorage.setItem('pm_domains_cache_ts', String(_domainsCacheTs));
      } catch (e) {
        console.log('[api] domains: sessionStorage write failed');
      }
      return data;
    });
  },

  /** GET /api/v1/timeline/:id -- feature timeline by ticket ID */
  timeline: function(id) {
    return apiFetch('/timeline/' + encodeURIComponent(id));
  },

  /** GET /api/v1/reports -- list all reports */
  reports: function() {
    return apiFetch('/reports');
  },

  /** GET /api/v1/reports/:filename -- get specific report */
  reportByFilename: function(filename) {
    return apiFetch('/reports/' + encodeURIComponent(filename));
  },

  /** POST /api/v1/capture -- create a new note (idea/task/meeting) */
  capture: function(type, text) {
    return apiFetch('/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: type, text: text })
    });
  },

  /** POST /api/v1/report/regenerate -- regenerate the weekly report */
  regenerate: function() {
    return apiFetch('/report/regenerate', { method: 'POST' });
  },

  /** GET /api/v1/pipeline -- list pipeline runs */
  pipeline: function() {
    return apiFetch('/pipeline');
  },

  /** POST /api/v1/jira/import -- import a single Jira issue by key */
  jiraImport: function(key) {
    return apiFetch('/jira/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key })
    });
  },

  /** GET /api/v1/tasks/by-key/:key -- single task by jira_key */
  taskByKey: function(key) {
    return apiFetch('/tasks/by-key/' + encodeURIComponent(key));
  },

  /** POST /api/v1/jira/create -- create a new Jira issue */
  jiraCreate: function(data) {
    return apiFetch('/jira/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
  },

  /** GET /api/v1/jira/projects -- list Jira projects (5-minute in-memory cache) */
  jiraProjects: function() {
    var now = Date.now();
    if (_jiraProjectsCache && (now - _jiraProjectsCacheTs) < _JIRA_CACHE_TTL) {
      console.log('[api] jiraProjects: returning cached data (age: ' + (now - _jiraProjectsCacheTs) + 'ms)');
      return Promise.resolve(_jiraProjectsCache);
    }
    return apiFetch('/jira/projects').then(function(data) {
      _jiraProjectsCache = data;
      _jiraProjectsCacheTs = Date.now();
      return data;
    });
  },

  /** GET /api/v1/jira/projects/:projectKey/epics -- list epics for a project (per-project 5-minute cache) */
  jiraProjectEpics: function(projectKey) {
    var now = Date.now();
    var cached = _jiraEpicsCaches[projectKey];
    if (cached && (now - cached.ts) < _JIRA_CACHE_TTL) {
      console.log('[api] jiraProjectEpics: returning cached data for ' + projectKey + ' (age: ' + (now - cached.ts) + 'ms)');
      return Promise.resolve(cached.data);
    }
    return apiFetch('/jira/projects/' + encodeURIComponent(projectKey) + '/epics').then(function(data) {
      _jiraEpicsCaches[projectKey] = { data: data, ts: Date.now() };
      return data;
    });
  },

  /** GET /api/v1/jira/projects/:projectKey/issue-types -- list issue types for a project (per-project 5-minute cache) */
  jiraIssueTypes: function(projectKey) {
    var now = Date.now();
    var cached = _jiraIssueTypesCaches[projectKey];
    if (cached && (now - cached.ts) < _JIRA_CACHE_TTL) {
      console.log('[api] jiraIssueTypes: returning cached data for ' + projectKey + ' (age: ' + (now - cached.ts) + 'ms)');
      return Promise.resolve(cached.data);
    }
    return apiFetch('/jira/projects/' + encodeURIComponent(projectKey) + '/issue-types').then(function(data) {
      _jiraIssueTypesCaches[projectKey] = { data: data, ts: Date.now() };
      return data;
    });
  },

  /** GET /api/v1/jira/search — search issues in a Jira project */
  jiraSearch: function(projectKey, type, status, maxResults) {
    maxResults = maxResults || 50;
    var cacheKey = projectKey + '|' + (type || '') + '|' + (status || '') + '|' + maxResults;
    var now = Date.now();
    var cached = _jiraSearchCache[cacheKey];
    if (cached && (now - cached.ts) < _JIRA_SEARCH_CACHE_TTL) {
      console.log('[api] jiraSearch: returning cached data for', cacheKey);
      return Promise.resolve(cached.data);
    }
    var path = '/jira/search?project=' + encodeURIComponent(projectKey)
      + '&max_results=' + maxResults;
    if (type) path += '&type=' + encodeURIComponent(type);
    if (status) path += '&status=' + encodeURIComponent(status);
    return apiFetch(path).then(function(data) {
      _jiraSearchCache[cacheKey] = { data: data, ts: Date.now() };
      return data;
    });
  },

  /** POST /api/v1/jira/sync -- trigger forced Jira sync */
  jiraSync: function() {
    return apiFetch('/jira/sync', { method: 'POST' });
  },

  /** GET /api/v1/jira/sync-status -- get Jira sync status and metrics */
  jiraSyncStatus: function() {
    return apiFetch('/jira/sync-status');
  },

  /** GET /api/v1/domain-config -- list all domain config entries */
  domainConfig: function() {
    return apiFetch('/domain-config');
  },

  /** PUT /api/v1/domain-config/:slug -- save (upsert) a domain config entry */
  saveDomainConfig: function(slug, entry) {
    return apiFetch('/domain-config/' + encodeURIComponent(slug), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry)
    });
  },

  /** POST /api/v1/domain-config/seed -- seed domain config from existing domains */
  seedDomainConfig: function() {
    return apiFetch('/domain-config/seed', { method: 'POST' });
  },

  /** GET /api/v1/user-prefs -- user preferences (refresh mode, etc.) */
  getUserPrefs: function() {
    return apiFetch('/user-prefs');
  },

  /** PUT /api/v1/user-prefs -- save user preferences */
  saveUserPrefs: function(prefs) {
    return apiFetch('/user-prefs', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs)
    });
  },

  /** POST /api/v1/test-ollama -- test Ollama connection */
  testOllama: function(url) {
    return apiFetch('/test-ollama', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url })
    });
  },

  /** PATCH /api/v1/ideas/:filename/status -- update idea status via drag-drop */
  updateIdeaStatus: function(filename, status) {
    return apiFetch('/ideas/' + encodeURIComponent(filename) + '/status', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: status })
    });
  },

  /** GET /api/v1/vault/health -- vault health score with breakdown and trends */
  vaultHealth: function() {
    return apiFetch('/vault/health');
  },

  /** GET /api/v1/ideas/creative?count=N -- forgotten ideas for creative recall */
  creative: function(count) {
    count = count || 5;
    return apiFetch('/ideas/creative?count=' + count);
  },

  /** POST /api/v1/decay/touch -- reset decay timer for an idea */
  touchIdea: function(filepath) {
    return apiFetch('/decay/touch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filepath: filepath })
    });
  },

  setTier: function(filepath, tier) {
    return apiFetch('/decay/set-tier', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filepath: filepath, tier: tier })
    });
  },

  /** GET /api/v1/decay/snapshot -- full decay state snapshot */
  decaySnapshot: function() {
    return apiFetch('/decay/snapshot');
  },

  /** GET /api/v1/artifact?path=<filepath> -- single artifact details */
  artifact: function(filepath) {
    return apiFetch('/artifact?path=' + encodeURIComponent(filepath));
  },

  /** GET /api/v1/search?q=<query>&limit=<N> -- full-text search across vault */
  search: function(query, limit) {
    limit = limit || 20;
    return apiFetch('/search?q=' + encodeURIComponent(query) + '&limit=' + limit);
  },

  /** PATCH /api/v1/artifact/{filename}/field — update single frontmatter field */
  updateField: function(filename, key, value) {
    return apiFetch('/artifact/' + encodeURIComponent(filename) + '/field', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key: key, value: value})
    });
  },
  /** PATCH /api/v1/artifact/{filename}/body — update markdown body */
  updateBody: function(filename, body) {
    return apiFetch('/artifact/' + encodeURIComponent(filename) + '/body', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({body: body})
    });
  },

  /** POST /api/v1/test-openrouter -- test OpenRouter connection */
  testOpenRouter: function(model) {
    return apiFetch('/test-openrouter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: model })
    });
  },

  /** GET /api/v1/openrouter-key-status -- check if API key is set */
  openrouterKeyStatus: function() {
    return apiFetch('/openrouter-key-status');
  },

  /** GET /api/v1/openrouter-models -- list available OpenRouter models */
  openrouterModels: function() {
    return apiFetch('/openrouter-models');
  }
};

/**
 * Invalidate the domains cache.
 * Call after capture/synthesize to force re-fetch on next domains() call.
 */
api.domains.invalidate = function() {
  console.log('[api] domains cache invalidated');
  _domainsCache = null;
  _domainsCacheTs = 0;
  try {
    sessionStorage.removeItem('pm_domains_cache');
    sessionStorage.removeItem('pm_domains_cache_ts');
  } catch (e) { /* ignore */ }
};
