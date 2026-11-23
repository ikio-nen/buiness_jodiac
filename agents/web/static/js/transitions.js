/* Native document.startViewTransition, no library (React's <ViewTransition>
   needs canary React; this app is zero-build). Falls back to a plain append
   on unsupported browsers. Only user-meaningful state changes call it: a new
   message/card appearing, a drawer or panel opening — never scroll ticks or
   event spam, which would animate every pipeline frame. */

export const vtSupported = typeof document.startViewTransition === 'function';

// `after` runs once the node is actually in the DOM. The view-transition
// callback is not synchronous, so callers that measure or scroll the new
// content (scroll-to-bottom after a tall result card) must use it instead of
// running straight after vtAppend and measuring the old layout.
export function vtAppend(parent, el, after) {
  if (!vtSupported) {
    parent.appendChild(el);
    if (after) after();
    return;
  }
  document.startViewTransition(() => {
    parent.appendChild(el);
    if (after) after();
  });
}

export function vtSwap(showEl, hideEls) {
  // Apply the class change SYNCHRONOUSLY first, then animate the swap.
  // The DOM must reflect the new state immediately: handlers compute
  // `opening` from these classes, and rapid clicks queue VT callbacks —
  // class changes that only exist inside a transition callback get
  // clobbered by the next transition's snapshot. Classes first, then
  // the transition just re-records the (already correct) state.
  hideEls.forEach(e => { if (e !== showEl) e.classList.remove('open', 'is-active'); });
  if (showEl) showEl.classList.add('open', 'is-active');
  if (vtSupported && document.startViewTransition) {
    try { document.startViewTransition(() => {}); } catch (e) { /* cosmetic only */ }
  }
}
