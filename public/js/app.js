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
};

let map;
let trackLayer;
let forecastLayer;
let windLayer;
let satelliteLayer;
let markerLayer;

const STATUS_LABEL = {
  on_time: "準時",
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

function renderTyphoonList() {
  const list = document.getElementById("typhoonList");
  list.innerHTML = "";
  if (!state.typhoons.length) {
    list.innerHTML = '<li class="muted">目前無活躍熱帶氣旋（若持續為空請重啟 start.bat）</li>';
    return;
  }
  state.typhoons.forEach((t) => {
    const li = document.createElement("li");
    li.className = `typhoon-item${t.id === state.selectedId ? " active" : ""}`;
    li.innerHTML = `<div class="name">${typhoonLabel(t)}</div><div class="en">${t.nameEn || ""}</div>`;
    li.onclick = () => selectTyphoon(t.id);
    list.appendChild(li);
  });
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

  if (state.airportFilter !== "all") {
    rows = rows.filter((f) => f.airport === state.airportFilter);
  }
  if (state.statusFilter !== "all") {
    rows = rows.filter((f) => f.status === state.statusFilter);
  }

  const limit = state.searchActive ? 200 : 60;
  const total = rows.length;
  rows = rows.slice(0, limit);

  if (state.searchActive) {
    hint.textContent = `查詢 ${state.searchAirline || "—"}${state.searchNumber || ""} · 共 ${total} 筆`;
  } else {
    hint.textContent = total > limit ? `顯示前 ${limit} 筆，共 ${total} 筆（可用上方查詢）` : "";
  }

  if (!rows.length) {
    list.innerHTML = '<p class="muted">無符合條件的航班</p>';
    return;
  }

  list.innerHTML = rows
    .map(
      (f) => `
    <div class="flight-card">
      <div class="top">
        <span class="flight-no">${f.flightNo || "-"}</span>
        <span class="badge ${f.status}">${STATUS_LABEL[f.status] || f.statusText || "-"}</span>
      </div>
      <div>${AIRPORT_LABEL[f.airport] || f.airport} · ${f.direction === "arrival" ? "抵達" : "出發"}</div>
      <div>${f.airline || "-"} → ${f.destination || f.origin || "-"}</div>
      <div class="muted">表定 ${f.scheduledTime || "-"} · 預估 ${f.estimatedTime || "-"}</div>
      ${f.remark ? `<div class="muted">${f.remark}</div>` : ""}
    </div>`
    )
    .join("");
}

async function searchFlights() {
  const airline = document.getElementById("searchAirline").value.trim();
  const number = document.getElementById("searchNumber").value.trim();
  if (!airline && !number) {
    state.searchActive = false;
    await loadFlights();
    return;
  }
  const params = new URLSearchParams();
  if (airline) params.set("airline", airline);
  if (number) params.set("number", number);
  const res = await fetch(`/api/flights?${params}`);
  if (!res.ok) throw new Error("航班查詢失敗");
  const data = await res.json();
  state.flights = data.flights || [];
  state.airports = data.airports || [];
  state.searchActive = true;
  state.searchAirline = airline.toUpperCase();
  state.searchNumber = number;
  state.airportFilter = "all";
  renderAirportTabs();
  renderFlights();
}

function clearFlightSearch() {
  document.getElementById("searchAirline").value = "";
  document.getElementById("searchNumber").value = "";
  state.searchActive = false;
  state.searchAirline = "";
  state.searchNumber = "";
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

async function loadFlights() {
  if (state.searchActive) return;
  document.getElementById("searchHint").textContent = "航班載入中…";
  state.flights = [];
  state.airports = AIRPORT_CODES.map((code) => ({
    code,
    name: AIRPORT_LABEL[code] || code,
  }));
  renderAirportTabs();
  renderFlights();

  const results = await Promise.allSettled(
    AIRPORT_CODES.map(async (code) => {
      const res = await fetch(`/api/flights/airport/${code}`);
      if (!res.ok) throw new Error(`${code} 載入失敗`);
      return res.json();
    })
  );

  const merged = [];
  const airports = [];
  results.forEach((result, i) => {
    const code = AIRPORT_CODES[i];
    if (result.status === "fulfilled") {
      const data = result.value;
      airports.push({
        code: data.airport || code,
        name: data.name || AIRPORT_LABEL[code],
        error: data.error || null,
      });
      merged.push(...(data.flights || []));
    } else {
      airports.push({
        code,
        name: AIRPORT_LABEL[code],
        error: result.reason?.message || "載入失敗",
      });
    }
  });

  state.flights = merged;
  state.airports = airports;
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
      "最後更新 " + new Date().toLocaleString("zh-TW");
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
refresh();
setInterval(refresh, 5 * 60 * 1000);
