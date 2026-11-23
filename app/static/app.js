// Upload: list chosen files. Job page: poll status until done.
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("files");
  const list = document.getElementById("file-list");
  if (input && list) {
    input.addEventListener("change", () => {
      list.textContent = "";
      for (const f of input.files) {
        const li = document.createElement("li");
        li.textContent = `${f.name} (${(f.size / 1048576).toFixed(1)} MB)`;
        list.appendChild(li);
      }
    });
  }
  const form = document.getElementById("upload-form");
  if (form) form.addEventListener("submit", () => {
    const b = form.querySelector("button[type=submit]");
    if (b) { b.disabled = true; b.textContent = "Uploading..."; }
  });
  const prog = document.getElementById("progress");
  if (prog) {
    const id = prog.dataset.job;
    const bar = document.getElementById("bar");
    const step = document.getElementById("step");
    const tick = async () => {
      try {
        const r = await fetch(`/jobs/${id}/status`, { credentials: "same-origin" });
        if (!r.ok) return;
        const s = await r.json();
        step.textContent = s.step || "";
        bar.className = "meter-fill w" + Math.floor((s.progress || 0) / 5) * 5;
        bar.parentElement.setAttribute("aria-valuenow", s.progress || 0);
        if (s.status === "done" || s.status === "failed") { location.reload(); return; }
      } catch (e) { /* retry on next tick */ }
      setTimeout(tick, 3000);
    };
    setTimeout(tick, 2000);
  }
});
