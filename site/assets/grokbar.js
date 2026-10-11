// "Paste into Grok" copy bars for API cards (apis.html, directory.html). Prompts are generated at build time
// (grok_prompt / grok_prompt_template fields); the optional place box (#gplace) fills {place} where an API supports it.
(function () {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const KEY = "civicbot-place";
  let MAP = {};
  const box = () => document.getElementById("gplace");
  const place = () => ((box() && box().value) || "").trim();
  window.grokPrompt = a => {
    const m = Object.assign({}, MAP[a.id] || {}, a.grok_prompt ? {grok_prompt: a.grok_prompt, grok_prompt_template: a.grok_prompt_template} : {});
    return m.grok_prompt_template && place() ? m.grok_prompt_template.split("{place}").join(place()) : (m.grok_prompt || "");
  };
  window.grokBar = a => {
    const p = window.grokPrompt(a);
    return p ? `<div class="gbar"><span class="glabel">Paste into Grok</span><button type="button" class="gcopy" ` +
      `aria-label="Copy the Grok prompt for ${esc(a.name)}">Copy</button><span class="gtext">${esc(p)}</span></div>` : "";
  };
  async function copy(text, btn) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) { const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select();
      document.execCommand("copy"); t.remove(); }
    const old = btn.textContent; btn.textContent = "Copied ✓"; setTimeout(() => (btn.textContent = old), 1500);
  }
  document.addEventListener("click", e => {
    const b = e.target.closest(".gbar .gcopy"); if (!b) return;
    copy(b.parentElement.querySelector(".gtext").textContent, b);
  });
  const rerender = () => { const q = document.getElementById("q"); if (q) q.dispatchEvent(new Event("input")); };
  document.addEventListener("DOMContentLoaded", () => {
    const b = box(); if (!b) return;
    try { b.value = localStorage.getItem(KEY) || ""; } catch (e) { /* storage off */ }
    b.addEventListener("input", () => { try { localStorage.setItem(KEY, b.value.trim()); } catch (e) { /* ignore */ } rerender(); });
  });
  if (document.currentScript && document.currentScript.dataset.prompts) {
    fetch(document.currentScript.dataset.prompts).then(r => r.json()).then(d => { MAP = d.prompts || {}; rerender(); }).catch(() => {});
  }
})();
