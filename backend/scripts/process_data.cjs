/**
 * 澳門用水資料處理 v5
 * - 降雨資料（Open-Meteo API）
 * - 異常檢測（閾值 + 突變）
 * - 排名變化追蹤
 * - DMA多維對比
 * - 路氹城非住宅日曆熱力圖
 * - 水表搜尋索引
 */

const XLSX = require('xlsx');
const path = require('path');
const fs = require('fs');
const https = require('https');

// Configure these paths to point to your data directories
const CONS_DIR = process.env.CONS_DIR || './data/input/consumption';
const REF_DIR = process.env.REF_DIR || './data/input/reference';
const OUT_DIR = path.resolve(__dirname, '../data/output');

fs.mkdirSync(OUT_DIR, { recursive: true });
console.log('🚀 開始處理資料 (v5)...\n');

// === 1. 參考資料去重 ===
console.log('📖 讀取參考資料（去重）...');
const meterInfo = {};
const codeToMeter = {};
for (const fname of fs.readdirSync(REF_DIR).filter(f=>f.endsWith('.xlsx')).sort((a,b) => {
  // 按修改時間排序，最新的最後處理（這樣新資料會覆蓋舊資料）
  const sa = fs.statSync(path.join(REF_DIR, a)).mtimeMs;
  const sb = fs.statSync(path.join(REF_DIR, b)).mtimeMs;
  return sa - sb;
})) {
  const wb = XLSX.readFile(path.join(REF_DIR, fname));
  const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1 });
  const h = rows[0];
  const mi = h.indexOf('錶位編號'), di = h.indexOf('DMA分區'), pi = h.indexOf('物業類型');
  const bi = h.indexOf('建築物名稱'), ci = h.indexOf('合同編號'), si = h.indexOf('供水模式');
  const coi = h.indexOf('錶碼'), mci = h.indexOf('主錶錶碼');
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i], mid = String(r[mi]||'').trim(), dma = String(r[di]||'').trim();
    if (!mid || !dma || dma==='undefined') continue;
    const mc = String(r[mci]||'').trim(), c = String(r[coi]||'').trim();
    if (c && c!=='undefined') codeToMeter[c] = mid;
    meterInfo[mid] = {
      dma, propertyType: String(r[pi]||'').trim(),
      isResidential: String(r[pi]||'').trim()==='001:住宅',
      contractId: String(r[ci]||'').trim(), buildingName: String(r[bi]||'').trim(),
      supplyMode: String(r[si]||'').trim(),
      mainCode: String(r[si]||'').trim()==='INDIRECT' && mc!=='undefined' ? mc : null
    };
  }
}
console.log(`   ✅ ${Object.keys(meterInfo).length} 個唯一水表\n`);

