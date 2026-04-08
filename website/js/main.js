/* ============================================================
   SpendGuard — Main JavaScript
   Nav, scroll, counters, copy, code tabs, sticky CTA, fade-in
   ============================================================ */

(function () {
  'use strict';

  // --- Nav scroll effect — glass gets more opaque on scroll ---
  var nav = document.getElementById('nav');
  window.addEventListener('scroll', function () {
    if (window.scrollY > 10) {
      nav.style.background = 'rgba(255,255,255,0.72)';
      nav.style.boxShadow = '0 8px 32px rgba(0,0,0,0.08)';
      nav.style.borderColor = 'rgba(255,255,255,0.3)';
    } else {
      nav.style.background = 'rgba(255,255,255,0.45)';
      nav.style.boxShadow = '0 4px 16px rgba(0,0,0,0.05)';
      nav.style.borderColor = 'rgba(255,255,255,0.2)';
    }
  });

  // --- Mobile nav toggle ---
  var toggle = document.getElementById('nav-toggle');
  var mobileNav = document.getElementById('nav-mobile');
  if (toggle && mobileNav) {
    toggle.addEventListener('click', function () {
      mobileNav.classList.toggle('open');
    });
    mobileNav.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        mobileNav.classList.remove('open');
      });
    });
  }

  // --- Smooth scroll for anchor links ---
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      var target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth' });
      }
    });
  });

  // --- Stat counter animation ---
  var counters = document.querySelectorAll('.counter');
  var animated = false;

  function animateCounters() {
    if (animated) return;
    animated = true;
    counters.forEach(function (counter) {
      var target = parseInt(counter.getAttribute('data-target'), 10);
      if (isNaN(target)) return;
      var startTime = null;
      function step(timestamp) {
        if (!startTime) startTime = timestamp;
        var progress = Math.min((timestamp - startTime) / 1500, 1);
        var eased = 1 - (1 - progress) * (1 - progress);
        counter.textContent = Math.round(eased * target);
        if (progress < 1) {
          requestAnimationFrame(step);
        } else {
          counter.textContent = target;
        }
      }
      requestAnimationFrame(step);
    });
  }

  var statsSection = document.getElementById('stats');
  if (statsSection && 'IntersectionObserver' in window) {
    var statsObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCounters();
          statsObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.3 });
    statsObserver.observe(statsSection);
  } else {
    animateCounters();
  }

  // --- Scroll-triggered fade-in ---
  var fadeEls = document.querySelectorAll('.fade-up');
  if (fadeEls.length && 'IntersectionObserver' in window) {
    var fadeObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          fadeObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    fadeEls.forEach(function (el) { fadeObserver.observe(el); });
  } else {
    fadeEls.forEach(function (el) { el.classList.add('visible'); });
  }

  // --- Copy button ---
  document.querySelectorAll('.code-block-copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var codeBlock = this.closest('.code-block');
      var activeContent = codeBlock.querySelector('.code-tab-content.active code') || codeBlock.querySelector('code');
      if (!activeContent) return;
      navigator.clipboard.writeText(activeContent.textContent).then(function () {
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
        setTimeout(function () {
          btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
        }, 2000);
      });
    });
  });

  // --- Hero code tab switching ---
  var codeTabs = document.querySelectorAll('.code-tab');
  if (codeTabs.length) {
    codeTabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var lang = this.getAttribute('data-lang');
        var block = this.closest('.code-block');
        if (!block) return;
        // Remove active state from all tabs
        block.querySelectorAll('.code-tab').forEach(function (t) {
          t.classList.remove('active');
          t.classList.remove('text-white', 'border-brand-500');
          t.classList.add('text-slate-500', 'border-transparent');
        });
        // Remove active content panels
        block.querySelectorAll('.code-tab-content').forEach(function (p) { p.classList.remove('active'); });
        // Activate clicked tab
        this.classList.add('active');
        this.classList.remove('text-slate-500', 'border-transparent');
        this.classList.add('text-white', 'border-brand-500');
        // Show the matching panel
        var panel = document.getElementById('code-' + lang);
        if (panel) panel.classList.add('active');
      });
    });
  }

  // --- Checkout cancel toast (D024) ---
  // When the user comes back from Stripe Checkout after cancelling,
  // the URL has ?checkout=cancel — show a brief, non-alarming toast.
  (function () {
    var params = new URLSearchParams(window.location.search);
    var checkout = params.get('checkout');
    if (checkout !== 'cancel') return;

    // Clean the URL so refreshing doesn't re-show
    history.replaceState({}, document.title, window.location.pathname);

    var toast = document.createElement('div');
    toast.className = 'checkout-cancel-toast';
    toast.setAttribute('role', 'status');
    toast.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
      '<span>Checkout cancelled — no charges were made.</span>';
    document.body.appendChild(toast);

    // Auto-dismiss after 5 seconds
    setTimeout(function () {
      toast.classList.add('fade-out');
      setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 400);
    }, 5000);
  })();

  // --- Sticky mobile CTA (visible after scrolling past hero) ---
  var stickyCta = document.getElementById('sticky-cta');
  var heroSection = document.querySelector('.hero');
  if (stickyCta && heroSection && 'IntersectionObserver' in window) {
    var stickyObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          stickyCta.classList.remove('visible');
        } else {
          stickyCta.classList.add('visible');
        }
      });
    }, { threshold: 0 });
    stickyObserver.observe(heroSection);
  }

})();
