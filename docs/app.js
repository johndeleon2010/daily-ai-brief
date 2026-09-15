const state = {
  items: [],
  archiveItems: [],
  briefs: [],
  topic: "all",
  creator: "",
  date: "",
  query: "",
};

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
  filters.innerHTML = '<button class="filter active" data-topic="all" type="button">All signals</button>';
  const topics = [...new Set(state.items.flatMap(item => item.topics || item.focus || []))].sort();
  topics.forEach(topic => {
    const button = document.createElement("button");
    button.className = "filter";
    button.type = "button";
    button.dataset.topic = topic;
    button.textContent = topic;
    filters.append(button);
  });
}

function matchesSearch(item, query) {
  const action = item.practical_action || {};
  const text = [
    item.creator,
    item.title,
    item.summary,
    item.why_it_matters,
    ...(item.topics || item.focus || []),
    action.work_area,
    action.title,
    action.time_needed,
    ...(action.steps || []),
    action.expected_result,
    action.test,
    action.safety,
    item.try_this,
  ].filter(Boolean).join(" ").toLowerCase();
  return query.toLowerCase().trim().split(/\s+/).filter(Boolean).every(word => text.includes(word));
}

function filterItems(items, filters = {}) {
  return items.filter(item =>
    (!filters.date || item.brief_date === filters.date) &&
    (!filters.creator || item.creator === filters.creator) &&
    (!filters.topic || filters.topic === "all" || (item.topics || item.focus || []).includes(filters.topic)) &&
    matchesSearch(item, filters.query || "")
  );
}