// === 2. 讀取降雨資料 ===
console.log('🌧️ 載入降雨資料...');
// 內嵌降雨資料（從 Open-Meteo 取得，澳門座標 22.1987°N 113.5439°E）
const rainfall = {
  "2024-01-01": 0, "2024-01-02": 0, "2024-01-03": 0, "2024-01-04": 0, "2024-01-05": 0,
  "2024-01-06": 0, "2024-01-07": 0, "2024-01-08": 0, "2024-01-09": 1.3, "2024-01-10": 0,
  "2024-01-11": 0, "2024-01-12": 0, "2024-01-13": 0, "2024-01-14": 0, "2024-01-15": 0,
  "2024-01-16": 0, "2024-01-17": 0.1, "2024-01-18": 1.8, "2024-01-19": 0, "2024-01-20": 0.4,
  "2024-01-21": 0, "2024-01-22": 0.2, "2024-01-23": 5.6, "2024-01-24": 0, "2024-01-25": 0,
  "2024-01-26": 0, "2024-01-27": 0.2, "2024-01-28": 0.9, "2024-01-29": 0, "2024-01-30": 0.1,
  "2024-01-31": 0.1, "2024-02-01": 0.5, "2024-02-02": 0, "2024-02-03": 0.5, "2024-02-04": 0.7,
  "2024-02-05": 0.2, "2024-02-06": 1.7, "2024-02-07": 2.6, "2024-02-08": 6, "2024-02-09": 4.1,
  "2024-02-10": 0.8, "2024-02-11": 0, "2024-02-12": 0, "2024-02-13": 0, "2024-02-14": 0,
  "2024-02-15": 0, "2024-02-16": 0, "2024-02-17": 0.2, "2024-02-18": 1.2, "2024-02-19": 1.1,
  "2024-02-20": 3.1, "2024-02-21": 0, "2024-02-22": 1.3, "2024-02-23": 0.2, "2024-02-24": 0,
  "2024-02-25": 0, "2024-02-26": 0, "2024-02-27": 0.2, "2024-02-28": 1.8, "2024-02-29": 1.7,
  "2024-03-01": 0.3, "2024-03-02": 1.4, "2024-03-03": 2.6, "2024-03-04": 2, "2024-03-05": 0.9,
  "2024-03-06": 2.7, "2024-03-07": 2.3, "2024-03-08": 3.1, "2024-03-09": 1.4, "2024-03-10": 10.1,
  "2024-03-11": 10.2, "2024-03-12": 0, "2024-03-13": 0.1, "2024-03-14": 0, "2024-03-15": 0.1,
  "2024-03-16": 0, "2024-03-17": 0.2, "2024-03-18": 0.2, "2024-03-19": 0.8, "2024-03-20": 0,
  "2024-03-21": 0, "2024-03-22": 0, "2024-03-23": 0.3, "2024-03-24": 0.2, "2024-03-25": 0.7,
  "2024-03-26": 0.1, "2024-03-27": 0, "2024-03-28": 1.2, "2024-03-29": 1, "2024-03-30": 0.3,
  "2024-03-31": 33.2, "2024-04-01": 5.2, "2024-04-02": 1.5, "2024-04-03": 4.3, "2024-04-04": 5.8,
  "2024-04-05": 9.3, "2024-04-06": 8.3, "2024-04-07": 4.7, "2024-04-08": 4.8, "2024-04-09": 0.3,
  "2024-04-10": 0, "2024-04-11": 0, "2024-04-12": 0.3, "2024-04-13": 0, "2024-04-14": 1,
  "2024-04-15": 0.9, "2024-04-16": 0.2, "2024-04-17": 1.2, "2024-04-18": 12.5, "2024-04-19": 13.3,
  "2024-04-20": 22, "2024-04-21": 7.5, "2024-04-22": 10.8, "2024-04-23": 48, "2024-04-24": 11.8,
  "2024-04-25": 20.4, "2024-04-26": 28.8, "2024-04-27": 22, "2024-04-28": 59.2, "2024-04-29": 7.4,
  "2024-04-30": 15.5, "2024-05-01": 54.8, "2024-05-02": 10.6, "2024-05-03": 4.2, "2024-05-04": 24.2,
  "2024-05-05": 17.4, "2024-05-06": 2.4, "2024-05-07": 3.1, "2024-05-08": 2.5, "2024-05-09": 0.2,
  "2024-05-10": 0.5, "2024-05-11": 0.7, "2024-05-12": 15.3, "2024-05-13": 33, "2024-05-14": 1.6,
  "2024-05-15": 0, "2024-05-16": 0, "2024-05-17": 0.1, "2024-05-18": 1.1, "2024-05-19": 26.3,
  "2024-05-20": 43.9, "2024-05-21": 12.4, "2024-05-22": 18, "2024-05-23": 7.8, "2024-05-24": 46.5,
  "2024-05-25": 10.9, "2024-05-26": 7.1, "2024-05-27": 19.7, "2024-05-28": 16, "2024-05-29": 0.6,
  "2024-05-30": 16, "2024-05-31": 5.9, "2024-06-01": 39.3, "2024-06-02": 3.9, "2024-06-03": 13.6,
  "2024-06-04": 13, "2024-06-05": 27.6, "2024-06-06": 5, "2024-06-07": 6.8, "2024-06-08": 17.8,
  "2024-06-09": 10.3, "2024-06-10": 15.6, "2024-06-11": 16.3, "2024-06-12": 6.5, "2024-06-13": 2.6,
  "2024-06-14": 9.1, "2024-06-15": 13.5, "2024-06-16": 11.1, "2024-06-17": 3.5, "2024-06-18": 12.9,
  "2024-06-19": 4, "2024-06-20": 0.6, "2024-06-21": 1.4, "2024-06-22": 0.8, "2024-06-23": 3.6,
  "2024-06-24": 7.8, "2024-06-25": 9.1, "2024-06-26": 2.6, "2024-06-27": 14.1, "2024-06-28": 1.1,
  "2024-06-29": 2.1, "2024-06-30": 2, "2024-07-01": 2.7, "2024-07-02": 2.6, "2024-07-03": 2.8,
  "2024-07-04": 5.1, "2024-07-05": 1.4, "2024-07-06": 1.1, "2024-07-07": 4.2, "2024-07-08": 0.8,
  "2024-07-09": 0.4, "2024-07-10": 1, "2024-07-11": 3.1, "2024-07-12": 2, "2024-07-13": 1.6,
  "2024-07-14": 2.3, "2024-07-15": 4, "2024-07-16": 12.7, "2024-07-17": 6.6, "2024-07-18": 15.5,
  "2024-07-19": 1, "2024-07-20": 2.5, "2024-07-21": 10.7, "2024-07-22": 3.6, "2024-07-23": 1,
  "2024-07-24": 1.7, "2024-07-25": 0.5, "2024-07-26": 6.4, "2024-07-27": 7.2, "2024-07-28": 46.2,
  "2024-07-29": 35, "2024-07-30": 32.4, "2024-07-31": 10.7, "2024-08-01": 3.5, "2024-08-02": 1.5,
  "2024-08-03": 0.1, "2024-08-04": 0.4, "2024-08-05": 4.1, "2024-08-06": 7.4, "2024-08-07": 5.4,
  "2024-08-08": 0.4, "2024-08-09": 0, "2024-08-10": 4.3, "2024-08-11": 2.3, "2024-08-12": 16.3,
  "2024-08-13": 13.1, "2024-08-14": 1.4, "2024-08-15": 7.2, "2024-08-16": 16.6, "2024-08-17": 31.5,
  "2024-08-18": 20.3, "2024-08-19": 15.6, "2024-08-20": 28, "2024-08-21": 34.6, "2024-08-22": 16.9,
  "2024-08-23": 0.3, "2024-08-24": 0.5, "2024-08-25": 3.3, "2024-08-26": 11.9, "2024-08-27": 1.8,
  "2024-08-28": 1.6, "2024-08-29": 25.7, "2024-08-30": 2.6, "2024-08-31": 18, "2024-09-01": 1.9,
  "2024-09-02": 6.1, "2024-09-03": 9.7, "2024-09-04": 13.2, "2024-09-05": 9.5, "2024-09-06": 61.4,
  "2024-09-07": 9.5, "2024-09-08": 4.7, "2024-09-09": 21.5, "2024-09-10": 1.3, "2024-09-11": 0.8,
  "2024-09-12": 1.6, "2024-09-13": 2.5, "2024-09-14": 7.7, "2024-09-15": 1.2, "2024-09-16": 2.5,
  "2024-09-17": 9.5, "2024-09-18": 2.9, "2024-09-19": 0.7, "2024-09-20": 9.3, "2024-09-21": 41.5,
  "2024-09-22": 70.3, "2024-09-23": 32, "2024-09-24": 21.6, "2024-09-25": 1.3, "2024-09-26": 1.6,
  "2024-09-27": 1.8, "2024-09-28": 12.8, "2024-09-29": 1.4, "2024-09-30": 0, "2024-10-01": 0.1,
  "2024-10-02": 0, "2024-10-03": 0, "2024-10-04": 0, "2024-10-05": 0, "2024-10-06": 0,
  "2024-10-07": 0, "2024-10-08": 0.5, "2024-10-09": 0.2, "2024-10-10": 0.1, "2024-10-11": 0.7,
  "2024-10-12": 0.1, "2024-10-13": 0, "2024-10-14": 0.2, "2024-10-15": 0.8, "2024-10-16": 0.8,
  "2024-10-17": 1, "2024-10-18": 1.2, "2024-10-19": 0, "2024-10-20": 2.5, "2024-10-21": 0,
  "2024-10-22": 0, "2024-10-23": 0, "2024-10-24": 0, "2024-10-25": 0, "2024-10-26": 3.3,
  "2024-10-27": 1.1, "2024-10-28": 0, "2024-10-29": 0, "2024-10-30": 0, "2024-10-31": 0,
  "2024-11-01": 0, "2024-11-02": 0, "2024-11-03": 17.9, "2024-11-04": 5.5, "2024-11-05": 0.1,
  "2024-11-06": 0, "2024-11-07": 0.1, "2024-11-08": 0, "2024-11-09": 1.3, "2024-11-10": 1.7,
  "2024-11-11": 0, "2024-11-12": 0, "2024-11-13": 0.4, "2024-11-14": 18.2, "2024-11-15": 2.8,
  "2024-11-16": 3.7, "2024-11-17": 5.5, "2024-11-18": 0, "2024-11-19": 9.5, "2024-11-20": 34.7,
  "2024-11-21": 5.8, "2024-11-22": 0, "2024-11-23": 0.3, "2024-11-24": 1.6, "2024-11-25": 6.9,
  "2024-11-26": 0, "2024-11-27": 0, "2024-11-28": 0, "2024-11-29": 0, "2024-11-30": 0,
  "2024-12-01": 0, "2024-12-02": 0, "2024-12-03": 0, "2024-12-04": 0, "2024-12-05": 0.4,
  "2024-12-06": 0, "2024-12-07": 0, "2024-12-08": 0, "2024-12-09": 0, "2024-12-10": 0,
  "2024-12-11": 0.1, "2024-12-12": 0, "2024-12-13": 0, "2024-12-14": 0, "2024-12-15": 0,
  "2024-12-16": 0, "2024-12-17": 0, "2024-12-18": 0, "2024-12-19": 0, "2024-12-20": 0,
  "2024-12-21": 0, "2024-12-22": 0, "2024-12-23": 0, "2024-12-24": 0, "2024-12-25": 0,
  "2024-12-26": 0, "2024-12-27": 0, "2024-12-28": 0, "2024-12-29": 0, "2024-12-30": 0,
  "2024-12-31": 0, "2025-01-01": 0, "2025-01-02": 0, "2025-01-03": 0, "2025-01-04": 0.3,
  "2025-01-05": 1.3, "2025-01-06": 0, "2025-01-07": 0, "2025-01-08": 0, "2025-01-09": 0,
  "2025-01-10": 0, "2025-01-11": 0, "2025-01-12": 0, "2025-01-13": 0, "2025-01-14": 1.3,
  "2025-01-15": 1.1, "2025-01-16": 0, "2025-01-17": 0, "2025-01-18": 0, "2025-01-19": 0,
  "2025-01-20": 0, "2025-01-21": 1.1, "2025-01-22": 10.2, "2025-01-23": 2.9, "2025-01-24": 0,
  "2025-01-25": 0, "2025-01-26": 1.2, "2025-01-27": 0, "2025-01-28": 0, "2025-01-29": 0,
  "2025-01-30": 0, "2025-01-31": 4.3, "2025-02-01": 2.1, "2025-02-02": 1.1, "2025-02-03": 6.6,
  "2025-02-04": 0, "2025-02-05": 0, "2025-02-06": 0, "2025-02-07": 0, "2025-02-08": 0,
  "2025-02-09": 0, "2025-02-10": 0, "2025-02-11": 0.3, "2025-02-12": 4.4, "2025-02-13": 0.4,
  "2025-02-14": 0, "2025-02-15": 0.7, "2025-02-16": 0.5, "2025-02-17": 0, "2025-02-18": 0,
  "2025-02-19": 0, "2025-02-20": 0, "2025-02-21": 0, "2025-02-22": 2.7, "2025-02-23": 0,
  "2025-02-24": 0, "2025-02-25": 1.1, "2025-02-26": 3, "2025-02-27": 0, "2025-02-28": 0,
  "2025-03-01": 0.3, "2025-03-02": 0.4, "2025-03-03": 0, "2025-03-04": 4.4, "2025-03-05": 2.3,
  "2025-03-06": 16.2, "2025-03-07": 11.3, "2025-03-08": 0, "2025-03-09": 0, "2025-03-10": 0,
  "2025-03-11": 0, "2025-03-12": 0, "2025-03-13": 0.2, "2025-03-14": 0, "2025-03-15": 7.8,
  "2025-03-16": 0, "2025-03-17": 0, "2025-03-18": 0, "2025-03-19": 0, "2025-03-20": 0,
  "2025-03-21": 0, "2025-03-22": 0, "2025-03-23": 0, "2025-03-24": 0, "2025-03-25": 0,
  "2025-03-26": 0, "2025-03-27": 2.4, "2025-03-28": 5.3, "2025-03-29": 2.3, "2025-03-30": 7.1,
  "2025-03-31": 5.6, "2025-04-01": 0.5, "2025-04-02": 0, "2025-04-03": 0, "2025-04-04": 2.6,
  "2025-04-05": 1.1, "2025-04-06": 0, "2025-04-07": 0, "2025-04-08": 0, "2025-04-09": 0.3,
  "2025-04-10": 0.1, "2025-04-11": 1.6, "2025-04-12": 9.2, "2025-04-13": 0, "2025-04-14": 0,
  "2025-04-15": 0, "2025-04-16": 0, "2025-04-17": 0, "2025-04-18": 0.4, "2025-04-19": 2.3,
  "2025-04-20": 0.8, "2025-04-21": 1.7, "2025-04-22": 0.7, "2025-04-23": 1.1, "2025-04-24": 5.7,
  "2025-04-25": 12.5, "2025-04-26": 8.7, "2025-04-27": 4.2, "2025-04-28": 5.2, "2025-04-29": 0,
  "2025-04-30": 0.3, "2025-05-01": 13.3, "2025-05-02": 0.1, "2025-05-03": 9.1, "2025-05-04": 1.4,
  "2025-05-05": 3.3, "2025-05-06": 13, "2025-05-07": 15.1, "2025-05-08": 6.4, "2025-05-09": 2.7,
  "2025-05-10": 9.8, "2025-05-11": 5.8, "2025-05-12": 0, "2025-05-13": 0.6, "2025-05-14": 0.9,
  "2025-05-15": 0.8, "2025-05-16": 5.7, "2025-05-17": 1.7, "2025-05-18": 9.2, "2025-05-19": 3.2,
  "2025-05-20": 4.6, "2025-05-21": 6.6, "2025-05-22": 1.1, "2025-05-23": 4.6, "2025-05-24": 8.7,
  "2025-05-25": 0.1, "2025-05-26": 0.3, "2025-05-27": 0.3, "2025-05-28": 12.6, "2025-05-29": 35,
  "2025-05-30": 7.1, "2025-05-31": 0.9, "2025-06-01": 1, "2025-06-02": 2.4, "2025-06-03": 17.6,
  "2025-06-04": 19.2, "2025-06-05": 1.5, "2025-06-06": 0.1, "2025-06-07": 0.2, "2025-06-08": 0.2,
  "2025-06-09": 1.7, "2025-06-10": 0.5, "2025-06-11": 20.5, "2025-06-12": 27.4, "2025-06-13": 24.3,
  "2025-06-14": 18.9, "2025-06-15": 14.3, "2025-06-16": 28.6, "2025-06-17": 44.9, "2025-06-18": 8.1,
  "2025-06-19": 1.5, "2025-06-20": 10.7, "2025-06-21": 10.7, "2025-06-22": 15.2, "2025-06-23": 1.1,
  "2025-06-24": 0.4, "2025-06-25": 0.1, "2025-06-26": 16, "2025-06-27": 16.8, "2025-06-28": 20.4,
  "2025-06-29": 5.3, "2025-06-30": 19.9, "2025-07-01": 21.8, "2025-07-02": 1.1, "2025-07-03": 1.5,
  "2025-07-04": 1, "2025-07-05": 1.9, "2025-07-06": 1.1, "2025-07-07": 2.8, "2025-07-08": 12.7,
  "2025-07-09": 9.9, "2025-07-10": 21.4, "2025-07-11": 3.1, "2025-07-12": 12.6, "2025-07-13": 0.7,
  "2025-07-14": 12.3, "2025-07-15": 2.5, "2025-07-16": 2.6, "2025-07-17": 3.8, "2025-07-18": 34.1,
  "2025-07-19": 32.9, "2025-07-20": 69.1, "2025-07-21": 44.7, "2025-07-22": 25.8, "2025-07-23": 6.4,
  "2025-07-24": 7, "2025-07-25": 8, "2025-07-26": 7.1, "2025-07-27": 1.5, "2025-07-28": 7.2,
  "2025-07-29": 26.2, "2025-07-30": 11.5, "2025-07-31": 17.2, "2025-08-01": 9.4, "2025-08-02": 21.1,
  "2025-08-03": 8.4, "2025-08-04": 36.6, "2025-08-05": 29.1, "2025-08-06": 25.5, "2025-08-07": 2.8,
  "2025-08-08": 0.3, "2025-08-09": 0, "2025-08-10": 2.7, "2025-08-11": 4.5, "2025-08-12": 2.2,
  "2025-08-13": 4, "2025-08-14": 43.7, "2025-08-15": 32.3, "2025-08-16": 3.9, "2025-08-17": 20,
  "2025-08-18": 34.7, "2025-08-19": 8.5, "2025-08-20": 2.1, "2025-08-21": 1.5, "2025-08-22": 0.2,
  "2025-08-23": 2.8, "2025-08-24": 7.4, "2025-08-25": 2, "2025-08-26": 0.5, "2025-08-27": 4.7,
  "2025-08-28": 16.3, "2025-08-29": 1.4, "2025-08-30": 9.7, "2025-08-31": 2, "2025-09-01": 2.1,
  "2025-09-02": 0.6, "2025-09-03": 1, "2025-09-04": 0.2, "2025-09-05": 0.1, "2025-09-06": 0,
  "2025-09-07": 18.4, "2025-09-08": 65.3, "2025-09-09": 7.4, "2025-09-10": 14.9, "2025-09-11": 0.9,
  "2025-09-12": 0.9, "2025-09-13": 0.2, "2025-09-14": 0.2, "2025-09-15": 1.5, "2025-09-16": 13.5,
  "2025-09-17": 2.8, "2025-09-18": 2.7, "2025-09-19": 3.6, "2025-09-20": 15.1, "2025-09-21": 42.7,
  "2025-09-22": 0.7, "2025-09-23": 2.4, "2025-09-24": 85.2, "2025-09-25": 24.7, "2025-09-26": 3.5,
  "2025-09-27": 2.5, "2025-09-28": 7.2, "2025-09-29": 1.3, "2025-09-30": 0, "2025-10-01": 0.1,
  "2025-10-02": 1, "2025-10-03": 0.1, "2025-10-04": 15.5, "2025-10-05": 23.4, "2025-10-06": 0.8,
  "2025-10-07": 0, "2025-10-08": 0.8, "2025-10-09": 0.9, "2025-10-10": 1.1, "2025-10-11": 1,
  "2025-10-12": 18.6, "2025-10-13": 5.3, "2025-10-14": 1.1, "2025-10-15": 0.2, "2025-10-16": 3.5,
  "2025-10-17": 0.2, "2025-10-18": 0.3, "2025-10-19": 2.5, "2025-10-20": 0.6, "2025-10-21": 8.6,
  "2025-10-22": 16.8, "2025-10-23": 2.5, "2025-10-24": 0.5, "2025-10-25": 0, "2025-10-26": 0,
  "2025-10-27": 4.8, "2025-10-28": 1.9, "2025-10-29": 0.9, "2025-10-30": 0, "2025-10-31": 0,
  "2025-11-01": 2.6, "2025-11-02": 0, "2025-11-03": 0.1, "2025-11-04": 0.2, "2025-11-05": 0,
  "2025-11-06": 0.5, "2025-11-07": 1.8, "2025-11-08": 0.3, "2025-11-09": 0, "2025-11-10": 0,
  "2025-11-11": 0, "2025-11-12": 0, "2025-11-13": 0.4, "2025-11-14": 0.3, "2025-11-15": 0,
  "2025-11-16": 0, "2025-11-17": 0, "2025-11-18": 0.5, "2025-11-19": 2.4, "2025-11-20": 0.1,
  "2025-11-21": 0, "2025-11-22": 0, "2025-11-23": 0, "2025-11-24": 0, "2025-11-25": 0,
  "2025-11-26": 0, "2025-11-27": 0, "2025-11-28": 0, "2025-11-29": 0, "2025-11-30": 0,
  "2025-12-01": 0.4, "2025-12-02": 1.2, "2025-12-03": 3.8, "2025-12-04": 0, "2025-12-05": 0.1,
  "2025-12-06": 0.1, "2025-12-07": 0, "2025-12-08": 0, "2025-12-09": 0, "2025-12-10": 1.5,
  "2025-12-11": 0, "2025-12-12": 0, "2025-12-13": 3.6, "2025-12-14": 0, "2025-12-15": 0,
  "2025-12-16": 0, "2025-12-17": 0, "2025-12-18": 0, "2025-12-19": 12.1, "2025-12-20": 2.3,
  "2025-12-21": 0, "2025-12-22": 0.2, "2025-12-23": 1.2, "2025-12-24": 0, "2025-12-25": 0,
  "2025-12-26": 0, "2025-12-27": 0, "2025-12-28": 0.3, "2025-12-29": 0, "2025-12-30": 0,
  "2025-12-31": 0.3, "2026-01-01": 0, "2026-01-02": 0, "2026-01-03": 0, "2026-01-04": 0,
  "2026-01-05": 0, "2026-01-06": 0, "2026-01-07": 0, "2026-01-08": 0, "2026-01-09": 0,
  "2026-01-10": 0, "2026-01-11": 0, "2026-01-12": 0, "2026-01-13": 0, "2026-01-14": 0,
  "2026-01-15": 0, "2026-01-16": 0, "2026-01-17": 0, "2026-01-18": 0, "2026-01-19": 0,
  "2026-01-20": 0.3, "2026-01-21": 0, "2026-01-22": 0, "2026-01-23": 0, "2026-01-24": 0,
  "2026-01-25": 0, "2026-01-26": 0, "2026-01-27": 0, "2026-01-28": 0.2, "2026-01-29": 1.4,
  "2026-01-30": 2.1, "2026-01-31": 4.4, "2026-02-01": 0.1, "2026-02-02": 0, "2026-02-03": 0,
  "2026-02-04": 0, "2026-02-05": 0, "2026-02-06": 0, "2026-02-07": 0.5, "2026-02-08": 0.2,
  "2026-02-09": 0, "2026-02-10": 0, "2026-02-11": 0, "2026-02-12": 0.1, "2026-02-13": 0,
  "2026-02-14": 0, "2026-02-15": 0.2, "2026-02-16": 0.3, "2026-02-17": 0.9, "2026-02-18": 0,
  "2026-02-19": 0.1, "2026-02-20": 0, "2026-02-21": 0, "2026-02-22": 0.5, "2026-02-23": 0,
  "2026-02-24": 0.1, "2026-02-25": 0.1, "2026-02-26": 0.9, "2026-02-27": 4.1, "2026-02-28": 8.9,
  "2026-03-01": 0.6, "2026-03-02": 5.8, "2026-03-03": 13.4, "2026-03-04": 20.8, "2026-03-05": 0.2,
  "2026-03-06": 0, "2026-03-07": 0.1, "2026-03-08": 0, "2026-03-09": 3, "2026-03-10": 3.1,
  "2026-03-11": 0.4, "2026-03-12": 0, "2026-03-13": 0, "2026-03-14": 0, "2026-03-15": 0,
  "2026-03-16": 0, "2026-03-17": 1, "2026-03-18": 0.1, "2026-03-19": 0, "2026-03-20": 1,
  "2026-03-21": 0.4, "2026-03-22": 0, "2026-03-23": 0, "2026-03-24": 0.6, "2026-03-25": 0,
  "2026-03-26": 0.3, "2026-03-27": 1.6, "2026-03-28": 4.6, "2026-03-29": 2.1, "2026-03-30": 0.6,
  "2026-03-31": 4.1, "2026-04-01": 0.4, "2026-04-02": 7.9, "2026-04-03": 7.7, "2026-04-04": 28.5,
  "2026-04-05": 24.5, "2026-04-06": 10.2, "2026-04-07": 0.4, "2026-04-08": 3.8, "2026-04-09": 1.3,
  "2026-04-10": 0.4, "2026-04-11": 0.9, "2026-04-12": 1.3, "2026-04-13": 0.6, "2026-04-14": 1.4,
  "2026-04-15": 2.7, "2026-04-16": 0.4, "2026-04-17": 10, "2026-04-18": 0.4, "2026-04-19": 0,
  "2026-04-20": 4.8, "2026-04-21": 0.6, "2026-04-22": 0.2, "2026-04-23": 5.5, "2026-04-24": 52.5,
  "2026-04-25": 0, "2026-04-26": 0.6, "2026-04-27": 0.5, "2026-04-28": 14.6, "2026-04-29": 23.7,
  "2026-04-30": 0, "2026-05-01": 1, "2026-05-02": 1.8, "2026-05-03": 34.9, "2026-05-04": 1.1,
  "2026-05-05": 39.6, "2026-05-06": 0.2
};
console.log(`   ✅ ${Object.keys(rainfall).length} 天降雨資料\n`);

