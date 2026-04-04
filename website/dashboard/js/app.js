/* ============================================================
   SpendGuard Dashboard — Single Page App
   Auth, overview, policies, violations
   ============================================================ */

var API_BASE = '';  // Same origin
var apiKey = null;
var violationsCursor = null;

// ============================================================
// AUTH
// ============================================================

function handleLogin() {
  var input = document.getElementById('api-key-input');
  var errorEl = document.getElementById('login-error');
  var key = input.value.trim();

  if (!key) {
    errorEl.textContent = 'Please enter your API key.';
    errorEl.classList.remove('hidden');
    return;
  }

  errorEl.classList.add('hidden');
  document.getElementById('login-btn').textContent = 'Connecting...';

  // Validate key by calling /v1/usage
  fetch(API_BASE + '/v1/usage', {
    headers: { 'X-API-Key': key }
  })
  .then(function(resp) {
    if (resp.ok) return resp.json();
    throw new Error(resp.status === 401 ? 'Invalid API key. Check your key and try again.' : 'Connection failed. Please try again.');
  })
  .then(function(data) {
    apiKey = key;
    sessionStorage.setItem('sg_api_key', key);
    showDashboard(data);
  })
  .catch(function(err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    document.getElementById('login-btn').textContent = 'Connect';
  });
}

function handleLogout() {
  apiKey = null;
  sessionStorage.removeItem('sg_api_key');
  document.getElementById('dashboard-shell').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('api-key-input').value = '';
  document.getElementById('login-error').classList.add('hidden');
  document.getElementById('login-btn').textContent = 'Connect';
}

// Check for existing session on load
(function() {
  var savedKey = sessionStorage.getItem('sg_api_key');
  if (savedKey) {
    apiKey = savedKey;
    fetch(API_BASE + '/v1/usage', { headers: { 'X-API-Key': savedKey } })
    .then(function(resp) { if (resp.ok) return resp.json(); throw new Error(); })
    .then(function(data) { showDashboard(data); })
    .catch(function() { handleLogout(); });
  }
})();

// Enter key on input
document.getElementById('api-key-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') handleLogin();
});

// ============================================================
// DASHBOARD INIT
// ============================================================

function showDashboard(usageData) {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('dashboard-shell').classList.remove('hidden');

  // Set user name
  var name = usageData.owner_name || usageData.email || 'User';
  document.getElementById('user-name').textContent = name;

  updateOverview(usageData);
  showView('overview');
}

// ============================================================
// VIEW SWITCHING
// ============================================================

function showView(viewName) {
  // Hide all views
  document.querySelectorAll('.view').forEach(function(v) { v.classList.add('hidden'); });
  // Show selected
  document.getElementById('view-' + viewName).classList.remove('hidden');

  // Update nav active state
  document.querySelectorAll('.nav-link').forEach(function(l) {
    l.classList.remove('active');
    if (l.getAttribute('data-view') === viewName) l.classList.add('active');
  });

  // Load data for view
  if (viewName === 'policies') loadPolicies();
  if (viewName === 'violations') { violationsCursor = null; loadViolations(); }
  if (viewName === 'overview') refreshOverview();
}

// ============================================================
// OVERVIEW
// ============================================================

function refreshOverview() {
  apiFetch('/v1/usage')
  .then(function(data) { updateOverview(data); })
  .catch(function() {});
}

function updateOverview(data) {
  document.getElementById('metric-checks-today').textContent = data.checks_today.toLocaleString();
  document.getElementById('metric-violations-today').textContent = data.violations_today.toLocaleString();
  document.getElementById('metric-plan-usage').textContent = data.current_period_usage.toLocaleString() + ' / ' + data.plan_limit.toLocaleString();
  document.getElementById('metric-plan-name').textContent = data.plan_name;

  // Usage bar
  var pct = Math.min((data.current_period_usage / data.plan_limit) * 100, 100);
  var bar = document.getElementById('usage-bar');
  bar.style.width = pct + '%';
  bar.className = 'h-full rounded-full transition-all duration-500 ' +
    (pct >= 90 ? 'usage-red' : pct >= 70 ? 'usage-yellow' : 'usage-green');

  document.getElementById('usage-label').textContent = data.current_period_usage.toLocaleString() + ' / ' + data.plan_limit.toLocaleString() + ' checks';

  var warning = document.getElementById('usage-warning');
  if (pct >= 100) {
    warning.textContent = 'Quota reached. ' + (data.overage_enabled ? 'Overage billing active at $0.005/check.' : 'Enable overage or upgrade your plan.');
    warning.classList.remove('hidden');
  } else if (pct >= 90) {
    warning.textContent = 'Approaching quota limit (' + Math.round(pct) + '% used).';
    warning.classList.remove('hidden');
  } else {
    warning.classList.add('hidden');
  }
}

