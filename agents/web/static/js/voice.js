/* Dictation (browser speech recognition; no service, no dependency).

   Owns the recognizer and its listening state outright — the composer only
   hands over the input element to dictate into. Where the browser has no
   SpeechRecognition (anything but Chrome/Edge) the button is disabled with a
   reason in its tooltip rather than failing when pressed. */

export function initDictation({ input, setActivity }) {
  const voiceBtn = document.getElementById('voiceBtn');
  if (!voiceBtn) return;

  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    voiceBtn.disabled = true;
    voiceBtn.title = 'Dictation needs Chrome or Edge';
    return;
  }

  let recognizer = null;
  let listening = false;
  let speechBase = '';

  voiceBtn.addEventListener('click', () => {
    if (listening) { recognizer.stop(); return; }
    recognizer = new SpeechRec();
    recognizer.lang = navigator.language || 'en-IN';
    recognizer.interimResults = true;
    recognizer.continuous = false;
    speechBase = input.value ? input.value.trim() + ' ' : '';

    recognizer.onresult = (ev) => {
      let finalTxt = '', interim = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalTxt += t; else interim += t;
      }
      input.value = speechBase + (finalTxt || interim);
      if (finalTxt) speechBase = input.value + ' ';
    };
    recognizer.onerror = (ev) => {
      listening = false;
      voiceBtn.setAttribute('aria-pressed', 'false');
      setActivity(ev.error === 'not-allowed'
        ? 'Microphone blocked — allow it in the browser to dictate.'
        : `Dictation stopped (${ev.error}).`, '');
    };
    recognizer.onend = () => {
      listening = false;
      voiceBtn.setAttribute('aria-pressed', 'false');
      input.focus();
    };
    try {
      recognizer.start();
      listening = true;
      voiceBtn.setAttribute('aria-pressed', 'true');
      setActivity('Listening… speak, then it drops into the box', 'busy');
    } catch (e) {
      setActivity('Could not start dictation.', '');
    }
  });
}
