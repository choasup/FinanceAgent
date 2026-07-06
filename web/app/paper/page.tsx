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

type PaperState = {
  config: { strategy: string; symbols: string[]; initial_cash: number };
  created_at: string;
  last_run: string | null;
  cash: number;
  equity: number;
  total_return: number;
  positions: Position[];
  pending: { symbol: string; target_weight: number; signal_bar: string }[];
  trades: { date: string; symbol: string; side: string; shares: number; price: number; cost: number }[];
  equity_history: { date: string; equity: number; benchmark: number | null }[];
};

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
const money = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: 0 });

export default function PaperPage() {
  const [s, setS] = useState<PaperState | null>(null);
  const [running, setRunning] = useState(false);

  const reload = () => fetch('/api/paper').then((r) => r.json()).then(setS);
  useEffect(() => { reload(); }, []);

  const runOnce = async () => {
    setRunning(true);
    try {
      await fetch('/api/paper/run', { method: 'POST' });
    } finally {
      setRunning(false);
      reload();
    }
  };

  const equity: Point[] = (s?.equity_history ?? []).map((e) => ({ time: e.date, value: e.equity }));
  const bench: Point[] = (s?.equity_history ?? []).map((e) => ({ time: e.date, value: e.benchmark }));

  return (
    <div className="shell">
      <aside className="side">
        <Nav />
        {s && (
          <>
            <div className="section-label">配置</div>
            <p style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.8 }}>
              策略: <b style={{ color: 'var(--text)' }}>{s.config.strategy}</b><br />
              标的: {s.config.symbols.join(', ')}<br />
              初始资金: ${money(s.config.initial_cash)}<br />
              开始于: {s.created_at}<br />
              上次运行: {s.last_run ?? '—'}
            </p>
            <button className="btn-primary" onClick={runOnce} disabled={running} style={{ marginTop: 10 }}>
              {running && <span className="spinner" />}
              {running ? '运行中…' : '手动跑一轮'}
            </button>
            <p className="hint" style={{ marginTop: 8 }}>
              每天早 7 点 / 下午 5 点行情刷新后自动运行; 信号按次日开盘价成交 (T+1)。
              模拟盘不连接任何真实账户。
            </p>
          </>
        )}
      </aside>

      <main className="main">
        <h1 className="page-title">
          模拟盘
          {s && (
            <span
              className={`badge ${s.total_return >= 0 ? 'bull' : 'bear'}`}
              style={{ marginLeft: 12, verticalAlign: 'middle' }}
            >
              {pct(s.total_return)}
            </span>
          )}
        </h1>
        <p className="page-sub">
          真实行情 + 虚拟资金, 与回测同纪律 (T+1 开盘成交, 含费用滑点)。用它验证策略值不值得给真钱。
        </p>

        {s && (
          <>
            <div className="metric-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
              <div className="metric">
                <div className="label">总净值</div>
                <div className="value">${money(s.equity)}</div>
              </div>
              <div className="metric">
                <div className="label">现金</div>
                <div className="value">${money(s.cash)}</div>
              </div>
              <div className="metric">
                <div className="label">持仓数</div>
                <div className="value">{s.positions.length}</div>
              </div>
              <div className="metric">
                <div className="label">待成交挂单</div>
                <div className="value">{s.pending.length}</div>
              </div>
            </div>

            {equity.length >= 2 && (
              <div className="chart-block">
                <div className="chart-title">
                  净值曲线 <span>— 金线=模拟盘, 蓝虚线=等权买入持有基准</span>
                </div>
                <div className="chart-box">
                  <EquityChart equity={equity} benchmark={bench} />
                </div>
              </div>
            )}
            {equity.length < 2 && (
              <div className="notice" style={{ marginBottom: 20 }}>
                模拟盘刚启动, 净值曲线需要积累几个交易日后显示。当前信号已挂单, 将按下一个交易日开盘价成交。
              </div>
            )}

            <h2 className="symbol-title">持仓</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>标的</th><th>股数</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th></tr>
                </thead>
                <tbody>
                  {s.positions.length === 0 && (
                    <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--muted)' }}>暂无持仓</td></tr>
                  )}
                  {s.positions.map((p) => (
                    <tr key={p.symbol}>
                      <td><b>{p.symbol}</b></td>
                      <td>{p.shares.toFixed(1)}</td>
                      <td>{p.avg_cost.toFixed(2)}</td>
                      <td>{p.last?.toFixed(2) ?? '—'}</td>
                      <td>{money(p.market_value)}</td>
                      <td style={{ color: (p.pnl_pct ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                        {pct(p.pnl_pct)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {s.pending.length > 0 && (
              <>
                <h2 className="symbol-title">待成交挂单 (下一交易日开盘价成交)</h2>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>标的</th><th>目标仓位</th><th>信号日</th></tr></thead>
                    <tbody>
                      {s.pending.map((o) => (
                        <tr key={o.symbol}>
                          <td><b>{o.symbol}</b></td>
                          <td>{(o.target_weight * 100).toFixed(0)}% (单票配额)</td>
                          <td>{o.signal_bar}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            <details className="trades" style={{ marginTop: 16 }}>
              <summary>成交记录 ({s.trades.length} 笔)</summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>日期</th><th>标的</th><th>动作</th><th>股数</th><th>成交价</th><th>费用</th></tr>
                  </thead>
                  <tbody>
                    {[...s.trades].reverse().map((t, i) => (
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
          </>
        )}
      </main>
    </div>
  );
}
