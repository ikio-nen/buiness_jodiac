/* ═══════════════════════════════════════════════════════════════════
   DOT-MATRIX SHELL — additive only.

   The skin itself is dotmatrix.css. This module adds the one behaviour the
   skin needs: while the office is working (the activity strip says anything
   other than "idle"), a dot grid pulses beside the line. It reads the DOM that
   app.js owns and never writes app.js state, so deleting the <script> tag in
   index.html leaves the app exactly as it was.
   ═══════════════════════════════════════════════════════════════════ */

import { dotLoader } from './dotmatrix-loader.js?v=1';

const IDLE = /office idle/i;

function attach() {
  const strip = document.getElementById('activityStrip');
  if (!strip) return;

  const sync = () => {
    const text = strip.textContent || '';
    const busy = text.trim() && !IDLE.test(text);
    const existing = strip.querySelector('.dm-loader');
    if (busy && !existing) {
      // The strip is already an aria-live region, so the loader is decorative
      // to a screen reader: the line beside it carries the meaning.
      const loader = dotLoader({ size: 3, label: 'Working' });
      loader.setAttribute('aria-hidden', 'true');
      strip.prepend(loader);
    } else if (!busy && existing) {
      existing.remove();
    }
  };

  // childList + characterData covers both a re-render and a text-only update.
  new MutationObserver(sync).observe(strip, {
    childList: true, characterData: true, subtree: true,
  });
  sync();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', attach, { once: true });
} else {
  attach();
}