// === 3. 每日消費資料 ===
console.log('📊 處理每日消費資料...');
const consFiles = fs.readdirSync(CONS_DIR).filter(f=>f.endsWith('.xlsx')).sort();
const hourCols = Array.from({length:24},(_,i)=>`${String(i).padStart(2,'0')}:00`);

// 聚合容器
const dailySummary = {};   // date -> dmas
const dailyTop20 = {};      // date -> top20
const dailyTop20ByDma = {}; // date -> byDma
const monthlyMainSub = {};  // month -> { meterId -> accumulated }
const dailyTotalByDma = {}; // date -> { dma -> total } 用於趨勢圖
const meterDailyRank = {};  // meterId -> [{ date, rank, total }] 用於排名追蹤
const cotaiCalendar = {};   // date -> [{ meterId, total, buildingName, contractId }] 路氹非住宅
const meterMonthly = {};    // meterId -> { month -> total } 水表月度匯總

// 用於追蹤每個水表的首次出現日期（過濾初始讀值）

const fullMeterDaily = {};   // meterId -> { date -> value } — 從所有 consumption 構建
let days = 0, records = 0;

for (const fname of consFiles) {
  const dateStr = fname.replace('.xlsx','');
  const monthStr = dateStr.substring(0,7);
  const rain = rainfall[dateStr] || 0;
  
  const wb = XLSX.readFile(path.join(CONS_DIR, fname));
  const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1 });
  if (rows.length < 2) continue;
  
  const headers = rows[0];
  const mi = headers.indexOf('錶位編號');
  const hi = hourCols.map(h=>headers.indexOf(h)).filter(i=>i!==-1);
  if (mi===-1 || hi.length===0) continue;
  
  const dayUsage = {};
  const dayMeters = [];
  
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i], mid = String(r[mi]||'').trim();
    if (!mid) continue;
    let total = 0;
    for (const h of hi) { const v=Number(r[h])||0; if(v>0) total+=v; }
    if (total < 0) continue;
    // 消費資料單位是升，轉換為立方米
    total = total / 1000;
    // 過濾極端異常值：負數、Infinity、超過30000m³/天的極端值
    if (total < 0 || !isFinite(total) || total > 30000) continue;
    dayUsage[mid] = total;
    // 累计月度水表用水
    if (!meterMonthly[mid]) meterMonthly[mid] = {};
    meterMonthly[mid][monthStr] = (meterMonthly[mid][monthStr] || 0) + total;
    const info = meterInfo[mid] || { dma:'未分類', propertyType:'', isResidential:true, contractId:'', buildingName:'', supplyMode:'DIRECT', mainCode:null };
    dayMeters.push({ meterId:mid, total, dma:info.dma, propertyType:info.propertyType, isResidential:info.isResidential, contractId:info.contractId, buildingName:info.buildingName, supplyMode:info.supplyMode, mainCode:info.mainCode });
    records++;
    // 累积完整 meterDaily（所有水表）
    if (!fullMeterDaily[mid]) fullMeterDaily[mid] = {};
    fullMeterDaily[mid][dateStr] = total;
  }
  
  // DMA匯總
  const ds = {};
  for (const m of dayMeters) {
    if (!ds[m.dma]) ds[m.dma] = { total:0, residential:0, nonResidential:0, resCount:0, nonResCount:0, meterCount:0, rain };
    const d = ds[m.dma];
    d.total += m.total; d.meterCount++;
    if (m.isResidential) { d.residential += m.total; d.resCount++; }
    else { d.nonResidential += m.total; d.nonResCount++; }
  }
  dailySummary[dateStr] = ds;
  dailyTotalByDma[dateStr] = {};
  for (const [dma, v] of Object.entries(ds)) dailyTotalByDma[dateStr][dma] = Math.round(v.total);
  
  // Top20
  dayMeters.sort((a,b)=>b.total-a.total);
  dailyTop20[dateStr] = dayMeters.slice(0,50).map(m=>({meterId:m.meterId,total:Math.round(m.total),dma:m.dma,contractId:m.contractId,propertyType:m.propertyType,buildingName:m.buildingName}));
  
  // 分DMA Top20
  const byDma = {};
  for (const m of dayMeters) { if(!byDma[m.dma]) byDma[m.dma]=[]; byDma[m.dma].push(m); }
  const t20d = {};
  for (const [dma, meters] of Object.entries(byDma)) {
    meters.sort((a,b)=>b.total-a.total);
    t20d[dma] = meters.slice(0,50).map(m=>({meterId:m.meterId,total:Math.round(m.total),contractId:m.contractId,propertyType:m.propertyType,buildingName:m.buildingName}));
  }
  dailyTop20ByDma[dateStr] = t20d;
  
  // 月度主分表累加
  if (!monthlyMainSub[monthStr]) monthlyMainSub[monthStr] = {};
  const mainsAddedToday = new Set(); // 防止主表被重复累加
  for (const m of dayMeters) {
    if (m.mainCode && codeToMeter[m.mainCode]) {
      const mainId = codeToMeter[m.mainCode];
      if (!monthlyMainSub[monthStr][mainId]) {
        const mi2 = meterInfo[mainId]||{};
        monthlyMainSub[monthStr][mainId] = { mainMeterId:mainId, mainContractId:mi2.contractId||'', mainBuilding:mi2.buildingName||'', dma:mi2.dma||'未分類', subCount:0, mainMonthTotal:0, subMonthTotal:0, subs:new Set() };
      }
      // 主表當日用量只加一次（防重複累加），並過濾異常值
      if (!mainsAddedToday.has(mainId)) {
        const mainDaily = dayUsage[mainId] || 0;
        const mainFiltered = mainDaily > 5000 ? 0 : mainDaily;
        monthlyMainSub[monthStr][mainId].mainMonthTotal += mainFiltered;
        mainsAddedToday.add(mainId);
      }
      monthlyMainSub[monthStr][mainId].subMonthTotal += m.total;
      monthlyMainSub[monthStr][mainId].subs.add(m.meterId);
    }
  }
  
  // 路氹城非住宅日曆資料（用charCode匹配避免編碼問題）
  const cotaiNonRes = dayMeters.filter(m => (m.dma.charCodeAt(1)===0xebf3 || m.dma.includes('路氹') || m.dma.includes('氹城')) && !m.isResidential);
  if (cotaiNonRes.length) {
    cotaiCalendar[dateStr] = cotaiNonRes.map(m=>({
      meterId:m.meterId, total:Math.round(m.total), buildingName:m.buildingName||m.contractId, contractId:m.contractId
    }));
  }
  
  days++;
  if (days % 30 === 0) console.log(`   ${days} 天...`);
}
console.log(`   ✅ ${days} 天, ${records} 條記錄\n`);

