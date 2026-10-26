(() => {
  if (!document.body.classList.contains("home") && !document.querySelector(".brand-mark")) {
    const brand = document.createElement("a");
    brand.className = "brand-mark";
    brand.href = "/";
    brand.setAttribute("aria-label", "LoadLine");
    brand.innerHTML = `<svg viewBox="0 0 56 32" aria-hidden="true" focusable="false"><circle cx="28" cy="16" r="11" fill="none" stroke="currentColor" stroke-width="1.75"/><line x1="8" y1="16" x2="48" y2="16" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/></svg>`;
    document.body.prepend(brand);
  }

  const toggle = document.getElementById("menu-toggle");
  const panel = document.getElementById("menu-panel");
  if (!toggle || !panel) return;

  const groups = [
    ["Inventory", [["/organisational-units", "Organisational Units"], ["/software-systems", "Software Systems"], ["/software-components", "Software Components"], ["/business-processes", "Business Processes"]]],
    ["Intelligence", [["/mitre-attack", "MITRE ATT&CK"], ["/vulnerability-database", "Vulnerability Database"], ["/threat-actors", "Threat Actors"], ["/attack-vectors", "Attack Vectors"]]],
    ["Risk Analysis", [["/risk-scenarios", "Risk Scenarios"], ["/control-catalog", "Control Catalog"], ["/scenario-control-mapping", "Scenario-Control Mapping"], ["/risk-register", "Risk Register"], ["/decision-log", "Decision Log"], ["/risk-simulation", "Risk Simulation"]]],
  ];
  panel.replaceChildren();
  const home = document.createElement("li");
  const homeLink = document.createElement("a");
  homeLink.href = "/";
  homeLink.textContent = "Home";
  home.appendChild(homeLink);
  panel.appendChild(home);
  groups.forEach(([label, links]) => {
    const heading = document.createElement("li");
    heading.className = "menu-group";
    heading.textContent = label;
    panel.appendChild(heading);
    links.forEach(([href, text]) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = href;
      link.textContent = text;
      item.appendChild(link);
      panel.appendChild(item);
    });
  });
  const settings = document.createElement("li");
  settings.className = "menu-settings";
  const settingsLink = document.createElement("a");
  settingsLink.href = "/settings";
  settingsLink.textContent = "Settings";
  settings.appendChild(settingsLink);
  panel.appendChild(settings);

  const setOpen = (open) => {
    toggle.setAttribute("aria-expanded", String(open));
    panel.hidden = !open;
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(panel.hidden);
  });

  document.addEventListener("click", (event) => {
    if (!panel.hidden && !panel.contains(event.target)) setOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      setOpen(false);
      toggle.focus();
    }
  });
})();
