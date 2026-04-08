/* ============================================================
   SpendGuard Dashboard — Single Page App
   Auth, overview, policies, violations
   ============================================================ */

var API_BASE = '';  // Same origin
var apiKey = null;
var violationsCursor = null;
var lastUsageData = null;  // Cached /v1/usage response — used by Account view

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
    localStorage.setItem('sg_api_key', key);
    showDashboard(data);
    handleUpgradeReturn();
  })
  .catch(function(err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    document.getElementById('login-btn').textContent = 'Connect';
  });
}

function handleLogout() {
  apiKey = null;
  localStorage.removeItem('sg_api_key');
  document.getElementById('dashboard-shell').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('api-key-input').value = '';
  document.getElementById('login-error').classList.add('hidden');
  document.getElementById('login-btn').textContent = 'Connect';
}

// Check for existing session on load
(function() {
  var savedKey = localStorage.getItem('sg_api_key');
  if (savedKey) {
    apiKey = savedKey;
    fetch(API_BASE + '/v1/usage', { headers: { 'X-API-Key': savedKey } })
    .then(function(resp) { if (resp.ok) return resp.json(); throw new Error(); })
    .then(function(data) { showDashboard(data); handleUpgradeReturn(); })
    .catch(function() { handleLogout(); });
  } else {
    // No saved key but landed on dashboard with ?upgraded= — they need to log in first
    // The banner will fire after they log in successfully
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
  if (viewName === 'account') loadAccount();
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
  lastUsageData = data;  // Cache for Account view
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
  var sidebar = document.getElementById('dash-sidebar');
  var existing = document.getElementById('sidebar-backdrop');

  if (sidebar.classList.contains('mobile-open')) {
    // Close
    sidebar.classList.remove('mobile-open');
    if (existing) existing.remove();
  } else {
    // Open with backdrop
    sidebar.classList.add('mobile-open');
    var backdrop = document.createElement('div');
    backdrop.id = 'sidebar-backdrop';
    backdrop.className = 'sidebar-backdrop';
    backdrop.onclick = function() { toggleDashMobileNav(); };
    document.body.appendChild(backdrop);
  }
}

// Close mobile nav when a view is selected
var origShowView = showView;
showView = function(viewName) {
  var sidebar = document.getElementById('dash-sidebar');
  if (sidebar && sidebar.classList.contains('mobile-open')) {
    toggleDashMobileNav();
  }
  origShowView(viewName);
};

// ============================================================
// UPGRADE FLOW
// ============================================================

// POST helper for dashboard API calls
function apiFetchPost(path, body) {
  return fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify(body)
  }).then(function(resp) {
    if (resp.ok) return resp.json();
    if (resp.status === 401) { handleLogout(); throw new Error('Session expired'); }
    return resp.json().then(function(data) {
      var err = (data.detail && data.detail.error) || data.error || {};
      throw new Error(err.message || 'API error: ' + resp.status);
    });
  });
}

function dashboardUpgrade(plan) {
  apiFetchPost('/v1/checkout', { plan: plan })
  .then(function(data) {
    // Branch 1: Free → paid. Redirect to Stripe Checkout.
    if (data.checkout_url) {
      window.location.href = data.checkout_url;
      return;
    }

    // Branch 2: Plan change between Pro and Growth. No checkout — refresh
    // the dashboard and show a confirmation toast.
    if (data.change_type === 'plan_change') {
      var planDisplay = plan === 'pro' ? 'Pro' : 'Growth';
      loadAccount();
      refreshOverview();
      showAccountToast('Plan changed to ' + planDisplay + '. A confirmation email is on its way.');
    }
  })
  .catch(function(err) {
    // Same-plan case returns 409 with a friendly message — surface it via toast
    var message = err.message || 'Failed to start checkout.';
    if (message.indexOf('already on') !== -1) {
      showAccountToast(message);
    } else {
      alert('Failed: ' + message);
    }
  });
}

// ============================================================
// UPGRADE RETURN BANNER (D024)
// ============================================================
// When the user comes back from Stripe Checkout, the URL has ?upgraded=pro
// or ?upgraded=growth. We show a green success banner and poll /v1/usage
// every 2 seconds until plan_name matches (handles webhook delay).

var _upgradePollTimer = null;
var _upgradePollAttempts = 0;
var UPGRADE_POLL_MAX_ATTEMPTS = 8;  // 8 × 2s = 16s max wait