// === 初始讀值異常過濾 ===
console.log('🔍 檢測初始讀值異常（首日消費 > 後續均值 × 10）...');

// 使用完整 meterDaily（已在讀取 consumption 時構建 fullMeterDaily）
const meterDailyAll = fullMeterDaily;

// 檢測並過濾初始讀值異常（只有首日異常高的才過濾）
const initialReadingMeters = new Set();
for (const [meterId, daily] of Object.entries(meterDailyAll)) {
  const dates = Object.keys(daily).sort();
  if (dates.length < 3) continue; // 至少需要3天資料
  
  const firstDate = dates[0];
  const firstVal = daily[firstDate];
  
  // 計算後續日期的平均值（排除首日）
  const laterVals = dates.slice(1).map(d => daily[d]).filter(v => v > 0);
  if (laterVals.length < 2) continue;
  
  const avgLater = laterVals.reduce((a, b) => a + b, 0) / laterVals.length;
  
  // 只有首日值是后续均值的10倍以上，才标记为初始读值异常
  if (avgLater > 0 && firstVal > avgLater * 10) {
    initialReadingMeters.add({ meterId, firstDate, firstVal, avgLater });
  }
}

// 过滤异常的初始读值
let filteredCount = 0;
for (const { meterId, firstDate } of initialReadingMeters) {
  // 從 dailyTop20 中移除
  if (dailyTop20[firstDate]) {
    const before = dailyTop20[firstDate].length;
    dailyTop20[firstDate] = dailyTop20[firstDate].filter(m => m.meterId !== meterId);
    if (before > dailyTop20[firstDate].length) filteredCount++;
  }
  // 從 dailyTop20ByDma 中移除
  if (dailyTop20ByDma[firstDate]) {
    for (const dma of Object.keys(dailyTop20ByDma[firstDate])) {
      dailyTop20ByDma[firstDate][dma] = dailyTop20ByDma[firstDate][dma].filter(m => m.meterId !== meterId);
    }
  }
  // 從 meterDailyAll 中移除首日
  delete meterDailyAll[meterId][firstDate];
}
console.log(`   ✅ 發現 ${initialReadingMeters.size} 個初始讀值異常，過濾了 ${filteredCount} 條記錄\n`);

