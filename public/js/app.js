const state = {
  typhoons: [],
  selectedId: null,
  satellite: null,
  flights: [],
  airports: [],
  airportFilter: "all",
  directionFilter: "departure",
  statusFilter: "all",
  searchActive: false,
  searchAirline: "",
  searchNumber: "",
  searchDestination: "",
  allFlights: [],
  byAirport: {},
  byAirportDirection: {},
  byDirection: {},
  cacheHint: "",
  dataUpdatedAt: null,
  cacheMeta: {},
  renderedRows: [],
};

let map;
let trackLayer;
let forecastLayer;
let windLayer;
let satelliteLayer;
let markerLayer;

const STATUS_LABEL = {
  on_time: "準時",
  changed: "變更",
  delayed: "延誤",
  cancelled: "取消",
};

const AIRPORT_LABEL = {
  TPE: "桃園",
  TSA: "松山",
  KHH: "高雄",
  RMQ: "臺中",
};

const AIRPORT_CODES = ["TSA", "KHH", "RMQ", "TPE"];

function isFlightPast(f) {
  return !!f.isPast;
}

function formatFlightTimeLine(f) {
  const sched = f.scheduledTime || "-";
  if (f.status === "changed") {
    return `表定 ${sched} · 變更 ${f.displayTime || f.estimatedTime || "-"}`;
  }
  if (f.status === "delayed") {
    const changed = f.displayTime || f.estimatedTime;
    if (changed && changed !== sched) {
      return `表定 ${sched} · 變更 ${changed}`;
    }
    return `表定 ${sched} · 延誤`;
  }
  if (f.status === "cancelled") {
    return `表定 ${sched}`;
  }
  const est = f.displayTime || f.estimatedTime;
  if (est && est !== sched) {
    return `表定 ${sched} · 預估 ${est}`;
  }
  return `表定 ${sched}`;
}

function initMap() {
  map = L.map("map", { zoomControl: true }).setView([20, 125], 5);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: 18,
  }).addTo(map);

  trackLayer = L.layerGroup().addTo(map);
  forecastLayer = L.layerGroup().addTo(map);
  windLayer = L.layerGroup().addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

function kmToDegLat(km) {
  return km / 111;
}

function kmToDegLon(km, lat) {
  return km / (111 * Math.cos((lat * Math.PI) / 180));
}

function drawTyphoon(typhoon) {
  trackLayer.clearLayers();
  forecastLayer.clearLayers();
  windLayer.clearLayers();
  markerLayer.clearLayers();

  if (!typhoon) return;

  const track = typhoon.track || [];
  if (track.length) {
    const latlngs = track.map((p) => [p.lat, p.lon]);
    L.polyline(latlngs, { color: "#3d9cf5", weight: 3, opacity: 0.9 }).addTo(trackLayer);
    latlngs.forEach((ll, i) => {
      if (i === latlngs.length - 1) return;
      L.circleMarker(ll, { radius: 3, color: "#3d9cf5", fillOpacity: 0.8 }).addTo(trackLayer);
    });
  }

  const forecast = typhoon.forecast || [];
  if (forecast.length) {
    const fLatLngs = forecast.map((p) => [p.lat, p.lon]);
    L.polyline(fLatLngs, { color: "#f0a202", weight: 2, dashArray: "6 6", opacity: 0.85 }).addTo(
      forecastLayer
    );
  }

  const current = typhoon.current || track[track.length - 1];
  if (current) {
    L.circleMarker([current.lat, current.lon], {
      radius: 8,
      color: "#fff",
      weight: 2,
      fillColor: "#f05d5e",
      fillOpacity: 1,
    })
      .bindPopup(
        `<strong>${typhoonLabel(typhoon)}</strong><br/>風速 ${current.windSpeed ?? "-"} m/s<br/>氣壓 ${current.pressure ?? "-"} hPa`
      )
      .addTo(markerLayer);

    if (document.getElementById("toggleWind").checked) {
      drawWindCircle(current, "radius7", "#3ecf8e", 0.12);
      drawWindCircle(current, "radius10", "#f0a202", 0.18);
    }

    map.setView([current.lat, current.lon], 5, { animate: true });
  }
}

