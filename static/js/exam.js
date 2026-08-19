(function () {
  const root = document.getElementById("examRoot");
  const sessionId = Number(root.dataset.sessionId);
  const durationSeconds = Number(root.dataset.duration);

  const video = document.getElementById("proctorVideo");
  const canvas = document.getElementById("captureCanvas");
  const cameraBadge = document.getElementById("cameraBadge");
  const clockRing = document.getElementById("clockRing");
  const clockProgress = document.getElementById("clockProgress");
  const clockLabel = document.getElementById("clockLabel");
  const toastStack = document.getElementById("toastStack");
  const violationTally = document.getElementById("violationTally");
  const submitBtn = document.getElementById("submitExamBtn");
  const examForm = document.getElementById("examForm");

  const FRAME_INTERVAL_MS = 4000;
  const AUDIO_CHECK_MS = 300;
  const AUDIO_THRESHOLD = 0.09; // RMS 0..1, tune per mic/environment
  const EVENT_THROTTLE_MS = { tab_switch: 3000, window_blur: 3000, audio_spike: 8000 };

  const VIOLATION_META = {
    no_face: { label: "Face not visible", severity: "warn" },
    multiple_faces: { label: "Multiple people detected", severity: "flag" },
    identity_mismatch: { label: "Identity mismatch", severity: "flag" },
    tab_switch: { label: "Switched tabs", severity: "flag" },
    window_blur: { label: "Left exam window", severity: "warn" },
    audio_spike: { label: "Excess background noise", severity: "warn" },
  };

  const CIRCUMFERENCE = 2 * Math.PI * 36;
  let remainingSeconds = durationSeconds;
  let submitted = false;
  let stream = null;
  const lastEventSent = {};

  // ---------------------------------------------------------- utilities --

  function showToast(type) {
    const meta = VIOLATION_META[type] || { label: type, severity: "warn" };
    const el = document.createElement("div");
    el.className = "toast " + (meta.severity === "warn" ? "warn" : "");
    const ts = new Date().toLocaleTimeString([], { hour12: false });
    el.innerHTML = `<div>${meta.label}</div><div style="opacity:.6; margin-top:2px;">${ts}</div>`;
    toastStack.appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  function updateTally(counts) {
    const total = Object.values(counts || {}).reduce((a, b) => a + b, 0);
    violationTally.innerHTML = `<strong>${total}</strong> flag${total === 1 ? "" : "s"} logged this session`;
  }

  function setCameraStatus(status) {
    cameraBadge.classList.remove("is-verified", "is-flagged");
    if (status === "verified") cameraBadge.classList.add("is-verified");
    if (status === "flagged") cameraBadge.classList.add("is-flagged");
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { ok: res.ok, data: await res.json() };
  }

  function logEvent(type, detail) {
    const now = Date.now();
    const throttle = EVENT_THROTTLE_MS[type] || 3000;
    if (lastEventSent[type] && now - lastEventSent[type] < throttle) return;
    lastEventSent[type] = now;
    postJSON("/api/proctor/event", { session_id: sessionId, type, detail }).then(({ data }) => {
      if (data && data.counts) updateTally(data.counts);
      if (!(data && data.throttled)) showToast(type);
    });
  }

  // ------------------------------------------------------------ camera ---

  async function setupCamera() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240 },
        audio: true,
      });
      video.srcObject = stream;
      startFrameLoop();
      startAudioLoop();
    } catch (err) {
      showToast("no_face");
      console.error("Camera/mic access failed:", err);
    }
  }

  function startFrameLoop() {
    setInterval(async () => {
      if (submitted || !video.videoWidth) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.7);

      const { ok, data } = await postJSON("/api/proctor/frame", {
        session_id: sessionId,
        image: dataUrl,
      });
      if (!ok) return;

      if (data.violation_type) {
        setCameraStatus("flagged");
        showToast(data.violation_type);
      } else {
        setCameraStatus("verified");
      }
      updateTally(data.counts);
    }, FRAME_INTERVAL_MS);
  }

  function startAudioLoop() {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const buffer = new Uint8Array(analyser.fftSize);

    setInterval(() => {
      if (submitted) return;
      analyser.getByteTimeDomainData(buffer);
      let sumSquares = 0;
      for (let i = 0; i < buffer.length; i++) {
        const normalized = (buffer[i] - 128) / 128;
        sumSquares += normalized * normalized;
      }
      const rms = Math.sqrt(sumSquares / buffer.length);
      if (rms > AUDIO_THRESHOLD) {
        logEvent("audio_spike", `rms=${rms.toFixed(3)}`);
      }
    }, AUDIO_CHECK_MS);
  }

  // -------------------------------------------------------- focus events -

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && !submitted) logEvent("tab_switch");
  });
  window.addEventListener("blur", () => {
    if (!submitted) logEvent("window_blur");
  });

  // -------------------------------------------------------------- timer --

  function formatTime(totalSeconds) {
    const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
    const s = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  }

  function tickTimer() {
    clockLabel.textContent = formatTime(remainingSeconds);
    const fraction = Math.max(0, remainingSeconds / durationSeconds);
    clockProgress.style.strokeDashoffset = String(CIRCUMFERENCE * (1 - fraction));
    clockRing.classList.toggle("is-low", remainingSeconds <= 60);

    if (remainingSeconds <= 0) {
      submitExam(true);
      return;
    }
    remainingSeconds -= 1;
    setTimeout(tickTimer, 1000);
  }

  // ----------------------------------------------------------- submit ----

  function collectAnswers() {
    const answers = {};
    const formData = new FormData(examForm);
    for (const [key, value] of formData.entries()) {
      if (key.startsWith("q_")) answers[key.slice(2)] = value;
    }
    return answers;
  }

  async function submitExam(auto) {
    if (submitted) return;
    submitted = true;
    submitBtn.disabled = true;
    submitBtn.textContent = auto ? "Time's up — submitting…" : "Submitting…";

    const { data } = await postJSON(`/api/exam/${sessionId}/submit`, {
      answers: collectAnswers(),
    });

    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (data && data.redirect) {
      window.location.href = data.redirect;
    }
  }

  submitBtn.addEventListener("click", () => submitExam(false));

  // ------------------------------------------------------------- start --

  setupCamera();
  tickTimer();
})();