// === 4. 排名變化追蹤 ===
console.log('📈 計算排名變化...');
// 收集每个水表在哪些天进入Top20
const rankTracker = {}; // meterId -> { count, avgRank, avgTotal, entries:[] }
const allTop20Dates = Object.keys(dailyTop20).sort();
for (const date of allTop20Dates) {
  dailyTop20[date].forEach((m, idx) => {
    if (!rankTracker[m.meterId]) rankTracker[m.meterId] = { meterId:m.meterId, contractId:m.contractId, buildingName:m.buildingName, dma:m.dma, propertyType:m.propertyType, count:0, totalSum:0, ranks:[] };
    const t = rankTracker[m.meterId];
    t.count++; t.totalSum += m.total; t.ranks.push(idx+1);
  });
}
// 转换为数组并排序
const rankChanges = Object.values(rankTracker).map(t => ({
  meterId: t.meterId,
  contractId: t.contractId,
  buildingName: t.buildingName,
  dma: t.dma,
  propertyType: t.propertyType,
  daysInTop20: t.count,
  avgTotal: Math.round(t.totalSum / t.count),
  avgRank: Math.round(t.ranks.reduce((a,b)=>a+b,0) / t.ranks.length * 10) / 10,
  trend: t.ranks.length >= 3 ? (t.ranks[t.ranks.length-1] < t.ranks[0] ? '↑' : t.ranks[t.ranks.length-1] > t.ranks[0] ? '↓' : '→') : '-'
})).sort((a,b) => b.daysInTop20 - a.daysInTop20);
console.log(`   ✅ ${rankChanges.length} 個水表進入過Top50\n`);

