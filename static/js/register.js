(function () {
  const video = document.getElementById("video");
  const canvas = document.getElementById("canvas");
  const captureBtn = document.getElementById("captureBtn");
  const submitBtn = document.getElementById("submitBtn");
  const thumbStrip = document.getElementById("thumbStrip");
  const captureCount = document.getElementById("captureCount");
  const nameInput = document.getElementById("name");
  const emailInput = document.getElementById("email");
  const formMsg = document.getElementById("formMsg");

  const MIN_CAPTURES = 3;
  const MAX_CAPTURES = 8;
  const captures = [];

  async function setupCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 } });
      video.srcObject = stream;
    } catch (err) {
      formMsg.textContent = "Could not access the camera: " + err.message;
    }
  }

  function updateUI() {
    captureCount.textContent = `${captures.length} captured` + (captures.length < MIN_CAPTURES ? ` (min ${MIN_CAPTURES})` : "");
    thumbStrip.innerHTML = "";
    captures.forEach((dataUrl) => {
      const img = document.createElement("img");
      img.src = dataUrl;
      thumbStrip.appendChild(img);
    });
    captureBtn.disabled = captures.length >= MAX_CAPTURES;
    submitBtn.disabled = captures.length < MIN_CAPTURES || !nameInput.value.trim();
  }

  captureBtn.addEventListener("click", () => {
    if (!video.videoWidth) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    captures.push(canvas.toDataURL("image/jpeg", 0.85));
    updateUI();
  });

  nameInput.addEventListener("input", updateUI);

  submitBtn.addEventListener("click", async () => {
    formMsg.textContent = "";
    submitBtn.disabled = true;
    submitBtn.textContent = "Registering…";
    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: nameInput.value.trim(),
          email: emailInput.value.trim(),
          images: captures,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        formMsg.textContent = data.error || "Registration failed.";
        submitBtn.disabled = false;
        submitBtn.textContent = "Register & continue to exam";
        return;
      }
      if (!data.enrolled) {
        formMsg.textContent = `Only ${data.saved} usable photo(s) — need at least 3 with exactly one clear face. Capture more and resubmit.`;
        submitBtn.disabled = false;
        submitBtn.textContent = "Register & continue to exam";
        return;
      }
      window.location.href = `/exam/${data.student_id}`;
    } catch (err) {
      formMsg.textContent = "Network error: " + err.message;
      submitBtn.disabled = false;
      submitBtn.textContent = "Register & continue to exam";
    }
  });

  setupCamera();
  updateUI();
})();
