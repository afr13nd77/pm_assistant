/* decay.js -- Decay State Dashboard logic */

// ================================================================
// Constants
// ================================================================
var TIER_COLORS = {
  core:    '#378ADD',
  active:  '#1D9E75',
  warm:    '#EF9F27',
  cold:    '#D85A30',
  archive: '#888780'
};
var TIERS = ['core', 'active', 'warm', 'cold', 'archive'];

// Module state
var _snapshotData = null;
var _items = [];
var _thresholds = {};
var _total = 0;
var _tierCounts = {};

// ================================================================
// Theme detection
// ================================================================
function isLightTheme() {
  return document.documentElement.classList.contains('theme-light');
}

function getAxisColor() {
  return isLightTheme() ? '#555' : '#b0b0b0';
}

function getGridColor() {
  return isLightTheme() ? 'rgba(0,0,0,0.07)' : 'rgba(255,255,255,0.07)';
}

function getCenterTextColor() {
  return isLightTheme() ? '#1a1a1a' : '#e8e8e8';
}

// ================================================================
// Data loading
// ================================================================
async function loadSnapshot() {
  console.log('[decay] loading snapshot...');
  try {
    _snapshotData = await api.decaySnapshot();
    _items = _snapshotData.items || [];
    _thresholds = _snapshotData.tier_thresholds || { active: 7, warm: 21, cold: 60 };
    _total = _snapshotData.total || 0;

    // Count tiers
    _tierCounts = { core: 0, active: 0, warm: 0, cold: 0, archive: 0 };
    _items.forEach(function(item) {
      if (_tierCounts[item.tier] !== undefined) {
        _tierCounts[item.tier]++;
      }
    });

    console.log('[decay] loaded:', _total, 'items');
    return true;
  } catch (err) {
    console.error('[decay] failed to load snapshot:', err.message);
    return false;
  }
}

// ================================================================
// Metrics strip (AC-10)
// ================================================================
function renderMetrics() {
  document.getElementById('metric-total').textContent = _total;
  document.getElementById('metric-active').textContent =
    _tierCounts.active + _tierCounts.warm + _tierCounts.core;
  document.getElementById('metric-cold').textContent =
    _tierCounts.cold + _tierCounts.archive;

  var healthPct = _total > 0
    ? Math.round((_tierCounts.active + _tierCounts.warm * 0.6 + _tierCounts.core * 0.8) / _total * 100)
    : 0;
  document.getElementById('metric-health').textContent = healthPct + '%';

  // generated_at
  if (_snapshotData && _snapshotData.generated_at) {
    document.getElementById('generated-at').textContent =
      'Обновлено: ' + _snapshotData.generated_at.replace('T', ' ');
  }
}

// ================================================================
// Charts: Bubble Scatter (T-10), Tier Donut (T-10)
// Remaining stubs: Projection, DomainBars, ForgottenGems (T-11)
// ================================================================
function renderBubbleScatter() {
  var axisColor = getAxisColor();
  var gridColor = getGridColor();

  // Build HTML legend
  var legendEl = document.getElementById('scatter-legend');
  legendEl.innerHTML = TIERS.map(function(t) {
    return '<span class="decay-legend-item"><span class="decay-legend-dot" style="background:' + TIER_COLORS[t] + '"></span>' + t + '</span>';
  }).join('');

  // Prepare datasets per tier
  var datasets = TIERS.map(function(t) {
    var points = [];
    _items.forEach(function(item) {
      if (item.tier !== t) return;
      // Small jitter to avoid overlap
      var jx = (Math.random() - 0.5) * 1.5;
      var jy = (Math.random() - 0.5) * 0.6;
      points.push({
        x: item.days_since_access + jx,
        y: item.access_count + jy,
        r: Math.max(3, item.relevance * 9),
        _domain: item.domain,
        _type: item.type,
        _rel: item.relevance
      });
    });
    return {
      label: t,
      data: points,
      backgroundColor: TIER_COLORS[t] + '90',
      borderColor: TIER_COLORS[t] + 'bb',
      borderWidth: 0.5
    };
  });

  new Chart(document.getElementById('scatter-chart'), {
    type: 'bubble',
    data: { datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              var r = ctx.raw;
              return ctx.dataset.label + ' · ' + r._type + ' · ' + r._domain
                + ' · ' + Math.round(ctx.parsed.x) + 'д'
                + ' · ×' + Math.round(ctx.parsed.y)
                + ' · rel ' + r._rel.toFixed(2);
            }
          }
        }
      },
      scales: {
        x: {
          min: -3,
          title: { display: true, text: 'дней с последнего обращения', font: { size: 11 }, color: axisColor },
          ticks: { color: axisColor, font: { size: 10 } },
          grid: { color: gridColor }
        },
        y: {
          min: -1,
          title: { display: true, text: 'обращений', font: { size: 11 }, color: axisColor },
          ticks: { color: axisColor, font: { size: 10 } },
          grid: { color: gridColor }
        }
      }
    }
  });

  console.log('[decay] scatter rendered');
}

