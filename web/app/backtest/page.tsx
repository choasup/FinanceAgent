'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Nav from '@/components/Nav';
import MetricCards, { type Metrics } from '@/components/MetricCards';
import CandleChart, { type Candle, type Trade } from '@/components/CandleChart';
import EquityChart, { type Point } from '@/components/EquityChart';

type StratParam = { name: string; label: string; help: string; type: 'int' | 'float'; default: number };
type StratMeta = { name: string; desc: string; params: StratParam[] };

type Result = {
  symbol: string;
  strategy: string;
  metrics: Metrics;
  benchmark_metrics: Metrics;
  candles: Candle[];
  equity: Point[];
  benchmark: Point[];
  drawdown: Point[];
  trades: (Trade & { cost: number })[];
};

function BacktestPage() {
  const sp = useSearchParams();
  const [strats, setStrats] = useState<StratMeta[]>([]);
  const [stratName, setStratName] = useState('trend_vol');
  const [params, setParams] = useState<Record<string, number>>({});
  const [symbols, setSymbols] = useState(sp.get('symbols') ?? 'AAPL, MSFT');
  const [start, setStart] = useState('2019-01-01');
  const [end, setEnd] = useState('');
  const [cash, setCash] = useState(100000);
  const [commission, setCommission] = useState(0.0005);
  const [slippage, setSlippage] = useState(0.0005);

  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [errors, setErrors] = useState<{ symbol: string; message: string }[]>([]);
  const [ran, setRan] = useState(false);

  useEffect(() => {
    fetch('/api/strategies')
      .then((r) => r.json())
      .then((list: StratMeta[]) => {
        setStrats(list);
        const def = list.find((s) => s.name === 'trend_vol') ?? list[0];
        if (def) selectStrategy(def);
      })
      .catch(() => setErrors([{ symbol: 'API', message: '无法连接后端服务' }]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectStrategy = (s: StratMeta) => {
    setStratName(s.name);
    setParams(Object.fromEntries(s.params.map((p) => [p.name, p.default])));
  };

  const current = strats.find((s) => s.name === stratName);

  const run = useCallback(async () => {
    setLoading(true);
    setRan(true);
    try {
      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
          strategy: stratName,
          params,
          start,
          end: end || null,
          initial_cash: cash,
          commission,
          slippage,
        }),
      });
      const data = await res.json();
      setResults(data.results ?? []);
      setErrors(data.errors ?? []);
    } catch {
      setResults([]);
      setErrors([{ symbol: 'API', message: '请求失败, 请检查后端服务' }]);
    } finally {
      setLoading(false);
    }
  }, [symbols, stratName, params, start, end, cash, commission, slippage]);

  return (
    <div className="shell">
      <aside className="side">
        <Nav />

        <div className="field">
          <label>标的代码 (逗号分隔)</label>
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="AAPL, MSFT" />
        </div>

        <div className="field">
          <label>策略</label>
          <select
            value={stratName}
            onChange={(e) => {
              const s = strats.find((x) => x.name === e.target.value);
              if (s) selectStrategy(s);
            }}
          >
            {strats.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
          {current?.desc && <div className="hint">{current.desc}</div>}
        </div>

        {current && current.params.length > 0 && (
          <>
            <div className="section-label">策略参数</div>
            {current.params.map((p) => (
              <div className="field" key={p.name} title={p.help}>
                <label>{p.label}</label>
                <input
                  type="number"
                  step={p.type === 'float' ? 0.05 : 1}
                  value={params[p.name] ?? p.default}
                  onChange={(e) => setParams({ ...params, [p.name]: Number(e.target.value) })}
                />
                {p.help && <div className="hint">{p.help}</div>}
              </div>
            ))}
          </>
        )}

        <div className="section-label">区间与成本</div>
        <div className="row2">
          <div className="field">
            <label>起始</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>结束 (空=今天)</label>
            <input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="YYYY-MM-DD" />
          </div>
        </div>
        <div className="field">
          <label>初始资金</label>
          <input type="number" step={10000} value={cash} onChange={(e) => setCash(Number(e.target.value))} />
        </div>
        <div className="row2">
          <div className="field">
            <label>手续费率</label>
            <input type="number" step={0.0001} value={commission} onChange={(e) => setCommission(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>滑点率</label>
            <input type="number" step={0.0001} value={slippage} onChange={(e) => setSlippage(Number(e.target.value))} />
          </div>
        </div>

        <button className="btn-primary" onClick={run} disabled={loading}>
          {loading && <span className="spinner" />}
          {loading ? '回测中…' : '运行回测'}
        </button>
      </aside>

      <main className="main">
        <h1 className="page-title">策略回测</h1>
        <p className="page-sub">左侧选标的 / 策略 / 参数, 一键回测。仅供研究, 不构成投资建议。</p>

        {errors.map((e) => (
          <div className="error-box" key={e.symbol}>
            <b>{e.symbol}</b>: {e.message}
          </div>
        ))}

        {!ran && (
          <div className="notice">
            在左侧设置参数后点击 <b>运行回测</b>。K 线图上会标出每一次买卖:
            红↑买入、绿↓卖出, 可滚轮缩放、拖动查看细节。
          </div>
        )}

        {results.map((r) => {
          const nBuy = r.trades.filter((t) => t.side === 'BUY').length;
          return (
            <section key={r.symbol}>
              <h2 className="symbol-title">
                {r.symbol}
                <span>{r.strategy}</span>
              </h2>
              <MetricCards m={r.metrics} b={r.benchmark_metrics} />

              <div className="chart-block">
                <div className="chart-title">
                  K线与买卖点 <span>— 共买入 {nBuy} 次、卖出 {r.trades.length - nBuy} 次 (红↑买 绿↓卖)</span>
                </div>
                <div className="chart-box">
                  <CandleChart candles={r.candles} trades={r.trades} />
                </div>
              </div>

              <div className="chart-block">
                <div className="chart-title">
                  资金曲线 <span>— 金线=策略, 蓝虚线=买入持有, 底部红色阴影=回撤</span>
                </div>
                <div className="chart-box">
                  <EquityChart equity={r.equity} benchmark={r.benchmark} drawdown={r.drawdown} />
                </div>
              </div>

              <details className="trades">
                <summary>成交明细 ({r.trades.length} 笔)</summary>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>动作</th>
                        <th>股数</th>
                        <th>成交价</th>
                        <th>费用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.trades.map((t, i) => (
                        <tr key={i}>
                          <td>{t.date}</td>
                          <td className={t.side === 'BUY' ? 'buy' : 'sell'}>
                            {t.side === 'BUY' ? '买入' : '卖出'}
                          </td>
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
        })}
      </main>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BacktestPage />
    </Suspense>
  );
}
