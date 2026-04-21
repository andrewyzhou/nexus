import React, { useState, useMemo } from 'react';
import { ArrowUpRight, ArrowLeft, ChevronDown, Sparkles, ExternalLink } from 'lucide-react';

export default function InvestmentTrack() {
  const [sortBy, setSortBy] = useState('marketCap');
  const [tickerFilter, setTickerFilter] = useState('all');
  const [newsSort, setNewsSort] = useState('referenced');
  const [hoveredRow, setHoveredRow] = useState(null);

  const companies = [
    { ticker: 'AZ', name: 'A2Z Cust2Mate Solutions Corp.', sector: 'Technology', price: 8.30, change: 2.4, marketCap: 369.7, pe: null, sparkline: [7.8, 7.85, 7.9, 8.1, 7.95, 8.05, 8.2, 8.15, 8.25, 8.3] },
    { ticker: 'ASLE', name: 'AerSale Corporation', sector: 'Industrials', price: 6.94, change: 3.4, marketCap: 327.9, pe: 38.6, sparkline: [6.5, 6.55, 6.6, 6.7, 6.65, 6.75, 6.8, 6.85, 6.9, 6.94] },
    { ticker: 'PEW', name: 'GrabAGun Digital Holdings Inc.', sector: 'Industrials', price: 2.99, change: -1.2, marketCap: 89.7, pe: null, sparkline: [3.1, 3.08, 3.05, 3.0, 3.02, 2.98, 2.95, 3.01, 3.0, 2.99] },
  ];

  const news = [
    { id: 1, title: 'AerSale (ASLE) Stock Trades Up, Here Is Why', source: 'StockStory', date: 'Apr 8, 2026', dateNum: 20260408, ticker: 'ASLE', excerpt: 'Shares of aerospace and defense company AerSale jumped 3.4% in the afternoon session after the U.S. and Iran agreed to a two-week ceasefire, pausing a conflict that had sent equity prices reeling.', referenced: true },
    { id: 2, title: 'We Think A2Z Cust2Mate Solutions Can Easily Afford To Drive Business Growth', source: 'Simply Wall St.', date: 'Apr 11, 2026', dateNum: 20260411, ticker: 'AZ', excerpt: "There's no doubt that money can be made by owning shares of unprofitable businesses. For example, biotech and mining exploration companies often make losses for years before finding success.", referenced: false },
    { id: 3, title: "How A2Z Cust2Mate's $30M Super Sapir Contract Shapes Its 2026 Outlook", source: 'Insider Monkey', date: 'Dec 8, 2025', dateNum: 20251208, ticker: 'AZ', excerpt: 'A2Z Cust2Mate Solutions is one of the best-performing small-cap tech stocks in the past three years. On November 25, the company announced a $30M contract with Super Sapir.', referenced: true },
    { id: 4, title: 'Spotting Winners: AerSale And Aerospace Stocks In Q4', source: 'StockStory', date: 'Apr 2, 2026', dateNum: 20260402, ticker: 'ASLE', excerpt: "Let's dig into the relative performance of AerSale and its peers as we unravel the now-completed Q4 aerospace earnings season.", referenced: false },
    { id: 5, title: 'GrabAGun Outperforms Firearms Market, Launches Logistics Platform', source: 'Exec Edge', date: 'Mar 16, 2026', dateNum: 20260316, ticker: 'PEW', excerpt: 'GrabAGun Digital Holdings continues to gain market share in a weak firearms retail environment, supported by strong digital execution and a new logistics platform.', referenced: true },
    { id: 6, title: '3 Small-Cap Stocks with Questionable Fundamentals', source: 'StockStory', date: 'Apr 13, 2026', dateNum: 20260413, ticker: 'ASLE', excerpt: "Investors looking for hidden gems should keep an eye on small-cap stocks because they're frequently overlooked by Wall Street.", referenced: false },
    { id: 7, title: '3 Growth Companies With High Insider Ownership Growing Revenues Up To 55%', source: 'Simply Wall St.', date: 'Aug 27, 2025', dateNum: 20250827, ticker: 'AZ', excerpt: 'As the U.S. stock market hovers near record highs, investors are closely monitoring major events that could influence future market dynamics.', referenced: false },
  ];

  const sortedCompanies = useMemo(() => {
    const sorted = [...companies];
    switch (sortBy) {
      case 'marketCap': return sorted.sort((a, b) => b.marketCap - a.marketCap);
      case 'price': return sorted.sort((a, b) => b.price - a.price);
      case 'change': return sorted.sort((a, b) => b.change - a.change);
      case 'ticker': return sorted.sort((a, b) => a.ticker.localeCompare(b.ticker));
      default: return sorted;
    }
  }, [sortBy]);

  const filteredNews = useMemo(() => {
    let filtered = tickerFilter === 'all' ? news : news.filter(n => n.ticker === tickerFilter);
    filtered = filtered.sort((a, b) => {
      if (newsSort === 'referenced' && a.referenced !== b.referenced) return b.referenced - a.referenced;
      return newsSort === 'oldest' ? a.dateNum - b.dateNum : b.dateNum - a.dateNum;
    });
    return filtered;
  }, [tickerFilter, newsSort]);

  const Sparkline = ({ data, positive, width = 100, height = 32 }) => {
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const points = data.map((val, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((val - min) / range) * (height - 4) - 2;
      return [x, y];
    });
    const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ');
    const areaPath = `${path} L${width},${height} L0,${height} Z`;
    const color = positive ? '#34d399' : '#f87171';
    const gradId = `grad-${positive ? 'p' : 'n'}-${Math.random().toString(36).slice(2, 7)}`;

    return (
      <svg width={width} height={height} className="inline-block overflow-visible">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#${gradId})`} />
        <path d={path} fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={points[points.length - 1][0]} cy={points[points.length - 1][1]} r="2.5" fill={color} />
      </svg>
    );
  };

  const tickers = ['all', ...new Set(companies.map(c => c.ticker))];
  const monoFont = { fontFamily: '"JetBrains Mono", ui-monospace, monospace' };

  return (
    <div
      className="min-h-screen text-slate-100"
      style={{
        fontFamily: '"Geist", ui-sans-serif, system-ui, sans-serif',
        background: 'radial-gradient(ellipse at top left, #0a1a1a 0%, #030712 45%, #000000 100%)',
      }}
    >
      {/* Top nav */}
      <div className="relative border-b border-white/5 backdrop-blur-xl bg-black/40 sticky top-0 z-50">
        <div className="max-w-[1440px] mx-auto px-8 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="relative">
              <div className="w-2 h-2 rounded-full bg-emerald-400"></div>
              <div className="absolute inset-0 w-2 h-2 rounded-full bg-emerald-400 animate-ping opacity-75"></div>
            </div>
            <span className="font-semibold tracking-[0.25em] text-sm text-emerald-400" style={monoFont}>NEXUS</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="px-3 py-1.5 rounded-md bg-white/5 border border-white/10 text-xs text-slate-400 flex items-center gap-1.5">
              <span className="text-emerald-400">$</span> IPICK.AI
            </div>
            <button className="group flex items-center gap-1.5 text-xs text-slate-400 hover:text-emerald-400 transition px-3 py-1.5 rounded-lg border border-white/10 hover:border-emerald-500/30 hover:bg-emerald-500/5">
              <ArrowLeft size={13} className="group-hover:-translate-x-0.5 transition" />
              back to graph
            </button>
          </div>
        </div>
      </div>

      <div className="relative max-w-[1440px] mx-auto px-8 py-12">
        {/* ============ HERO — OVERSIZED ============ */}
        <div className="relative mb-16">
          <div className="absolute -top-24 -left-24 w-[600px] h-[600px] bg-emerald-500/10 rounded-full blur-[120px] pointer-events-none"></div>
          <div className="absolute top-0 right-0 w-[400px] h-[400px] bg-teal-500/5 rounded-full blur-[100px] pointer-events-none"></div>

          <div className="relative">
            <div className="flex items-center gap-4 mb-8">
              <span className="text-[16px] tracking-[0.35em] text-emerald-400/90 font-medium uppercase" style={monoFont}>
                Investment Track
              </span>
              <div className="h-px flex-1 bg-gradient-to-r from-emerald-400/30 via-white/5 to-transparent max-w-[240px]"></div>
            </div>

            {/* Massive headline */}
            <h1 className="text-[clamp(96px,13vw,192px)] leading-[0.88] font-light tracking-[-0.045em] text-white mb-10">
              Aerospace
              <br />
              <span className="italic font-extralight text-slate-400">Others</span>
            </h1>

            {/* Description + meta strip */}
            <div className="flex flex-wrap items-end justify-between gap-8 pt-6 border-t border-white/5">
              <p className="text-lg text-slate-400 max-w-xl leading-relaxed">
                Companies in the Aerospace — Others investment track.
              </p>
              <div className="flex items-center gap-8" style={monoFont}>
                <div>
                  <div className="text-[10px] tracking-[0.2em] text-slate-600 uppercase mb-1.5">Companies</div>
                  <div className="text-3xl font-light text-white tabular-nums">{companies.length}</div>
                </div>
                <div className="h-10 w-px bg-white/10"></div>
                <div>
                  <div className="text-[10px] tracking-[0.2em] text-slate-600 uppercase mb-1.5">Sectors</div>
                  <div className="text-3xl font-light text-white tabular-nums">2</div>
                </div>
                <div className="h-10 w-px bg-white/10"></div>
                <div>
                  <div className="text-[10px] tracking-[0.2em] text-slate-600 uppercase mb-1.5">Leader</div>
                  <div className="text-3xl font-light text-white">AZ</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ============ COMPANIES TABLE — FULL WIDTH ============ */}
        <div className="mb-12">
          <div className="flex items-end justify-between mb-6">
            <div>
              <h2 className="text-3xl font-light text-white tracking-tight">Companies</h2>
              <p className="text-sm text-slate-500 mt-1">3 stocks in this track</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider" style={monoFont}>Sort</span>
              <div className="relative">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="appearance-none bg-white/5 border border-white/10 rounded-md px-3 py-1.5 pr-7 text-xs text-slate-200 cursor-pointer hover:bg-white/10 focus:outline-none focus:border-emerald-500/40"
                >
                  <option value="marketCap">Market cap</option>
                  <option value="price">Price</option>
                  <option value="change">% Change</option>
                  <option value="ticker">Ticker A-Z</option>
                </select>
                <ChevronDown size={11} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-black/30 backdrop-blur-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] tracking-[0.15em] text-slate-600 uppercase border-b border-white/5" style={monoFont}>
                    <th className="text-left font-normal px-6 py-4 w-12">#</th>
                    <th className="text-left font-normal py-4">Ticker</th>
                    <th className="text-left font-normal py-4">Company</th>
                    <th className="text-left font-normal py-4">Sector</th>
                    <th className="text-right font-normal py-4">Price</th>
                    <th className="text-right font-normal py-4">Δ 1D</th>
                    <th className="text-center font-normal py-4">Trend</th>
                    <th className="text-right font-normal py-4">Mkt Cap</th>
                    <th className="text-right font-normal py-4 pr-8">P/E</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedCompanies.map((c, idx) => (
                    <tr
                      key={c.ticker}
                      className={`border-b border-white/5 last:border-0 cursor-pointer transition-all duration-200 ${
                        hoveredRow === idx
                          ? 'bg-gradient-to-r from-emerald-500/5 via-white/[0.02] to-transparent'
                          : 'hover:bg-white/[0.015]'
                      }`}
                      onMouseEnter={() => setHoveredRow(idx)}
                      onMouseLeave={() => setHoveredRow(null)}
                    >
                      <td className="px-6 py-5 text-slate-600 font-mono text-[11px]">{String(idx + 1).padStart(2, '0')}</td>
                      <td className="py-5">
                        <div className="flex items-center gap-2">
                          <span
                            className={`font-semibold tracking-wide transition text-base ${hoveredRow === idx ? 'text-emerald-400' : 'text-white'}`}
                            style={monoFont}
                          >
                            {c.ticker}
                          </span>
                          <ArrowUpRight
                            size={13}
                            className={`transition-all ${hoveredRow === idx ? 'text-emerald-400 translate-x-0 opacity-100' : 'text-slate-700 -translate-x-1 opacity-0'}`}
                          />
                        </div>
                      </td>
                      <td className="py-5 text-slate-300 max-w-[280px] truncate">{c.name}</td>
                      <td className="py-5">
                        <span className="text-[10px] px-2 py-1 rounded-md bg-white/5 text-slate-400 border border-white/5" style={monoFont}>
                          {c.sector}
                        </span>
                      </td>
                      <td className="py-5 text-right font-mono text-slate-100 tabular-nums text-base">
                        ${c.price.toFixed(2)}
                      </td>
                      <td className={`py-5 text-right font-mono font-medium tabular-nums text-base ${c.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {c.change >= 0 ? '+' : ''}{c.change.toFixed(2)}%
                      </td>
                      <td className="py-5 text-center">
                        <div className="flex justify-center">
                          <Sparkline data={c.sparkline} positive={c.change >= 0} />
                        </div>
                      </td>
                      <td className="py-5 text-right font-mono text-slate-100 tabular-nums">${c.marketCap.toFixed(1)}M</td>
                      <td className="py-5 pr-8 text-right font-mono tabular-nums">
                        {c.pe !== null ? (
                          <span className="text-slate-300">{c.pe.toFixed(1)}</span>
                        ) : (
                          <span className="text-slate-700" title="Unprofitable — no P/E">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* ============ AI SUMMARY — PROMOTED, FULL WIDTH ============ */}
        <div className="relative mb-12">
          <div className="absolute -inset-px rounded-[20px] bg-gradient-to-r from-emerald-500/20 via-teal-500/10 to-emerald-500/20 blur-sm opacity-50"></div>
          <div className="relative rounded-[20px] border border-emerald-500/25 bg-gradient-to-br from-emerald-500/[0.04] via-black/50 to-black/60 backdrop-blur-sm overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-emerald-400/60 to-transparent"></div>

            <div className="px-8 py-6 border-b border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
                    <Sparkles size={18} className="text-emerald-400" />
                  </div>
                  <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse ring-4 ring-black"></div>
                </div>
                <div>
                  <h2 className="text-xl font-medium text-white tracking-tight">AI Summary</h2>
                  <div className="text-xs text-slate-500 mt-0.5" style={monoFont}>
                    Synthesized from 3 sources · freshly generated
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></div>
                <span className="text-[11px] font-medium text-emerald-400 uppercase tracking-wider">Fresh</span>
              </div>
            </div>

            {/* 3-column bullet grid for density */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-px bg-white/5">
              {[
                { ticker: 'AZ', cite: '3', text: <>Secured a <span className="text-white font-semibold">$30M purchase order</span> from Super Sapir, an Israeli supermarket chain, for 3,000 smart shopping carts.</>, date: 'Nov 25, 2025' },
                { ticker: 'ASLE', cite: '1', text: <>Shares <span className="text-emerald-400 font-semibold">jumped 3.4%</span> after the U.S. and Iran agreed to a two-week ceasefire, signaling sector sensitivity to geopolitical risk.</>, date: 'Apr 8, 2026' },
                { ticker: 'PEW', cite: '5', text: <>Reported Q4 and full-year 2025 results showing <span className="text-white font-semibold">market share gains</span> and early traction from the newly launched PEW Logistics platform.</>, date: 'Mar 16, 2026' },
              ].map((bullet, i) => (
                <div key={i} className="bg-black/40 p-6 hover:bg-black/20 transition-colors">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-xs px-2 py-1 rounded bg-white/10 text-slate-200 font-semibold tracking-wider" style={monoFont}>
                      {bullet.ticker}
                    </span>
                    <a href="#" className="text-[10px] text-emerald-400 hover:text-emerald-300" style={monoFont}>
                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition">
                        [{bullet.cite}]
                      </span>
                    </a>
                  </div>
                  <p className="text-[15px] text-slate-200 leading-relaxed mb-3">
                    {bullet.text}
                  </p>
                  <div className="text-[10px] text-slate-600 uppercase tracking-wider" style={monoFont}>
                    {bullet.date}
                  </div>
                </div>
              ))}
            </div>

            <div className="px-8 py-3 border-t border-white/5 bg-black/20 flex items-center justify-between">
              <span className="text-[10px] text-slate-500 tracking-wider uppercase" style={monoFont}>
                Generated by Claude
              </span>
              <button className="text-[10px] text-slate-400 hover:text-emerald-400 transition tracking-wider uppercase" style={monoFont}>
                Regenerate ↻
              </button>
            </div>
          </div>
        </div>

        {/* ============ NEWS — FULL WIDTH, 2-COL GRID ============ */}
        <div>
          <div className="flex flex-wrap items-end justify-between gap-3 mb-6">
            <div>
              <h2 className="text-3xl font-light text-white tracking-tight">News</h2>
              <p className="text-sm text-slate-500 mt-1">{filteredNews.length} articles across all tickers</p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-0.5 p-0.5 bg-white/5 rounded-lg border border-white/10">
                {tickers.map(t => (
                  <button
                    key={t}
                    onClick={() => setTickerFilter(t)}
                    className={`px-3 py-1.5 text-[11px] rounded-md transition tracking-wide ${
                      tickerFilter === t
                        ? 'bg-emerald-400/15 text-emerald-400 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.3)]'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                    style={monoFont}
                  >
                    {t === 'all' ? 'ALL' : t}
                  </button>
                ))}
              </div>
              <div className="relative">
                <select
                  value={newsSort}
                  onChange={(e) => setNewsSort(e.target.value)}
                  className="appearance-none bg-white/5 border border-white/10 rounded-md px-3 py-1.5 pr-7 text-xs text-slate-200 cursor-pointer hover:bg-white/10 focus:outline-none focus:border-emerald-500/40"
                >
                  <option value="referenced">Referenced first</option>
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                </select>
                <ChevronDown size={11} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* 2-column grid of news cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filteredNews.map(article => (
              <a
                key={article.id}
                href="#"
                className="group relative block rounded-xl border border-white/10 bg-black/30 backdrop-blur-sm p-5 hover:bg-white/[0.02] hover:border-white/20 transition-all overflow-hidden"
              >
                {article.referenced && (
                  <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-gradient-to-b from-emerald-400 via-emerald-400 to-emerald-400/40"></div>
                )}
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-2.5 flex-wrap">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-slate-200 font-semibold tracking-wider" style={monoFont}>
                        {article.ticker}
                      </span>
                      <span className="text-[11px] text-slate-500">{article.source}</span>
                      <span className="text-slate-700">·</span>
                      <span className="text-[11px] text-slate-500" style={monoFont}>{article.date}</span>
                      {article.referenced && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1 font-medium tracking-wider uppercase">
                          <Sparkles size={8} />
                          Cited
                        </span>
                      )}
                    </div>
                    <h3 className="text-[15px] font-medium text-white group-hover:text-emerald-300 transition mb-2 leading-snug">
                      {article.title}
                    </h3>
                    <p className="text-[13px] text-slate-400 leading-relaxed line-clamp-3">
                      {article.excerpt}
                    </p>
                  </div>
                  <ExternalLink size={14} className="text-slate-700 group-hover:text-emerald-400 transition flex-shrink-0 mt-1 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 duration-200" />
                </div>
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
