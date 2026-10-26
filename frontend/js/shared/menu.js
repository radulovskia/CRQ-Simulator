(() => {
  const toggle = document.getElementById("menu-toggle");
  const panel = document.getElementById("menu-panel");
  if (!toggle || !panel) return;

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
