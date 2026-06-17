/* components.js -- Shared Vue 3 components registered globally */

/** Format ISO date (YYYY-MM-DD) → DD.MM.YYYY. Non-matching strings returned as-is. */
function fmtDate(d) {
  if (!d) return '';
  var m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? m[3] + '.' + m[2] + '.' + m[1] : d;
}

/**
 * Apply the specified theme (CSS, body classes, glow blobs).
 * @param {string} [theme] - 'matrix' or 'light'. Defaults to localStorage or 'matrix'.
 * Returns a Promise for backward compatibility.
 */
function applyPageTheme(theme) {
  if (!theme) {
    try {
      theme = localStorage.getItem('pm_theme') || 'matrix';
    } catch (e) {
      theme = 'matrix';
    }
  }

  if (theme !== 'matrix' && theme !== 'light') {
    console.warn('[theme] invalid theme "' + theme + '", falling back to matrix');
    theme = 'matrix';
  }

  console.log('[theme] applying theme:', theme);

  var html = document.documentElement;
  html.classList.remove('theme-matrix', 'theme-light');
  html.classList.add('theme-' + theme);

  var link = document.getElementById('theme-css');
  if (link) {
    var newHref = theme === 'light' ? 'style-light.css' : 'style-matrix.css';
    if (link.getAttribute('href') !== newHref) {
      link.setAttribute('href', newHref);
      console.log('[theme] CSS link updated to:', newHref);
    }
  }

  if (theme === 'matrix') {
    document.body.classList.add('bg-matrix');
    document.body.classList.remove('bg-light');
    if (!document.querySelector('.glow-blob-1')) {
      var blob1 = document.createElement('div');
      blob1.className = 'glow-blob-1';
      document.body.appendChild(blob1);
      var blob2 = document.createElement('div');
      blob2.className = 'glow-blob-2';
      document.body.appendChild(blob2);
    }
  } else {
    document.body.classList.remove('bg-matrix');
    document.body.classList.add('bg-light');
    var blobs = document.querySelectorAll('.glow-blob-1, .glow-blob-2, .glow-overlay');
    for (var i = 0; i < blobs.length; i++) {
      blobs[i].parentNode.removeChild(blobs[i]);
    }
  }

  try {
    localStorage.setItem('pm_theme', theme);
  } catch (e) { /* ignore */ }

  return Promise.resolve();
}

/**
 * Register all shared components on a Vue app instance.
 * Call registerComponents(app) before app.mount().
 * @param {object} app - Vue 3 app instance from createApp()
 */
