const state = { items: [], topic: "all" };

const safe = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const dateLabel = value => new Intl.DateTimeFormat("en-US", {
  weekday: "long", month: "long", day: "numeric", year: "numeric",
  timeZone: "America/Los_Angeles"
}).format(new Date(`${value}T12:00:00-07:00`));

function renderFilters() {
  const filters = document.querySelector("#filters");
  const topics = [...new Set(state.items.flatMap(item => item.topics || item.focus || []))].sort();
  topics.forEach(topic => {
    const button = document.createElement("button");
    button.className = "filter";
    button.type = "button";
    button.dataset.topic = topic;
    button.textContent = topic;
    filters.append(button);
  });
  filters.addEventListener("click", event => {
    const button = event.target.closest("button[data-topic]");
    if (!button) return;
    state.topic = button.dataset.topic;
    filters.querySelectorAll("button").forEach(item => item.classList.toggle("active", item === button));
    renderCards();
  });
}

function cardMarkup(item, index) {
  const topics = item.topics || item.focus || [];
  return `
    <article class="signal-card">
      <div class="card-top">
        <div><div class="creator">${safe(item.creator)}</div><div class="published">${safe(new Date(item.published).toLocaleString("en-US", { timeZone: "America/Los_Angeles", dateStyle: "medium", timeStyle: "short" }))}</div></div>
        <span class="score" title="Editorial score">${safe(item.score ?? "NA")}</span>
      </div>
      <h2>${safe(item.title)}</h2>
      <p class="card-summary">${safe(item.summary)}</p>
      <div class="card-insight">
        <div><strong>Why it matters</strong><p>${safe(item.why_it_matters)}</p></div>
        <div><strong>Try this</strong><p>${safe(item.try_this)}</p></div>
      </div>
      <div class="card-footer">
        <div class="topics">${topics.map(topic => `<span class="topic">${safe(topic)}</span>`).join("")}</div>
        <a class="source-link" href="${safe(item.source)}" target="_blank" rel="noopener noreferrer">Open source</a>
      </div>
    </article>`;
}

function renderCards() {
  const grid = document.querySelector("#briefGrid");
  const items = state.topic === "all" ? state.items : state.items.filter(item => (item.topics || item.focus || []).includes(state.topic));
  document.querySelector("#resultCount").textContent = `${items.length} signals`;
  if (!items.length) {
    grid.replaceChildren(document.querySelector("#emptyTemplate").content.cloneNode(true));
    return;
  }
  grid.innerHTML = items.map(cardMarkup).join("");
}

async function loadBrief() {
  try {
    const response = await fetch("data/latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Source returned ${response.status}`);
    const brief = await response.json();
    state.items = brief.items || [];
    document.querySelector("#edition").textContent = dateLabel(brief.date);
    document.querySelector("#summary").textContent = brief.editorial_summary;
    document.querySelector("#generated").textContent = `Generated ${new Date(brief.generated_at).toLocaleString("en-US", { timeZone: "America/Los_Angeles", dateStyle: "medium", timeStyle: "short" })} Pacific`;
    const errors = brief.source_errors || [];
    document.querySelector("#healthValue").textContent = errors.length ? `${errors.length} sources need review` : "All checked sources responded";
    renderFilters();
    renderCards();
  } catch (error) {
    document.querySelector("#summary").textContent = "The latest brief did not load.";
    document.querySelector("#generated").textContent = error.message;
    document.querySelector("#healthValue").textContent = "Collection unavailable";
    renderCards();
  }
}

window.addEventListener("scroll", () => {
  const distance = document.documentElement.scrollHeight - window.innerHeight;
  document.querySelector("#scrollMeter").style.width = `${distance > 0 ? window.scrollY / distance * 100 : 0}%`;
}, { passive: true });

loadBrief();