function drawWindCircle(point, key, color, fillOpacity) {
  const km = point[key];
  if (!km) return;
  const latR = kmToDegLat(km);
  const lonR = kmToDegLon(km, point.lat);
  L.ellipse
    ? L.ellipse([point.lat, point.lon], [latR * 2, lonR * 2], 0, {
        color,
        fillColor: color,
        fillOpacity,
        weight: 1,
      }).addTo(windLayer)
    : L.circle([point.lat, point.lon], {
        radius: km * 1000,
        color,
        fillColor: color,
        fillOpacity,
        weight: 1,
      }).addTo(windLayer);
}

function parseSatelliteBounds(raw) {
  if (Array.isArray(raw) && raw.length === 2) return raw;
  if (typeof raw === "string") {
    const parts = raw.split(",").map(Number);
    if (parts.length === 4) {
      const [west, south, east, north] = parts;
      return [
        [south, west],
        [north, east],
      ];
    }
  }
  return [
    [0, 105],
    [30, 140],
  ];
}

function updateSatelliteLayer() {
  if (satelliteLayer) {
    map.removeLayer(satelliteLayer);
    satelliteLayer = null;
  }
  const toggle = document.getElementById("toggleSatellite");
  if (!toggle.checked || !state.satellite?.url) return;

  const bounds = parseSatelliteBounds(state.satellite.bounds);
  const url = state.satellite.url;
  satelliteLayer = L.imageOverlay(url, bounds, { opacity: 0.55, crossOrigin: true });
  satelliteLayer.on("error", () => {
    if (satelliteLayer) {
      map.removeLayer(satelliteLayer);
      satelliteLayer = null;
    }
  });
  satelliteLayer.addTo(map);
}

function typhoonLabel(t) {
  return t.nameZh || t.nameEn || "未命名";
}

function initTyphoonPanel() {
  const panel = document.getElementById("typhoonPanel");
  if (!panel) return;
  const mq = window.matchMedia("(max-width: 900px)");
  const apply = () => {
    if (mq.matches) panel.removeAttribute("open");
    else panel.setAttribute("open", "");
  };
  apply();
  mq.addEventListener("change", apply);
}

function updateTyphoonSummary() {
  const hint = document.getElementById("typhoonSummaryHint");
  if (!hint) return;
  const t = state.typhoons.find((x) => x.id === state.selectedId);
  if (t) {
    hint.textContent = typhoonLabel(t);
    return;
  }
  hint.textContent = state.typhoons.length ? "點開查看" : "目前無活躍颱風";
}

function renderTyphoonList() {
  const list = document.getElementById("typhoonList");
  list.innerHTML = "";
  if (!state.typhoons.length) {
    list.innerHTML = '<li class="muted">目前無活躍熱帶氣旋</li>';
    updateTyphoonSummary();
    return;
  }
  state.typhoons.forEach((t) => {
    const li = document.createElement("li");
    li.className = `typhoon-item${t.id === state.selectedId ? " active" : ""}`;
    li.innerHTML = `<div class="name">${typhoonLabel(t)}</div><div class="en">${t.nameEn || ""}</div>`;
    li.onclick = () => selectTyphoon(t.id);
    list.appendChild(li);
  });
  updateTyphoonSummary();
}

function renderTyphoonInfo(typhoon) {
  const panel = document.getElementById("typhoonInfo");
  if (!typhoon) {
    panel.innerHTML = '<p class="muted">請選擇颱風</p>';
    return;
  }
  const c = typhoon.current || {};
  panel.innerHTML = `
    <h2>${typhoonLabel(typhoon)}</h2>
    <div class="row"><span>英文名稱</span><span>${typhoon.nameEn || "-"}</span></div>
    <div class="row"><span>最大風速</span><span>${c.windSpeed ?? "-"} m/s</span></div>
    <div class="row"><span>中心氣壓</span><span>${c.pressure ?? "-"} hPa</span></div>
    <div class="row"><span>移動方向</span><span>${c.movingDirection || "-"}</span></div>
    <div class="row"><span>移動速度</span><span>${c.movingSpeed ?? "-"} km/h</span></div>
    <div class="row"><span>7級風圈</span><span>${c.radius7 ? c.radius7 + " km" : "-"}</span></div>
    <div class="row"><span>10級風圈</span><span>${c.radius10 ? c.radius10 + " km" : "-"}</span></div>
  `;
}

function selectTyphoon(id) {
  state.selectedId = id;
  const typhoon = state.typhoons.find((t) => t.id === id);
  renderTyphoonList();
  renderTyphoonInfo(typhoon);
  drawTyphoon(typhoon);
}

