/**
 * 驗證 CWA API Key 與各機場免費航班 JSON
 * 使用方式：複製 .env.example 為 .env 並填入 CWA 授權碼後執行
 *   node scripts/verify-api-keys.mjs
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(__dirname, '..', '.env');
const airportsPath = resolve(__dirname, '..', 'config', 'airports.json');

function loadEnv() {
  if (!existsSync(envPath)) return {};
  const env = {};
  for (const line of readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const [key, ...rest] = trimmed.split('=');
    env[key.trim()] = rest.join('=').trim();
  }
  return env;
}

async function verifyCWA(key) {
  const url =
    `https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005?Authorization=${encodeURIComponent(key)}`;
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok || data.success === 'false') {
    throw new Error(data.message || `HTTP ${res.status}`);
  }
  const records = data.records?.tropicalCyclones?.tropicalCyclone ?? [];
  const count = Array.isArray(records) ? records.length : records ? 1 : 0;
  return `成功（目前熱帶氣旋筆數：${count}）`;
}

async function verifyAirport(code, config) {
  const url = config.departure || config.departureInternational;
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const text = await res.text();
  if (!text.trim().startsWith('{') && !text.trim().startsWith('[')) {
    throw new Error('回應非 JSON');
  }
  const data = JSON.parse(text);
  const count = Array.isArray(data)
    ? data.length
    : data.InstantSchedule?.length ?? data.records?.length ?? Object.keys(data).length;
  return `成功（約 ${count} 筆）`;
}

const env = loadEnv();
const airports = JSON.parse(readFileSync(airportsPath, 'utf8'));

console.log('=== API 驗證 ===\n');

if (!env.CWA_API_KEY) {
  console.log('❌ CWA_API_KEY：未設定（颱風模組需要）');
} else {
  try {
    const msg = await verifyCWA(env.CWA_API_KEY);
    console.log(`✅ CWA_API_KEY：${msg}`);
  } catch (e) {
    console.log(`❌ CWA_API_KEY：${e.message}`);
  }
}

console.log('\n--- 免費機場航班 JSON（無需 Key）---\n');

for (const [code, config] of Object.entries(airports)) {
  try {
    const msg = await verifyAirport(code, config);
    console.log(`✅ ${code} ${config.name}：${msg}`);
  } catch (e) {
    console.log(`❌ ${code} ${config.name}：${e.message}`);
  }
}
