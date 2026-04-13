/* ============================================================
   SpendGuard — Signup Modal + Pricing Flow
   ============================================================ */

var _signupApiKey = null;

function openSignupModal() {
  document.getElementById('signup-modal').classList.remove('hidden');
  document.getElementById('signup-step-form').classList.remove('hidden');
  document.getElementById('signup-step-key').classList.add('hidden');
  document.getElementById('signup-error').classList.add('hidden');
  document.getElementById('signup-name').value = '';
  document.getElementById('signup-email').value = '';
  document.getElementById('signup-submit-btn').textContent = 'Create Free Account';
  document.body.style.overflow = 'hidden';
}

function closeSignupModal() {
  document.getElementById('signup-modal').classList.add('hidden');
  document.body.style.overflow = '';
}

function handleSignup() {
  var name = document.getElementById('signup-name').value.trim();
  var email = document.getElementById('signup-email').value.trim();
  var errorEl = document.getElementById('signup-error');
  var btn = document.getElementById('signup-submit-btn');

  if (!name) {
    errorEl.textContent = 'Please enter your name.';
    errorEl.classList.remove('hidden');
    return;
  }
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errorEl.textContent = 'Please enter a valid email.';
    errorEl.classList.remove('hidden');
    return;
  }

  errorEl.classList.add('hidden');
  btn.textContent = 'Creating account...';
  btn.disabled = true;

  fetch('/v1/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, email: email })
  })
  .then(function(resp) {
    if (resp.ok) return resp.json();
    return resp.json().then(function(data) {
      var err = (data.detail && data.detail.error) || data.error || {};
      throw new Error(err.message || 'Signup failed. Please try again.');
    });
  })
  .then(function(data) {
    _signupApiKey = data.api_key;
    localStorage.setItem('sg_api_key', data.api_key);
    document.getElementById('signup-key-display').textContent = data.api_key;
    document.getElementById('signup-step-form').classList.add('hidden');
    document.getElementById('signup-step-key').classList.remove('hidden');
  })
  .catch(function(err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    btn.textContent = 'Create Free Account';
    btn.disabled = false;
  });
}

function copySignupKey() {
  if (!_signupApiKey) return;
  navigator.clipboard.writeText(_signupApiKey).then(function() {
    var btn = document.getElementById('signup-copy-btn');
    btn.innerHTML = '<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>';
    setTimeout(function() {
      btn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
    }, 2000);
  });
}

function handlePaidPlan(plan) {
  // For paid plans, first sign up (if not already), then redirect to Stripe checkout
  var savedKey = localStorage.getItem('sg_api_key');
  if (savedKey) {
    // Already have a key — go straight to checkout
    redirectToCheckout(plan, savedKey);
    return;
  }

  // Need to sign up first — show modal with a different flow
  openSignupModal();
  var btn = document.getElementById('signup-submit-btn');
  btn.textContent = 'Create Account & Upgrade to ' + plan.charAt(0).toUpperCase() + plan.slice(1);
  btn.onclick = function() {
    handleSignupThenCheckout(plan);
  };
}

function handleSignupThenCheckout(plan) {
  var name = document.getElementById('signup-name').value.trim();
  var email = document.getElementById('signup-email').value.trim();
  var errorEl = document.getElementById('signup-error');
  var btn = document.getElementById('signup-submit-btn');

  if (!name || !email || !email.includes('@')) {
    errorEl.textContent = 'Please fill in your name and email.';
    errorEl.classList.remove('hidden');
    return;
  }

  errorEl.classList.add('hidden');
  btn.textContent = 'Creating account...';
  btn.disabled = true;

  fetch('/v1/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, email: email })
  })
  .then(function(resp) {
    if (resp.ok) return resp.json();
    return resp.json().then(function(data) {
      var err = (data.detail && data.detail.error) || data.error || {};
      throw new Error(err.message || 'Signup failed.');
    });
  })
  .then(function(data) {
    localStorage.setItem('sg_api_key', data.api_key);
    btn.textContent = 'Redirecting to Stripe...';
    redirectToCheckout(plan, data.api_key);
  })
  .catch(function(err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    btn.textContent = 'Create Account & Upgrade';
    btn.disabled = false;
  });
}

function redirectToCheckout(plan, apiKey) {
  fetch('/v1/checkout', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey
    },
    body: JSON.stringify({ plan: plan })
  })
  .then(function(resp) {
    if (resp.ok) return resp.json();
    throw new Error('Failed to create checkout session.');
  })
  .then(function(data) {
    if (data.checkout_url) {
      window.location.href = data.checkout_url;
    }
  })
  .catch(function(err) {
    alert('Could not start checkout: ' + err.message);
  });
}

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeSignupModal();
});