function renderDirectionTabs() {
  const tabs = document.getElementById("directionTabs");
  tabs.innerHTML = "";
  [
    { id: "departure", label: "起飛" },
    { id: "arrival", label: "抵達" },
  ].forEach(({ id, label }) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `direction-tab${state.directionFilter === id ? " active" : ""}`;
    btn.textContent = label;
    btn.onclick = () => {
      state.directionFilter = id;
      renderDirectionTabs();
      renderFlights();
    };
    tabs.appendChild(btn);
  });
}

function matchesDirection(f) {
  if (state.directionFilter === "departure") return f.direction === "departure";
  if (state.directionFilter === "arrival") return f.direction === "arrival";
  return true;
}

function buildFlightIndexes(flights) {
  const byAirport = {};
  const byAirportDirection = {};
  const byDirection = { departure: [], arrival: [] };

  for (const f of flights) {
    const code = f.airport || "?";
    const dir = f.direction === "arrival" ? "arrival" : "departure";
    (byAirport[code] ||= []).push(f);
    (byAirportDirection[code] ||= { departure: [], arrival: [] })[dir].push(f);
    byDirection[dir].push(f);
  }
  return { byAirport, byAirportDirection, byDirection };
}

function mergeDirectionBuckets(target, source) {
  for (const dir of ["departure", "arrival"]) {
    if (source?.[dir]?.length) {
      target[dir] = (target[dir] || []).concat(source[dir]);
    }
  }
}

function getFlightRows() {
  const dir = state.directionFilter;
  const code = state.airportFilter;

  if (state.searchActive) {
    let rows = state.flights.filter(matchesDirection);
    if (code !== "all") {
      rows = rows.filter((f) => f.airport === code);
    }
    return rows;
  }

  if (code !== "all") {
    const bucket = state.byAirportDirection?.[code]?.[dir];
    if (bucket) return bucket;
    const pool =
      state.byAirport?.[code] || state.allFlights.filter((f) => f.airport === code);
    return pool.filter(matchesDirection);
  }

  const bucket = state.byDirection?.[dir];
  if (bucket) return bucket;
  return state.allFlights.filter(matchesDirection);
}

function formatFlightRoute(f) {
  if (f.direction === "arrival") {
    const from = f.origin || f.destination || "-";
    return `${from} → ${AIRPORT_LABEL[f.airport] || f.airport}`;
  }
  return `${f.origin || AIRPORT_LABEL[f.airport] || f.airport} → ${f.destination || "-"}`;
}

function formatFlightAirline(f) {
  const name = (f.airline || "").trim();
  if (name) return name;
  return (f.airlineCode || "").trim() || "-";
}

const DIRECTION_LABEL = { departure: "起飛", arrival: "抵達" };

function dashIfEmpty(value) {
  const v = (value || "").trim();
  return v || "—";
}

async function openFlightModal(f) {
  const modal = document.getElementById("flightModal");
  const body = document.getElementById("flightModalBody");
  if (!modal || !body || !f) return;

  await loadAircraftCredits();
  const imgUrl = aircraftImageUrl(f.aircraftType || "");
  const aircraftLabel = f.aircraftType ? aircraftDisplayName(f.aircraftType) : "—";
  const creditHtml = formatAircraftAttributionHtml(f.aircraftType || "");
  const terminalRow =
    f.airport === "TPE" || f.terminal
      ? `<dt>航廈</dt><dd>${dashIfEmpty(f.terminal)}</dd>`
      : "";

  body.innerHTML = `
    <div class="flight-modal-image">
      <img src="${imgUrl}" alt="${aircraftLabel === "—" ? "客機示意圖" : aircraftLabel}" loading="lazy" />
    </div>
    <div class="flight-modal-head">
      <div>
        <h3 class="flight-modal-title" id="flightModalTitle">${f.flightNo || "-"}</h3>
        <p class="flight-modal-sub">${dashIfEmpty(f.airline)}${f.airlineCode ? ` (${f.airlineCode})` : ""}</p>
      </div>
      <span class="badge ${f.status}">${STATUS_LABEL[f.status] || f.statusText || "-"}</span>
    </div>
    <dl class="flight-modal-grid">
      <dt>機場</dt><dd>${AIRPORT_LABEL[f.airport] || f.airport}</dd>
      <dt>方向</dt><dd>${DIRECTION_LABEL[f.direction] || f.direction || "—"}</dd>
      <dt>路線</dt><dd>${formatFlightRoute(f)}</dd>
      <dt>時間</dt><dd>${formatFlightTimeLine(f)}</dd>
      ${terminalRow}
      <dt>登機門</dt><dd>${dashIfEmpty(f.gate)}</dd>
      <dt>機型</dt><dd>${aircraftLabel}</dd>
      <dt>動態</dt><dd>${dashIfEmpty(f.statusText)}</dd>
      ${f.remark ? `<dt>備註</dt><dd>${f.remark}</dd>` : ""}
    </dl>
    ${creditHtml ? `<p class="flight-modal-credit">${creditHtml}</p>` : ""}
    <p class="flight-modal-note">示意照片僅供辨識機型級別，非該航班實機或航空公司塗裝。</p>
  `;

  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
}

