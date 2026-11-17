// Zero-build dot loader. Usage: import { dotLoader } from './dotmatrix-loader.js?v=1';
// parent.append(dotLoader()); parent.append(dotLoader({ size: 5, pattern: 'diag' }));
//
// A dot grid that pulses in a calm order. The dots are the loading state, so no
// spinner image, no CSS keyframe soup and nothing to install.
const ORDER = {
  3: {
    row: [0, 1, 2, 3, 4, 5, 6, 7, 8],
    spiral: [0, 1, 2, 5, 8, 7, 6, 3, 4],
    diag: [0, 1, 3, 2, 4, 6, 5, 7, 8],
  },
  5: null,
};

export function dotLoader({ size = 3, pattern = 'spiral', label = 'Working' } = {}) {
  const el = document.createElement('span');
  el.className = 'dm-loader';
  el.dataset.size = String(size);
  el.setAttribute('role', 'status');
  el.setAttribute('aria-label', label);
  const n = size * size;
  const order = (ORDER[size] && (ORDER[size][pattern] || ORDER[size].row))
    || [...Array(n).keys()];
  const delay = new Array(n);
  order.forEach((cell, step) => { delay[cell] = step; });
  for (let i = 0; i < n; i++) {
    const d = document.createElement('i');
    d.style.setProperty('--d', String(delay[i] ?? i));
    el.appendChild(d);
  }
  return el;
}