function handleUpgradeReturn() {
  var params = new URLSearchParams(window.location.search);
  var upgradedPlan = params.get('upgraded');
  if (!upgradedPlan) return;
  if (upgradedPlan !== 'pro' && upgradedPlan !== 'growth') return;

  // Clean the URL so refreshing doesn't re-show
  var cleanUrl = window.location.pathname;
  history.replaceState({}, document.title, cleanUrl);

  showUpgradeBanner(upgradedPlan, false);
  startUpgradePolling(upgradedPlan);
}

function showUpgradeBanner(plan, confirmed) {
  var banner = document.getElementById('upgrade-success-banner');
  var title = document.getElementById('upgrade-success-title');
  var body = document.getElementById('upgrade-success-body');
  if (!banner) return;

  var planDisplay = plan === 'pro' ? 'Pro' : 'Growth';
  var planLimit = plan === 'pro' ? '10,000' : '100,000';

  if (confirmed) {
    title.textContent = 'Welcome to SpendGuard ' + planDisplay;
    body.textContent = 'Your plan is now active with ' + planLimit + ' checks per month. A confirmation email is on its way.';
  } else {
    title.textContent = 'Confirming your upgrade to ' + planDisplay + '…';
    body.textContent = 'This takes a few seconds. Your dashboard will update automatically.';
  }

  banner.classList.remove('hidden');
}

function dismissUpgradeBanner() {
  var banner = document.getElementById('upgrade-success-banner');
  if (banner) banner.classList.add('hidden');
  if (_upgradePollTimer) { clearTimeout(_upgradePollTimer); _upgradePollTimer = null; }
}

function startUpgradePolling(expectedPlan) {
  _upgradePollAttempts = 0;
  pollForUpgrade(expectedPlan);
}

// ============================================================
// ACCOUNT VIEW + SUBSCRIPTION CANCEL (D025)
// ============================================================

function loadAccount() {
  // Always re-fetch so we show the freshest subscription state
  apiFetch('/v1/usage')
  .then(function(data) {
    lastUsageData = data;
    renderAccount(data);
  })
  .catch(function(err) {
    var plan = document.getElementById('account-plan');
    if (plan) plan.textContent = 'Error loading account';
  });
}

function renderAccount(data) {
  if (!data) return;

  // Profile
  document.getElementById('account-name').textContent = data.owner_name || '—';
  document.getElementById('account-email').textContent = data.email || '—';

  // API key — populate masked by default, store full key in dataset for toggle
  var keyInput = document.getElementById('api-key-display');
  if (keyInput && apiKey) {
    keyInput.dataset.fullKey = apiKey;
    keyInput.dataset.visible = 'false';
    keyInput.value = maskApiKey(apiKey);
  }

  // Plan info
  var plan = (data.plan_name || 'free').toLowerCase();
  var planDisplay = plan.charAt(0).toUpperCase() + plan.slice(1);
  document.getElementById('account-plan').textContent = planDisplay;
  document.getElementById('account-limit').textContent = (data.plan_limit || 0).toLocaleString() + ' checks';

  // Hide all state sections first
  var freeState = document.getElementById('account-state-free');
  var activeState = document.getElementById('account-state-active');
  var scheduledState = document.getElementById('account-state-scheduled');
  freeState.classList.add('hidden');
  activeState.classList.add('hidden');
  scheduledState.classList.add('hidden');

  if (plan === 'free') {
    freeState.classList.remove('hidden');
    return;
  }

  // Paid tier — check cancellation state
  if (data.cancel_at_period_end) {
    scheduledState.classList.remove('hidden');
    var endDate = formatPeriodEnd(data.current_period_end);
    var body = document.getElementById('account-cancel-body');
    if (body) {
      body.textContent = 'Your ' + planDisplay + ' plan remains active until ' + endDate + '. After that date, your account will revert to the free plan.';
    }
  } else {
    activeState.classList.remove('hidden');
    var next = document.getElementById('account-next-billing');
    if (next) next.textContent = formatPeriodEnd(data.current_period_end);

    // Show plan-switch button labelled with the OTHER plan
    var switchBtn = document.getElementById('account-switch-btn');
    if (switchBtn) {
      if (plan === 'pro') {
        switchBtn.textContent = 'Switch to Growth — $199/mo';
        switchBtn.dataset.targetPlan = 'growth';
        switchBtn.classList.remove('hidden');
      } else if (plan === 'growth') {
        switchBtn.textContent = 'Switch to Pro — $49/mo';
        switchBtn.dataset.targetPlan = 'pro';
        switchBtn.classList.remove('hidden');
      } else {
        switchBtn.classList.add('hidden');
      }
    }
  }
}