function closeFlightModal() {
  const modal = document.getElementById("flightModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function initFlightModal() {
  const modal = document.getElementById("flightModal");
  if (!modal) return;
  modal.querySelector(".flight-modal-close")?.addEventListener("click", closeFlightModal);
  modal.querySelector(".flight-modal-backdrop")?.addEventListener("click", closeFlightModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) closeFlightModal();
  });
}

function renderAirportTabs() {
  const tabs = document.getElementById("airportTabs");
  tabs.innerHTML = "";
  const allBtn = document.createElement("button");
  allBtn.className = `tab-btn${state.airportFilter === "all" ? " active" : ""}`;
  allBtn.textContent = "全部";
  allBtn.onclick = () => {
    state.airportFilter = "all";
    renderAirportTabs();
    renderCachePanel();
    renderFlights();
  };
  tabs.appendChild(allBtn);

  state.airports.forEach((a) => {
    const btn = document.createElement("button");
    btn.className = `tab-btn${state.airportFilter === a.code ? " active" : ""}`;
    btn.textContent = AIRPORT_LABEL[a.code] || a.name || a.code;
    const cm = getAirportCacheMeta(a.code);
    if (cm?.stale) btn.textContent += " ⚠";
    btn.onclick = () => {
      state.airportFilter = a.code;
      renderAirportTabs();
      renderCachePanel();
      renderFlights();
    };
    tabs.appendChild(btn);
  });
}

function renderFlights() {
  const list = document.getElementById("flightList");
  const hint = document.getElementById("searchHint");
  let rows = getFlightRows();

  if (state.statusFilter !== "all") {
    rows = rows.filter((f) => f.status === state.statusFilter);
  }

  const limit = state.searchActive ? 200 : 60;
  const total = rows.length;
  rows = rows.slice(0, limit);

  if (state.searchActive) {
    const parts = [];
    if (state.searchDestination) parts.push(`目的地「${state.searchDestination}」`);
    if (state.searchAirline || state.searchNumber) {
      parts.push(`${state.searchAirline || "—"}${state.searchNumber || ""}`);
    }
    hint.textContent = `查詢 ${parts.join(" · ")} · 共 ${total} 筆`;
  } else {
    const browse =
      total > limit ? `顯示前 ${limit} 筆，共 ${total} 筆（可用上方查詢）` : "";
    hint.textContent = [state.cacheHint, browse].filter(Boolean).join(" · ");
  }

  state.renderedRows = rows;

  if (!rows.length) {
    list.innerHTML = '<p class="muted">無符合條件的航班</p>';
    return;
  }

  list.innerHTML = rows
    .map(
      (f, idx) => `
    <div class="flight-card${isFlightPast(f) ? " departed" : ""}" data-idx="${idx}" tabindex="0" role="button" aria-label="查看 ${f.flightNo || "航班"} 詳情">
      <div class="top">
        <div class="flight-head">
          <span class="flight-no">${f.flightNo || "-"}</span>
          <span class="flight-airline">${formatFlightAirline(f)}</span>
        </div>
        <span class="badge ${f.status}">${STATUS_LABEL[f.status] || f.statusText || "-"}</span>
      </div>
      <div>${AIRPORT_LABEL[f.airport] || f.airport}</div>
      <div>${formatFlightRoute(f)}</div>
      <div class="muted">${formatFlightTimeLine(f)}</div>
      ${f.gate ? `<div class="muted">登機門 ${f.gate}</div>` : ""}
      ${f.remark ? `<div class="muted">${f.remark}</div>` : ""}
    </div>`
    )
    .join("");
}

