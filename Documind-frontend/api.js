const API = "http://127.0.0.1:8000";
const API_KEY = "documind-secret-key-32-chars-minimum-token";

async function getJSON(path) {
  const res = await fetch(`${API}${path}`, {
    headers: { "X-API-Key": API_KEY },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function uploadFile(path, file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "X-API-Key": API_KEY },
    body: formData,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function deleteReq(path) {
  const res = await fetch(`${API}${path}`, {
    method: "DELETE",
    headers: { "X-API-Key": API_KEY },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return true;
}

function fmtMs(n) {
  return n != null ? `${n}ms` : "—";
}

function fmtInr(n) {
  return n != null ? `₹${n.toFixed(4)}` : "—";
}

function setStatusDot(el, color, label) {
  if (!el) return;
  el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-${color} inline-block"></span><span class="font-code-sm text-code-sm text-on-surface tracking-wider uppercase">${label}</span>`;
}

function showError(el, msg) {
  setStatusDot(el, "error", msg);
}

document.addEventListener("DOMContentLoaded", () => {
  const pathMap = {
    "architecture": "/stitch_documind_glass_box_ui/code.html",
    "console": "/stitch_documind_glass_box_ui (1)/code.html",
    "proof": "/stitch_documind_glass_box_ui (2)/code.html",
    "library": "/stitch_documind_glass_box_ui (3)/code.html",
    "benchmarks": "/stitch_documind_glass_box_ui (2)/code.html",
    "compliance": "/stitch_documind_glass_box_ui (2)/code.html",
  };
  document.querySelectorAll("[data-path]").forEach((el) => {
    const target = pathMap[el.getAttribute("data-path")];
    if (target) {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        window.location.href = target;
      });
    }
  });
});