// === 5. 月度差額（含每日資料）===
console.log('💰 月度主分表差額...');
const allDates = Object.keys(dailySummary).sort();

// 构建最终的 meterDaily（包含所有水表的每日数据）
// 构建最终的 meterDaily（所有水表，用于异常检测和曲线弹窗）
const meterDaily = {};
for (const [meterId, daily] of Object.entries(fullMeterDaily)) {
  if (Object.keys(daily).length > 0) {
    meterDaily[meterId] = daily;
  }
}

// 從 daily_by_date 載入每日資料並預聚合
const dailyByDate = {};
const dailyByDateDir = path.resolve(__dirname, '../../public/data/daily_by_date');
if (fs.existsSync(dailyByDateDir)) {
  const dailyFiles = fs.readdirSync(dailyByDateDir).filter(f => f.endsWith('.json')).sort();
  console.log(`   📂 載入 ${dailyFiles.length} 天的日資料...`);
  
  for (const file of dailyFiles) {
    const dateStr = file.replace('.json', '');
    const dayData = JSON.parse(fs.readFileSync(path.join(dailyByDateDir, file), 'utf8'));
    
    // 构建 meterId -> total 的映射
    dailyByDate[dateStr] = {};
    dayData.forEach(m => {
      dailyByDate[dateStr][m.meterId] = m.total;
    });
  }
  console.log(`   ✅ 載入完成\n`);
}

const monthlyDiffArr = [];
for (const [month, meters] of Object.entries(monthlyMainSub)) {
  const diffs = Object.values(meters).map(m => {
    const subIds = Array.from(m.subs);
    const mainId = m.mainMeterId;
    
    // 獲取該月所有日期（從 allDates 中篩選）
    const allMonthDates = allDates.filter(d => d.startsWith(month));
    
    // 使用 meterDaily 获取主表日数据
    const mainMeterDaily = meterDaily[mainId] || {};
    
    // 計算每日資料
    const dailyData = {};
    
    // 检查是否有实际日数据
    let hasRealDailyData = false;
    
    // 計算分表日均值（用於沒有日資料的分表）
    const subDailyAvg = allMonthDates.length > 0 ? Math.round(m.subMonthTotal / allMonthDates.length) : 0;
    
    allMonthDates.forEach(date => {
      // 优先使用 meterDaily 的数据（已转换为立方米）
      const mainDaily = mainMeterDaily[date] || 0;
      
      // 嘗試從 dailyByDate 獲取分表資料，如果沒有則使用日均值
      let subDaily = 0;
      const dayData = dailyByDate[date] || {};
      let hasSubDailyData = false;
      
      subIds.forEach(subId => {
        const subVal = (dayData[subId] || 0) / 1000; // 升转立方米
        if (subVal > 0) hasSubDailyData = true;
        subDaily += subVal;
      });
      
      // 如果没有分表日数据，使用日均值
      if (!hasSubDailyData) {
        subDaily = subDailyAvg;
      }
      
      if (mainDaily > 0 || subDaily > 0) hasRealDailyData = true;
      
      dailyData[date] = {
        main: Math.round(mainDaily),
        sub: Math.round(subDaily),
        diff: Math.round(mainDaily - subDaily)
      };
    });
    
    // 如果没有实际日数据，使用月总量按日均分
    if (!hasRealDailyData && allMonthDates.length > 0) {
      const mainDailyAvg = Math.round(m.mainMonthTotal / allMonthDates.length);
      const subDailyAvg = Math.round(m.subMonthTotal / allMonthDates.length);
      
      allMonthDates.forEach(date => {
        dailyData[date] = {
          main: mainDailyAvg,
          sub: subDailyAvg,
          diff: mainDailyAvg - subDailyAvg
        };
      });
    }
    
    return {
      mainMeterId: mainId,
      mainContractId: m.mainContractId,
      mainBuilding: m.mainBuilding,
      dma: m.dma,
      subs: subIds,
      subCount: m.subs.size,
      mainMonthTotal: Math.round(m.mainMonthTotal),
      subMonthTotal: Math.round(m.subMonthTotal),
      diff: Math.round(m.mainMonthTotal - m.subMonthTotal),
      diffPct: m.mainMonthTotal > 0 ? Math.round((m.mainMonthTotal - m.subMonthTotal) / m.mainMonthTotal * 1000) / 10 : 0,
      daily: dailyData,
      hasRealData: hasRealDailyData  // 标记是否有实际日数据
    };
  }).filter(m => m.subCount > 0 && m.mainMonthTotal > 0)
    .sort((a,b) => Math.abs(b.diff) - Math.abs(a.diff));
  
  monthlyDiffArr.push({ month, diffs });
}
monthlyDiffArr.sort((a,b) => a.month.localeCompare(b.month));
console.log(`   ✅ ${monthlyDiffArr.length} 個月\n`);

// === 6. 異常檢測 ===

console.log('🚨 異常檢測...');
// -----------------------------------------------------------
// 异常检测 v3：参考 用水異常.py 重构
// - 滚动14天窗口基准（避免均值被历史稀释）
// - Z-score + tanh 压缩得到有界异常指数 [0,1]
// - 双阈值：同时满足 mean+2std AND mean×multiplier
// - 三类型：暴增(spike)/暴跌(drop)/归零(zero)
// -----------------------------------------------------------

const anomalies = []; // { date, meterId, total, contractId, buildingName, dma, reason, type, anomalyScore, pastMean, pastStd }