function renderTierDonut() {
  var centerColor = getCenterTextColor();
  var axisColor = getAxisColor();

  new Chart(document.getElementById('donut-chart'), {
    type: 'doughnut',
    plugins: [{
      id: 'centerText',
      beforeDraw: function(chart) {
        var ctx = chart.ctx;
        var w = chart.width;
        var h = chart.height;
        ctx.save();
        ctx.font = '500 20px sans-serif';
        ctx.fillStyle = centerColor;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(_total, w / 2, h / 2 - 9);
        ctx.font = '400 11px sans-serif';
        ctx.fillStyle = axisColor;
        ctx.fillText('артефактов', w / 2, h / 2 + 10);
        ctx.restore();
      }
    }],
    data: {
      labels: TIERS,
      datasets: [{
        data: TIERS.map(function(t) { return _tierCounts[t]; }),
        backgroundColor: TIERS.map(function(t) { return TIER_COLORS[t]; }),
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '65%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              var pct = _total > 0 ? Math.round(ctx.parsed / _total * 100) : 0;
              return ctx.label + ': ' + ctx.parsed + ' (' + pct + '%)';
            }
          }
        }
      }
    }
  });

  // HTML legend
  var legendEl = document.getElementById('donut-legend');
  legendEl.innerHTML = TIERS.map(function(t) {
    var pct = _total > 0 ? Math.round(_tierCounts[t] / _total * 100) : 0;
    return '<div class="decay-donut-legend-item">'
      + '<span class="decay-donut-legend-dot" style="background:' + TIER_COLORS[t] + '"></span>'
      + '<span style="color:var(--text-muted); flex:1;">' + t + '</span>'
      + '<span style="font-weight:500;">' + _tierCounts[t] + '</span>'
      + '<span style="color:var(--text-muted); font-size:12px; margin-left:4px;">' + pct + '%</span>'
      + '</div>';
  }).join('');

  console.log('[decay] donut rendered');
}

function renderProjection() {
  var slider = document.getElementById('projection-slider');
  var daysLabel = document.getElementById('projection-days');
  var barsContainer = document.getElementById('projection-bars');

  function calcTierClient(days) {
    if (days <= _thresholds.active) return 'active';
    if (days <= _thresholds.warm) return 'warm';
    if (days <= _thresholds.cold) return 'cold';
    return 'archive';
  }

  function projectTiers(offset) {
    var counts = { core: 0, active: 0, warm: 0, cold: 0, archive: 0 };
    _items.forEach(function(item) {
      if (item.tier === 'core') { counts.core++; return; }
      var newDays = item.days_since_access + offset;
      counts[calcTierClient(newDays)]++;
    });
    return counts;
  }

  function renderBars(offset) {
    var projected = projectTiers(offset);
    var axisColor = getAxisColor();
    var html = '';

    TIERS.forEach(function(t) {
      var pct = _total > 0 ? Math.round(projected[t] / _total * 100) : 0;
      var delta = projected[t] - _tierCounts[t];
      var deltaStr = delta === 0 ? '·' : (delta > 0 ? '+' : '') + delta;

      // Color logic: growth in cold/archive = bad (red), growth in active/warm = good (green)
      var deltaColor;
      if (t === 'cold' || t === 'archive') {
        deltaColor = delta > 0 ? '#D85A30' : (delta < 0 ? '#1D9E75' : axisColor);
      } else {
        deltaColor = delta < 0 ? '#D85A30' : (delta > 0 ? '#1D9E75' : axisColor);
      }

      html += '<div class="decay-projection-bar">'
        + '<span class="decay-bar-label" style="color:' + TIER_COLORS[t] + ';">' + t + '</span>'
        + '<div class="decay-bar-track"><div class="decay-bar-fill" style="width:' + pct + '%;background:' + TIER_COLORS[t] + ';opacity:0.75;"></div></div>'
        + '<span class="decay-bar-count">' + projected[t] + '</span>'
        + '<span class="decay-bar-delta" style="color:' + deltaColor + ';">' + deltaStr + '</span>'
        + '</div>';
    });

    barsContainer.innerHTML = html;
  }

  // Initial render
  renderBars(0);

  // Slider listener
  slider.addEventListener('input', function() {
    var val = parseInt(this.value, 10);
    daysLabel.textContent = val;
    renderBars(val);
  });

  console.log('[decay] projection rendered');
}