function actionMarkup(item) {
  const action = item.practical_action;
  if (!action) return "";
  return `
    <div class="practical-action">
      <div class="action-heading"><strong>Practical action</strong><span>${safe(action.time_needed)}</span></div>
      <h3>${safe(action.title)}</h3>
      <ol>${action.steps.map(step => `<li>${safe(step)}</li>`).join("")}</ol>
      <p><b>Result:</b> ${safe(action.expected_result)}</p>
      <p><b>Test:</b> ${safe(action.test)}</p>
      <p><b>Safety:</b> ${safe(action.safety)}</p>
    </div>`;
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
        ${actionMarkup(item)}
      </div>
      <div class="card-footer">
        <div class="topics">${topics.map(topic => `<span class="topic">${safe(topic)}</span>`).join("")}</div>
        <a class="source-link" href="${safe(item.source)}" target="_blank" rel="noopener noreferrer">Open source</a>
      </div>
    </article>`;
}

function renderCards() {
  const grid = document.querySelector("#briefGrid");
  const items = filterItems(state.items, {
    date: state.date,
    creator: state.creator,
    topic: state.topic,
    query: state.query,
  });
  document.querySelector("#resultCount").textContent = `${items.length} signals`;
  if (!items.length) {
    grid.replaceChildren(document.querySelector("#emptyTemplate").content.cloneNode(true));
    return;
  }
  grid.innerHTML = items.map(cardMarkup).join("");
}

async function loadBrief(date = "") {
  try {
    const source = date ? `data/${date}.json` : "data/latest.json";
    const response = await fetch(source, { cache: "no-store" });
    if (!response.ok) throw new Error(`Source returned ${response.status}`);
    const brief = await response.json();
    state.items = brief.items || [];
    document.querySelector("#edition").textContent = dateLabel(brief.date);
    document.querySelector("#summary").textContent = brief.editorial_summary;
    document.querySelector("#generated").textContent = `Generated ${new Date(brief.generated_at).toLocaleString("en-US", { timeZone: "America/Los_Angeles", dateStyle: "medium", timeStyle: "short" })} Pacific`;
    const errors = brief.source_errors || [];
    document.querySelector("#healthValue").textContent = errors.length ? `${errors.length} sources need review` : "All checked sources responded";
    document.querySelector("#latestButton").classList.toggle("active", !date);
    document.querySelector("#archiveButton").classList.toggle("active", Boolean(date));
    renderFilters();
    renderCards();
  } catch (error) {
    document.querySelector("#summary").textContent = "The latest brief did not load.";
    document.querySelector("#generated").textContent = error.message;
    document.querySelector("#healthValue").textContent = "Collection unavailable";
    renderCards();
  }
}

async function loadArchive() {
  try {
    const response = await fetch("data/archive.json", { cache: "no-store" });
    if (!response.ok) return;
    const archive = await response.json();
    state.briefs = archive.briefs || [];
    state.archiveItems = archive.items || [];
    const select = document.querySelector("#briefDate");
    state.briefs.forEach(brief => {
      const option = document.createElement("option");
      option.value = brief.date;
      option.textContent = `${dateLabel(brief.date)} (${brief.item_count} items)`;
      select.append(option);
    });
    const creatorSelect = document.querySelector("#creatorFilter");
    [...new Set(state.archiveItems.map(item => item.creator))].sort().forEach(creator => {
      const option = document.createElement("option");
      option.value = creator;
      option.textContent = creator;
      creatorSelect.append(option);
    });
  } catch (error) {
    document.querySelector("#archiveButton").title = "Archive index unavailable";
  }
}

function showArchive(show) {
  document.querySelector("#archivePicker").hidden = !show;
  document.querySelector("#creatorPicker").hidden = !show;
  document.querySelector("#archiveButton").setAttribute("aria-expanded", String(show));
}

function showArchivedItems(date = "") {
  state.items = state.archiveItems;
  state.date = date;
  const brief = state.briefs.find(item => item.date === date);
  document.querySelector("#edition").textContent = date ? dateLabel(date) : "All saved briefs";
  document.querySelector("#summary").textContent = brief
    ? brief.editorial_summary
    : `${state.briefs.length} saved briefs. Search by creator, topic, or practical action.`;
  document.querySelector("#generated").textContent = date
    ? `${brief?.item_count || 0} saved items`
    : `${state.archiveItems.length} saved cards`;
  document.querySelector("#healthValue").textContent = "Archive ready";
  document.querySelector("#latestButton").classList.remove("active");
  document.querySelector("#archiveButton").classList.add("active");
  renderFilters();
  renderCards();
}

function setupControls() {
  document.querySelector("#filters").addEventListener("click", event => {
    const button = event.target.closest("button[data-topic]");
    if (!button) return;
    state.topic = button.dataset.topic;
    document.querySelectorAll("#filters button").forEach(item => item.classList.toggle("active", item === button));
    renderCards();
  });
  document.querySelector("#briefSearch").addEventListener("input", event => {
    state.query = event.target.value;
    renderCards();
  });
  document.querySelector("#archiveButton").addEventListener("click", () => {
    showArchive(true);
    showArchivedItems(document.querySelector("#briefDate").value);
  });
  document.querySelector("#latestButton").addEventListener("click", () => {
    history.replaceState({}, "", window.location.pathname);
    document.querySelector("#briefDate").value = "";
    document.querySelector("#creatorFilter").value = "";
    state.creator = "";
    state.date = "";
    showArchive(false);
    loadBrief();
  });
  document.querySelector("#briefDate").addEventListener("change", event => {
    const date = event.target.value;
    history.replaceState({}, "", date ? `?date=${encodeURIComponent(date)}` : window.location.pathname);
    showArchivedItems(date);
  });
  document.querySelector("#creatorFilter").addEventListener("change", event => {
    state.creator = event.target.value;
    renderCards();
  });
}

if (typeof module !== "undefined") module.exports = { filterItems, matchesSearch };

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("scroll", () => {
    const distance = document.documentElement.scrollHeight - window.innerHeight;
    document.querySelector("#scrollMeter").style.width = `${distance > 0 ? window.scrollY / distance * 100 : 0}%`;
  }, { passive: true });
  setupControls();
  loadArchive().then(() => {
    const selectedDate = new URLSearchParams(window.location.search).get("date") || "";
    if (selectedDate) {
      document.querySelector("#briefDate").value = selectedDate;
      showArchive(true);
      showArchivedItems(selectedDate);
    } else {
      loadBrief();
    }
  });
}
