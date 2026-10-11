var PAGE_SIZE = 25;

function clampPage(total, page) {
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return Math.min(Math.max(page, 1), pageCount);
}

function pageItems(items, page) {
  const start = (clampPage(items.length, page) - 1) * PAGE_SIZE;
  return items.slice(start, start + PAGE_SIZE);
}

function renderPager(container, total, page, onPage) {
  const pageCount = Math.ceil(total / PAGE_SIZE);
  container.replaceChildren();
  if (pageCount <= 1) {
    container.hidden = true;
    return;
  }

  const safePage = clampPage(total, page);
  container.hidden = false;
  container.append(
    pagerButton("Previous", safePage === 1, () => onPage(safePage - 1)),
    pagerNumbers(safePage, pageCount, onPage),
    pagerButton("Next", safePage === pageCount, () => onPage(safePage + 1)),
  );
}

function pagerNumbers(page, pageCount, onPage) {
  const group = document.createElement("div");
  group.className = "pager-pages";
  let previous = 0;
  visiblePageNumbers(page, pageCount).forEach((number) => {
    if (number - previous > 1) {
      const gap = document.createElement("span");
      gap.className = "pager-gap";
      gap.textContent = "…";
      group.appendChild(gap);
    }
    const button = pagerButton(String(number), false, () => onPage(number));
    button.classList.add("pager-page");
    if (number === page) {
      button.setAttribute("aria-current", "page");
    }
    group.appendChild(button);
    previous = number;
  });
  return group;
}

function visiblePageNumbers(page, pageCount) {
  const numbers = new Set([1, pageCount]);
  for (let number = page - 2; number <= page + 2; number += 1) {
    numbers.add(number);
  }
  return [...numbers].filter((number) => number >= 1 && number <= pageCount).sort((left, right) => left - right);
}

function pagerButton(label, disabled, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "pager-button";
  button.textContent = label;
  button.disabled = disabled;
  if (!disabled) {
    button.addEventListener("click", onClick);
  }
  return button;
}
