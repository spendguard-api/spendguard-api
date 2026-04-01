/* ============================================================
   SpendGuard — Live Demo Widget
   Calls POST /v1/simulate (demo mode, no auth) and renders results
   ============================================================ */

(function () {
  'use strict';

  var DEMO_ACTIONS = [
    {
      agent_id: 'demo-agent',
      policy_id: 'demo_refund_policy',
      action_type: 'refund',
      amount: 50.00,
      currency: 'USD',
      counterparty: 'customer_001',
      metadata: { days_since_purchase: 10 }
    },
    {
      agent_id: 'demo-agent',
      policy_id: 'demo_refund_policy',
      action_type: 'refund',
      amount: 750.00,
      currency: 'USD',
      counterparty: 'customer_002'
    },
    {
      agent_id: 'demo-agent',
      policy_id: 'demo_refund_policy',
      action_type: 'refund',
      amount: 200.00,
      currency: 'USD',
      counterparty: 'customer_003',
      metadata: { days_since_purchase: 45 }
    },
    {
      agent_id: 'demo-agent',
      policy_id: 'demo_refund_policy',
      action_type: 'refund',
      amount: 300.00,
      currency: 'USD',
      counterparty: 'customer_004'
    },
    {
      agent_id: 'demo-agent',
      policy_id: 'demo_refund_policy',
      action_type: 'discount',
      amount: 100.00,
      currency: 'USD',
      counterparty: 'customer_005',
      metadata: { discount_percent: 15 }
    }
  ];

  var runBtn = document.getElementById('demo-run');
  var errorEl = document.getElementById('demo-error');
  var footerEl = document.getElementById('demo-footer');
  var summaryEl = document.getElementById('demo-summary');
  var running = false;

  if (!runBtn) return;

  runBtn.addEventListener('click', function () {
    if (running) return;
    running = true;
    runBtn.textContent = 'Running...';
    runBtn.disabled = true;
    errorEl.style.display = 'none';

    // Clear previous results
    for (var i = 0; i < 5; i++) {
      var el = document.getElementById('result-' + i);
      if (el) {
        el.innerHTML = '';
        el.classList.remove('visible');
      }
    }
    footerEl.classList.add('demo-footer-hidden');

    fetch('/v1/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        policy_id: 'demo_refund_policy',
        actions: DEMO_ACTIONS
      })
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        renderResults(data);
      })
      .catch(function (err) {
        console.error('Demo error:', err);
        errorEl.style.display = 'block';
      })
      .finally(function () {
        running = false;
        runBtn.textContent = 'Run Simulation';
        runBtn.disabled = false;
      });
  });

  function renderResults(data) {
    var results = data.results || [];
    var summary = data.summary || {};

    results.forEach(function (result, index) {
      var el = document.getElementById('result-' + index);
      if (!el) return;

      var decision = result.decision || 'unknown';
      var message = result.message || '';

      // Truncate message for display
      if (message.length > 50) {
        message = message.substring(0, 50) + '...';
      }

      var badgeClass = decision === 'allow' ? 'allow' :
                       decision === 'block' ? 'block' :
                       decision === 'escalate' ? 'escalate' : '';

      el.innerHTML =
        '<span class="demo-result-message">' + escapeHtml(message) + '</span>' +
        '<span class="decision-badge ' + badgeClass + '">' + decision.toUpperCase() + '</span>';

      // Stagger the reveal
      setTimeout(function () {
        el.classList.add('visible');
      }, index * 150);
    });

    // Render summary
    var allowed = summary.allowed || 0;
    var blocked = summary.blocked || 0;
    var escalated = summary.escalated || 0;

    summaryEl.innerHTML =
      '<span class="demo-summary-item"><span class="demo-summary-dot allow"></span>' + allowed + ' allowed</span>' +
      '<span class="demo-summary-item"><span class="demo-summary-dot block"></span>' + blocked + ' blocked</span>' +
      '<span class="demo-summary-item"><span class="demo-summary-dot escalate"></span>' + escalated + ' escalated</span>';

    // Show footer after last result animates in
    setTimeout(function () {
      footerEl.classList.remove('demo-footer-hidden');
    }, results.length * 150 + 200);
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

})();