function onFlightListClick(e) {
  const card = e.target.closest(".flight-card");
  if (!card) return;
  const idx = Number(card.dataset.idx);
  const flight = state.renderedRows[idx];
  if (flight) openFlightModal(flight).catch(() => {});
}

function onFlightListKeydown(e) {
  if (e.key !== "Enter" && e.key !== " ") return;
  const card = e.target.closest(".flight-card");
  if (!card) return;
  e.preventDefault();
  const idx = Number(card.dataset.idx);
  const flight = state.renderedRows[idx];
  if (flight) openFlightModal(flight).catch(() => {});
}

async function searchFlights() {
  const destination = document.getElementById("searchDestination").value.trim();
  const airline = document.getElementById("searchAirline").value.trim();
  const number = document.getElementById("searchNumber").value.trim();
  if (!destination && !airline && !number) {
    state.searchActive = false;
    state.allFlights = [];
    await loadFlights();
    return;
  }
  if (!state.allFlights.length) {
    await loadFlights();
  }
  state.searchActive = true;
  state.searchDestination = destination;
  state.searchAirline = airline.toUpperCase();
  state.searchNumber = number;
  state.flights = filterFlightsLocal(state.allFlights, {
    destination,
    airline,
    number,
  });
  state.airportFilter = "all";
  renderDirectionTabs();
  renderAirportTabs();
  renderFlights();
}

function clearFlightSearch() {
  document.getElementById("searchDestination").value = "";
  document.getElementById("searchAirline").value = "";
  document.getElementById("searchNumber").value = "";
  state.searchActive = false;
  state.searchDestination = "";
  state.searchAirline = "";
  state.searchNumber = "";
  state.allFlights = [];
  loadFlights();
}

async function loadTyphoons() {
  const res = await fetch("/api/typhoons", FETCH_NO_STORE);
  if (!res.ok) throw new Error("颱風資料載入失敗");
  const data = await res.json();
  state.typhoons = data.typhoons || [];
  state.satellite = data.satellite;
  if (!state.selectedId && state.typhoons[0]) {
    state.selectedId = state.typhoons[0].id;
  }
  renderTyphoonList();
  selectTyphoon(state.selectedId);
  updateSatelliteLayer();
}

const FETCH_NO_STORE = { cache: "no-store" };

function isLocalDev() {
  return location.hostname === "localhost" || location.hostname === "127.0.0.1";
}

function flightsSnapshotUrl() {
  if (isLocalDev()) return "/data/flights.json";
  return "/api/flights/snapshot";
}

function mergeTpeIfNeeded(data) {
  const tpeInMain = (data.byAirportDirection?.TPE?.departure?.length || 0) > 0;
  if (tpeInMain) return data;
  return null;
}

async function fetchTpeFallback(mainData) {
  const tpeUrl = isLocalDev() ? "/data/tpe-flights.json" : null;
  if (!tpeUrl) return mainData;

  try {
    const tpeRes = await fetch(tpeUrl, FETCH_NO_STORE);
    if (!tpeRes.ok) return mainData;
    const tpeData = await tpeRes.json();
    const tpeRows = tpeData.flights || [];
    if (!tpeRows.length) return mainData;

    const others = (mainData.flights || []).filter((f) => f.airport !== "TPE");
    const byAirport = { ...(mainData.byAirport || {}) };
    const byAirportDirection = { ...(mainData.byAirportDirection || {}) };
    const byDirection = {
      departure: [...(mainData.byDirection?.departure || []).filter((f) => f.airport !== "TPE")],
      arrival: [...(mainData.byDirection?.arrival || []).filter((f) => f.airport !== "TPE")],
    };

    delete byAirport.TPE;
    delete byAirportDirection.TPE;
    byAirport.TPE = tpeData.byAirport?.TPE || tpeRows;
    byAirportDirection.TPE = tpeData.byAirportDirection?.TPE || {
      departure: tpeRows.filter((f) => f.direction === "departure"),
      arrival: tpeRows.filter((f) => f.direction === "arrival"),
    };
    mergeDirectionBuckets(byDirection, tpeData.byDirection);
    if (!tpeData.byDirection) {
      byDirection.departure.push(...byAirportDirection.TPE.departure);
      byDirection.arrival.push(...byAirportDirection.TPE.arrival);
    }

    const airports = (mainData.airports || []).filter((a) => a.code !== "TPE");
    airports.push({
      code: "TPE",
      name: "桃園國際機場",
      stale: true,
      error: "合併 tpe-flights.json 快取",
      ...(tpeData.cacheMeta?.TPE || {}),
    });
    return {
      ...mainData,
      flights: [...others, ...tpeRows],
      byAirport,
      byAirportDirection,
      byDirection,
      cacheMeta: { ...(mainData.cacheMeta || {}), ...(tpeData.cacheMeta || {}) },
      airports,
      count: others.length + tpeRows.length,
    };
  } catch {
    return mainData;
  }
}

