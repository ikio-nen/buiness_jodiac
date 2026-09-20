/* Music corner — a tiny generative lo-fi player.

   WebAudio synthesizes everything live (no files, no streaming). Three
   stations, one engine, and all of its state (context, scheduler, current
   station) is private to this module: the rest of the office only needs to
   start it once at init. It takes vtSwap because opening the corner is a
   view transition like any other panel. */

export function initMusicCorner({ vtSwap }) {
  let ctx = null;
  let master = null;
  let playing = false;
  let station = 'lofi';
  let schedulerTimer = null;
  let nextTime = 0;   // when the next scheduled step plays (AudioContext time)
  let step = 0;

  const STATIONS = {
    lofi:  { name: 'lo-fi office',   desc: 'warm tape hiss · soft keys',      bpm: 72,  root: 220, wave: 'triangle' },
    rain:  { name: 'monsoon rain',   desc: 'filtered noise · far thunder',    bpm: 60,  root: 174, wave: 'sine' },
    night: { name: 'midnight synth', desc: 'slow pads · deep pulse',          bpm: 50,  root: 130.8, wave: 'sawtooth' },
  };

  // Simple pentatonic palette per station — safe, always consonant.
  const SCALES = {
    lofi:  [0, 3, 5, 7, 10, 12],
    rain:  [0, 2, 5, 7, 9, 12],
    night: [0, 3, 7, 10, 12, 15],
  };

  function ensureCtx() {
    if (ctx) return;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    master = ctx.createGain();
    master.gain.value = (document.getElementById('musicVol')?.value || 35) / 100 * 0.5;
    master.connect(ctx.destination);
  }

  function noteFreq(root, semis) { return root * Math.pow(2, semis / 12); }

  function playTone(freq, t, dur, gainVal, type) {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(gainVal, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g).connect(master);
    osc.start(t); osc.stop(t + dur + 0.05);
  }

  function playNoise(t, dur, gainVal, filterFreq) {
    const len = Math.max(1, Math.floor(ctx.sampleRate * dur));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const filt = ctx.createBiquadFilter();
    filt.type = 'lowpass';
    filt.frequency.value = filterFreq;
    const g = ctx.createGain();
    g.gain.setValueAtTime(gainVal, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(filt).connect(g).connect(master);
    src.start(t); src.stop(t + dur);
  }

  function scheduleStep(t) {
    const st = STATIONS[station];
    const scale = SCALES[station];
    const beat = 60 / st.bpm;
    // Bass every 4 steps, melody sparkle probabilistically, hats quietly.
    if (step % 4 === 0) {
      playTone(st.root / 2, t, beat * 3.4, 0.16, st.wave);
    }
    if (Math.random() < 0.62) {
      const semi = scale[Math.floor(Math.random() * scale.length)];
      playTone(noteFreq(st.root, semi + 12), t, beat * 1.1, 0.07, station === 'night' ? 'sine' : 'triangle');
    }
    if (station === 'rain') {
      // Continuous-ish rain bed + occasional thunder rumble.
      playNoise(t, beat * 0.9, 0.045, 1600);
      if (Math.random() < 0.05) playNoise(t, beat * 4, 0.09, 220);
    } else if (step % 2 === 1) {
      playNoise(t, 0.05, 0.02, 6000); // soft hat
    }
    if (station === 'night' && step % 8 === 0) {
      playTone(st.root / 4, t, beat * 7, 0.1, 'sine');
    }
    step++;
  }

  function scheduler() {
    const st = STATIONS[station];
    const beat = 60 / st.bpm;
    if (!nextTime) nextTime = ctx.currentTime + 0.06;
    // Look-ahead scheduling: fill the next 120ms with steps.
    while (nextTime < ctx.currentTime + 0.12) {
      scheduleStep(nextTime);
      nextTime += beat / 2;
    }
  }

  function start() {
    ensureCtx();
    if (ctx.state === 'suspended') ctx.resume();
    playing = true;
    nextTime = 0;
    schedulerTimer = setInterval(scheduler, 90);
    updateUI();
  }

  function stop() {
    playing = false;
    if (schedulerTimer) { clearInterval(schedulerTimer); schedulerTimer = null; }
    updateUI();
  }

  function setStation(key) {
    station = key;
    step = 0;
    updateUI();
  }

  function setVolume(v) {
    if (master) master.gain.value = (v / 100) * 0.5;
  }

  function updateUI() {
    const st = STATIONS[station];
    document.getElementById('musicStation').textContent = st.name;
    document.getElementById('musicDesc').textContent = st.desc;
    const play = document.getElementById('musicPlay');
    play.textContent = playing ? '⏸' : '▶';
    document.getElementById('vinyl').classList.toggle('spin', playing);
    document.querySelectorAll('.station-btn').forEach(b =>
      b.classList.toggle('is-active', b.dataset.station === station));
  }

  // Wiring
  document.getElementById('musicBtn')?.addEventListener('click', () => {
    const corner = document.getElementById('musicCorner');
    vtSwap(corner.classList.contains('open') ? null : corner, [corner]);
  });
  document.getElementById('closeMusic')?.addEventListener('click', () =>
    document.getElementById('musicCorner').classList.remove('open'));
  document.getElementById('musicPlay')?.addEventListener('click', () =>
    playing ? stop() : start());
  document.getElementById('musicVol')?.addEventListener('input', (e) => setVolume(+e.target.value));
  document.querySelectorAll('.station-btn').forEach(b =>
    b.addEventListener('click', () => setStation(b.dataset.station)));

  return { start, stop, setStation };
}
