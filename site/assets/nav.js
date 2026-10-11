// Shared header/footer. No trackers, no cookies, no third-party scripts.
(function () {
  const here = location.pathname.split("/").pop() || "index.html";
  const links = [["index.html", "Home"], ["apis.html", "Free APIs"], ["directory.html", "Global directory"], ["grok.html", "Use with Grok"], ["playground.html", "Playground"],
                 ["guide.html", "Run your own robot"], ["https://github.com/fitzyracing1/civicbot", "GitHub"]];
  const h = document.createElement("header"); h.className = "top";
  h.innerHTML = '<div class="in"><b>🤖 civicbot</b><nav>' + links.map(([u, t]) =>
    `<a href="${u}"${u === here ? ' aria-current="page"' : ""}>${t}</a>`).join("") + "</nav></div>";
  document.body.prepend(h);
  const f = document.createElement("footer");
  f.innerHTML = 'civicbot is open source (MIT). Not affiliated with X, any city, or any API provider listed here. ' +
    'This site sets no cookies and loads no analytics or trackers. Data on the directory page was checked live by ' +
    '<a href="https://github.com/fitzyracing1/civicbot/blob/main/scripts/free_apis/verify.py">verify.py</a>.';
  document.body.append(f);
})();
