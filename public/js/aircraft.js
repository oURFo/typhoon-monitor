/** 機型代碼 → Wikimedia 照片（含授權資訊） */
const AIRCRAFT_IMAGE_BASE = "/static/assets/aircraft";
const AIRCRAFT_CREDITS_URL = "/static/data/aircraft-credits.json";

let aircraftCredits = {};
let aircraftCreditsReady = null;

const PHOTO_KEY_RULES = [
  { key: "a330neo", re: /A330-9|A339|A33N|330-9|330NEO/i },
  { key: "a330", re: /A33[03]|^333$|A330/i },
  { key: "a350", re: /A35[09K]|^359$|^35K$/i },
  { key: "a321", re: /A321|A21N|^321$|32Q/i },
  { key: "a320", re: /A320|A20N|^320$|32[0-9]N/i },
  { key: "a319", re: /A319|^319$/i },
  { key: "b787", re: /B787|78[1789]|^781$|^788$|^789$/i },
  { key: "b777", re: /B777|77[WL3]|^773$|^77W$/i },
  { key: "b747", re: /B747|74[48H]/i },
  { key: "b737", re: /B73[79]|^738$|^739$|^737$/i },
  { key: "atr72", re: /ATR|AT7|AT76/i },
];

const AIRCRAFT_FAMILY_RULES = [
  { family: "regional", re: /^(ATR|AT7|AT5|AT4|AT76|AT72|DH8|CRJ|E17|E19|E90|E95|ERJ|SF3|DHC)/ },
  { family: "wide", re: /^(A35|A33|A34|A38|A30|B74|B77|B78|B76|77[WL3]|78[1789]|35[09K]|33[39]|34[06]|747|767|777|787|350|330|340)/ },
  { family: "narrow", re: /^(A32|A21|A22|A31|A20|B73|B72|B71|32[0-9NQ]|31[0-9]|21N|20N|73[0-9]|72[0-9]|319|320|321|737|738|739)/ },
];

function normalizeAircraftToken(raw) {
  if (!raw || raw === "-" || raw === "null") return "";
  return String(raw).trim().toUpperCase().replace(/\s+/g, "");
}

function resolveAircraftPhotoKey(raw) {
  const token = normalizeAircraftToken(raw);
  if (!token) return null;
  for (const { key, re } of PHOTO_KEY_RULES) {
    if (re.test(token)) return key;
  }
  if (/^\d{3}$/.test(token)) {
    if (token.startsWith("33")) return token === "333" ? "a330" : "a330neo";
    if (token.startsWith("35")) return "a350";
    if (token === "321") return "a321";
    if (token.startsWith("32") || token === "320") return "a320";
    if (token === "319") return "a319";
    if (token.startsWith("77")) return "b777";
    if (token.startsWith("78")) return "b787";
    if (token.startsWith("74")) return "b747";
    if (token.startsWith("73") || token === "738" || token === "739") return "b737";
  }
  return null;
}

function resolveAircraftFamily(raw) {
  const token = normalizeAircraftToken(raw);
  if (!token) return "generic";
  for (const { family, re } of AIRCRAFT_FAMILY_RULES) {
    if (re.test(token)) return family;
  }
  return "generic";
}

function getCreditEntry(key) {
  if (!key) return null;
  const entry = aircraftCredits[key];
  if (!entry) return null;
  if (entry.aliasOf) return aircraftCredits[entry.aliasOf] || entry;
  return entry;
}

async function loadAircraftCredits() {
  if (aircraftCreditsReady) return aircraftCreditsReady;
  aircraftCreditsReady = fetch(AIRCRAFT_CREDITS_URL)
    .then((res) => (res.ok ? res.json() : {}))
    .then((data) => {
      aircraftCredits = data || {};
      return aircraftCredits;
    })
    .catch(() => {
      aircraftCredits = {};
      return aircraftCredits;
    });
  return aircraftCreditsReady;
}

function aircraftImageUrl(raw) {
  const photoKey = resolveAircraftPhotoKey(raw);
  const credit = getCreditEntry(photoKey);
  if (credit?.localPath) return credit.localPath;
  const family = resolveAircraftFamily(raw);
  return `${AIRCRAFT_IMAGE_BASE}/${family}.svg`;
}

function aircraftImageCredit(raw) {
  const photoKey = resolveAircraftPhotoKey(raw);
  return getCreditEntry(photoKey);
}

function aircraftDisplayName(raw) {
  const token = normalizeAircraftToken(raw);
  if (!token) return "";
  return raw.trim();
}

function formatAircraftAttributionHtml(raw) {
  const credit = aircraftImageCredit(raw);
  if (!credit) return "";
  const author = credit.author || "Unknown";
  const license = credit.license || "";
  const commonsUrl = credit.commonsUrl || "#";
  const licenseUrl = credit.licenseUrl || commonsUrl;
  return (
    `圖片：<a href="${commonsUrl}" target="_blank" rel="noopener noreferrer">${author}</a>` +
    ` / <a href="${licenseUrl}" target="_blank" rel="noopener noreferrer">${license}</a>` +
    ` / <a href="${commonsUrl}" target="_blank" rel="noopener noreferrer">Wikimedia Commons</a>`
  );
}
