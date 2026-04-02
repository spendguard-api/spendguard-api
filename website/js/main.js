/* ============================================================
   SpendGuard — Main JavaScript
   Nav, scroll, counters, copy, code tabs, sticky CTA, fade-in
   ============================================================ */

(function () {
  'use strict';

  // --- Nav scroll effect ---
  var nav = document.getElementById('nav');
  window.addEventListener('scroll', function () {
    if (window.scrollY > 10) {
      nav.classList.add('scrolled');
    } else {
      nav.classList.remove('scrolled');
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
  var fadeEls = document.querySelectorAll('.fade-in');
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
        block.querySelectorAll('.code-tab').forEach(function (t) { t.classList.remove('active'); });
        block.querySelectorAll('.code-tab-content').forEach(function (p) { p.classList.remove('active'); });
        this.classList.add('active');
        var panel = document.getElementById('code-' + lang);
        if (panel) panel.classList.add('active');
      });
    });
  }

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