// ---------- 配置参数 ----------
const WINDOW_DAYS = 14;       // 滚动窗口天数
const SPIKE_MULT = 4.0;       // 暴增倍数阈值（需同时满足 mean+2std 和 mean×6）
const DROP_PCT = 0.40;        // 暴跌：当前 < 均值 × (1-DROP_PCT)，即降幅>40%
const DROP_ABS = 20;          // 暴跌：绝对降幅需 >20m³（避免小波动误报）
const ZERO_SCORE = 0.1;       // 归零判定阈值
const MIN_WINDOW_DATA = 5;    // 窗口最少需要的数据点
const MIN_DROP_MEAN = 5;      // drop检测最小水表均值（<5m³的水表太容易波动，跳过）
const MIN_ANOMALY_SCORE = 0.25; // 所有类型的最小异常分数（过滤边缘情况）

// ---------- 辅助：tanH 压缩 z-score -> [0,1] ----------
function tanhZ(z) {
    // 保护溢出：z 超过 700 时 exp 会溢出到 Infinity
    if (z > 700) return 1.0;
    if (z < -700) return 0.0;
    const e = Math.exp(2 * z / 3);
    return e / (e + 1);
}

// ---------- 检测所有水表在所有日期 ----------
const sortedDates = allDates.sort();
const meterIds = Object.keys(meterDaily); // 所有有记录的水表

for (const mid of meterIds) {
    const daily = meterDaily[mid]; // { date -> total(m3) }
    const dates = Object.keys(daily).sort();
    if (dates.length < 3) continue;

    // 获取该水表在 allDates 中的位置映射
    const dateIndexMap = {};
    dates.forEach((d, idx) => { dateIndexMap[d] = idx; });

    for (const dateStr of dates) {
        const idx = dateIndexMap[dateStr];
        if (idx < 0) continue;

        // 构建过去WINDOW_DAYS天的窗口（不含当天）
        const windowStart = Math.max(0, idx - WINDOW_DAYS);
        const windowDates = dates.slice(windowStart, idx);
        const pastUsages = windowDates.map(d => daily[d]).filter(v => v !== undefined && v > 0);

        if (pastUsages.length < MIN_WINDOW_DATA) continue;

        const pastMean = pastUsages.reduce((s, v) => s + v, 0) / pastUsages.length;
        const pastStd = Math.sqrt(pastUsages.reduce((s, v) => s + Math.pow(v - pastMean, 2), 0) / pastUsages.length);
        const currentUsage = daily[dateStr];

        let anomalyType = null;
        let reason = '';
        let anomalyScore = 0;

        // ---- 计算异常指数（tanh压缩z-score）----
        if (pastStd > 0) {
            const z = (currentUsage - pastMean) / pastStd;
            anomalyScore = Math.round(tanhZ(z) * 1000) / 1000; // [0,1]
        }

        // ---- 归零检测 ----
        if (currentUsage <= ZERO_SCORE) {
            if (pastMean > 10 && pastUsages.every(v => v > ZERO_SCORE)) {
                anomalyType = 'zero';
                reason = `归零: 今日${currentUsage}m³，窗口均值${Math.round(pastMean)}m³`;
            }
        }
        // ---- 暴增检测（双阈值）----
        else if (pastMean > 10) {
            const upper = pastMean + 2 * pastStd;
            const spikeThresh = pastMean * SPIKE_MULT;
            if (currentUsage > spikeThresh && anomalyScore >= MIN_ANOMALY_SCORE) {
                anomalyType = 'spike';
                reason = `暴增: ${Math.round(currentUsage)}m³，较14天均值${Math.round(pastMean)}m³上升${((currentUsage/pastMean-1)*100).toFixed(0)}%`;
            }
            // ---- 暴跌检测（高用水量水表）----
            else if (pastMean >= 50) {
                const dropPct = (pastMean - currentUsage) / pastMean;
                const dropAbs = pastMean - currentUsage;
                // 同时满足：降幅>40% AND 绝对降幅>20m³ AND anomalyScore>=0.25
                if (dropPct > DROP_PCT && dropAbs > DROP_ABS && anomalyScore >= MIN_ANOMALY_SCORE) {
                    anomalyType = 'drop';
                    reason = `暴跌: ${Math.round(currentUsage)}m³，较均值${Math.round(pastMean)}m³下降${Math.round(dropPct*100)}%`;
                }
            }
        }
        // ---- 暴增检测（低用水量水表，均值<10m³）----
        if (!anomalyType && pastMean < 10) {
            // 纯倍数检测：当前值 > 均值 × 10 且至少 50m³
            if (currentUsage > pastMean * 10 && currentUsage > 50 && anomalyScore >= MIN_ANOMALY_SCORE) {
                anomalyType = 'spike';
                reason = `暴增: ${Math.round(currentUsage)}m³，较均值${pastMean.toFixed(1)}m³上升${((currentUsage/pastMean-1)*100).toFixed(0)}%`;
            }
        }
        // ---- 暴跌检测（低用水量水表，均值5~50m³）----
        if (!anomalyType && pastMean >= MIN_DROP_MEAN && pastMean < 50) {
            const dropPct = (pastMean - currentUsage) / pastMean;
            const dropAbs = pastMean - currentUsage;
            // 纯百分比检测：降幅>70% 且至少降了2m³
            if (dropPct > 0.70 && dropAbs > 2 && anomalyScore >= MIN_ANOMALY_SCORE) {
                anomalyType = 'drop';
                reason = `暴跌: ${currentUsage.toFixed(1)}m³，较均值${pastMean.toFixed(1)}m³下降${Math.round(dropPct*100)}%`;
            }
        }

        if (!anomalyType) continue;

        // 获取水表信息
        const info = (dailyTop20[dateStr] || []).find(m => m.meterId === mid)
            || (meterInfo[mid] || {});

        anomalies.push({
            date: dateStr,
            meterId: mid,
            total: Math.round(currentUsage),
            contractId: info.contractId || '',
            dma: info.dma || '',
            buildingName: info.buildingName || '',
            reason,
            type: anomalyType,
            anomalyScore,          // 0-1 有界分数
            pastMean: Math.round(pastMean * 10) / 10,
            pastStd: Math.round(pastStd * 10) / 10,
            windowDays: pastUsages.length
        });
    }
}

// ---------- 持续异常降级为"关注" ----------
// 同一水表同月触发>=8次 -> 降级为 watch（正常用水模式）
const meterMonthCount = {};
for (const a of anomalies) {
    const key = `${a.meterId}@${a.date.substring(0,7)}`;
    if (!meterMonthCount[key]) meterMonthCount[key] = [];
    meterMonthCount[key].push(a);
}
for (const records of Object.values(meterMonthCount)) {
    if (records.length >= 8) {
        records.forEach(r => {
            r.type = 'watch';
            r.reason = r.reason.replace('暴增', '关注（持续高用水）').replace('归零', '关注（间歇归零）');
        });
    }
}

// ---------- 去重 ----------
const seen = new Set();
anomalies.splice(0, anomalies.length, ...anomalies.filter(a => {
    const k = `${a.date}@${a.meterId}@${a.type}`;
    if (seen.has(k)) return false;
    seen.add(k); return true;
}));

// 按日期排序
anomalies.sort((a, b) => a.date.localeCompare(b.date));

const countByType = ['spike', 'drop', 'zero', 'watch'].map(t =>
    `${t}=${anomalies.filter(a => a.type === t).length}`
).join(', ');

console.log(` ✅ ${anomalies.length} 條異常 (${countByType})
`);



// === 7. 水表搜尋索引 ===
const searchIndex = Object.entries(meterInfo).map(([id, info]) => ({
  id, contract: info.contractId, building: info.buildingName, dma: info.dma, type: info.propertyType
}));

// === 7. 週資料（用於對比分析）===
console.log('📊 計算週資料...');
const weekData = {};

