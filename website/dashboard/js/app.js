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

  // Show upgrade banner for free tier
  var banner = document.getElementById('upgrade-banner');
  if (banner) {
    if (data.plan_name === 'free') {
      banner.classList.remove('hidden');
    } else {
      banner.classList.add('hidden');
    }
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
      var rules = Array.isArray(p.rules) ? p.rules : [];
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
  var rules = Array.isArray(policy.rules) ? policy.rules : [];

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

// ============================================================
// MOBILE NAV
// ============================================================

function toggleDashMobileNav() {
  var sidebar = document.querySelector('aside');
  if (sidebar.classList.contains('hidden')) {
    sidebar.classList.remove('hidden');
    sidebar.classList.add('fixed', 'z-20', 'bg-white', 'shadow-lg');
  } else {
    sidebar.classList.add('hidden');
    sidebar.classList.remove('fixed', 'z-20', 'shadow-lg');
  }
}

// ============================================================
// UPGRADE FLOW
// ============================================================

function dashboardUpgrade(plan) {
  apiFetch('/v1/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify({ plan: plan })
  })
  .then(function(resp) { return resp.json(); })
  .then(function(data) {
    if (data.checkout_url) window.location.href = data.checkout_url;
  })
  .catch(function() { alert('Failed to start checkout. Please try again.'); });
}

// Override apiFetch for POST support
function apiFetchPost(path, body) {
  return fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify(body)
  }).then(function(resp) {
    if (resp.ok) return resp.json();
    if (resp.status === 401) { handleLogout(); throw new Error('Session expired'); }
    throw new Error('API error: ' + resp.status);
  });
}

function dashboardUpgrade(plan) {
  apiFetchPost('/v1/checkout', { plan: plan })
  .then(function(data) {
    if (data.checkout_url) window.location.href = data.checkout_url;
  })
  .catch(function() { alert('Failed to start checkout. Please try again.'); });
}

// ============================================================
// POLICY BUILDER
// ============================================================

var builderRules = [];
var ruleCounter = 0;

var RULE_TYPES = {
  max_amount: { label: 'Maximum Amount', fields: [
    { key: 'limit', label: 'Dollar limit', type: 'number', placeholder: '500' },
    { key: 'currency', label: 'Currency', type: 'text', placeholder: 'USD', default: 'USD' }
  ]},
  refund_age_limit: { label: 'Refund Age Limit', fields: [
    { key: 'max_days', label: 'Maximum days since purchase', type: 'number', placeholder: '30' }
  ]},
  blocked_categories: { label: 'Blocked Categories', fields: [
    { key: 'categories', label: 'Categories to block (comma separated)', type: 'text', placeholder: 'gambling, luxury_goods' }
  ]},
  vendor_allowlist: { label: 'Vendor Allowlist', fields: [
    { key: 'vendors', label: 'Allowed vendors (comma separated)', type: 'text', placeholder: 'vendor_acme, vendor_globex' }
  ]},
  blocked_payment_rails: { label: 'Blocked Payment Methods', fields: [
    { key: 'rails', label: 'Methods to block (comma separated)', type: 'text', placeholder: 'wire, crypto, cash' }
  ]},
  discount_cap: { label: 'Discount Cap', fields: [
    { key: 'max_percent', label: 'Maximum discount %', type: 'number', placeholder: '20' }
  ]},
  geography_block: { label: 'Geography Block', fields: [
    { key: 'blocked_countries', label: 'Blocked country codes (comma separated)', type: 'text', placeholder: 'RU, KP, IR' }
  ]},
  time_restriction: { label: 'Time Restriction', fields: [
    { key: 'allowed_days', label: 'Allowed days (comma separated)', type: 'text', placeholder: 'mon, tue, wed, thu, fri' },
    { key: 'allowed_hours_utc', label: 'Allowed hours (UTC)', type: 'text', placeholder: '09:00-17:00' }
  ]},
  duplicate_guard: { label: 'Duplicate Guard', fields: [
    { key: 'window_minutes', label: 'Window (minutes)', type: 'number', placeholder: '10' }
  ]},
  escalate_if: { label: 'Escalate If', fields: [
    { key: 'amount_above', label: 'Escalate above this amount', type: 'number', placeholder: '200' },
    { key: 'action_types', label: 'For these action types (comma separated)', type: 'text', placeholder: 'refund, credit' }
  ]}
};