async function fetchFlightsPayload() {
  const res = await fetch(flightsSnapshotUrl(), FETCH_NO_STORE);
  if (!res.ok) throw new Error("航班資料載入失敗");
  let data = await res.json();

  if (isLocalDev()) {
    if (!mergeTpeIfNeeded(data)) {
      data = await fetchTpeFallback(data);
    }
  }
  return data;
}

function filterFlightsLocal(flights, { destination = "", airline = "", number = "" } = {}) {
  let rows = flights;
  const destQ = destination.trim().toLowerCase();
  if (destQ) {
    rows = rows.filter((f) => {
      const dest = (f.destination || "").toLowerCase();
      const orig = (f.origin || "").toLowerCase();
      return dest.includes(destQ) || orig.includes(destQ);
    });
  }

  const airlineCode = airline.trim().toUpperCase();
  const flightNum = number.trim();
  if (!airlineCode && !flightNum) return rows;

  return rows.filter((f) => {
    const fno = (f.flightNo || "").toUpperCase().replace(/\s/g, "");
    const ac = (f.airlineCode || "").toUpperCase();
    if (airlineCode && flightNum) {
      const target = `${airlineCode}${flightNum}`;
      return fno === target || (fno.startsWith(airlineCode) && fno.endsWith(flightNum));
    }
    if (airlineCode) return ac === airlineCode || fno.startsWith(airlineCode);
    return fno.endsWith(flightNum) || ` ${fno}`.includes(` ${flightNum}`);
  });
}

function formatTs(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-TW");
}

function getAirportCacheMeta(code) {
  const meta = state.cacheMeta[code] || state.airports.find((a) => a.code === code);
  return meta ? { code, ...meta } : null;
}

function formatAirportCacheDetail(code) {
  const meta = getAirportCacheMeta(code);
  if (!meta) return `${AIRPORT_LABEL[code] || code}：無快取資訊`;
  const label = AIRPORT_LABEL[code] || code;
  const lines = [];
  lines.push(`資料時間：${formatTs(meta.cachedAt || meta.lastSuccessAt)}`);
  lines.push(`上次嘗試：${formatTs(meta.lastAttemptAt || state.dataUpdatedAt)}`);
  if (meta.stale) {
    lines.push(`狀態：快取（本次更新失敗）`);
    lines.push(`連續失敗：${meta.failCount || 0} 次`);
  } else if (meta.failCount > 0) {
    lines.push(`連續失敗：${meta.failCount} 次（本次已成功）`);
  } else {
    lines.push(`狀態：本次更新成功`);
  }
  if (meta.rowCount != null) lines.push(`筆數：${meta.rowCount}`);
  if (meta.lastError) lines.push(`錯誤：${meta.lastError}`);
  return `${label} — ${lines.join(" · ")}`;
}

function renderCachePanel() {
  const panel = document.getElementById("cachePanel");
  if (!panel) return;

  const parts = [`整體快照：${formatTs(state.dataUpdatedAt)}（GitHub 每 10 分鐘更新 · 經由網站 API 讀取）`];

  if (state.airportFilter !== "all") {
    parts.push(formatAirportCacheDetail(state.airportFilter));
  } else {
    AIRPORT_CODES.map((code) => getAirportCacheMeta(code))
      .filter((m) => m && (m.stale || (m.failCount || 0) > 0 || m.lastError))
      .forEach((m) => parts.push(formatAirportCacheDetail(m.code)));
  }

  panel.className = `cache-panel${getAirportCacheMeta("TPE")?.stale ? " cache-warn" : ""}`;
  panel.innerHTML = parts.map((p) => `<div>${p}</div>`).join("");
}