// ============================================================
// POLICIES
// ============================================================

function loadPolicies() {
  var container = document.getElementById('policies-list');
  container.innerHTML = '<p class="text-sm text-slate-400">Loading policies...</p>';

  apiFetch('/v1/policies?limit=50')
  .then(function(data) {
    var policies = data.data || [];
    if (policies.length === 0) {
      container.innerHTML = '<div class="bg-white rounded-xl border border-slate-200 p-8 text-center"><p class="text-slate-500 text-sm">No policies yet.</p><a href="https://spendguard.mintlify.app/guides/quickstart" target="_blank" rel="noopener" class="text-brand-600 text-sm hover:underline mt-2 inline-block">Create your first policy →</a></div>';
      return;
    }

    container.innerHTML = '';
    policies.forEach(function(p) {
      var rules = p.rules || [];
      var ruleTypes = rules.map(function(r) { return r.rule_type; });
      var ruleTags = ruleTypes.map(function(t) { return '<span class="rule-tag">' + t + '</span>'; }).join('');

      var card = document.createElement('div');
      card.className = 'policy-card bg-white rounded-xl border border-slate-200 p-5 cursor-pointer';
      card.innerHTML =
        '<div class="flex items-start justify-between mb-3">' +
          '<div>' +
            '<h3 class="font-semibold text-slate-900">' + escHtml(p.name) + '</h3>' +
            '<p class="text-xs font-mono text-slate-400 mt-0.5">' + escHtml(p.policy_id) + '</p>' +
          '</div>' +
          '<span class="text-xs text-slate-400">v' + p.version + '</span>' +
        '</div>' +
        (p.description ? '<p class="text-sm text-slate-500 mb-3">' + escHtml(p.description) + '</p>' : '') +
        '<div class="flex flex-wrap gap-1 mb-3">' + ruleTags + '</div>' +
        '<p class="text-xs text-slate-400">' + rules.length + ' rule' + (rules.length !== 1 ? 's' : '') + '</p>';

      card.onclick = function() { showPolicyDetail(p); };
      container.appendChild(card);
    });
  })
  .catch(function(err) {
    container.innerHTML = '<p class="text-sm text-red-500">Failed to load policies: ' + err.message + '</p>';
  });
}

function showPolicyDetail(policy) {
  var container = document.getElementById('policies-list');
  var rules = policy.rules || [];

  var rulesHtml = rules.map(function(r) {
    return '<div class="border border-slate-200 rounded-lg p-4">' +
      '<div class="flex items-center justify-between mb-2">' +
        '<span class="font-medium text-sm text-slate-900">' + escHtml(r.rule_id || '') + ' — ' + escHtml(r.rule_type) + '</span>' +
      '</div>' +
      (r.description ? '<p class="text-xs text-slate-500 mb-2">' + escHtml(r.description) + '</p>' : '') +
      '<pre class="text-xs font-mono bg-slate-50 rounded p-3 overflow-x-auto text-slate-600">' + escHtml(JSON.stringify(r.parameters, null, 2)) + '</pre>' +
    '</div>';
  }).join('');

  container.innerHTML =
    '<button onclick="loadPolicies()" class="text-sm text-brand-600 hover:underline mb-4 inline-flex items-center gap-1">' +
      '<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"/></svg>' +
      'Back to all policies' +
    '</button>' +
    '<div class="bg-white rounded-xl border border-slate-200 p-6">' +
      '<h3 class="text-lg font-bold text-slate-900">' + escHtml(policy.name) + '</h3>' +
      '<p class="text-xs font-mono text-slate-400 mt-1">' + escHtml(policy.policy_id) + ' — version ' + policy.version + '</p>' +
      (policy.description ? '<p class="text-sm text-slate-500 mt-3">' + escHtml(policy.description) + '</p>' : '') +
      '<h4 class="text-sm font-semibold text-slate-800 mt-6 mb-3">Rules (' + rules.length + ')</h4>' +
      '<div class="space-y-3">' + rulesHtml + '</div>' +
    '</div>';
}