function renderDomainBars() {
  var axisColor = getAxisColor();
  var gridColor = getGridColor();

  // Group by domain
  var domainMap = {};
  _items.forEach(function(item) {
    var dom = item.domain || 'other';
    if (!domainMap[dom]) {
      domainMap[dom] = { active: 0, warm: 0, cold: 0, archive: 0, core: 0 };
    }
    if (domainMap[dom][item.tier] !== undefined) {
      domainMap[dom][item.tier]++;
    }
  });

  var domains = Object.keys(domainMap).sort();

  // Short labels for long domain names
  var shortLabels = domains.map(function(d) {
    if (d.length > 14) return d.substring(0, 12) + '..';
    return d;
  });

  // Legend (active, warm, cold, archive — without core)
  var barTiers = ['active', 'warm', 'cold', 'archive'];
  var legendEl = document.getElementById('domains-legend');
  legendEl.innerHTML = barTiers.map(function(t) {
    return '<span class="decay-legend-item"><span class="decay-legend-dot" style="background:' + TIER_COLORS[t] + ';border-radius:2px;"></span>' + t + '</span>';
  }).join('');

  var datasets = barTiers.map(function(t) {
    return {
      label: t,
      data: domains.map(function(d) { return domainMap[d][t]; }),
      backgroundColor: TIER_COLORS[t] + 'bb',
      borderWidth: 0
    };
  });

  new Chart(document.getElementById('domains-chart'), {
    type: 'bar',
    data: { labels: shortLabels, datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'y',
          callbacks: {
            label: function(ctx) {
              return ctx.dataset.label + ': ' + ctx.parsed.x;
            }
          }
        }
      },
      scales: {
        x: { stacked: true, ticks: { color: axisColor, font: { size: 10 } }, grid: { color: gridColor } },
        y: { stacked: true, ticks: { color: axisColor, font: { size: 11 } }, grid: { color: gridColor } }
      }
    }
  });

  console.log('[decay] domain bars rendered');
}

function renderForgottenGems() {
  var gems = _items
    .filter(function(i) { return i.tier === 'cold' || i.tier === 'archive'; })
    .sort(function(a, b) { return b.access_count - a.access_count; })
    .slice(0, 5);

  var container = document.getElementById('gems-container');

  if (gems.length === 0) {
    container.innerHTML = '<div class="decay-empty-state" style="padding:24px;">Нет забытых артефактов</div>';
    console.log('[decay] gems: none found');
    return;
  }

  container.innerHTML = gems.map(function(g) {
    // Domain abbreviation (first 2 chars uppercase)
    var abbr = (g.domain || '??').substring(0, 2).toUpperCase();
    return '<div class="decay-gem-card">'
      + '<div class="decay-gem-icon" style="background:' + TIER_COLORS[g.tier] + '20;color:' + TIER_COLORS[g.tier] + ';">' + abbr + '</div>'
      + '<div class="decay-gem-info">'
      + '<p class="decay-gem-title">' + (g.title || g.type + ' · ' + g.domain) + '</p>'
      + '<p class="decay-gem-meta">' + g.days_since_access + ' дней назад · ×' + g.access_count + ' обращений</p>'
      + '</div>'
      + '<span class="decay-gem-tier" style="background:' + TIER_COLORS[g.tier] + '20;color:' + TIER_COLORS[g.tier] + ';">' + g.tier + '</span>'
      + '<span class="decay-gem-rel">rel ' + g.relevance.toFixed(2) + '</span>'
      + '</div>';
  }).join('');

  console.log('[decay] gems rendered:', gems.length);
}

// ================================================================
// Init
// ================================================================
document.addEventListener('DOMContentLoaded', async function() {
  console.log('[decay] init');

  var ok = await loadSnapshot();
  if (!ok || _total === 0) {
    document.getElementById('empty-state').style.display = 'block';
    document.getElementById('decay-content').style.display = 'none';
    console.log('[decay] empty state shown');
    return;
  }

  document.getElementById('empty-state').style.display = 'none';
  document.getElementById('decay-content').style.display = 'block';

  renderMetrics();
  renderBubbleScatter();
  renderTierDonut();
  renderProjection();
  renderDomainBars();
  renderForgottenGems();

  console.log('[decay] render complete');
});