function formatFlightCacheHint(data) {
  const parts = [];
  if (data.updatedAt) {
    parts.push(`整體更新 ${formatTs(data.updatedAt)}`);
  }
  const stale = (data.airports || []).filter((a) => a.stale);
  if (stale.length) {
    parts.push(
      stale
        .map(
          (a) =>
            `${AIRPORT_LABEL[a.code] || a.code} 快取 ${formatTs(a.cachedAt)}（失敗 ${a.failCount || "?"} 次）`
        )
        .join(" · ")
    );
  }
  const failed = (data.airports || []).filter((a) => a.error && !a.stale);
  if (failed.length) {
    parts.push(
      failed.map((a) => `${AIRPORT_LABEL[a.code] || a.code}：${a.error}`).join(" · ")
    );
  }
  return parts.join(" · ");
}

async function loadFlights() {
  if (state.searchActive) return;
  const data = await fetchFlightsPayload();

  state.allFlights = data.flights || [];
  state.byAirport = data.byAirport || {};
  state.byAirportDirection = data.byAirportDirection || {};
  state.byDirection = data.byDirection || { departure: [], arrival: [] };

  if (state.allFlights.length && !Object.keys(state.byAirportDirection).length) {
    const built = buildFlightIndexes(state.allFlights);
    state.byAirport = built.byAirport;
    state.byAirportDirection = built.byAirportDirection;
    state.byDirection = built.byDirection;
  }

  state.dataUpdatedAt = data.updatedAt || null;
  state.cacheMeta = data.cacheMeta || {};
  state.flights = state.allFlights;
  const fromApi = data.airports || [];
  state.airports = fromApi.length
    ? fromApi.map((a) => ({
        code: a.code,
        name: AIRPORT_LABEL[a.code] || a.name || a.code,
        error: a.error || null,
        stale: !!a.stale,
        cachedAt: a.cachedAt || null,
        lastAttemptAt: a.lastAttemptAt || null,
        lastSuccessAt: a.lastSuccessAt || null,
        failCount: a.failCount || 0,
        lastError: a.lastError || null,
        rowCount: a.rowCount ?? null,
      }))
    : AIRPORT_CODES.map((code) => ({
        code,
        name: AIRPORT_LABEL[code] || code,
      }));
  if (!Object.keys(state.cacheMeta).length) {
    state.cacheMeta = Object.fromEntries(
      state.airports.filter((a) => a.cachedAt || a.stale).map((a) => [a.code, a])
    );
  }
  state.cacheHint = formatFlightCacheHint(data);
  document.getElementById("searchHint").textContent = state.cacheHint;
  renderCachePanel();
  renderDirectionTabs();
  renderAirportTabs();
  renderFlights();
}

async function refresh() {
  try {
    await loadTyphoons();
    if (!state.searchActive) {
      await loadFlights();
    }
    document.getElementById("lastUpdate").textContent =
      "颱風 " + new Date().toLocaleString("zh-TW") + " 更新";
  } catch (err) {
    document.getElementById("lastUpdate").textContent = "更新失敗：" + err.message;
  }
}

document.getElementById("flightSearchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  searchFlights().catch((err) => {
    document.getElementById("searchHint").textContent = "查詢失敗：" + err.message;
  });
});

document.getElementById("searchClear").addEventListener("click", () => {
  clearFlightSearch();
});

document.getElementById("statusFilter").addEventListener("change", (e) => {
  state.statusFilter = e.target.value;
  renderFlights();
});

document.getElementById("toggleTrack").addEventListener("change", () => {
  const t = state.typhoons.find((x) => x.id === state.selectedId);
  drawTyphoon(t);
});

document.getElementById("toggleWind").addEventListener("change", () => {
  const t = state.typhoons.find((x) => x.id === state.selectedId);
  drawTyphoon(t);
});

document.getElementById("toggleSatellite").addEventListener("change", updateSatelliteLayer);

initMap();
initTyphoonPanel();
initFlightModal();
loadAircraftCredits();
document.getElementById("flightList")?.addEventListener("click", onFlightListClick);
document.getElementById("flightList")?.addEventListener("keydown", onFlightListKeydown);
refresh();
setInterval(loadTyphoons, 5 * 60 * 1000);
setInterval(() => {
  if (!state.searchActive) loadFlights();
}, 60 * 1000);