function confirmPlanSwitch() {
  var btn = document.getElementById('account-switch-btn');
  if (!btn) return;
  var targetPlan = btn.dataset.targetPlan;
  if (!targetPlan) return;

  var currentPlan = lastUsageData ? (lastUsageData.plan_name || '').toLowerCase() : 'your plan';
  var currentDisplay = currentPlan === 'pro' ? 'Pro' : currentPlan === 'growth' ? 'Growth' : 'your plan';
  var targetDisplay = targetPlan === 'pro' ? 'Pro' : 'Growth';
  var targetPrice = targetPlan === 'pro' ? '$49/month' : '$199/month';

  var msg = 'Switch from ' + currentDisplay + ' to ' + targetDisplay + ' (' + targetPrice + ')?\n\n' +
    'Your billing cycle will reset to today and you will be charged the new plan price minus a credit for unused time on your current plan.';

  if (!window.confirm(msg)) return;

  btn.disabled = true;
  btn.textContent = 'Switching…';

  apiFetchPost('/v1/checkout', { plan: targetPlan })
  .then(function(data) {
    if (data.change_type === 'plan_change') {
      loadAccount();
      refreshOverview();
      showAccountToast('Plan changed to ' + targetDisplay + '. A confirmation email is on its way.');
    } else if (data.checkout_url) {
      window.location.href = data.checkout_url;
    }
  })
  .catch(function(err) {
    btn.disabled = false;
    var label = targetPlan === 'pro' ? 'Switch to Pro — $49/mo' : 'Switch to Growth — $199/mo';
    btn.textContent = label;
    alert('Failed to switch plan: ' + (err.message || 'Unknown error'));
  });
}

function formatPeriodEnd(iso) {
  if (!iso) return '—';
  try {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  } catch (e) {
    return '—';
  }
}

