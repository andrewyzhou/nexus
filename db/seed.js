#!/usr/bin/env node
/**
 * db/seed.js
 * Populates the nexus_db with realistic S&P 500-like company data
 * and synthetic relationship edges.
 *
 * Usage:  node db/seed.js
 */

require("dotenv").config();
const { Pool } = require("pg");

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

// ----------------------------------------------------------------
// Company seed data  (~50 companies, 10 sectors)
// ----------------------------------------------------------------
const COMPANIES = [
  // Technology
  { ticker: "AAPL",  name: "Apple Inc.",              sector: "Technology",          industry: "Consumer Electronics",       price: 189.30, mcap: 2950, country: "USA" },
  { ticker: "MSFT",  name: "Microsoft Corporation",   sector: "Technology",          industry: "Software",                   price: 415.20, mcap: 3080, country: "USA" },
  { ticker: "NVDA",  name: "NVIDIA Corporation",      sector: "Technology",          industry: "Semiconductors",             price: 875.40, mcap: 2150, country: "USA" },
  { ticker: "AVGO",  name: "Broadcom Inc.",            sector: "Technology",          industry: "Semiconductors",             price: 168.50, mcap: 790,  country: "USA" },
  { ticker: "ORCL",  name: "Oracle Corporation",      sector: "Technology",          industry: "Enterprise Software",        price: 127.80, mcap: 350,  country: "USA" },
  { ticker: "AMD",   name: "Advanced Micro Devices",  sector: "Technology",          industry: "Semiconductors",             price: 177.60, mcap: 285,  country: "USA" },

  // Consumer Discretionary
  { ticker: "AMZN",  name: "Amazon.com Inc.",          sector: "Consumer Discretionary", industry: "E-Commerce",            price: 186.50, mcap: 1940, country: "USA" },
  { ticker: "TSLA",  name: "Tesla Inc.",               sector: "Consumer Discretionary", industry: "Electric Vehicles",     price: 245.80, mcap: 780,  country: "USA" },
  { ticker: "HD",    name: "Home Depot Inc.",          sector: "Consumer Discretionary", industry: "Home Improvement",      price: 345.20, mcap: 350,  country: "USA" },
  { ticker: "MCD",   name: "McDonald's Corporation",  sector: "Consumer Discretionary", industry: "Quick Service Restaurants", price: 288.40, mcap: 208, country: "USA" },
  { ticker: "NKE",   name: "NIKE Inc.",                sector: "Consumer Discretionary", industry: "Footwear & Apparel",   price: 92.40,  mcap: 141,  country: "USA" },

  // Financials
  { ticker: "JPM",   name: "JPMorgan Chase & Co.",    sector: "Financials",          industry: "Diversified Banks",          price: 195.60, mcap: 567,  country: "USA" },
  { ticker: "BRK",   name: "Berkshire Hathaway Inc.", sector: "Financials",          industry: "Multi-Sector Holdings",      price: 538.20, mcap: 786,  country: "USA" },
  { ticker: "V",     name: "Visa Inc.",                sector: "Financials",          industry: "Payment Processing",         price: 272.80, mcap: 558,  country: "USA" },
  { ticker: "MA",    name: "Mastercard Inc.",          sector: "Financials",          industry: "Payment Processing",         price: 455.70, mcap: 425,  country: "USA" },
  { ticker: "BAC",   name: "Bank of America Corp.",   sector: "Financials",          industry: "Diversified Banks",          price: 38.70,  mcap: 304,  country: "USA" },
  { ticker: "GS",    name: "Goldman Sachs Group Inc.",sector: "Financials",          industry: "Investment Banking",         price: 478.30, mcap: 159,  country: "USA" },

  // Health Care
  { ticker: "UNH",   name: "UnitedHealth Group Inc.", sector: "Health Care",         industry: "Managed Health Care",        price: 495.80, mcap: 455,  country: "USA" },
  { ticker: "JNJ",   name: "Johnson & Johnson",       sector: "Health Care",         industry: "Pharmaceuticals",            price: 152.30, mcap: 365,  country: "USA" },
  { ticker: "LLY",   name: "Eli Lilly and Company",   sector: "Health Care",         industry: "Pharmaceuticals",            price: 768.40, mcap: 731,  country: "USA" },
  { ticker: "ABT",   name: "Abbott Laboratories",     sector: "Health Care",         industry: "Medical Devices",            price: 109.50, mcap: 189,  country: "USA" },
  { ticker: "PFE",   name: "Pfizer Inc.",              sector: "Health Care",         industry: "Pharmaceuticals",            price: 27.80,  mcap: 158,  country: "USA" },

  // Communication Services
  { ticker: "GOOG",  name: "Alphabet Inc.",            sector: "Communication Services", industry: "Internet Search",        price: 155.70, mcap: 1940, country: "USA" },
  { ticker: "META",  name: "Meta Platforms Inc.",      sector: "Communication Services", industry: "Social Media",           price: 484.10, mcap: 1240, country: "USA" },
  { ticker: "NFLX",  name: "Netflix Inc.",             sector: "Communication Services", industry: "Streaming Services",     price: 628.40, mcap: 271,  country: "USA" },
  { ticker: "DIS",   name: "The Walt Disney Company", sector: "Communication Services", industry: "Entertainment",          price: 111.20, mcap: 203,  country: "USA" },
  { ticker: "T",     name: "AT&T Inc.",                sector: "Communication Services", industry: "Integrated Telecom",    price: 17.40,  mcap: 124,  country: "USA" },

  // Industrials
  { ticker: "RTX",   name: "RTX Corporation",          sector: "Industrials",        industry: "Aerospace & Defense",        price: 92.50,  mcap: 125,  country: "USA" },
  { ticker: "HON",   name: "Honeywell International", sector: "Industrials",         industry: "Conglomerates",              price: 198.30, mcap: 130,  country: "USA" },
  { ticker: "UPS",   name: "United Parcel Service",   sector: "Industrials",         industry: "Air Freight & Logistics",    price: 148.20, mcap: 127,  country: "USA" },
  { ticker: "GE",    name: "GE Aerospace",             sector: "Industrials",        industry: "Aerospace Engines",          price: 168.40, mcap: 183,  country: "USA" },
  { ticker: "CAT",   name: "Caterpillar Inc.",         sector: "Industrials",         industry: "Heavy Machinery",            price: 356.80, mcap: 174,  country: "USA" },

  // Energy
  { ticker: "XOM",   name: "Exxon Mobil Corporation", sector: "Energy",              industry: "Integrated Oil & Gas",       price: 109.40, mcap: 437,  country: "USA" },
  { ticker: "CVX",   name: "Chevron Corporation",     sector: "Energy",              industry: "Integrated Oil & Gas",       price: 152.30, mcap: 286,  country: "USA" },
  { ticker: "COP",   name: "ConocoPhillips",           sector: "Energy",              industry: "Oil & Gas Exploration",      price: 116.80, mcap: 147,  country: "USA" },
  { ticker: "SLB",   name: "SLB (Schlumberger)",      sector: "Energy",              industry: "Oil & Gas Equipment",        price: 46.20,  mcap: 65,   country: "USA" },

  // Consumer Staples
  { ticker: "PG",    name: "Procter & Gamble Co.",    sector: "Consumer Staples",    industry: "Household Products",         price: 161.80, mcap: 381,  country: "USA" },
  { ticker: "KO",    name: "The Coca-Cola Company",   sector: "Consumer Staples",    industry: "Soft Drinks",                price: 60.40,  mcap: 261,  country: "USA" },
  { ticker: "PEP",   name: "PepsiCo Inc.",             sector: "Consumer Staples",   industry: "Soft Drinks",                price: 172.30, mcap: 236,  country: "USA" },
  { ticker: "WMT",   name: "Walmart Inc.",             sector: "Consumer Staples",   industry: "Discount Stores",            price: 59.20,  mcap: 473,  country: "USA" },
  { ticker: "COST",  name: "Costco Wholesale Corp.",  sector: "Consumer Staples",    industry: "Warehouse Clubs",            price: 735.40, mcap: 326,  country: "USA" },

  // Real Estate
  { ticker: "PLD",   name: "Prologis Inc.",            sector: "Real Estate",        industry: "Industrial REITs",           price: 118.30, mcap: 112,  country: "USA" },
  { ticker: "AMT",   name: "American Tower Corp.",    sector: "Real Estate",         industry: "Specialty REITs",            price: 189.40, mcap: 87,   country: "USA" },

  // Utilities
  { ticker: "NEE",   name: "NextEra Energy Inc.",     sector: "Utilities",           industry: "Electric Utilities",         price: 71.20,  mcap: 145,  country: "USA" },
  { ticker: "DUK",   name: "Duke Energy Corporation", sector: "Utilities",           industry: "Electric Utilities",         price: 101.30, mcap: 78,   country: "USA" },

  // Materials
  { ticker: "LIN",   name: "Linde plc",               sector: "Materials",           industry: "Industrial Gases",           price: 453.20, mcap: 220,  country: "USA" },
  { ticker: "APD",   name: "Air Products & Chemicals",sector: "Materials",           industry: "Industrial Gases",           price: 265.40, mcap: 59,   country: "USA" },
  { ticker: "NEM",   name: "Newmont Corporation",     sector: "Materials",           industry: "Gold Mining",                price: 36.80,  mcap: 29,   country: "USA" },
];