function registerComponents(app) {

  /* --------------------------------------------------------
     Inject component-scoped CSS for domain-config-drawer.
     Runs once per page load; skips if the style tag already
     exists (e.g. registerComponents called more than once).
     -------------------------------------------------------- */
  if (!document.getElementById('domain-config-drawer-styles')) {
    var _drawerStyle = document.createElement('style');
    _drawerStyle.id = 'domain-config-drawer-styles';
    _drawerStyle.textContent = [
      '.drawer-panel { position:fixed; top:0; right:0; bottom:0; background:var(--card); border-left:1px solid var(--border); z-index:201; display:flex; flex-direction:column; overflow:hidden; }',
      '.domain-config-drawer { width:420px; max-width:90vw; }',
      '.drawer-header { display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); flex-shrink:0; }',
      '.drawer-header h3 { font-family:var(--font); font-size:12px; letter-spacing:0.1em; color:var(--cyan); font-weight:normal; margin:0; }',
      '.drawer-close { font-family:var(--font); font-size:16px; color:var(--text-muted); cursor:pointer; background:none; border:none; padding:4px 8px; line-height:1; }',
      '.drawer-close:hover { color:var(--text-body); }',
      '.drawer-body { flex:1; overflow-y:auto; padding:20px; }',
      '.drawer-footer { display:flex; justify-content:flex-end; gap:8px; padding:16px 20px; border-top:1px solid var(--border); flex-shrink:0; }',
      '.btn { font-family:var(--font); font-size:11px; letter-spacing:0.08em; padding:6px 16px; background:transparent; border:1px solid var(--border); color:var(--text-body); cursor:pointer; transition:all 0.15s; }',
      '.btn:hover { border-color:var(--border-hover); }',
      '.btn:disabled { opacity:0.5; cursor:not-allowed; }',
      '.btn-primary { border-color:var(--cyan); color:var(--cyan); }',
      '.btn-primary:hover { background:var(--cyan-bg); }',
      '.btn-sm { padding:4px 12px; font-size:13px; }',
      '.color-swatch { width:32px; height:32px; border-radius:4px; border:1px solid rgba(255,255,255,0.2); flex-shrink:0; }',
      '.label-tags { display:flex; flex-wrap:wrap; gap:6px; }',
      '.label-tag { display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:4px; background:rgba(255,255,255,0.1); font-size:13px; }',
      '.label-tag-remove { background:none; border:none; color:inherit; cursor:pointer; opacity:0.6; padding:0 2px; }',
      '.label-tag-remove:hover { opacity:1; }',
      '.form-group { margin-bottom:16px; }',
      '.form-group label { display:block; margin-bottom:4px; font-size:13px; opacity:0.7; }',
      '.form-group input, .form-group textarea { width:100%; padding:8px; border:1px solid rgba(255,255,255,0.2); background:rgba(0,0,0,0.2); color:inherit; font-family:var(--font); font-size:12px; box-sizing:border-box; outline:none; transition:border-color 0.15s; }',
      '.form-group input:focus, .form-group textarea:focus { border-color:var(--cyan); }',
      '.form-group textarea { resize:vertical; }',
      '.form-group small { font-size:11px; opacity:0.5; display:block; margin-top:3px; }',
      '.input-readonly { opacity:0.6; cursor:not-allowed; }',
      '.form-error { color:#ef5350; font-size:13px; margin-top:8px; padding:8px; background:rgba(239,83,80,0.1); border-radius:4px; }'
    ].join('\n');
    document.head.appendChild(_drawerStyle);
    console.log('[components] domain-config-drawer-styles injected');
  }

  /* ========================================
     AppSidebar -- shared navigation sidebar
     Props:
       active (string): overview | domains | ideas | roadmap | board | timeline | report | settings | about
     ======================================== */
  app.component('app-sidebar', {
    props: {
      active: { type: String, default: '' }
    },
    emits: ['search'],
    computed: {
      links: function() {
        return [
          { name: 'overview', label: 'OVERVIEW', href: 'overview.html', icon: 'monitoring' },
          { name: 'domains', label: 'DASHBOARD', href: 'dashboard.html', icon: 'space_dashboard' },
          { name: 'ideas', label: 'IDEAS', href: 'ideas.html', icon: 'lightbulb' },
          { name: 'roadmap', label: 'DEVELOPMENT', href: 'roadmap.html', icon: 'rocket_launch' },
          { name: 'board', label: 'TASKS', href: 'board.html', icon: 'task_alt' },
          { name: 'report', label: 'REPORTS', href: 'report.html', icon: 'summarize' },
          { name: 'timeline', label: 'TIMELINE', href: 'timeline.html', icon: 'timeline' },
          { name: 'decay', label: 'DECAY', href: 'decay.html', icon: 'psychology' }
        ];
      }
    },
    template: '\
      <nav class="sidebar">\
        <div class="sidebar-logo">PM<span class="accent">_</span>BOARD</div>\
        <button class="nav-link search-trigger" @click="$emit(\'search\')"><span class="material-symbols-outlined">search</span>SEARCH<kbd class="sidebar-kbd">Ctrl+K</kbd></button>\
        <a v-for="link in links"\
           :key="link.name"\
           :href="link.href"\
           class="nav-link"\
           :class="{ active: active === link.name }"\
        ><span class="material-symbols-outlined">{{ link.icon }}</span>{{ link.label }}</a>\
        <div class="nav-divider"></div>\
        <a href="settings.html"\
           class="nav-link"\
           :class="{ active: active === \'settings\' }"\
        ><span class="material-symbols-outlined">settings</span>SETTINGS</a>\
        <a href="about.html"\
           class="nav-link"\
           :class="{ active: active === \'about\' }"\
        ><span class="material-symbols-outlined">info</span>ABOUT</a>\
      </nav>'
  });

  /* ========================================
     NoteCard -- used in board.html for inbox/tasks/done cards
     Props:
       type (string): e.g. IDEA_CAPTURE, MEETING_SUMMARY, JIRA_DRAFT
       title (string): card title text
       tags (array): list of tag strings (idea, prd, jira, done, wip, todo, blocked)
       date (string): date string e.g. 2026-04-26
       status (string): inbox, processing, done, etc.
     Emits: click
     ======================================== */
  app.component('note-card', {
    props: {
      type:     { type: String, default: '' },
      title:    { type: String, default: '' },
      tags:     { type: Array, default: function() { return []; } },
      date:     { type: String, default: '' },
      status:   { type: String, default: '' },
      jiraKey:  { type: String, default: '' },
      tier:     { type: String, default: 'active' },
      filepath: { type: String, default: '' },
      filename: { type: String, default: '' }
    },
    emits: ['click', 'pin'],
    computed: {
      tagClasses: function() {
        var self = this;
        return self.tags.map(function(tag) {
          var lower = tag.toLowerCase();
          return {
            text: tag.toUpperCase(),
            cls: 'tag tag-' + lower
          };
        });
      },
      typeLabel: function() {
        return this.type ? this.type.toUpperCase() : '';
      },
      cardClass: function() {
        var t = (this.type || '').toUpperCase();
        if (t.indexOf('MEETING') !== -1) return 'card-meeting';
        if (t.indexOf('IDEA') !== -1) return 'card-idea';
        if (t === 'JIRA_BUG') return 'card-meeting';
        if (t.indexOf('JIRA') !== -1) return 'card-jira';
        if (t.indexOf('SYNTHESIS') !== -1) return 'card-synthesis';
        return '';
      },
      clipCut: function() {
        var t = (this.type || '').toUpperCase();
        if (t.indexOf('MEETING') !== -1 || t === 'JIRA_BUG') return 'card-cut-bl';
        return 'card-cut-br';
      },
      accentColor: function() {
        var t = (this.type || '').toUpperCase();
        if (t.indexOf('MEETING') !== -1) return 'magenta';
        if (t.indexOf('IDEA') !== -1) return 'cyan';
        if (t === 'JIRA_BUG') return 'magenta';
        if (t.indexOf('JIRA') !== -1) return 'amber';
        if (t.indexOf('SYNTHESIS') !== -1) return 'purple';
        return 'cyan';
      },
      clipBorderClass: function() {
        return 'card-cut-' + this.accentColor;
      },
      statusLabel: function() {
        return this.status ? this.status.toUpperCase() : '';
      },
      statusTagClass: function() {
        var s = (this.status || '').toLowerCase();
        if (s === 'done') return 'tag tag-done';
        if (s === 'in-progress') return 'tag tag-jira';
        if (s === 'in-review' || s === 'in-testing') return 'tag tag-prd';
        if (s === 'todo') return 'tag tag-muted';
        if (s === 'cancelled') return 'tag tag-blocked';
        if (s === 'deploy' || s === 'staging') return 'tag tag-idea';
        return 'tag tag-muted';
      }
    },
    methods: {
      fmtDate: fmtDate
    },
    template: '\
      <div class="card-clip" :class="[clipCut, clipBorderClass]" :data-filename="filename" @click="$emit(\'click\')">\
        <div class="card-accent" :class="\'card-accent-\' + accentColor"></div>\
        <svg class="card-corner-svg" :class="\'card-corner-\' + accentColor" viewBox="0 0 16 16">\
          <polyline points="14,2 2,2 2,14" fill="none" stroke="currentColor" stroke-width="1.5"/>\
        </svg>\
        <div style="position:relative;z-index:1">\
          <div class="card-header">\
            <span class="card-stage" :class="\'text-\' + accentColor" v-if="typeLabel">{{ typeLabel }}</span>\
            <span class="card-date">{{ fmtDate(date) }}</span>\
          </div>\
          <div class="card-title">{{ title }}</div>\
          <div class="card-meta">\
            <span>\
              <span v-if="statusLabel" :class="statusTagClass + \' mr-xs\'">{{ statusLabel }}</span>\
              <span v-if="jiraKey" class="tag tag-jira tag-sm mr-xs">JIRA</span>\
              <span v-else class="tag tag-muted tag-sm mr-xs">LOCAL</span>\
              <span v-for="t in tagClasses" :key="t.text" :class="t.cls + \' mr-xs\'">{{ t.text }}</span>\
            </span>\
          </div>\
        </div>\
        <button class="pin-btn" :class="{pinned: tier === \'core\'}" @click.stop="$emit(\'pin\')" :title="tier === \'core\' ? \'Открепить\' : \'Закрепить\'">📌</button>\
      </div>'
  });

  /* ========================================
     EpicCard -- used in roadmap.html
     Props:
       id (string): e.g. E-01
       title (string): epic title
       horizon (string): now, next, later
       priority (string): p1, p2, p3
       progress (number): 0-100
       prd_status (string): APPROVED, DRAFT, etc.
       tickets (array): list of ticket objects
       tags (array): list of tag strings
     Emits: click
     ======================================== */
  app.component('epic-card', {
    props: {
      id:         { type: String, default: '' },
      title:      { type: String, default: '' },
      horizon:    { type: String, default: '' },
      priority:   { type: String, default: 'p3' },
      progress:   { type: Number, default: 0 },
      prd_status: { type: String, default: '' },
      tickets:    { type: Array, default: function() { return []; } },
      tags:       { type: Array, default: function() { return []; } }
    },
    emits: ['click'],
    computed: {
      priorityClass: function() {
        var p = this.priority.toLowerCase();
        if (p === 'p1') return 'card-p1';
        if (p === 'p2') return 'card-p2';
        return 'card-p3';
      },
      fillColor: function() {
        if (this.progress >= 80) return 'fill-high';
        if (this.progress >= 40) return 'fill-mid';
        return 'fill-low';
      },
      computedTags: function() {
        var result = [];
        if (this.tags && this.tags.length > 0) {
          for (var i = 0; i < this.tags.length; i++) {
            var tag = this.tags[i];
            result.push({
              text: tag.toUpperCase(),
              cls: 'tag tag-' + tag.toLowerCase()
            });
          }
        } else {
          if (this.prd_status) {
            result.push({ text: 'PRD', cls: 'tag tag-prd' });
          }
          if (this.tickets && this.tickets.length > 0) {
            result.push({ text: 'JIRA', cls: 'tag tag-jira' });
          }
          if (!this.prd_status && (!this.tickets || this.tickets.length === 0)) {
            result.push({ text: 'IDEA', cls: 'tag tag-idea' });
          }
        }
        return result;
      },
      clipAccent: function() {
        if (this.progress >= 80) return 'green';
        if (this.priority.toLowerCase() === 'p1') return 'magenta';
        return 'cyan';
      },
      clipCut: function() {
        if (this.priority.toLowerCase() === 'p1') return 'card-cut-bl';
        return 'card-cut-br';
      },
      clipBorderClass: function() {
        return 'card-cut-' + this.clipAccent;
      }
    },
    template: '\
      <div class="card-clip" :class="[clipCut, clipBorderClass]" :data-filename="id" @click="$emit(\'click\')">\
        <div class="card-accent" :class="\'card-accent-\' + clipAccent"></div>\
        <svg class="card-corner-svg" :class="\'card-corner-\' + clipAccent" viewBox="0 0 16 16">\
          <polyline points="14,2 2,2 2,14" fill="none" stroke="currentColor" stroke-width="1.5"/>\
        </svg>\
        <div style="position:relative;z-index:1">\
          <div class="card-header">\
            <span class="card-stage" :class="\'text-\' + clipAccent">EPIC</span>\
            <span class="card-id">{{ id }}</span>\
          </div>\
          <div class="card-title">{{ title }}</div>\
          <div class="progress-wrap">\
            <div class="progress-label">\
              <span>progress</span>\
              <span>{{ progress }}%</span>\
            </div>\
            <div class="progress-bar">\
              <div class="progress-fill" :class="fillColor" :style="{ width: progress + \'%\' }"></div>\
            </div>\
          </div>\
          <div class="card-meta">\
            <span>\
              <span v-for="t in computedTags" :key="t.text" :class="t.cls + \' mr-xs\'">{{ t.text }}</span>\
            </span>\
            <span class="card-date" v-if="tickets.length">{{ tickets.length }} tickets</span>\
          </div>\
        </div>\
      </div>'
  });

  /* ========================================
     IdeaCard -- used in ideas.html
     Props:
       ideaId (string): e.g. ID-01
       title (string): idea title
       readiness (number): 0-100
       date (string): date string e.g. 2026-04-26
       domain (string): domain slug
     Emits: click
     ======================================== */
  app.component('idea-card', {
    props: {
      ideaId:    { type: String, default: '' },
      title:     { type: String, default: '' },
      readiness: { type: Number, default: 0 },
      date:      { type: String, default: '' },
      domain:    { type: String, default: '' },
      filename:  { type: String, default: '' },
      status:    { type: String, default: '' },
      tier:      { type: String, default: 'active' },
      filepath:  { type: String, default: '' }
    },
    emits: ['click', 'dragstart', 'pin'],
    computed: {
      fillColor: function() {
        if (this.readiness >= 80) return 'fill-high';
        if (this.readiness >= 40) return 'fill-mid';
        return 'fill-low';
      },
      displayId: function() { return this.ideaId || ''; }
    },
    methods: {
      fmtDate: fmtDate
    },
    template: '\
      <div class="card-clip card-cut-br card-cut-cyan" :data-filename="filename" draggable="true" @click="$emit(\'click\')" @dragstart="$emit(\'dragstart\', $event)">\
        <div class="card-accent card-accent-cyan"></div>\
        <svg class="card-corner-svg card-corner-cyan" viewBox="0 0 16 16">\
          <polyline points="14,2 2,2 2,14" fill="none" stroke="currentColor" stroke-width="1.5"/>\
        </svg>\
        <div style="position:relative;z-index:1">\
          <div class="card-header">\
            <span class="card-stage text-cyan">{{ displayId }}</span>\
            <span class="card-date">{{ fmtDate(date) }}</span>\
          </div>\
          <div class="card-title">{{ title }}</div>\
          <div class="progress-wrap">\
            <div class="progress-label">\
              <span>readiness</span>\
              <span>{{ readiness }}%</span>\
            </div>\
            <div class="progress-bar">\
              <div class="progress-fill" :class="fillColor" :style="{ width: readiness + \'%\' }"></div>\
            </div>\
          </div>\
        </div>\
        <button class="pin-btn" :class="{pinned: tier === \'core\'}" @click.stop="$emit(\'pin\')" :title="tier === \'core\' ? \'Открепить\' : \'Закрепить\'">📌</button>\
      </div>'
  });

  /* ========================================
     ProgressBar
     Props:
       value (number): 0-100
       color (string): low, mid, high
     ======================================== */
  app.component('progress-bar', {
    props: {
      value: { type: Number, default: 0 },
      color: { type: String, default: 'mid' }
    },
    computed: {
      fillClass: function() {
        return 'fill-' + this.color;
      },
      clampedValue: function() {
        return Math.max(0, Math.min(100, this.value));
      }
    },
    template: '\
      <div class="progress-wrap">\
        <div class="progress-label">\
          <span>progress</span>\
          <span>{{ clampedValue }}%</span>\
        </div>\
        <div class="progress-bar">\
          <div class="progress-fill"\
               :class="fillClass"\
               :style="{ width: clampedValue + \'%\' }"\
          ></div>\
        </div>\
      </div>'
  });

  /* ========================================
     MetricBox
     Props:
       label (string): metric label text
       value (string|number): metric value
       color (string): CSS variable name without -- prefix (cyan, green, etc.)
     ======================================== */
  app.component('metric-box', {
    props: {
      label: { type: String, default: '' },
      value: { type: [String, Number], default: '' },
      color: { type: String, default: 'cyan' }
    },
    template: '\
      <div class="metric">\
        <div class="metric-label">{{ label }}</div>\
        <div :class="\'metric-value metric-\' + color">{{ value }}</div>\
      </div>'
  });

  /* ========================================
     CmdButton
     Props:
       label (string): button text
       color (string): cyan, magenta, green
       loading (boolean): show loading state
     Emits: click
     ======================================== */
  app.component('cmd-button', {
    props: {
      label:   { type: String, default: '' },
      color:   { type: String, default: 'cyan' },
      loading: { type: Boolean, default: false }
    },
    emits: ['click'],
    computed: {
      btnClass: function() {
        return 'cmd-btn cmd-btn-' + this.color;
      },
      displayLabel: function() {
        if (this.loading) return '[ ... ]';
        return '[ ' + this.label + ' ]';
      }
    },
    template: '\
      <button :class="btnClass"\
              :disabled="loading"\
              @click="$emit(\'click\')"\
      >{{ displayLabel }}</button>'
  });

  /* ========================================
     editable-field -- inline click-to-edit for frontmatter fields
     Props:
       label    (string): field display label
       value    (string): current value
       options  (array|null): dropdown options; null = free text input
       filename (string): artifact filename (e.g. 'IDEA-123.md')
       fieldKey (string): frontmatter key (e.g. 'status', 'domain')
     Emits: updated(key, newValue, response)
     ======================================== */
  app.component('editable-field', {
    props: {
      label:    { type: String, default: '' },
      value:    { type: String, default: '' },
      options:  { type: Array, default: null },
      filename: { type: String, default: '' },
      fieldKey: { type: String, default: '' }
    },
    emits: ['updated'],
    data: function() {
      return {
        editing: false,
        editValue: '',
        saving: false,
        feedbackClass: '',
        errorMsg: ''
      };
    },
    methods: {
      startEdit: function() {
        this.editValue = this.value || '';
        this.editing = true;
        this.errorMsg = '';
        this.feedbackClass = '';
        var self = this;
        this.$nextTick(function() {
          var el = self.$refs.editInput || self.$refs.editSelect;
          if (el) el.focus();
        });
      },
      save: function() {
        if (this.editValue === this.value) {
          this.editing = false;
          return;
        }
        this.saving = true;
        this.feedbackClass = 'editable-saving';
        var self = this;
        api.updateField(this.filename, this.fieldKey, this.editValue)
          .then(function(resp) {
            self.saving = false;
            self.editing = false;
            self.feedbackClass = 'editable-success';
            self.$emit('updated', self.fieldKey, self.editValue, resp);
            setTimeout(function() { self.feedbackClass = ''; }, 1500);
          })
          .catch(function(err) {
            self.saving = false;
            self.feedbackClass = 'editable-error';
            self.errorMsg = (err && err.message) || 'Save failed';
            setTimeout(function() { self.feedbackClass = ''; self.errorMsg = ''; }, 3000);
          });
      },
      cancel: function() {
        this.editing = false;
        this.editValue = '';
        this.errorMsg = '';
        this.feedbackClass = '';
      },
      onKeydown: function(e) {
        if (e.key === 'Enter') this.save();
        if (e.key === 'Escape') this.cancel();
      }
    },
    watch: {
      value: function(newVal) {
        if (!this.editing) {
          this.editValue = newVal || '';
        }
      }
    },
    template: '\
      <span v-if="!editing" :class="[\'editable-value\', feedbackClass]" @click="startEdit" :title="\'Click to edit \' + label">\
        <slot>{{ value || \'—\' }}</slot>\
        <span class="edit-icon">✎</span>\
      </span>\
      <span v-else :class="feedbackClass" style="display:inline-flex;align-items:center;gap:4px;">\
        <select v-if="options" ref="editSelect" class="editable-select" v-model="editValue" @change="save" @keydown="onKeydown" :disabled="saving">\
          <option v-for="opt in options" :key="opt" :value="opt">{{ opt }}</option>\
        </select>\
        <input v-else ref="editInput" class="editable-input" v-model="editValue" @keydown="onKeydown" @blur="cancel" :disabled="saving" />\
        <span v-if="errorMsg" style="color:#e53935;font-size:11px;">{{ errorMsg }}</span>\
      </span>'
  });

  /* ========================================
     body-editor -- fullscreen popup with split Markdown editor
     Props:
       open     (boolean): whether editor is visible
       filename (string): artifact filename
       body     (string): current body Markdown
       title    (string): title for the editor header
     Emits: close, saved(newBody, response)
     ======================================== */
  app.component('body-editor', {
    props: {
      open:     { type: Boolean, default: false },
      filename: { type: String, default: '' },
      body:     { type: String, default: '' },
      title:    { type: String, default: '' }
    },
    emits: ['close', 'saved'],
    data: function() {
      return {
        editBody: '',
        saving: false,
        errorMsg: '',
        dirty: false
      };
    },
    computed: {
      preview: function() {
        if (typeof marked !== 'undefined' && marked.parse) {
          try {
            var renderer = new marked.Renderer();
            renderer.link = function(href, title, text) {
              if (typeof href === 'object') { text = href.text; title = href.title; href = href.href; }
              return '<a href="' + href + '" target="_blank" rel="noopener noreferrer"' + (title ? ' title="' + title + '"' : '') + '>' + (text || href) + '</a>';
            };
            return marked.parse(this.editBody, { renderer: renderer });
          } catch(e) { return this.editBody; }
        }
        return this.editBody.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
      }
    },
    methods: {
      save: function() {
        if (this.saving) return;
        this.saving = true;
        this.errorMsg = '';
        var self = this;
        api.updateBody(this.filename, this.editBody)
          .then(function(resp) {
            self.saving = false;
            self.dirty = false;
            self.$emit('saved', self.editBody, resp);
            self.$emit('close');
          })
          .catch(function(err) {
            self.saving = false;
            self.errorMsg = (err && err.message) || 'Save failed';
          });
      },
      tryClose: function() {
        if (this.dirty) {
          if (!confirm('Отменить изменения?')) return;
        }
        this.$emit('close');
      },
      onKeydown: function(e) {
        if (e.ctrlKey && e.key === 's') {
          e.preventDefault();
          this.save();
        }
        if (e.key === 'Escape') {
          this.tryClose();
        }
      },
      onOverlayClick: function(e) {
        if (e.target === e.currentTarget) {
          this.tryClose();
        }
      }
    },
    watch: {
      open: function(val) {
        var self = this;
        if (val) {
          this.editBody = this.body || '';
          this.dirty = false;
          this.errorMsg = '';
          this.saving = false;
          this._keyHandler = function(e) { self.onKeydown(e); };
          document.addEventListener('keydown', this._keyHandler);
        } else {
          if (this._keyHandler) {
            document.removeEventListener('keydown', this._keyHandler);
            this._keyHandler = null;
          }
        }
      }
    },
    beforeUnmount: function() {
      if (this._keyHandler) {
        document.removeEventListener('keydown', this._keyHandler);
      }
    },
    template: '\
      <div v-if="open" class="body-editor-overlay" @click="onOverlayClick">\
        <div class="body-editor-panel">\
          <div class="body-editor-header">\
            <span class="body-editor-title">EDIT: {{ title || filename }}</span>\
            <div class="body-editor-actions">\
              <button class="body-editor-btn" @click="tryClose" :disabled="saving">CANCEL</button>\
              <button class="body-editor-btn body-editor-btn-save" @click="save" :disabled="saving">\
                {{ saving ? \'SAVING...\' : \'SAVE\' }}\
              </button>\
            </div>\
          </div>\
          <div v-if="saving" class="body-editor-saving-bar"></div>\
          <div v-if="errorMsg" class="body-editor-error">{{ errorMsg }}</div>\
          <div class="body-editor-split">\
            <textarea class="body-editor-textarea" v-model="editBody" @input="dirty = true" placeholder="Markdown body..."></textarea>\
            <div class="body-editor-preview" v-html="preview"></div>\
          </div>\
        </div>\
      </div>'
  });

  /* ========================================
     TaskDrawer -- slide-in panel for task/idea details
     Props:
       open (boolean): whether drawer is visible
       item (object): the item to display (must have title, date, status; may have body, tags, type, domain, priority, jira_key, story_points)
     Emits: close
     ======================================== */
  app.component('task-drawer', {
    props: {
      open: { type: Boolean, default: false },
      item: { type: Object, default: null }
    },
    emits: ['close', 'jira-created', 'field-updated'],
    data: function() {
      return {
        domains: [],
        bodyEditorOpen: false
      };
    },
    computed: {
      drawerClass: function() {
        return this.open ? 'task-drawer open' : 'task-drawer';
      },
      itemTags: function() {
        if (!this.item || !this.item.tags) return [];
        var tags = this.item.tags;
        if (typeof tags === 'string') {
          var cleaned = tags.replace(/^\[/, '').replace(/\]$/, '');
          if (!cleaned.trim()) return [];
          return cleaned.split(',').map(function(t) { return t.trim(); }).filter(function(t) { return t.length > 0; });
        }
        return Array.isArray(tags) ? tags : [];
      },
      statusClass: function() {
        if (!this.item) return 'tag tag-muted';
        var s = (this.item.status || '').toLowerCase();
        if (s === 'done') return 'tag tag-done';
        if (s === 'in-progress') return 'tag tag-jira';
        if (s === 'in-review' || s === 'in-testing') return 'tag tag-prd';
        if (s === 'todo') return 'tag tag-muted';
        if (s === 'cancelled') return 'tag tag-blocked';
        return 'tag tag-muted';
      }
    },
    methods: {
      fmtDate: fmtDate,
      renderMdSafe: function(text) {
        if (!text) return '';
        if (typeof marked !== 'undefined' && marked.parse) {
          return marked.parse(text);
        }
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
      },
      onJiraCreated: function(event) {
        console.log('[task-drawer] jira created:', event);
        if (this.item) {
          this.item.jira_key = event.jira_key;
          this.item.jira_url = event.jira_url;
        }
        this.$emit('jira-created', event);
      },
      onFieldUpdated: function(key, val, resp) {
        console.log('[task-drawer] field updated:', key, '=', val);
        if (this.item) { this.item[key] = val; }
        this.$emit('field-updated', key, val, resp);
      },
      onBodySaved: function(newBody, resp) {
        console.log('[task-drawer] body saved, length:', newBody.length);
        if (this.item) { this.item.body = newBody; }
        this.bodyEditorOpen = false;
        this.$emit('field-updated', 'body', newBody, resp);
      }
    },
    watch: {
      open: function(val) {
        if (val && this.domains.length === 0) {
          var self = this;
          api.domains().then(function(list) {
            self.domains = list.map(function(d) { return d.slug; });
          }).catch(function() {});
        }
      }
    },
    template: '\
      <div :class="drawerClass">\
        <div class="task-drawer-header">\
          <span class="task-drawer-title">{{ item ? (item.jira_key || item.filename || "DETAIL") : "DETAIL" }}</span>\
          <button class="task-drawer-close" @click="$emit(\'close\')">[×]</button>\
        </div>\
        <div class="task-drawer-body" v-if="item">\
          <div class="task-drawer-section">\
            <div class="task-drawer-section-title">INFO</div>\
            <div class="task-drawer-meta">\
              <span class="task-drawer-meta-label">title:</span>\
              <span class="task-drawer-meta-value">{{ item.title || "—" }}</span>\
              <span class="task-drawer-meta-label">date:</span>\
              <span class="task-drawer-meta-value">{{ fmtDate(item.date) || "—" }}</span>\
              <span class="task-drawer-meta-label">status:</span>\
              <span class="task-drawer-meta-value">\
                <editable-field label="status" :value="item.status || \'\'" field-key="status" :options="[\'todo\',\'in-progress\',\'in-review\',\'in-testing\',\'done\',\'cancelled\']" :filename="item.filename || \'\'" @updated="onFieldUpdated">\
                  <span :class="statusClass">{{ (item.status || \'—\').toUpperCase() }}</span>\
                </editable-field>\
              </span>\
              <span class="task-drawer-meta-label" v-if="item.type">type:</span>\
              <span class="task-drawer-meta-value" v-if="item.type">{{ item.type.toUpperCase() }}</span>\
              <span class="task-drawer-meta-label">domain:</span>\
              <span class="task-drawer-meta-value">\
                <editable-field label="domain" :value="item.domain || \'\'" field-key="domain" :options="domains" :filename="item.filename || \'\'" @updated="onFieldUpdated">\
                  <span class="text-cyan">{{ (item.domain || \'—\').toUpperCase() }}</span>\
                </editable-field>\
              </span>\
              <span class="task-drawer-meta-label">priority:</span>\
              <span class="task-drawer-meta-value">\
                <editable-field label="priority" :value="item.priority || \'\'" field-key="priority" :options="[\'critical\',\'high\',\'medium\',\'low\']" :filename="item.filename || \'\'" @updated="onFieldUpdated">\
                  {{ (item.priority || \'—\').toUpperCase() }}\
                </editable-field>\
              </span>\
              <span class="task-drawer-meta-label" v-if="item.story_points">story_points:</span>\
              <span class="task-drawer-meta-value" v-if="item.story_points">{{ item.story_points }}</span>\
              <span class="task-drawer-meta-label" v-if="item.jira_key">jira_key:</span>\
              <span class="task-drawer-meta-value" v-if="item.jira_key">{{ item.jira_key }}</span>\
            </div>\
          </div>\
          <div class="task-drawer-section" v-if="itemTags.length">\
            <div class="task-drawer-section-title">TAGS</div>\
            <div>\
              <span v-for="tag in itemTags" :key="tag" :class="\'tag tag-\' + tag.toLowerCase() + \' mr-xs\'">{{ tag.toUpperCase() }}</span>\
            </div>\
          </div>\
          <div class="task-drawer-section">\
            <div class="task-drawer-section-title">BODY <button class="cmd-btn cmd-btn-sm" style="margin-left:8px;font-size:11px;" @click="bodyEditorOpen = true">EDIT BODY</button></div>\
            <div class="task-drawer-content" v-if="item.body" v-html="renderMdSafe(item.body)"></div>\
            <div v-else style="color:var(--text-muted,#888);font-size:12px;">No body content</div>\
          </div>\
          <body-editor :open="bodyEditorOpen" :filename="item.filename || \'\'" :body="item.body || \'\'" :title="item.jira_key || item.filename || \'\'" @close="bodyEditorOpen = false" @saved="onBodySaved"></body-editor>\
          <jira-create-section\
            :filename="item.filename || \'\'"\
            :current-type="item.type || \'Task\'"\
            :title="item.title || \'\'"\
            :has-jira-key="!!(item.jira_key)"\
            :jira-key="item.jira_key || \'\'"\
            :jira-url="item.jira_url || \'\'"\
            :epic-ref="item.epic_key || \'\'"\
            @created="onJiraCreated"\
          ></jira-create-section>\
        </div>\
      </div>'
  });

  /* ========================================
     IdeaDrawer -- slide-in panel for idea details
     Props:
       open (boolean): whether drawer is visible
       item (object): the idea item to display
     Emits: close
     ======================================== */
  app.component('idea-drawer', {
    props: {
      open: { type: Boolean, default: false },
      item: { type: Object, default: null }
    },
    emits: ['close', 'field-updated'],
    data: function() {
      return {
        domains: [],
        bodyEditorOpen: false
      };
    },
    computed: {
      drawerClass: function() {
        return this.open ? 'task-drawer open' : 'task-drawer';
      },
      itemTags: function() {
        if (!this.item || !this.item.tags) return [];
        var tags = this.item.tags;
        if (typeof tags === 'string') {
          var cleaned = tags.replace(/^\[/, '').replace(/\]$/, '');
          if (!cleaned.trim()) return [];
          return cleaned.split(',').map(function(t) { return t.trim(); }).filter(function(t) { return t.length > 0; });
        }
        return Array.isArray(tags) ? tags : [];
      },
      statusClass: function() {
        if (!this.item) return 'tag tag-muted';
        var s = (this.item.status || '').toLowerCase();
        if (s === 'done') return 'tag tag-done';
        if (s === 'in-progress') return 'tag tag-jira';
        if (s === 'in-review' || s === 'in-testing') return 'tag tag-prd';
        if (s === 'todo') return 'tag tag-muted';
        if (s === 'cancelled') return 'tag tag-blocked';
        return 'tag tag-muted';
      }
    },
    methods: {
      fmtDate: fmtDate,
      renderMdSafe: function(text) {
        if (!text) return '';
        if (typeof marked !== 'undefined' && marked.parse) {
          return marked.parse(text);
        }
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
      },
      onFieldUpdated: function(key, val, resp) {
        console.log('[idea-drawer] field updated:', key, '=', val);
        if (this.item) {
          this.item[key] = val;
          if (resp && resp.readiness != null) this.item.readiness = resp.readiness;
        }
        this.$emit('field-updated', key, val, resp);
      },
      onBodySaved: function(newBody, resp) {
        console.log('[idea-drawer] body saved, length:', newBody.length);
        if (this.item) {
          this.item.body = newBody;
          if (resp && resp.readiness != null) this.item.readiness = resp.readiness;
        }
        this.bodyEditorOpen = false;
        this.$emit('field-updated', 'body', newBody, resp);
      }
    },
    watch: {
      open: function(val) {
        if (val && this.domains.length === 0) {
          var self = this;
          api.domains().then(function(list) {
            self.domains = list.map(function(d) { return d.slug; });
          }).catch(function() {});
        }
      }
    },
    template: '\
      <div :class="drawerClass">\
        <div class="task-drawer-header">\
          <span class="task-drawer-title">{{ item ? (item.id || item.filename || \'DETAIL\') : \'DETAIL\' }}</span>\
          <button class="task-drawer-close" @click="$emit(\'close\')">[×]</button>\
        </div>\
        <div class="task-drawer-body" v-if="item">\
          <div class="task-drawer-section">\
            <div class="task-drawer-section-title">INFO</div>\
            <div class="task-drawer-meta">\
              <span class="task-drawer-meta-label">id:</span>\
              <span class="task-drawer-meta-value text-cyan">{{ item.id || \'—\' }}</span>\
              <span class="task-drawer-meta-label">title:</span>\
              <span class="task-drawer-meta-value">{{ item.title || \'—\' }}</span>\
              <span class="task-drawer-meta-label">date:</span>\
              <span class="task-drawer-meta-value">{{ fmtDate(item.date) || \'—\' }}</span>\
              <span class="task-drawer-meta-label">status:</span>\
              <span class="task-drawer-meta-value">\
                <editable-field label="status" :value="item.status || \'\'" field-key="status" :options="[\'Новая\',\'Проверка гипотезы\',\'Готова к производству\',\'Отсев\']" :filename="item.filename || \'\'" @updated="onFieldUpdated">\
                  <span :class="statusClass">{{ (item.status || \'—\').toUpperCase() }}</span>\
                </editable-field>\
              </span>\
              <span class="task-drawer-meta-label">domain:</span>\
              <span class="task-drawer-meta-value">\
                <editable-field label="domain" :value="item.domain || \'\'" field-key="domain" :options="domains" :filename="item.filename || \'\'" @updated="onFieldUpdated">\
                  <span class="text-cyan">{{ (item.domain || \'—\').toUpperCase() }}</span>\
                </editable-field>\
              </span>\
              <span class="task-drawer-meta-label">readiness:</span>\
              <span class="task-drawer-meta-value">{{ (item.readiness != null ? item.readiness : 0) }}%</span>\
            </div>\
          </div>\
          <div class="task-drawer-section" v-if="itemTags.length">\
            <div class="task-drawer-section-title">TAGS</div>\
            <div>\
              <span v-for="tag in itemTags" :key="tag" :class="\'tag tag-\' + tag.toLowerCase() + \' mr-xs\'">{{ tag.toUpperCase() }}</span>\
            </div>\
          </div>\
          <div class="task-drawer-section">\
            <div class="task-drawer-section-title">BODY <button class="cmd-btn cmd-btn-sm" style="margin-left:8px;font-size:11px;" @click="bodyEditorOpen = true">EDIT BODY</button></div>\
            <div class="task-drawer-content" v-if="item.body" v-html="renderMdSafe(item.body)"></div>\
            <div v-else style="color:var(--text-muted,#888);font-size:12px;">No body content</div>\
          </div>\
          <body-editor :open="bodyEditorOpen" :filename="item.filename || \'\'" :body="item.body || \'\'" :title="item.id || item.filename || \'\'" @close="bodyEditorOpen = false" @saved="onBodySaved"></body-editor>\
        </div>\
      </div>'
  });

  /* ========================================
     domain-config-drawer -- slide-in panel for creating/editing domain config
     Props:
       open    (boolean): controls drawer visibility
       domain  (object|null): {slug, display_name, description, color, jira_labels}
                              for editing; null for new domain
       isNew   (boolean): when true the slug field is editable
     Emits: close, saved
     ======================================== */
  app.component('domain-config-drawer', {
    props: {
      open:   { type: Boolean, default: false },
      domain: { type: Object, default: null },
      isNew:  { type: Boolean, default: false }
    },
    emits: ['close', 'saved'],
    data: function() {
      return {
        form: { slug: '', display_name: '', description: '', color: '#607D8B', jira_labels: [] },
        newLabel: '',
        errorMsg: '',
        saving: false
      };
    },
    watch: {
      domain: {
        immediate: true,
        handler: function(val) {
          if (val) {
            this.form = {
              slug:         val.slug || val.name || '',
              display_name: val.display_name || '',
              description:  val.description || '',
              color:        val.color || '#607D8B',
              jira_labels:  Array.isArray(val.jira_labels) ? val.jira_labels.slice() : []
            };
          } else {
            this.form = { slug: '', display_name: '', description: '', color: '#607D8B', jira_labels: [] };
          }
          this.errorMsg = '';
          this.newLabel = '';
          console.log('[domain-config-drawer] domain watcher fired, isNew:', this.isNew, 'slug:', this.form.slug);
        }
      }
    },
    methods: {
      addLabel: function() {
        var lbl = this.newLabel.trim();
        if (lbl && this.form.jira_labels.indexOf(lbl) === -1) {
          this.form.jira_labels.push(lbl);
          console.log('[domain-config-drawer] addLabel:', lbl);
        }
        this.newLabel = '';
      },
      removeLabel: function(index) {
        var removed = this.form.jira_labels[index];
        this.form.jira_labels.splice(index, 1);
        console.log('[domain-config-drawer] removeLabel index:', index, 'value:', removed);
      },
      handleSave: async function() {
        this.errorMsg = '';
        // Local validation
        if (!this.form.slug || !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(this.form.slug)) {
          this.errorMsg = 'Slug must be lowercase alphanumeric with hyphens';
          console.log('[domain-config-drawer] handleSave validation failed: invalid slug:', this.form.slug);
          return;
        }
        if (!this.form.display_name.trim()) {
          this.errorMsg = 'Display name is required';
          console.log('[domain-config-drawer] handleSave validation failed: empty display_name');
          return;
        }
        if (this.form.color && !/^#[0-9A-Fa-f]{6}$/.test(this.form.color)) {
          this.errorMsg = 'Color must be valid hex format (#RRGGBB)';
          console.log('[domain-config-drawer] handleSave validation failed: invalid color:', this.form.color);
          return;
        }

        this.saving = true;
        console.log('[domain-config-drawer] handleSave start, slug:', this.form.slug);
        try {
          var entry = {
            display_name: this.form.display_name.trim(),
            description:  this.form.description.trim(),
            color:        this.form.color || '#607D8B',
            jira_labels:  this.form.jira_labels
          };
          var resp = await api.saveDomainConfig(this.form.slug, entry);
          console.log('[domain-config-drawer] handleSave success:', resp);
          if (resp && resp.status === 'error') {
            this.errorMsg = resp.message || 'Save failed';
            console.log('[domain-config-drawer] handleSave API returned error status:', this.errorMsg);
          } else {
            this.$emit('saved');
            this.$emit('close');
          }
        } catch (err) {
          // apiFetch throws Error with message "API error: <status> <body>"
          // Extract a human-readable message from the error
          var msg = err.message || 'Save failed';
          // Try to extract JSON detail from the error message body portion
          var bodyStart = msg.indexOf('{');
          if (bodyStart !== -1) {
            try {
              var parsed = JSON.parse(msg.slice(bodyStart));
              msg = parsed.detail || parsed.message || msg;
            } catch (parseErr) {
              // keep original msg
            }
          }
          this.errorMsg = msg;
          console.log('[domain-config-drawer] handleSave error:', err.message);
        } finally {
          this.saving = false;
        }
      }
    },
    template: `
      <div class="drawer-overlay" v-if="open" @click.self="$emit('close')">
        <div class="drawer-panel domain-config-drawer">
          <div class="drawer-header">
            <h3>{{ isNew ? 'Add Domain' : 'Edit Domain' }}</h3>
            <button class="drawer-close" @click="$emit('close')">&times;</button>
          </div>

          <div class="drawer-body">
            <!-- Slug -->
            <div class="form-group">
              <label>Slug (ID)</label>
              <input type="text" v-model="form.slug" :readonly="!isNew"
                     :class="{'input-readonly': !isNew}"
                     placeholder="my-domain" pattern="[a-z0-9]+(-[a-z0-9]+)*">
              <small v-if="isNew">lowercase letters, numbers, hyphens only</small>
            </div>

            <!-- Display Name -->
            <div class="form-group">
              <label>Display Name *</label>
              <input type="text" v-model="form.display_name" maxlength="100"
                     placeholder="My Domain" required>
            </div>

            <!-- Description -->
            <div class="form-group">
              <label>Description</label>
              <textarea v-model="form.description" maxlength="500" rows="3"
                        placeholder="What this domain covers..."></textarea>
            </div>

            <!-- Color -->
            <div class="form-group">
              <label>Color</label>
              <div style="display:flex;align-items:center;gap:8px">
                <input type="text" v-model="form.color" placeholder="#607D8B"
                       pattern="#[0-9A-Fa-f]{6}" style="width:120px">
                <div class="color-swatch" :style="{background: form.color || '#607D8B'}"></div>
              </div>
            </div>

            <!-- Jira Labels -->
            <div class="form-group">
              <label>Jira Labels</label>
              <div class="label-tags">
                <span class="label-tag" v-for="(lbl, i) in form.jira_labels" :key="i">
                  {{ lbl }}
                  <button class="label-tag-remove" @click="removeLabel(i)">&times;</button>
                </span>
              </div>
              <div style="display:flex;gap:8px;margin-top:4px">
                <input type="text" v-model="newLabel" placeholder="label_name"
                       @keyup.enter="addLabel" style="flex:1">
                <button class="btn btn-sm" @click="addLabel">+ Add</button>
              </div>
            </div>

            <!-- Error message -->
            <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>
          </div>

          <div class="drawer-footer">
            <button class="btn" @click="$emit('close')">Cancel</button>
            <button class="btn btn-primary" @click="handleSave" :disabled="saving">
              {{ saving ? 'Saving...' : (isNew ? 'Create' : 'Save') }}
            </button>
          </div>
        </div>
      </div>`
  });

  /* ========================================
     JiraCreateSection -- push task/epic to Jira or show existing link
     Props:
       filename    (string, required): source file name
       currentType (string): Task | Bug | Story — pre-selected issue type
       title       (string): pre-filled issue title
       hasJiraKey  (boolean): whether item already has a Jira ticket
       jiraKey     (string): existing Jira key (e.g. PM-42)
       jiraUrl     (string): URL to existing Jira ticket
       isEpic      (boolean): if true, creates an Epic and hides type/epic selectors
     Emits: created({ jira_key, jira_url })
     ======================================== */
  app.component('jira-create-section', {
    props: {
      filename:    { type: String, required: true },
      currentType: { type: String, default: 'Task' },
      title:       { type: String, default: '' },
      hasJiraKey:  { type: Boolean, default: false },
      jiraKey:     { type: String, default: '' },
      jiraUrl:     { type: String, default: '' },
      isEpic:      { type: Boolean, default: false },
      epicRef:     { type: String, default: '' }
    },
    emits: ['created'],
    data: function() {
      return {
        expanded:       false,
        projects:       [],
        epics:          [],
        selectedProject: '',
        selectedEpic:   '',
        editedTitle:    this.title,
        selectedType:   this.currentType || 'Task',
        creating:       false,
        error:          '',
        loadingProjects: false,
        loadingEpics:   false,
        issueTypes:     [],
        loadingTypes:   false
      };
    },
    watch: {
      title: function(val) { this.editedTitle = val; },
      currentType: function(val) { this.selectedType = val || 'Task'; }
    },
    methods: {
      toggle: function() {
        this.expanded = !this.expanded;
        console.log('[jira-create] toggle expanded:', this.expanded);
        if (this.expanded) {
          this.editedTitle = this.title;
          if (this.projects.length === 0) {
            this.loadProjects();
          }
        }
      },
      loadProjects: function() {
        var self = this;
        self.loadingProjects = true;
        console.log('[jira-create] loadProjects start');
        api.jiraProjects().then(function(data) {
          console.log('[jira-create] loadProjects success, count:', data.length);
          self.projects = data;
          self.loadingProjects = false;
        }).catch(function(err) {
          console.log('[jira-create] loadProjects error:', err.message);
          self.error = 'Failed to load projects: ' + err.message;
          self.loadingProjects = false;
        });
      },
      loadEpics: function() {
        var self = this;
        if (!self.selectedProject) {
          self.epics = [];
          console.log('[jira-create] loadEpics skipped: no project selected');
          return;
        }
        self.loadingEpics = true;
        console.log('[jira-create] loadEpics start for project:', self.selectedProject);
        api.jiraProjectEpics(self.selectedProject).then(function(data) {
          console.log('[jira-create] loadEpics success, count:', data.length);
          self.epics = data;
          self.loadingEpics = false;
          // Pre-select epic if epicRef matches
          if (self.epicRef) {
            var match = data.find(function(e) { return e.key === self.epicRef; });
            if (match) {
              self.selectedEpic = match.key;
              console.log('[jira-create] pre-selected epic:', self.epicRef);
            }
          }
        }).catch(function(err) {
          console.log('[jira-create] loadEpics error:', err.message);
          self.error = 'Failed to load epics: ' + err.message;
          self.loadingEpics = false;
        });
      },
      loadIssueTypes: function() {
        var self = this;
        if (!self.selectedProject) {
            self.issueTypes = [];
            console.log('[jira-create] loadIssueTypes skipped: no project selected');
            return;
        }
        self.loadingTypes = true;
        console.log('[jira-create] loadIssueTypes start for project:', self.selectedProject);
        api.jiraIssueTypes(self.selectedProject).then(function(data) {
            console.log('[jira-create] loadIssueTypes success, count:', data.length);
            self.issueTypes = data;
            self.loadingTypes = false;
            // Auto-select if currentType matches one of the loaded types
            if (self.currentType) {
                var match = data.find(function(t) { return t.name.toLowerCase() === self.currentType.toLowerCase(); });
                if (match) {
                    self.selectedType = match.name;
                } else if (data.length > 0) {
                    self.selectedType = data[0].name;
                }
            } else if (data.length > 0) {
                self.selectedType = data[0].name;
            }
        }).catch(function(err) {
            console.log('[jira-create] loadIssueTypes error:', err.message);
            self.error = 'Failed to load issue types: ' + err.message;
            self.loadingTypes = false;
        });
      },
      onProjectChange: function() {
        this.selectedEpic = '';
        this.selectedType = '';
        this.issueTypes = [];
        console.log('[jira-create] onProjectChange:', this.selectedProject);
        this.loadEpics();
        this.loadIssueTypes();
      },
      create: function() {
        var self = this;
        if (!self.selectedProject) {
          self.error = 'Select a project first';
          console.log('[jira-create] create validation failed: no project');
          return;
        }
        if (!self.editedTitle || !self.editedTitle.trim()) {
          self.error = 'Issue title cannot be empty';
          console.log('[jira-create] create validation failed: empty title');
          return;
        }
        self.creating = true;
        self.error = '';
        var data = {
          filename:    self.filename,
          project_key: self.selectedProject,
          issue_type:  self.isEpic ? 'Epic' : self.selectedType,
          summary:     self.editedTitle,
          epic_key:    self.selectedEpic || ''
        };
        console.log('[jira-create] create request:', data);
        api.jiraCreate(data).then(function(result) {
          console.log('[jira-create] create success:', result);
          self.$emit('created', { jira_key: result.jira_key, jira_url: result.jira_url });
          self.creating = false;
          self.expanded = false;
        }).catch(function(err) {
          console.log('[jira-create] create error:', err.message);
          self.error = (err.result && err.result.message) || err.message || 'Unknown error';
          self.creating = false;
        });
      }
    },
    template: `
      <div class="jira-create-section">
        <div v-if="hasJiraKey" class="task-drawer-section">
          <a :href="jiraUrl" target="_blank" rel="noopener" class="jira-create-link">
            [JIRA] {{ jiraKey }}
          </a>
        </div>
        <div v-else class="task-drawer-section">
          <div class="task-drawer-section-title">JIRA</div>
          <cmd-button v-if="!expanded"
            :label="isEpic ? 'PUSH_EPIC_TO_JIRA' : 'PUSH_TO_JIRA'"
            color="cyan" @click="toggle">
          </cmd-button>
          <div v-if="expanded" class="jira-create-form">
            <select v-model="selectedProject" @change="onProjectChange"
                    :disabled="creating">
              <option value="" disabled>
                {{ loadingProjects ? '// loading projects...' : '// select project' }}
              </option>
              <option v-for="p in projects" :key="p.key" :value="p.key">
                {{ p.key }} — {{ p.name }}
              </option>
            </select>
            <select v-if="!isEpic" v-model="selectedType" :disabled="creating || loadingTypes">
              <option value="" disabled>
                {{ loadingTypes ? '// loading types...' : '// select type' }}
              </option>
              <option v-for="t in issueTypes" :key="t.name" :value="t.name">
                {{ t.name }}
              </option>
            </select>
            <input class="cp-input" v-model="editedTitle" placeholder="// issue title"
                   :disabled="creating">
            <select v-if="!isEpic && selectedProject" v-model="selectedEpic"
                    :disabled="creating">
              <option value="">// no epic (none)</option>
              <option v-if="loadingEpics" value="" disabled>// loading epics...</option>
              <option v-for="e in epics" :key="e.key" :value="e.key">
                {{ e.key }} — {{ e.summary }}
              </option>
            </select>
            <div v-if="error" class="jira-create-error">{{ error }}</div>
            <div class="jira-create-actions">
              <cmd-button label="CREATE" color="cyan" :loading="creating" @click="create">
              </cmd-button>
              <span class="jira-create-cancel" @click="toggle">[CANCEL]</span>
            </div>
          </div>
        </div>
      </div>`
  });

  /* ========================================
     SearchOverlay -- fullscreen search modal (Ctrl+K)
     Props:
       open (boolean): whether overlay is visible
     Emits: close
     ======================================== */
  app.component('search-overlay', {
    props: { open: { type: Boolean, default: false } },
    emits: ['close'],
    data: function() {
      return {
        query: '',
        results: [],
        loading: false,
        error: '',
        activeFilter: 'all',
        debounceTimer: null
      };
    },
    computed: {
      filteredResults: function() {
        if (this.activeFilter === 'all') return this.results;
        return this.results.filter(r => r.category === this.activeFilter);
      },
      filterCounts: function() {
        var counts = { all: this.results.length, idea: 0, task: 0, epic: 0, meeting: 0 };
        this.results.forEach(function(r) {
          if (counts[r.category] !== undefined) counts[r.category]++;
        });
        return counts;
      },
      showHint: function() {
        return this.query.length > 0 && this.query.length < 2;
      },
      showEmpty: function() {
        return this.query.length >= 2 && !this.loading && this.results.length === 0 && !this.error;
      }
    },
    watch: {
      open: function(val) {
        if (val) {
          this.query = '';
          this.results = [];
          this.error = '';
          this.activeFilter = 'all';
          this.$nextTick(() => {
            if (this.$refs.searchInput) this.$refs.searchInput.focus();
          });
        }
      }
    },
    methods: {
      fmtDate: fmtDate,
      onInput: function() {
        clearTimeout(this.debounceTimer);
        if (this.query.length < 2) {
          this.results = [];
          this.error = '';
          return;
        }
        this.debounceTimer = setTimeout(() => this.doSearch(), 300);
      },
      doSearch: async function() {
        this.loading = true;
        this.error = '';
        try {
          var data = await api.search(this.query);
          this.results = data.results;
        } catch (err) {
          if (err.name !== 'AbortError') {
            this.error = 'Ошибка поиска, попробуйте позже';
            console.error('[search-overlay] search failed:', err);
          }
        } finally {
          this.loading = false;
        }
      },
      navigate: function(result) {
        var filename = result.path.split('/').pop();
        console.log('[search] navigate to', result.url, 'highlight:', filename);
        var sep = result.url.indexOf('?') === -1 ? '?' : '&';
        window.location.href = result.url + sep + 'highlight=' + encodeURIComponent(filename);
        this.$emit('close');
      },
      setFilter: function(filter) {
        this.activeFilter = filter;
      },
      onOverlayKeydown: function(e) {
        if (e.key === 'Escape') this.$emit('close');
      },
      categoryIcon: function(category) {
        var icons = {
          idea: 'lightbulb',
          task: 'task_alt',
          epic: 'rocket_launch',
          meeting: 'groups',
          prd: 'description',
          bug: 'bug_report',
          report: 'summarize'
        };
        return icons[category] || 'article';
      },
      filterLabel: function(f) {
        var labels = { all: 'ВСЕ', idea: 'ИДЕИ', task: 'ЗАДАЧИ', epic: 'ЭПИКИ', meeting: 'ВСТРЕЧИ' };
        return labels[f] || f.toUpperCase();
      }
    },
    template: `
      <div class="search-overlay" v-if="open" @click.self="$emit('close')" @keydown="onOverlayKeydown">
        <div class="search-panel">
          <div class="search-header">
            <span class="material-symbols-outlined search-icon">search</span>
            <input
              ref="searchInput"
              class="search-input"
              v-model="query"
              @input="onInput"
              placeholder="Поиск по vault..."
            >
            <kbd class="search-kbd">ESC</kbd>
          </div>
          <div class="search-filters" v-if="results.length">
            <button
              v-for="f in ['all','idea','task','epic','meeting']"
              :key="f"
              class="search-filter-btn"
              :class="{ active: activeFilter === f }"
              @click="setFilter(f)"
            >{{ filterLabel(f) }} ({{ filterCounts[f] || 0 }})</button>
          </div>
          <div class="search-hint" v-if="showHint">Введите минимум 2 символа</div>
          <div class="search-loading" v-if="loading">Поиск...</div>
          <div class="search-error" v-if="error">{{ error }}</div>
          <div class="search-empty" v-if="showEmpty">Ничего не найдено по запросу «{{ query }}»</div>
          <div class="search-results" v-if="filteredResults.length">
            <div
              class="search-result"
              v-for="(r, i) in filteredResults"
              :key="r.path"
              @click="navigate(r)"
            >
              <span class="material-symbols-outlined search-result-icon">{{ categoryIcon(r.category) }}</span>
              <div class="search-result-body">
                <div class="search-result-title"><span class="search-result-id" v-if="r.artifact_id">{{ r.artifact_id }}:</span> {{ r.title }}</div>
                <div class="search-result-meta">
                  <span class="search-result-category">{{ r.category.toUpperCase() }}</span>
                  <span class="search-result-domain" v-if="r.domain !== 'cross-domain'">{{ r.domain }}</span>
                  <span class="search-result-date">{{ fmtDate(r.date) }}</span>
                </div>
                <div class="search-result-tags" v-if="r.tags && r.tags.length">
                  <span class="tag tag-sm" v-for="tag in r.tags.slice(0, 5)" :key="tag">{{ tag }}</span>
                </div>
              </div>
              <span class="search-result-score">{{ r.score }}</span>
            </div>
          </div>
        </div>
      </div>`
  });
}
