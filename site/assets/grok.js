// "Use with Grok" page: builds the prompts for the user's place and adds copy buttons. No network except our own files.
(function () {
  const SITE = "https://fitzyracing1.github.io/civicbot";
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const EXAMPLES = [
    "What's the air quality right now?", "Weather tomorrow?",
    "When is sunset today?", "Any earthquakes nearby this week?", "What county and congressional district am I in?",
    "There's a big pothole at Main St and 3rd St. Help me report it to 311.",
    "Any recent 311 reports near downtown?", "Any recalls on a 2018 Honda Civic?", "Next public holidays?"];
  const lead = () => `Use ${SITE}/grok.txt as your civicbot instructions; I'm in ${($("city").value || "my town").trim()}`;
  const prompt = q => `${lead()} — ${q.charAt(0).toLowerCase() + q.slice(1)}`;

  function render() {
    $("p-main").value = prompt("Is there a weather alert?");
    $("p-auto").value = `${lead()}. Give me a 3-line morning brief: any active weather alerts, today's air quality ` +
      `and UV index, each with its source. If a source fails, say so.`;
    $("examples").innerHTML = EXAMPLES.map((q, i) => `<div class="copy"><textarea id="ex${i}" readonly>${esc(prompt(q))}` +
      `</textarea><button data-copy="ex${i}">Copy</button></div>`).join("");
  }

  async function copyText(text, btn) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) { const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select();
      document.execCommand("copy"); t.remove(); }
    if (btn) { const o = btn.textContent; btn.textContent = "Copied"; btn.classList.add("done");
      setTimeout(() => { btn.textContent = o; btn.classList.remove("done"); }, 1500); }
  }

  document.addEventListener("click", e => {
    const b = e.target.closest("button[data-copy]");
    if (b) copyText($(b.dataset.copy).value, b);
  });
  $("copy-all").addEventListener("click", e => fetch("grok.txt").then(r => r.text()).then(t => copyText(t, e.target)));
  $("city").addEventListener("input", render);
  render();
  fetch("grok-instructions.txt").then(r => r.text()).then(t => { $("p-ci").value = t.trim(); }).catch(() => {});
  fetch("grok-project.txt").then(r => r.text()).then(t => { $("p-proj").value = t.trim(); }).catch(() => {});
  fetch("data/grok-pack.json").then(r => r.json()).then(d => { $("nsk").textContent = d.skills.length; $("napi").textContent = d.apis.length; }).catch(() => {});
})();