// Derive 'size' from market cap
function getSize(mcap) {
  if (mcap >= 200) return "large";
  if (mcap >= 10)  return "mid";
  return "small";
}

// Relationship types pool
const REL_TYPES = ["supplier", "partner", "competitor", "investor"];

// Deterministic pseudo-random relationship generator
function buildRelationships(ids) {
  const edges = new Set();
  const result = [];

  const push = (src, tgt, type, weight) => {
    const key = `${src}-${tgt}-${type}`;
    if (src === tgt || edges.has(key)) return;
    edges.add(key);
    result.push({ source_id: src, target_id: tgt, type, weight });
  };

  // Hard-coded meaningful relationships
  const meaningful = [
    // Apple suppliers / partners
    [1, 3, "partner",    0.9],  // AAPL ↔ NVDA
    [1, 4, "supplier",   0.8],  // AAPL ← AVGO
    [1, 6, "supplier",   0.7],  // AAPL ← AMD
    [1, 5, "competitor", 0.6],  // AAPL vs ORCL (cloud)
    // Microsoft / Nvidia
    [2, 3, "partner",    0.95], // MSFT ↔ NVDA
    [2, 5, "competitor", 0.7],  // MSFT vs ORCL
    [2, 23, "competitor",0.8],  // MSFT vs GOOG
    [2, 7, "investor",   0.5],  // MSFT → AMZN
    // Amazon ecosystem
    [7, 1, "competitor", 0.8],  // AMZN vs AAPL
    [7, 2, "competitor", 0.85], // AMZN vs MSFT
    [7, 8, "partner",    0.6],  // AMZN ↔ TSLA
    // Tesla supply chain
    [8, 3, "supplier",   0.9],  // TSLA ← NVDA (autopilot)
    [8, 6, "supplier",   0.75], // TSLA ← AMD
    // Financials
    [12, 13, "investor", 0.7],  // JPM → BRK
    [14, 15, "competitor",0.9], // V vs MA
    [14, 16, "partner",  0.6],  // V ↔ BAC
    [15, 16, "partner",  0.65], // MA ↔ BAC
    [17, 12, "partner",  0.5],  // GS ↔ JPM
    // Health care
    [18, 19, "competitor",0.7], // UNH vs JNJ
    [20, 19, "competitor",0.8], // LLY vs JNJ
    [20, 22, "competitor",0.75],// LLY vs PFE
    [21, 19, "partner",  0.6],  // ABT ↔ JNJ
    // Big Tech comms
    [23, 24, "competitor",0.9], // GOOG vs META
    [23, 25, "competitor",0.7], // GOOG vs NFLX
    [24, 25, "partner",  0.5],  // META ↔ NFLX
    // Energy
    [33, 34, "competitor",0.85],// XOM vs CVX
    [33, 35, "partner",  0.6],  // XOM ↔ COP
    [34, 36, "partner",  0.55], // CVX ↔ SLB
    [33, 36, "partner",  0.65], // XOM ↔ SLB
    // Consumer staples
    [39, 40, "competitor",0.9], // KO vs PEP
    [37, 38, "partner",  0.7],  // PG ↔ WMT
    [41, 38, "partner",  0.8],  // COST ↔ WMT (logistics)
    // Industrials
    [28, 29, "competitor",0.7], // RTX vs HON
    [28, 31, "partner",  0.55], // RTX ↔ GE
    [30, 31, "partner",  0.6],  // UPS ↔ GE
    [32, 29, "partner",  0.5],  // CAT ↔ HON
    // Cross-sector
    [7, 30, "partner",   0.7],  // AMZN ↔ UPS (logistics)
    [12, 14, "partner",  0.8],  // JPM ↔ V
    [12, 15, "partner",  0.75], // JPM ↔ MA
    [2, 18, "investor",  0.4],  // MSFT → UNH
    [3, 8, "supplier",   0.9],  // NVDA → TSLA
    [3, 7, "partner",    0.7],  // NVDA ↔ AMZN (cloud/AI)
    // Utilities / Real estate
    [43, 44, "competitor",0.8], // NEE vs DUK
    [42, 43, "partner",  0.5],  // PLD ↔ NEE
    [45, 46, "competitor",0.7], // LIN vs APD
    // More cross-sector links to reach ~150
    [1, 2, "competitor", 0.8],
    [1, 7, "competitor", 0.75],
    [2, 4, "partner",    0.6],
    [5, 23, "competitor",0.7],
    [6, 3, "competitor", 0.85],
    [9, 38, "partner",   0.6],
    [10, 39, "partner",  0.5],
    [11, 37, "partner",  0.55],
    [13, 12, "investor", 0.9],
    [22, 20, "competitor",0.7],
    [22, 21, "partner",  0.5],
    [25, 26, "competitor",0.6],
    [26, 27, "competitor",0.5],
    [27, 23, "partner",  0.4],
    [29, 28, "partner",  0.6],
    [31, 32, "partner",  0.5],
    [34, 35, "partner",  0.55],
    [35, 36, "partner",  0.6],
    [37, 39, "partner",  0.5],
    [38, 41, "partner",  0.7],
    [39, 41, "competitor",0.5],
    [40, 41, "competitor",0.55],
    [42, 33, "investor", 0.4],
    [43, 45, "partner",  0.4],
    [44, 46, "partner",  0.4],
    [47, 45, "partner",  0.3],
    [16, 17, "competitor",0.65],
    [18, 12, "partner",  0.55],
    [20, 22, "partner",  0.45],
    [1, 23, "competitor", 0.7],
    [7, 23, "competitor", 0.75],
    [7, 24, "competitor", 0.6],
    [3, 2, "partner",    0.8],
    [4, 2, "partner",    0.6],
    [4, 1, "supplier",   0.7],
    [6, 1, "supplier",   0.6],
    [6, 8, "supplier",   0.65],
    [9, 7, "competitor", 0.5],
    [10, 7, "competitor",0.4],
    [11, 8, "partner",   0.5],
    [14, 12, "partner",  0.65],
    [15, 17, "partner",  0.5],
    [19, 22, "partner",  0.55],
    [21, 22, "competitor",0.6],
    [23, 7, "competitor",0.8],
    [24, 7, "investor",  0.3],
    [25, 23, "competitor",0.5],
    [26, 23, "competitor",0.6],
    [28, 32, "partner",  0.5],
    [30, 7, "partner",   0.65],
    [31, 28, "partner",  0.5],
    [33, 42, "partner",  0.35],
    [34, 42, "partner",  0.3],
    [37, 41, "competitor",0.4],
    [38, 7, "partner",   0.7],
    [39, 38, "partner",  0.45],
    [40, 38, "partner",  0.5],
    [43, 33, "partner",  0.35],
    [44, 34, "partner",  0.3],
    [45, 33, "partner",  0.3],
    [46, 34, "partner",  0.25],
  ];

  for (const [src, tgt, type, weight] of meaningful) {
    // Adjust for 1-based company IDs matching SERIAL
    push(src, tgt, type, weight);
  }

  return result;
}

