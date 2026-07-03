'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import Nav from '@/components/Nav';

type WatchItem = {
  symbol: string;
  name: string;
  ok: boolean;
  error?: string;
  as_of?: string;
  price?: number;
  chg_1d?: number | null;
  ret_1w?: number | null;
  ret_1m?: number | null;
  ret_3m?: number | null;
  rsi14?: number | null;
  above_sma200?: boolean | null;
  pct_below_52w_high?: number | null;
  spark?: number[];
};

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`;

// A股习惯: 红涨绿跌
const chgColor = (v: number | null | undefined) =>
  v === null || v === undefined ? 'var(--muted)' : v >= 0 ? 'var(--up)' : 'var(--down)';

function Spark({ values }: { values: number[] }) {
  const d = useMemo(() => {
    if (!values || values.length < 2) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values
      .map((v, i) => {
        const x = (i / (values.length - 1)) * 120;
        const y = 34 - ((v - min) / span) * 30;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [values]);
  const up = values.length >= 2 && values[values.length - 1] >= values[0];
  return (
    <svg viewBox="0 0 120 36" className="spark" preserveAspectRatio="none">
      <path d={d} fill="none" stroke={up ? 'var(--up)' : 'var(--down)'} strokeWidth="1.6" />
    </svg>
  );
}

type SortKey = 'chg_1d' | 'ret_1m' | 'ret_3m' | 'pct_below_52w_high';

export default function WatchPage() {
  const router = useRouter();
  const [items, setItems] = useState<WatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('chg_1d');
  const [filter, setFilter] = useState('');
  const [newSym, setNewSym] = useState('');
  const [editing, setEditing] = useState(false);

  const reload = () => {
    setLoading(true);
    fetch('/api/watch/summary')
      .then((r) => r.json())
      .then((d) => setItems(d.items ?? []))
      .finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const saveList = async (list: { symbol: string; name: string }[]) => {
    await fetch('/api/watchlist', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: list }),
    });
    reload();
  };

  const remove = (sym: string) =>
    saveList(items.filter((i) => i.symbol !== sym).map((i) => ({ symbol: i.symbol, name: i.name })));

  const [refreshing, setRefreshing] = useState(false);
  const refresh = async (symbols?: string[]) => {
    setRefreshing(true);
    try {
      await fetch('/api/watch/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: symbols ?? null }),
      });
    } finally {
      setRefreshing(false);
      reload();
    }
  };

  const add = async () => {
    const sym = newSym.trim().toUpperCase();
    if (!sym || items.some((i) => i.symbol === sym)) return;
    setNewSym('');
    await saveList([...items.map((i) => ({ symbol: i.symbol, name: i.name })), { symbol: sym, name: sym }]);
    refresh([sym]); // 新标的立即拉行情
  };

  const shown = useMemo(() => {
    const f = filter.trim().toUpperCase();
    const list = items.filter(
      (i) => !f || i.symbol.includes(f) || i.name.toUpperCase().includes(f),
    );
    return [...list].sort((a, b) => {
      if (a.ok !== b.ok) return a.ok ? -1 : 1;
      const av = (a[sortKey] as number | null | undefined) ?? -Infinity;
      const bv = (b[sortKey] as number | null | undefined) ?? -Infinity;
      return bv - av;
    });
  }, [items, sortKey, filter]);

  const okCount = items.filter((i) => i.ok).length;
  const asOf = items.find((i) => i.ok)?.as_of;

  return (
    <div className="shell">
      <aside className="side">
        <Nav />

        <div className="field">
          <label>筛选</label>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="代码 / 名称" />
        </div>
        <div className="field">
          <label>排序</label>
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="chg_1d">今日涨跌</option>
            <option value="ret_1m">近 1 月收益</option>
            <option value="ret_3m">近 3 月收益</option>
            <option value="pct_below_52w_high">距 52 周高点</option>
          </select>
        </div>

        <div className="section-label">管理</div>
        <div className="field">
          <label>添加标的 (如 NVDA / 0700.HK)</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input value={newSym} onChange={(e) => setNewSym(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && add()} placeholder="代码" />
            <button className="btn-primary" style={{ width: 72 }} onClick={add}>加</button>
          </div>
          <div className="hint">添加后自动拉取行情 (美股代码 / 港股加 .HK)</div>
        </div>
        <button className="btn-primary" onClick={() => refresh()} disabled={refreshing}
                style={{ marginBottom: 10 }}>
          {refreshing && <span className="spinner" />}
          {refreshing ? '刷新中 (可能要几分钟)…' : '刷新全部行情'}
        </button>
        <button
          className="btn-primary"
          style={{ background: 'none', border: '1px solid var(--border)', color: 'var(--muted)', boxShadow: 'none' }}
          onClick={() => setEditing(!editing)}
        >
          {editing ? '完成' : '编辑 (移除标的)'}
        </button>
      </aside>

      <main className="main">
        <h1 className="page-title">自选面板</h1>
        <p className="page-sub">
          {okCount}/{items.length} 只有数据{asOf ? ` · 行情截至 ${asOf} (日线)` : ''} ·
          点卡片进入个股页 (Agent 评级 + 回测)。仅供研究, 不构成投资建议。
        </p>

        {loading && <div className="notice">加载中…</div>}

        <div className="watch-grid">
          {shown.map((it) => (
            <div
              key={it.symbol}
              className={`watch-card ${it.ok ? '' : 'dead'}`}
              onClick={() => it.ok && !editing && router.push(`/stock/${encodeURIComponent(it.symbol)}`)}
            >
              {editing && (
                <button className="remove" onClick={(e) => { e.stopPropagation(); remove(it.symbol); }}>
                  ✕
                </button>
              )}
              <div className="wc-head">
                <div>
                  <div className="wc-sym">{it.symbol}</div>
                  <div className="wc-name">{it.name}</div>
                </div>
                {it.ok && (
                  <div className="wc-right">
                    <div className="wc-price">{it.price}</div>
                    <div className="wc-chg" style={{ color: chgColor(it.chg_1d) }}>
                      {pct(it.chg_1d)}
                    </div>
                  </div>
                )}
              </div>

              {it.ok ? (
                <>
                  {it.spark && <Spark values={it.spark} />}
                  <div className="wc-chips">
                    <span className="chip" style={{ color: chgColor(it.ret_1m) }}>1月 {pct(it.ret_1m, 0)}</span>
                    <span className="chip" style={{ color: chgColor(it.ret_3m) }}>3月 {pct(it.ret_3m, 0)}</span>
                    <span className="chip">RSI {it.rsi14 ?? '—'}</span>
                    {it.above_sma200 !== null && (
                      <span className="chip" style={{ color: it.above_sma200 ? 'var(--up)' : 'var(--down)' }}>
                        {it.above_sma200 ? '200日线上' : '200日线下'}
                      </span>
                    )}
                    <span className="chip">距高点 {pct(it.pct_below_52w_high, 0)}</span>
                  </div>
                </>
              ) : (
                <div className="wc-dead-msg">{it.error ?? '暂无数据'}</div>
              )}
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