// ============================================================
// VIOLATIONS
// ============================================================

function loadViolations() {
  violationsCursor = null;
  var params = buildViolationParams();

  apiFetch('/v1/violations?' + params)
  .then(function(data) { renderViolations(data, false); })
  .catch(function(err) {
    document.getElementById('violations-body').innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-red-500">Failed: ' + err.message + '</td></tr>';
  });
}

function loadMoreViolations() {
  if (!violationsCursor) return;
  var params = buildViolationParams() + '&cursor=' + encodeURIComponent(violationsCursor);

  apiFetch('/v1/violations?' + params)
  .then(function(data) { renderViolations(data, true); })
  .catch(function() {});
}

function buildViolationParams() {
  var parts = ['limit=20'];
  var decision = document.getElementById('filter-decision').value;
  var actionType = document.getElementById('filter-action-type').value;
  var agentId = document.getElementById('filter-agent-id').value.trim();
  if (decision) parts.push('decision=' + decision);
  if (actionType) parts.push('action_type=' + actionType);
  if (agentId) parts.push('agent_id=' + encodeURIComponent(agentId));
  return parts.join('&');
}

function renderViolations(data, append) {
  var violations = data.data || [];
  var tbody = document.getElementById('violations-body');

  if (!append) tbody.innerHTML = '';

  if (violations.length === 0 && !append) {
    tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-slate-400">No violations found.</td></tr>';
    document.getElementById('load-more-btn').classList.add('hidden');
    document.getElementById('violations-count').textContent = '0 violations';
    return;
  }

  violations.forEach(function(v) {
    var tr = document.createElement('tr');
    tr.className = 'border-b border-slate-100 hover:bg-slate-50 transition-colors';
    var time = v.timestamp ? new Date(v.timestamp).toLocaleString() : '—';
    var badgeClass = v.decision === 'block' ? 'badge-block' : 'badge-escalate';
    tr.innerHTML =
      '<td class="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">' + time + '</td>' +
      '<td class="px-4 py-3 text-xs font-mono text-slate-600">' + escHtml(v.agent_id) + '</td>' +
      '<td class="px-4 py-3 text-xs text-slate-600 capitalize">' + escHtml(v.action_type) + '</td>' +
      '<td class="px-4 py-3 text-xs text-slate-600">$' + Number(v.amount).toFixed(2) + '</td>' +
      '<td class="px-4 py-3"><span class="badge ' + badgeClass + '">' + v.decision + '</span></td>' +
      '<td class="px-4 py-3 text-xs text-slate-500">' + escHtml(v.violated_rule_description || v.violated_rule_id || '—') + '</td>';
    tbody.appendChild(tr);
  });

  violationsCursor = data.pagination.next_cursor;
  var btn = document.getElementById('load-more-btn');
  if (data.pagination.has_more) {
    btn.classList.remove('hidden');
  } else {
    btn.classList.add('hidden');
  }

  document.getElementById('violations-count').textContent = (data.pagination.total_count || 0) + ' total violations';
}

// ============================================================
// HELPERS
// ============================================================

function apiFetch(path) {
  return fetch(API_BASE + path, {
    headers: { 'X-API-Key': apiKey }
  }).then(function(resp) {
    if (resp.ok) return resp.json();
    if (resp.status === 401) { handleLogout(); throw new Error('Session expired'); }
    throw new Error('API error: ' + resp.status);
  });
}

function escHtml(str) {
  if (!str) return '';
  var div = document.createElement('div');
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
