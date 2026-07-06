'use client';

import { useEffect, useState } from 'react';
import Nav from '@/components/Nav';
import EquityChart, { type Point } from '@/components/EquityChart';

type Position = {
  symbol: string;
  shares: number;
  avg_cost: number;
  last: number | null;
  market_value: number | null;
  pnl_pct: number | null;
};

type Account = {
  account: string;
  label: string;
  desc: string;
  mode: string;
  config: { symbols: string[]; initial_cash: number };
  created_at: string;
  last_run: string | null;
  cash: number;
  equity: number;
  total_return: number;
  rebalance_note: { month: string; picks: string[]; momentum_top5: Record<string, number> } | null;
  positions: Position[];
  pending: { symbol: string; target_weight: number; signal_bar: string }[];
  trades: { date: string; symbol: string; side: string; shares: number; price: number; cost: number }[];
  equity_history: { date: string; equity: number; benchmark: number | null }[];
};

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
const money = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: 0 });

function AccountSection({ a }: { a: Account }) {
  const equity: Point[] = a.equity_history.map((e) => ({ time: e.date, value: e.equity }));
  const bench: Point[] = a.equity_history.map((e) => ({ time: e.date, value: e.benchmark }));
  return (
    <section style={{ marginBottom: 40 }}>
      <h2 className="symbol-title">
        {a.label}
        <span
          className={`badge ${a.total_return >= 0 ? 'bull' : 'bear'}`}
          style={{ marginLeft: 10 }}
        >
          {pct(a.total_return)}
        </span>
      </h2>
      <p className="page-sub" style={{ marginBottom: 14 }}>{a.desc}</p>

      <div className="metric-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="metric"><div className="label">总净值</div><div className="value">${money(a.equity)}</div></div>
        <div className="metric"><div className="label">现金</div><div className="value">${money(a.cash)}</div></div>
        <div className="metric"><div className="label">持仓数</div><div className="value">{a.positions.length}</div></div>
        <div className="metric"><div className="label">待成交挂单</div><div className="value">{a.pending.length}</div></div>
      </div>

      {a.rebalance_note && (
        <div className="notice" style={{ marginBottom: 14 }}>
          {a.rebalance_note.month} 月度调仓: 持有 <b>{a.rebalance_note.picks.join(' + ')}</b>
          {' '}(动量前五: {Object.entries(a.rebalance_note.momentum_top5)
            .map(([s, m]) => `${s} ${m >= 0 ? '+' : ''}${(m * 100).toFixed(0)}%`)
            .join(', ')})
        </div>
      )}

      {equity.length >= 2 ? (
        <div className="chart-block">
          <div className="chart-title">净值曲线 <span>— 金线=账户, 蓝虚线=等权买入持有基准</span></div>
          <div className="chart-box"><EquityChart equity={equity} benchmark={bench} /></div>
        </div>
      ) : (
        <div className="notice" style={{ marginBottom: 14 }}>净值曲线积累几个交易日后显示。</div>
      )}

      <div className="table-wrap">
        <table>
          <thead><tr><th>持仓</th><th>股数</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th></tr></thead>
          <tbody>
            {a.positions.length === 0 && (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--muted)' }}>暂无持仓 (全现金)</td></tr>
            )}
            {a.positions.map((p) => (
              <tr key={p.symbol}>
                <td><b>{p.symbol}</b></td>
                <td>{p.shares.toFixed(1)}</td>
                <td>{p.avg_cost.toFixed(2)}</td>
                <td>{p.last?.toFixed(2) ?? '—'}</td>
                <td>{money(p.market_value)}</td>
                <td style={{ color: (p.pnl_pct ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>{pct(p.pnl_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {a.pending.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead><tr><th>挂单 (次日开盘成交)</th><th>目标仓位 (占总净值)</th><th>信号日</th></tr></thead>
            <tbody>
              {a.pending.map((o) => (
                <tr key={o.symbol}>
                  <td><b>{o.symbol}</b></td>
                  <td>{(o.target_weight * 100).toFixed(0)}%</td>
                  <td>{o.signal_bar}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <details className="trades" style={{ marginTop: 10 }}>
        <summary>成交记录 ({a.trades.length} 笔)</summary>
        <div className="table-wrap">
          <table>
            <thead><tr><th>日期</th><th>标的</th><th>动作</th><th>股数</th><th>成交价</th><th>费用</th></tr></thead>
            <tbody>
              {[...a.trades].reverse().map((t, i) => (
                <tr key={i}>
                  <td>{t.date}</td>
                  <td><b>{t.symbol}</b></td>
                  <td className={t.side === 'BUY' ? 'buy' : 'sell'}>{t.side === 'BUY' ? '买入' : '卖出'}</td>
                  <td>{t.shares.toFixed(1)}</td>
                  <td>{t.price.toFixed(2)}</td>
                  <td>{t.cost.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

export default function PaperPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [running, setRunning] = useState(false);

  const reload = () => fetch('/api/paper').then((r) => r.json()).then((d) => setAccounts(d.accounts ?? []));
  useEffect(() => { reload(); }, []);

  const runOnce = async () => {
    setRunning(true);
    try { await fetch('/api/paper/run', { method: 'POST' }); }
    finally { setRunning(false); reload(); }
  };

  return (
    <div className="shell">
      <aside className="side">
        <Nav />
        <div className="section-label">模拟盘赛跑</div>
        <p style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.8 }}>
          两个账户各 $100,000 虚拟资金, 同日开赛, 用未来的真实行情决胜负:
          趋势跟踪控回撤 vs 动量轮动博收益。
        </p>
        <button className="btn-primary" onClick={runOnce} disabled={running} style={{ marginTop: 10 }}>
          {running && <span className="spinner" />}
          {running ? '运行中…' : '手动跑一轮'}
        </button>
        <p className="hint" style={{ marginTop: 8 }}>
          每天早 7 点 / 下午 5 点自动运行; 信号按次日开盘价成交 (T+1)。不连接任何真实账户。
        </p>
      </aside>

      <main className="main">
        <h1 className="page-title">模拟盘</h1>
        <p className="page-sub">真实行情 + 虚拟资金, 与回测同纪律。用它验证策略值不值得给真钱。</p>
        {accounts.map((a) => <AccountSection key={a.account} a={a} />)}
      </main>
    </div>
  );
}