function showCancelModal() {
  var modal = document.getElementById('cancel-modal');
  if (!modal) return;

  // Personalize the body with the plan + cancel date
  var plan = 'your plan';
  var endDate = 'the end of your current billing period';
  if (lastUsageData) {
    var p = (lastUsageData.plan_name || '').toLowerCase();
    if (p === 'pro') plan = 'your Pro plan';
    if (p === 'growth') plan = 'your Growth plan';
    if (lastUsageData.current_period_end) {
      endDate = formatPeriodEnd(lastUsageData.current_period_end);
    }
  }

  var title = document.getElementById('cancel-modal-title');
  var body = document.getElementById('cancel-modal-body');
  if (title) title.textContent = 'Cancel ' + plan + '?';
  if (body) body.textContent = 'You will retain full access until ' + endDate + '. After that, your account will revert to the free plan with 1,000 checks per month.';

  // Clear any prior error
  var err = document.getElementById('cancel-modal-error');
  if (err) err.classList.add('hidden');

  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function hideCancelModal() {
  var modal = document.getElementById('cancel-modal');
  if (modal) modal.classList.add('hidden');
  document.body.style.overflow = '';
  // Reset button state in case user clicks cancel mid-request
  var btn = document.getElementById('cancel-modal-confirm');
  if (btn) { btn.textContent = 'Yes, cancel'; btn.disabled = false; }
}

function confirmCancelSubscription() {
  var btn = document.getElementById('cancel-modal-confirm');
  var err = document.getElementById('cancel-modal-error');
  if (btn) { btn.textContent = 'Cancelling…'; btn.disabled = true; }
  if (err) err.classList.add('hidden');

  apiFetchPost('/v1/billing/cancel', {})
  .then(function(data) {
    hideCancelModal();
    // Refresh account + overview with new state
    loadAccount();
    refreshOverview();
    showAccountToast('Subscription cancelled. You have access until ' + formatPeriodEnd(data.current_period_end) + '.');
  })
  .catch(function(e) {
    if (btn) { btn.textContent = 'Yes, cancel'; btn.disabled = false; }
    if (err) {
      err.textContent = e.message || 'Failed to cancel. Please try again.';
      err.classList.remove('hidden');
    }
  });
}

function reactivateSubscription() {
  apiFetchPost('/v1/billing/reactivate', {})
  .then(function(data) {
    loadAccount();
    refreshOverview();
    showAccountToast('Subscription reactivated. Welcome back.');
  })
  .catch(function(e) {
    alert('Failed to reactivate: ' + (e.message || 'Unknown error'));
  });
}

// API key display helpers
function maskApiKey(key) {
  if (!key) return '';
  // Show the prefix (sg_live_ or sg_test_) + 4 chars, then mask the rest
  // Example: "sg_live_abcd••••••••••••••••••"
  var prefixMatch = key.match(/^([a-z]+_[a-z]+_)?/);
  var prefix = prefixMatch ? prefixMatch[0] : '';
  var afterPrefix = key.slice(prefix.length);
  var visible = afterPrefix.slice(0, 4);
  var masked = '•'.repeat(Math.max(afterPrefix.length - 4, 8));
  return prefix + visible + masked;
}

function toggleApiKeyVisibility() {
  var input = document.getElementById('api-key-display');
  var label = document.getElementById('api-key-toggle-label');
  var icon = document.getElementById('api-key-eye-icon');
  if (!input || !input.dataset.fullKey) return;

  var isVisible = input.dataset.visible === 'true';
  if (isVisible) {
    input.value = maskApiKey(input.dataset.fullKey);
    input.dataset.visible = 'false';
    if (label) label.textContent = 'Show';
    if (icon) icon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
  } else {
    input.value = input.dataset.fullKey;
    input.dataset.visible = 'true';
    if (label) label.textContent = 'Hide';
    if (icon) icon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
  }
}

function copyApiKey() {
  var input = document.getElementById('api-key-display');
  if (!input || !input.dataset.fullKey) return;

  var btn = document.getElementById('api-key-copy');
  var label = document.getElementById('api-key-copy-label');
  var icon = document.getElementById('api-key-copy-icon');

  // Always copy the FULL key, not the masked version
  navigator.clipboard.writeText(input.dataset.fullKey).then(function() {
    if (label) label.textContent = 'Copied';
    if (icon) icon.innerHTML = '<polyline points="20 6 9 17 4 12"/>';
    if (btn) btn.classList.add('api-key-btn-success');
    setTimeout(function() {
      if (label) label.textContent = 'Copy';
      if (icon) icon.innerHTML = '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>';
      if (btn) btn.classList.remove('api-key-btn-success');
    }, 2000);
  }).catch(function() {
    // Fallback for older browsers — select + execCommand
    input.value = input.dataset.fullKey;
    input.select();
    try { document.execCommand('copy'); } catch (e) {}
    if (input.dataset.visible !== 'true') input.value = maskApiKey(input.dataset.fullKey);
    if (label) label.textContent = 'Copied';
    setTimeout(function() { if (label) label.textContent = 'Copy'; }, 2000);
  });
}

function showAccountToast(message) {
  var existing = document.getElementById('account-toast');
  if (existing) existing.remove();

  var toast = document.createElement('div');
  toast.id = 'account-toast';
  toast.className = 'account-toast';
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(function() {
    toast.classList.add('fade-out');
    setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 400);
  }, 5000);
}

// ============================================================

function pollForUpgrade(expectedPlan) {
  _upgradePollAttempts++;

  apiFetch('/v1/usage')
  .then(function(data) {
    if (data.plan_name === expectedPlan) {
      // Webhook has fired — update overview and switch banner to confirmed state
      updateOverview(data);
      showUpgradeBanner(expectedPlan, true);
      _upgradePollTimer = null;
      return;
    }

    if (_upgradePollAttempts >= UPGRADE_POLL_MAX_ATTEMPTS) {
      // Timed out — show a fallback message
      var title = document.getElementById('upgrade-success-title');
      var body = document.getElementById('upgrade-success-body');
      if (title && body) {
        title.textContent = 'Payment received — still processing';
        body.textContent = 'Your upgrade should appear within a minute. Refresh the page if it does not update.';
      }
      _upgradePollTimer = null;
      return;
    }

    _upgradePollTimer = setTimeout(function() { pollForUpgrade(expectedPlan); }, 2000);
  })
  .catch(function() {
    // Silently retry — network blip is fine
    if (_upgradePollAttempts < UPGRADE_POLL_MAX_ATTEMPTS) {
      _upgradePollTimer = setTimeout(function() { pollForUpgrade(expectedPlan); }, 2000);
    }
  });
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
  document.getElementById('policies-header').classList.add('hidden');
  document.getElementById('policy-builder').classList.remove('hidden');
  clearBuilder();
}

function hidePolicyBuilder() {
  document.getElementById('policy-builder').classList.add('hidden');
  document.getElementById('policies-list').classList.remove('hidden');
  document.getElementById('policies-header').classList.remove('hidden');
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
