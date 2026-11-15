/**
 * The floor's artwork layer — a hand-plotted pixel scene behind the bots.
 *
 * Skin only: this never touches #opsStage's children, their positions or any
 * JS that drives them. The canvas is PREPENDED, so every later sibling (wall
 * strip, shade, stations, bots) keeps painting above it in DOM order without a
 * single z-index change. Delete this script and the floor falls back to the
 * CSS background it had before.
 *
 * The scene is drawn at 232x100 logical pixels and scaled with `cover`, so a
 * wide room crops vertically and a tall one crops horizontally rather than
 * shearing every rectangle in the picture.
 */
(function () {
  const W = 232;
  const H = 100;
  const FLOOR = 72;

  const P = {
    wall: '#2a0a13', wallD: '#330d18',
    frame: '#c8a15a', frameDark: '#2a0a12',
    sky: ['#57101e', '#701524', '#8d1b29', '#aa2630', '#c73c32', '#df6a3c', '#eb9a58'],
    sun: '#f7dc9a', sunCore: '#fff8e6',
    hill: '#2a0812', hill2: '#1b050c',
    floor: '#210a10', plank: '#2c0d14', seam: '#12050a',
    poolL: '#9c2a2f',
    desk: '#3d1622', deskTop: '#5f2431',
    leaf: '#2f5a3a', leafL: '#4d8452', pot: '#7d2434', potL: '#b04628',
    gold: '#c8a15a', bright: '#e8cb8e', lamp: '#fff3cc', paper: '#e8dfc9'
  };

  let seed = 20261115;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };

  const room = document.getElementById('opsStage') || document.querySelector('.room');
  if (!room) return;

  const canvas = document.createElement('canvas');
  canvas.id = 'floorArt';
  canvas.setAttribute('aria-hidden', 'true');
  room.insertBefore(canvas, room.firstChild);

  const ctx = canvas.getContext('2d');
  let art = null;          // offscreen 232x100 scene, drawn once
  let lastW = 0;
  let lastH = 0;

  function px(c, x, y, w, h, col) {
    c.fillStyle = col;
    c.fillRect(x | 0, y | 0, w | 0, h | 0);
  }

  function dither(c, x, y, w, h, a, b, step) {
    for (let j = 0; j < h; j++) {
      for (let i = 0; i < w; i++) {
        px(c, x + i, y + j, 1, 1, ((i + j) % step === 0) ? a : b);
      }
    }
  }

  function drawWindow(c, x, y, w, h) {
    px(c, x - 3, y - 3, w + 6, h + 6, P.frameDark);
    px(c, x - 2, y - 2, w + 4, h + 4, P.frame);
    const bh = Math.ceil(h / P.sky.length);
    P.sky.forEach((col, i) => px(c, x, y + i * bh, w, Math.min(bh, h - i * bh), col));

    const sx = x + Math.round(w * 0.62);
    const sy = y + h - 20;
    for (let r = 11; r >= 1; r--) {
      c.globalAlpha = 0.055 + (11 - r) * 0.055;
      c.beginPath();
      c.arc(sx, sy, r, 0, Math.PI * 2);
      c.fillStyle = P.sun;
      c.fill();
    }
    c.globalAlpha = 1;
    px(c, sx - 2, sy - 2, 5, 5, P.sunCore);

    for (let i = 0; i < w; i++) {
      const hh = Math.round(8 + Math.sin(i / 11) * 3.4 + Math.sin(i / 27) * 2.6);
      px(c, x + i, y + h - hh, 1, hh, P.hill);
      px(c, x + i, y + h - hh + 1, 1, hh - 1, P.hill2);
    }

    c.globalAlpha = 0.09;
    for (let i = 0; i < 6; i++) px(c, x + 5 + i * 13, y + 2, 2, h - 4, '#fff');
    c.globalAlpha = 1;

    px(c, x + Math.floor(w / 2), y, 2, h, P.frame);
    px(c, x, y + Math.floor(h * 0.58), w, 2, P.frame);
    px(c, x - 4, y + h + 2, w + 8, 3, P.frame);
    px(c, x - 4, y + h + 5, w + 8, 1, P.frameDark);
  }

  function drawShelf(c, x, y) {
    px(c, x, y, 18, FLOOR - y, '#2b0d15');
    px(c, x, y, 18, 2, '#3d1420');
    for (let sy = y + 18; sy < FLOOR - 18; sy += 18) px(c, x, sy, 18, 2, '#3d1420');
    const spines = ['#a8402a', '#7a2333', '#c8a15a', '#8e2230', '#5d2340', '#a8402a'];
    for (let sy = y + 6; sy < FLOOR - 18; sy += 18) {
      let bx = x + 2;
      spines.forEach((col, i) => {
        const wd = 2 + (i % 2);
        px(c, bx, sy + (i % 3), wd, 11 - (i % 3), col);
        bx += wd + 1;
      });
    }
  }

  function drawPlant(c, x, y) {
    px(c, x, y + 14, 13, 10, P.pot);
    px(c, x, y + 14, 13, 2, P.potL);
    px(c, x + 1, y + 12, 11, 3, P.potL);
    [[4, 7], [-2, 2], [8, 0], [2, 4], [10, 5], [-4, 8]].forEach(([dx, dy], i) => {
      px(c, x + 6 + dx, y + dy, 4, 3, i % 2 ? P.leafL : P.leaf);
      px(c, x + 6 + dx + 1, y + dy - 1, 2, 1, P.leafL);
    });
    px(c, x + 6, y - 2, 1, 15, P.leaf);
  }

  function drawDesk(c, x, y) {
    px(c, x + 3, y + 4, 3, FLOOR - y - 4, P.desk);
    px(c, x + 62, y + 4, 3, FLOOR - y - 4, P.desk);
    px(c, x, y, 68, 3, P.deskTop);
    px(c, x, y + 3, 68, 3, P.desk);
    px(c, x, y, 68, 1, '#7a3140');
    px(c, x + 40, y + 6, 22, 9, P.desk);
    px(c, x + 30, y - 3, 4, 4, P.frame);
    px(c, x + 31, y - 16, 2, 13, '#8a6a3c');
    px(c, x + 25, y - 22, 14, 7, P.frame);
    px(c, x + 27, y - 20, 10, 4, P.lamp);
    c.globalAlpha = 0.16;
    c.beginPath();
    c.arc(x + 32, y - 8, 20, 0, Math.PI * 2);
    c.fillStyle = P.sun;
    c.fill();
    c.globalAlpha = 1;
    px(c, x + 8, y - 3, 16, 3, P.paper);
    px(c, x + 10, y - 2, 12, 1, '#b9a892');
    px(c, x + 46, y - 5, 5, 6, '#a8402a');
  }

  function drawFiligree(c) {
    // The velvet reference's gold corner curls, plotted rather than stroked so
    // they keep the same pixel grain as everything else in the room.
    const curl = (cx, cy, fx, fy) => {
      c.globalAlpha = 0.75;
      c.strokeStyle = P.gold;
      c.lineWidth = 1;
      c.beginPath();
      c.moveTo(cx, cy + fy * 22);
      c.quadraticCurveTo(cx + fx * 1, cy + fy * 6, cx + fx * 20, cy + fy * 2);
      c.stroke();
      c.beginPath();
      c.moveTo(cx + fx * 4, cy + fy * 22);
      c.quadraticCurveTo(cx + fx * 5, cy + fy * 12, cx + fx * 24, cy + fy * 8);
      c.stroke();
      c.fillStyle = P.bright;
      c.fillRect(cx + fx * 20 - 1, cy + fy * 2 - 1, 2, 2);
      c.globalAlpha = 1;
    };
    curl(4, 4, 1, 1);
    curl(W - 4, 4, -1, 1);
    curl(4, H - 4, 1, -1);
    curl(W - 4, H - 4, -1, -1);
  }

  function buildArt() {
    art = document.createElement('canvas');
    art.width = W;
    art.height = H;
    const c = art.getContext('2d');
    c.imageSmoothingEnabled = false;

    // wall
    px(c, 0, 0, W, FLOOR, P.wall);
    dither(c, 0, 0, W, FLOOR, P.wallD, P.wall, 3);
    for (let i = 0; i < 30; i++) {
      c.globalAlpha = 0.14 - i * 0.004;
      px(c, 16 - i, 6, 2, 62, '#c2412f');
      px(c, 106 + i, 6, 2, 62, '#a8332c');
    }
    c.globalAlpha = 1;
    for (let x = 0; x < W; x += 44) px(c, x, 0, 1, FLOOR, '#160409');
    px(c, 0, FLOOR - 4, W, 4, '#2b0c14');
    px(c, 0, FLOOR - 4, W, 1, '#3a1220');

    drawShelf(c, 1, 16);
    drawWindow(c, 26, 8, 82, 50);

    // floor
    px(c, 0, FLOOR, W, H - FLOOR, P.floor);
    for (let y = FLOOR; y < H; y += 4) {
      px(c, 0, y, W, 1, P.plank);
      for (let x = (y * 7) % 30; x < W; x += 30) px(c, x, y + 1, 1, 3, P.seam);
    }
    for (let i = 0; i < 12; i++) {
      c.globalAlpha = 0.22 - i * 0.016;
      px(c, 26 + i * 4, 76 + i, 96 - i * 6, 3, P.poolL);
    }
    c.globalAlpha = 1;

    // light shaft from the window onto the boards
    c.save();
    c.globalAlpha = 0.13;
    c.beginPath();
    c.moveTo(32, 58);
    c.lineTo(102, 58);
    c.lineTo(150, H - 4);
    c.lineTo(18, H - 4);
    c.closePath();
    c.fillStyle = '#efa95f';
    c.fill();
    c.restore();

    drawPlant(c, 128, 56);
    drawDesk(c, 152, 52);

    for (let i = 0; i < 60; i++) {
      c.globalAlpha = 0.2 + rnd() * 0.5;
      px(c, 28 + rnd() * 78, 12 + rnd() * 56, 1, 1, '#f5d78f');
    }
    c.globalAlpha = 1;

    // slats — the reference's venetian layer, kept faint so the room reads
    c.globalAlpha = 0.13;
    for (let x = 0; x < W; x += 7) px(c, x, 0, 2, H, '#0b0708');
    c.globalAlpha = 1;

    drawFiligree(c);

    // vignette so the UI text over the floor stays readable
    const g = c.createRadialGradient(W / 2, H * 0.44, 30, W / 2, H * 0.5, W * 0.78);
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(1, 'rgba(0,0,0,.72)');
    c.fillStyle = g;
    c.fillRect(0, 0, W, H);
  }

  function paint() {
    const w = room.clientWidth;
    const h = room.clientHeight;
    if (!w || !h) return;
    if (w === lastW && h === lastH) return;
    lastW = w;
    lastH = h;

    canvas.width = w;
    canvas.height = h;
    if (!art) buildArt();

    // Fit the WIDTH and anchor the floor to the bottom edge. A tall panel can
    // never show a 232x100 scene whole under `cover` (it would crop to one
    // window), so the wall is extended upward instead and the join is dithered
    // to match. One uniform scale either way: no rectangle is ever sheared.
    const scale = w / W;
    const dw = w;
    const dh = H * scale;
    const top = h - dh;
    const left = 0;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = '#14080c';
    ctx.fillRect(0, 0, w, h);

    if (top > 0) {
      const wall = ctx.createLinearGradient(0, 0, 0, top);
      wall.addColorStop(0, '#1e0810');
      wall.addColorStop(1, P.wall);
      ctx.fillStyle = wall;
      ctx.fillRect(0, 0, w, top);
      // the same dither + panel seams the art uses, so the join is invisible
      ctx.globalAlpha = 0.5;
      const step = Math.max(2, Math.round(scale * 3));
      for (let y = 0; y < top; y += step) {
        for (let x = (y / step) % 2 ? 0 : step; x < w; x += step * 2) {
          ctx.fillStyle = P.wallD;
          ctx.fillRect(x, y, step, step);
        }
      }
      ctx.globalAlpha = 0.6;
      ctx.fillStyle = '#160409';
      for (let x = 0; x < w; x += Math.round(scale * 44)) ctx.fillRect(x, 0, 1, top);
      ctx.globalAlpha = 1;
    }

    ctx.drawImage(art, left, top, dw, dh);
  }

  paint();
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(paint).observe(room);
  } else {
    window.addEventListener('resize', paint);
  }
})();