async function seed() {
  const client = await pool.connect();
  try {
    console.log("🌱 Starting seed...");

    // ---- Insert companies ----
    let insertedCompanies = 0;
    const idMap = {}; // ticker → id

    for (const c of COMPANIES) {
      const size = getSize(c.mcap);
      const res = await client.query(
        `INSERT INTO companies
           (ticker, name, sector, industry, currency, current_price, market_cap_b, size, country)
         VALUES ($1,$2,$3,$4,'USD',$5,$6,$7,$8)
         ON CONFLICT (ticker) DO NOTHING
         RETURNING id, ticker`,
        [c.ticker, c.name, c.sector, c.industry, c.price, c.mcap, size, c.country]
      );
      if (res.rows.length > 0) {
        idMap[c.ticker] = res.rows[0].id;
        insertedCompanies++;
      } else {
        // Already existed – fetch the id
        const existing = await client.query("SELECT id FROM companies WHERE ticker=$1", [c.ticker]);
        idMap[c.ticker] = existing.rows[0].id;
      }
    }
    console.log(`   ✓ Companies: ${insertedCompanies} inserted (${COMPANIES.length - insertedCompanies} already existed)`);

    // ---- Insert relationships ----
    // Use sequential company IDs matching insertion order
    const tickerList = COMPANIES.map((c) => c.ticker);
    // Rebuild id map indexed by position (1-based)
    const posMap = {};
    for (let i = 0; i < tickerList.length; i++) {
      posMap[i + 1] = idMap[tickerList[i]];
    }

    const edges = buildRelationships(posMap);
    let insertedEdges = 0;

    for (const e of edges) {
      const srcId = posMap[e.source_id];
      const tgtId = posMap[e.target_id];
      if (!srcId || !tgtId) continue;

      const res = await client.query(
        `INSERT INTO relationships (source_id, target_id, type, weight)
         VALUES ($1,$2,$3,$4)
         ON CONFLICT ON CONSTRAINT uq_relationship DO NOTHING`,
        [srcId, tgtId, e.type, e.weight]
      );
      if (res.rowCount > 0) insertedEdges++;
    }

    console.log(`   ✓ Relationships: ${insertedEdges} inserted`);
    console.log("✅ Seed complete!");
  } finally {
    client.release();
    await pool.end();
  }
}

seed().catch((err) => {
  console.error("❌ Seed failed:", err.message);
  process.exit(1);
});