var TEMPLATES = {
  refund: {
    name: 'AI Support Refund Policy', desc: 'Controls refunds issued by AI support agents.',
    rules: [
      { rule_type: 'max_amount', desc: 'Block refunds over $500', params: { limit: 500, currency: 'USD' } },
      { rule_type: 'refund_age_limit', desc: 'No refunds after 30 days', params: { max_days: 30 } },
      { rule_type: 'escalate_if', desc: 'Escalate refunds over $200', params: { amount_above: 200, action_types: ['refund'] } },
      { rule_type: 'duplicate_guard', desc: 'Block duplicates within 10 min', params: { window_minutes: 10 } }
    ]
  },
  discount: {
    name: 'SaaS Discount Policy', desc: 'Controls discounts applied by AI pricing agents.',
    rules: [
      { rule_type: 'discount_cap', desc: 'Max 20% discount', params: { max_percent: 20 } },
      { rule_type: 'max_amount', desc: 'Max $5,000 discount value', params: { limit: 5000, currency: 'USD' } },
      { rule_type: 'escalate_if', desc: 'Escalate deals over $10,000', params: { amount_above: 10000, action_types: ['discount'] } }
    ]
  },
  vendor: {
    name: 'Vendor Spend Policy', desc: 'Controls payments made by AI procurement agents.',
    rules: [
      { rule_type: 'max_amount', desc: 'Block payments over $10,000', params: { limit: 10000, currency: 'USD' } },
      { rule_type: 'escalate_if', desc: 'Escalate payments over $2,500', params: { amount_above: 2500, action_types: ['spend'] } },
      { rule_type: 'blocked_payment_rails', desc: 'No wire or crypto', params: { rails: ['wire', 'crypto'] } },
      { rule_type: 'geography_block', desc: 'Block sanctioned countries', params: { blocked_countries: ['RU', 'KP', 'IR'] } }
    ]
  },
  expense: {
    name: 'Expense Reimbursement Policy', desc: 'Controls expense claims processed by AI agents.',
    rules: [
      { rule_type: 'max_amount', desc: 'Block claims over $500', params: { limit: 500, currency: 'USD' } },
      { rule_type: 'escalate_if', desc: 'Escalate claims over $250', params: { amount_above: 250, action_types: ['spend'] } },
      { rule_type: 'blocked_categories', desc: 'Block personal and gambling', params: { categories: ['personal', 'gambling'] } }
    ]
  }
};

function showPolicyBuilder() {
  document.getElementById('policies-list').classList.add('hidden');
  document.querySelector('#view-policies .flex.items-center.justify-between').classList.add('hidden');
  document.getElementById('policy-builder').classList.remove('hidden');
  clearBuilder();
}

function hidePolicyBuilder() {
  document.getElementById('policy-builder').classList.add('hidden');
  document.getElementById('policies-list').classList.remove('hidden');
  document.querySelector('#view-policies .flex.items-center.justify-between').classList.remove('hidden');
  loadPolicies();
}

function clearBuilder() {
  document.getElementById('builder-name').value = '';
  document.getElementById('builder-id').value = '';
  document.getElementById('builder-desc').value = '';
  document.getElementById('builder-error').classList.add('hidden');
  document.getElementById('builder-success').classList.add('hidden');
  builderRules = [];
  ruleCounter = 0;
  renderBuilderRules();
}

function loadTemplate(key) {
  var t = TEMPLATES[key];
  if (!t) return;
  document.getElementById('builder-name').value = t.name;
  document.getElementById('builder-desc').value = t.desc;
  builderRules = [];
  ruleCounter = 0;
  t.rules.forEach(function(r) {
    ruleCounter++;
    builderRules.push({ id: ruleCounter, rule_type: r.rule_type, description: r.desc, parameters: Object.assign({}, r.params) });
  });
  renderBuilderRules();
}

function addBuilderRule() {
  ruleCounter++;
  builderRules.push({ id: ruleCounter, rule_type: 'max_amount', description: '', parameters: {} });
  renderBuilderRules();
}

function removeBuilderRule(id) {
  builderRules = builderRules.filter(function(r) { return r.id !== id; });
  renderBuilderRules();
}

