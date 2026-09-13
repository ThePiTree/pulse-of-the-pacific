// Google Analytics 4 initialization for Pulse of the Pacific (elninotracker.org).
// The gtag.js loader tag lives in index.html's <head>; this file only wires up
// dataLayer + the config call, kept external so the site's CSP never needs
// 'unsafe-inline' for scripts.
//
// Measurement ID: G-3PBQEZBPZ9
// Per the Search Visibility, Creator Attribution & Analytics Standard:
//   - no PII in event parameters (names, emails, precise location, message contents)
//   - production-only: this file is only referenced from the deployed public/ tree,
//     so local `python -m http.server` / `npx serve` previews still fire test hits
//     against the real property unless you strip the <script> tags locally first.
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }
gtag('js', new Date());
gtag('config', 'G-3PBQEZBPZ9');

// --- Key events (Section 17-19 of the standard: snake_case, meaning not UI) ---
// Wired to existing interactive elements already in index.html / app.js.
// These are intentionally coarse-grained; extend as real usage patterns emerge.
document.addEventListener('DOMContentLoaded', function () {
  var rangeSeg = document.getElementById('rangeSeg');
  if (rangeSeg) {
    rangeSeg.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-range]');
      if (btn) gtag('event', 'timeline_range_changed', { range: btn.dataset.range });
    });
  }

  var idxSeg = document.getElementById('idxSeg');
  if (idxSeg) {
    idxSeg.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-idx]');
      if (btn) gtag('event', 'index_overlay_toggled', { index: btn.dataset.idx });
    });
  }

  var impactSvg = document.getElementById('impactSvg');
  if (impactSvg) {
    impactSvg.addEventListener('click', function () {
      gtag('event', 'region_selected');
    });
  }

  document.querySelectorAll('a[target="_blank"][rel~="noopener"]').forEach(function (a) {
    a.addEventListener('click', function () {
      gtag('event', 'official_source_clicked', { destination: a.hostname });
    });
  });
});