for (const date of allDates) {
  const d = new Date(date);
  const dayOfWeek = d.getDay() || 7; // 1=Mon...7=Sun
  const monday = new Date(d);
  monday.setDate(d.getDate() - dayOfWeek + 1);
  const weekKey = monday.toISOString().slice(0,10);
  
  if (!weekData[weekKey]) {
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    weekData[weekKey] = {
      weekStart: weekKey,
      weekEnd: sunday.toISOString().slice(0,10),
      dates: [],
      totalByDma: {},
      weekdayTotal: 0, weekdayDays: 0,
      weekendTotal: 0, weekendDays: 0,
      wdByDmaRes: {},
      dailyTotals: [],
      rain: 0
    };
  }
  
  const w = weekData[weekKey];
  w.dates.push(date);
  w.rain += (rainfall[date] || 0);
  
  let dayGrandTotal = 0;
  const dmas = dailySummary[date];
  if (dmas) {
    for (const [dma, v] of Object.entries(dmas)) {
      w.totalByDma[dma] = (w.totalByDma[dma] || 0) + v.total;
      dayGrandTotal += v.total;
      
      // 工作日/周末 + 住宅/非住宅
      if (!w.wdByDmaRes[dma]) w.wdByDmaRes[dma] = { resWd:0, resWdD:0, resWe:0, resWeD:0, nonResWd:0, nonResWdD:0, nonResWe:0, nonResWeD:0 };
      const dd = w.wdByDmaRes[dma];
      const isWeekend = dayOfWeek >= 6;
      if (!isWeekend) {
        dd.resWd += v.residential; dd.resWdD++;
        dd.nonResWd += v.nonResidential; dd.nonResWdD++;
      } else {
        dd.resWe += v.residential; dd.resWeD++;
        dd.nonResWe += v.nonResidential; dd.nonResWeD++;
      }
    }
    
    const isWeekend = dayOfWeek >= 6;
    if (isWeekend) { w.weekendTotal += dayGrandTotal; w.weekendDays++; }
    else { w.weekdayTotal += dayGrandTotal; w.weekdayDays++; }
  }
  
  w.dailyTotals.push({ date, total: dayGrandTotal, rain: rainfall[date] || 0 });
}

const weeklyArr = Object.values(weekData).sort((a,b) => a.weekStart.localeCompare(b.weekStart)).map(w => {
  const totalByDmaRounded = {};
  for (const [k,v] of Object.entries(w.totalByDma)) totalByDmaRounded[k] = Math.round(v);
  
  const wdByDmaResOut = {};
  for (const [dma, v] of Object.entries(w.wdByDmaRes)) {
    wdByDmaResOut[dma] = {
      resWdAvg: v.resWdD > 0 ? Math.round(v.resWd / v.resWdD) : 0,
      resWeAvg: v.resWeD > 0 ? Math.round(v.resWe / v.resWeD) : 0,
      nonResWdAvg: v.nonResWdD > 0 ? Math.round(v.nonResWd / v.nonResWdD) : 0,
      nonResWeAvg: v.nonResWeD > 0 ? Math.round(v.nonResWe / v.nonResWeD) : 0
    };
  }
  
  const label = w.weekStart.slice(5) + ' ~ ' + w.weekEnd.slice(5);
  
  return {
    weekStart: w.weekStart,
    weekEnd: w.weekEnd,
    label,
    dates: w.dates,
    totalByDma: totalByDmaRounded,
    weekdayAvg: w.weekdayDays > 0 ? Math.round(w.weekdayTotal / w.weekdayDays) : 0,
    weekendAvg: w.weekendDays > 0 ? Math.round(w.weekendTotal / w.weekendDays) : 0,
    wdByDmaRes: wdByDmaResOut,
    rain: Math.round(w.rain * 10) / 10,
    dailyTotals: w.dailyTotals
  };
});
console.log(`   ✅ ${weeklyArr.length} 週\n`);

// === 寫入JSON ===
console.log('💾 寫入JSON...');

fs.writeFileSync(path.join(OUT_DIR, 'meter_info.json'), JSON.stringify(meterInfo));

// DMA每日汇总（含降雨）
const summaryArr = Object.entries(dailySummary).sort(([a],[b])=>a.localeCompare(b)).map(([date,dmas])=>({date,dmas,rain:rainfall[date]||0}));
fs.writeFileSync(path.join(OUT_DIR, 'daily_dma.json'), JSON.stringify(summaryArr));

fs.writeFileSync(path.join(OUT_DIR, 'daily_top20.json'), JSON.stringify(Object.entries(dailyTop20).sort(([a],[b])=>a.localeCompare(b)).map(([date,top20])=>({date,top20}))));

fs.writeFileSync(path.join(OUT_DIR, 'daily_top20_by_dma.json'), JSON.stringify(Object.entries(dailyTop20ByDma).sort(([a],[b])=>a.localeCompare(b)).map(([date,byDma])=>({date,byDma}))));

fs.writeFileSync(path.join(OUT_DIR, 'monthly_main_sub_diff.json'), JSON.stringify(monthlyDiffArr));

fs.writeFileSync(path.join(OUT_DIR, 'rank_changes.json'), JSON.stringify(rankChanges));

fs.writeFileSync(path.join(OUT_DIR, 'anomalies.json'), JSON.stringify(anomalies));

fs.writeFileSync(path.join(OUT_DIR, 'cotai_calendar.json'), JSON.stringify(Object.entries(cotaiCalendar).sort(([a],[b])=>a.localeCompare(b)).map(([date,items])=>({date,items}))));

fs.writeFileSync(path.join(OUT_DIR, 'daily_total_by_dma.json'), JSON.stringify(Object.entries(dailyTotalByDma).sort(([a],[b])=>a.localeCompare(b)).map(([date,dmas])=>({date,dmas,rain:rainfall[date]||0}))));

fs.writeFileSync(path.join(OUT_DIR, 'search_index.json'), JSON.stringify(searchIndex));

fs.writeFileSync(path.join(OUT_DIR, 'available_dates.json'), JSON.stringify(Object.keys(dailySummary).sort()));

// 合并全部数据（供单文件HTML使用）
const allData = {
  dma: summaryArr,
  top20: Object.entries(dailyTop20).sort(([a],[b])=>a.localeCompare(b)).map(([date,top20])=>({date,top20})),
  top20dma: Object.entries(dailyTop20ByDma).sort(([a],[b])=>a.localeCompare(b)).map(([date,byDma])=>({date,byDma})),
  diff: monthlyDiffArr,
  dates: Object.keys(dailySummary).sort(),
  rank: rankChanges.slice(0, 50),
  anomalies: anomalies,
  cotai: Object.entries(cotaiCalendar).sort(([a],[b])=>a.localeCompare(b)).map(([date,items])=>({date,items})),
  trend: Object.entries(dailyTotalByDma).sort(([a],[b])=>a.localeCompare(b)).map(([date,dmas])=>({date,dmas,rain:rainfall[date]||0})),
  search: searchIndex,
  meterMonthly: meterMonthly,
  meterDaily: meterDaily,
  weekly: weeklyArr  // 周对比数据
};
fs.writeFileSync(path.join(OUT_DIR, 'all_data.json'), JSON.stringify(allData));

console.log(`\n🎉 全部完成！`);
console.log(`   範圍: ${allData.dates[0]} ~ ${allData.dates[allData.dates.length-1]}`);
console.log(`   異常: ${anomalies.length} 條`);
console.log(`   排名追蹤: ${rankChanges.length} 個水表`);
console.log(`   路氹日曆: ${Object.keys(cotaiCalendar).length} 天`);
console.log(`   all_data.json: ${(fs.statSync(path.join(OUT_DIR,'all_data.json')).size/1024).toFixed(0)}KB`);