function renderBuilderRules() {
  var container = document.getElementById('builder-rules');
  var noRules = document.getElementById('builder-no-rules');

  if (builderRules.length === 0) {
    container.innerHTML = '';
    noRules.classList.remove('hidden');
    return;
  }

  noRules.classList.add('hidden');
  container.innerHTML = '';

  builderRules.forEach(function(rule, idx) {
    var typeInfo = RULE_TYPES[rule.rule_type] || RULE_TYPES.max_amount;

    // Build type selector options
    var typeOptions = Object.keys(RULE_TYPES).map(function(k) {
      var sel = k === rule.rule_type ? ' selected' : '';
      return '<option value="' + k + '"' + sel + '>' + RULE_TYPES[k].label + '</option>';
    }).join('');

    // Build parameter fields
    var paramFields = typeInfo.fields.map(function(f) {
      var val = rule.parameters[f.key];
      if (Array.isArray(val)) val = val.join(', ');
      if (val === undefined || val === null) val = f.default || '';
      return '<div class="flex-1 min-w-0">' +
        '<label class="block text-xs text-slate-500 mb-1">' + f.label + '</label>' +
        '<input type="' + f.type + '" value="' + escHtml(String(val)) + '" placeholder="' + f.placeholder + '" ' +
        'data-rule-id="' + rule.id + '" data-param="' + f.key + '" onchange="updateRuleParam(this)" ' +
        'class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500">' +
      '</div>';
    }).join('');

    var card = document.createElement('div');
    card.className = 'border border-slate-200 rounded-lg p-4 bg-white';
    card.innerHTML =
      '<div class="flex items-start justify-between mb-3">' +
        '<div class="flex items-center gap-3 flex-1">' +
          '<span class="text-xs font-mono text-slate-400">r' + (idx + 1) + '</span>' +
          '<select onchange="changeRuleType(' + rule.id + ', this.value)" class="text-sm rounded-lg border border-slate-300 px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-500">' + typeOptions + '</select>' +
        '</div>' +
        '<button type="button" onclick="removeBuilderRule(' + rule.id + ')" class="text-slate-400 hover:text-red-500 transition p-1" title="Remove rule" aria-label="Remove rule">' +
          '<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12" stroke-linecap="round"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="mb-3">' +
        '<input type="text" value="' + escHtml(rule.description) + '" placeholder="Rule description (what it does)" ' +
        'data-rule-id="' + rule.id + '" data-field="description" onchange="updateRuleDesc(this)" ' +
        'class="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500">' +
      '</div>' +
      '<div class="flex flex-wrap gap-3">' + paramFields + '</div>';

    container.appendChild(card);
  });
}

function changeRuleType(ruleId, newType) {
  builderRules.forEach(function(r) {
    if (r.id === ruleId) {
      r.rule_type = newType;
      r.parameters = {};
    }
  });
  renderBuilderRules();
}

function updateRuleParam(input) {
  var ruleId = parseInt(input.getAttribute('data-rule-id'));
  var param = input.getAttribute('data-param');
  var val = input.value;

  builderRules.forEach(function(r) {
    if (r.id === ruleId) {
      // Convert comma lists to arrays for specific params
      if (['categories', 'vendors', 'rails', 'blocked_countries', 'allowed_days', 'action_types'].indexOf(param) !== -1) {
        r.parameters[param] = val.split(',').map(function(s) { return s.trim(); }).filter(function(s) { return s; });
      } else if (input.type === 'number') {
        r.parameters[param] = parseFloat(val) || 0;
      } else {
        r.parameters[param] = val;
      }
    }
  });
}

function updateRuleDesc(input) {
  var ruleId = parseInt(input.getAttribute('data-rule-id'));
  builderRules.forEach(function(r) {
    if (r.id === ruleId) r.description = input.value;
  });
}

function submitPolicy() {
  var name = document.getElementById('builder-name').value.trim();
  var policyId = document.getElementById('builder-id').value.trim() || undefined;
  var desc = document.getElementById('builder-desc').value.trim() || undefined;
  var errorEl = document.getElementById('builder-error');
  var successEl = document.getElementById('builder-success');
  var btn = document.getElementById('builder-submit');

  errorEl.classList.add('hidden');
  successEl.classList.add('hidden');

  if (!name) { errorEl.textContent = 'Please enter a policy name.'; errorEl.classList.remove('hidden'); return; }
  if (builderRules.length === 0) { errorEl.textContent = 'Add at least one rule.'; errorEl.classList.remove('hidden'); return; }

  // Build rules array
  var rules = builderRules.map(function(r, idx) {
    return {
      rule_id: 'r' + (idx + 1),
      rule_type: r.rule_type,
      description: r.description || RULE_TYPES[r.rule_type].label,
      parameters: r.parameters
    };
  });

  btn.textContent = 'Creating...';
  btn.disabled = true;

  var body = { name: name, rules: rules };
  if (policyId) body.policy_id = policyId;
  if (desc) body.description = desc;

  apiFetchPost('/v1/policies', body)
  .then(function(data) {
    successEl.textContent = 'Policy "' + data.name + '" created (version ' + data.version + ')';
    successEl.classList.remove('hidden');
    btn.textContent = 'Create Policy';
    btn.disabled = false;
  })
  .catch(function(err) {
    errorEl.textContent = 'Failed to create policy: ' + err.message;
    errorEl.classList.remove('hidden');
    btn.textContent = 'Create Policy';
    btn.disabled = false;
  });
}
