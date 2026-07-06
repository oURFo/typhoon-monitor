const state = {
  typhoons: [],
  selectedId: null,
  satellite: null,
  flights: [],
  airports: [],
  airportFilter: "all",
  statusFilter: "all",
  searchActive: false,
  searchAirline: "",
  searchNumber: "",
  searchDestination: "",
  allFlights: [],
  byAirport: {},
  cacheHint: "",
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

function updateSatelliteLayer() {
  if (satelliteLayer) {
    map.removeLayer(satelliteLayer);
    satelliteLayer = null;
  }
  if (!document.getElementById("toggleSatellite").checked || !state.satellite) return;
  const bounds = [
    [0, 95],
    [45, 150],
  ];
  satelliteLayer = L.imageOverlay(state.satellite.url, bounds, { opacity: 0.55 });
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

function renderAirportTabs() {
  const tabs = document.getElementById("airportTabs");
  tabs.innerHTML = "";
  const allBtn = document.createElement("button");
  allBtn.className = `tab-btn${state.airportFilter === "all" ? " active" : ""}`;
  allBtn.textContent = "全部";
  allBtn.onclick = () => {
    state.airportFilter = "all";
    renderAirportTabs();
    renderFlights();
  };
  tabs.appendChild(allBtn);

  state.airports.forEach((a) => {
    const btn = document.createElement("button");
    btn.className = `tab-btn${state.airportFilter === a.code ? " active" : ""}`;
    btn.textContent = AIRPORT_LABEL[a.code] || a.name || a.code;
    btn.onclick = () => {
      state.airportFilter = a.code;
      renderAirportTabs();
      renderFlights();
    };
    tabs.appendChild(btn);
  });
}

function renderFlights() {
  const list = document.getElementById("flightList");
  const hint = document.getElementById("searchHint");
  let rows = state.flights;

  if (!state.searchActive && state.airportFilter !== "all") {
    rows = state.byAirport[state.airportFilter] || rows;
  }

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

  if (!rows.length) {
    list.innerHTML = '<p class="muted">無符合條件的航班</p>';
    return;
  }

  list.innerHTML = rows
    .map(
      (f) => `
    <div class="flight-card${isFlightPast(f) ? " departed" : ""}">
      <div class="top">
        <span class="flight-no">${f.flightNo || "-"}</span>
        <span class="badge ${f.status}">${STATUS_LABEL[f.status] || f.statusText || "-"}</span>
      </div>
      <div>${AIRPORT_LABEL[f.airport] || f.airport} · ${f.direction === "arrival" ? "抵達" : "出發"}</div>
      <div>${f.airline || "-"} → ${f.destination || f.origin || "-"}</div>
      <div class="muted">${formatFlightTimeLine(f)}</div>
      ${f.remark ? `<div class="muted">${f.remark}</div>` : ""}
    </div>`
    )
    .join("");
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
  const res = await fetch("/api/typhoons");
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

const GITHUB_REPO = "oURFo/typhoon-monitor";
const GITHUB_BRANCH = "main";

function flightsDataUrl() {
  const local =
    location.hostname === "localhost" || location.hostname === "127.0.0.1";
  if (local) return "/data/flights.json";
  const bust = Math.floor(Date.now() / 600000);
  return `https://cdn.jsdelivr.net/gh/${GITHUB_REPO}@${GITHUB_BRANCH}/data/flights.json?t=${bust}`;
}

async function fetchFlightsPayload() {
  const res = await fetch(flightsDataUrl());
  if (!res.ok) throw new Error("航班資料載入失敗");
  const data = await res.json();
  const tpeCount = (data.byAirport?.TPE || data.flights || []).filter(
    (f) => f.airport === "TPE"
  ).length;
  if (tpeCount > 0) return data;

  const tpeUrl = flightsDataUrl().replace("flights.json", "tpe-flights.json");
  try {
    const tpeRes = await fetch(tpeUrl);
    if (!tpeRes.ok) return data;
    const tpeData = await tpeRes.json();
    const tpeRows = tpeData.byAirport?.TPE || tpeData.flights || [];
    if (!tpeRows.length) return data;
    const others = (data.flights || []).filter((f) => f.airport !== "TPE");
    const byAirport = { ...(data.byAirport || {}) };
    delete byAirport.TPE;
    const airports = (data.airports || []).filter((a) => a.code !== "TPE");
    airports.push({
      code: "TPE",
      name: "桃園國際機場",
      stale: true,
      error: "合併 tpe-flights.json 快取",
    });
    return {
      ...data,
      flights: [...others, ...tpeRows],
      byAirport: { ...byAirport, TPE: tpeRows },
      airports,
      count: others.length + tpeRows.length,
    };
  } catch {
    return data;
  }
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

function formatFlightCacheHint(data) {
  const parts = [];
  if (data.updatedAt) {
    parts.push(
      "航班資料 " +
        new Date(data.updatedAt).toLocaleString("zh-TW") +
        " 更新（GitHub 每 10 分鐘）"
    );
  }
  const stale = (data.airports || []).filter((a) => a.stale);
  if (stale.length) {
    parts.push(
      stale.map((a) => `${AIRPORT_LABEL[a.code] || a.code}：快取資料`).join(" · ")
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

  state.byAirport = data.byAirport || {};
  state.allFlights = data.flights || [];
  if (!Object.keys(state.byAirport).length && state.allFlights.length) {
    state.byAirport = state.allFlights.reduce((acc, f) => {
      const code = f.airport || "?";
      (acc[code] ||= []).push(f);
      return acc;
    }, {});
  }
  state.flights = state.allFlights;
  const fromApi = data.airports || [];
  state.airports = fromApi.length
    ? fromApi.map((a) => ({
        code: a.code,
        name: AIRPORT_LABEL[a.code] || a.name || a.code,
        error: a.error || null,
      }))
    : AIRPORT_CODES.map((code) => ({
        code,
        name: AIRPORT_LABEL[code] || code,
      }));
  state.cacheHint = formatFlightCacheHint(data);
  document.getElementById("searchHint").textContent = state.cacheHint;
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
refresh();
setInterval(loadTyphoons, 5 * 60 * 1000);
setInterval(() => {
  if (!state.searchActive) loadFlights();
}, 60 * 1000);
