'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
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

type AnalyzeRow = {
  strategy: string;
  desc: string;
  cagr: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  calmar: number | null;
  trades: number;
};

type Verdict = {
  symbol: string;
  as_of: string;
  score: number | null;
  rating: string;
  reasons: string[];
  risks: string[];
  technicals: Record<string, number | null>;
  snapshot: Record<string, number | null>;
};

const badgeClass = (rating: string) =>
  rating.includes('看多') ? 'bull' : rating.includes('看空') ? 'bear' : 'flat';

export default function StockPage({ params: routeParams }: { params: { symbol: string } }) {
  const symbol = decodeURIComponent(routeParams.symbol).toUpperCase();

  const [strats, setStrats] = useState<StratMeta[]>([]);
  const [stratName, setStratName] = useState('trend_vol');
  const [params, setParams] = useState<Record<string, number>>({});
  const [start, setStart] = useState('2019-01-01');
  const [end, setEnd] = useState('');
  const [cash, setCash] = useState(100000);
  const [commission, setCommission] = useState(0.0005);
  const [slippage, setSlippage] = useState(0.0005);

  const [result, setResult] = useState<Result | null>(null);
  const [btError, setBtError] = useState('');
  const [btLoading, setBtLoading] = useState(true);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [agentLoading, setAgentLoading] = useState(true);
  const [fitRows, setFitRows] = useState<AnalyzeRow[]>([]);
  const [bestStrat, setBestStrat] = useState('');

  const runBacktest = useCallback(
    async (strategy: string, stratParams: Record<string, number>) => {
      setBtLoading(true);
      setBtError('');
      try {
        const res = await fetch('/api/backtest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbols: [symbol],
            strategy,
            params: stratParams,
            start,
            end: end || null,
            initial_cash: cash,
            commission,
            slippage,
          }),
        });
        const data = await res.json();
        if (data.results?.length) setResult(data.results[0]);
        else setBtError(data.errors?.[0]?.message ?? '回测失败');
      } catch {
        setBtError('请求失败, 请检查后端服务');
      } finally {
        setBtLoading(false);
      }
    },
    [symbol, start, end, cash, commission, slippage],
  );

  useEffect(() => {
    // 串行: 策略元信息 → 全策略适配对比 → 用历史最优策略出详情 → Agent 评级
    // (并发网络抓取会压垮数据源)
    (async () => {
      try {
        const list: StratMeta[] = await (await fetch('/api/strategies')).json();
        setStrats(list);

        let bestName = 'trend_vol';
        try {
          const fit = await (
            await fetch('/api/stock/analyze', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ symbol, start: '2019-01-01' }),
            })
          ).json();
          setFitRows(fit.rows ?? []);
          if (fit.best) bestName = fit.best;
          setBestStrat(bestName);
        } catch {
          /* 适配表失败不阻塞详情 */
        }

        const def = list.find((s) => s.name === bestName) ?? list[0];
        if (def) {
          const p = Object.fromEntries(def.params.map((x) => [x.name, x.default]));
          setStratName(def.name);
          setParams(p);
          await runBacktest(def.name, p);
        }
      } catch {
        setBtError('无法连接后端服务');
        setBtLoading(false);
      }
      try {
        setAgentLoading(true);
        const d = await (
          await fetch('/api/agent/rank', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols: [symbol] }),
          })
        ).json();
        setVerdict(d.verdicts?.[0] ?? null);
      } catch {
        setVerdict(null);
      } finally {
        setAgentLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const current = strats.find((s) => s.name === stratName);
  const nBuy = result?.trades.filter((t) => t.side === 'BUY').length ?? 0;

  return (
    <div className="shell">
      <aside className="side">
        <Nav />
        <Link href="/" style={{ color: 'var(--muted)', fontSize: 13 }}>← 返回自选</Link>

        <div className="section-label">回测策略</div>
        <div className="field">
          <select
            value={stratName}
            onChange={(e) => {
              const s = strats.find((x) => x.name === e.target.value);
              if (s) {
                const p = Object.fromEntries(s.params.map((x) => [x.name, x.default]));
                setStratName(s.name);
                setParams(p);
              }
            }}
          >
            {strats.map((s) => (
              <option key={s.name} value={s.name}>{s.name}</option>
            ))}
          </select>
          {current?.desc && <div className="hint">{current.desc}</div>}
        </div>

        {current?.params.map((p) => (
          <div className="field" key={p.name} title={p.help}>
            <label>{p.label}</label>
            <input
              type="number"
              step={p.type === 'float' ? 0.05 : 1}
              value={params[p.name] ?? p.default}
              onChange={(e) => setParams({ ...params, [p.name]: Number(e.target.value) })}
            />
          </div>
        ))}

        <div className="section-label">区间与成本</div>
        <div className="row2">
          <div className="field">
            <label>起始</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>结束</label>
            <input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="空=今天" />
          </div>
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
        <div className="field">
          <label>初始资金</label>
          <input type="number" step={10000} value={cash} onChange={(e) => setCash(Number(e.target.value))} />
        </div>

        <button className="btn-primary" onClick={() => runBacktest(stratName, params)} disabled={btLoading}>
          {btLoading && <span className="spinner" />}
          {btLoading ? '回测中…' : '重新回测'}
        </button>
      </aside>

      <main className="main">
        <h1 className="page-title">
          {symbol}
          {verdict && (
            <span className={`badge ${badgeClass(verdict.rating)}`} style={{ marginLeft: 12, verticalAlign: 'middle' }}>
              {verdict.rating} {verdict.score !== null && `${verdict.score >= 0 ? '+' : ''}${verdict.score.toFixed(0)}分`}
            </span>
          )}
        </h1>
        <p className="page-sub">Agent 评级与策略回测一站式视图。仅供研究, 不构成投资建议。</p>

        {/* ---- Agent 评级 ---- */}
        <div className="verdict-card">
          {agentLoading ? (
            <div style={{ color: 'var(--muted)', fontSize: 13.5 }}>Agent 分析中 (拉数据 → 技术面 → 回测验证)…</div>
          ) : verdict ? (
            <>
              <div className="verdict-head">
                <span style={{ fontSize: 14, fontWeight: 700 }}>Agent 多因子分析</span>
                <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>{verdict.as_of}</span>
              </div>
              <div className="verdict-cols">
                <div>
                  <h4>依据</h4>
                  <ul>{(verdict.reasons.length ? verdict.reasons : ['(无明显看多信号)']).map((r, i) => <li key={i}>{r}</li>)}</ul>
                </div>
                <div>
                  <h4>风险</h4>
                  <ul>{(verdict.risks.length ? verdict.risks : ['(无明显风险信号)']).map((r, i) => <li key={i}>{r}</li>)}</ul>
                </div>
              </div>
            </>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 13.5 }}>Agent 分析不可用</div>
          )}
        </div>

        {/* ---- 策略适配表 ---- */}
        {fitRows.length > 0 && (
          <>
            <h2 className="symbol-title" style={{ marginTop: 22 }}>
              策略适配<span>2019 至今, 这只票什么打法有效</span>
            </h2>
            <div className="table-wrap" style={{ marginBottom: 8 }}>
              <table>
                <thead>
                  <tr>
                    <th>策略</th><th>年化收益</th><th>最大回撤</th><th>夏普</th><th>卡玛</th><th>交易次数</th>
                  </tr>
                </thead>
                <tbody>
                  {fitRows.map((r) => {
                    const isBest = r.strategy === bestStrat;
                    const isBench = r.strategy === 'buy_hold';
                    return (
                      <tr
                        key={r.strategy}
                        title={r.desc}
                        onClick={() => {
                          if (isBench) return;
                          const s = strats.find((x) => x.name === r.strategy);
                          if (s) {
                            const p = Object.fromEntries(s.params.map((x) => [x.name, x.default]));
                            setStratName(s.name);
                            setParams(p);
                            runBacktest(s.name, p);
                          }
                        }}
                        style={{
                          cursor: isBench ? 'default' : 'pointer',
                          background: isBest ? 'rgba(230,180,80,0.07)' : undefined,
                        }}
                      >
                        <td>
                          {isBench ? '🛋 买入持有' : r.strategy}
                          {isBest && <span style={{ color: 'var(--gold)', marginLeft: 6 }}>★ 历史最优</span>}
                        </td>
                        <td>{r.cagr === null ? '—' : `${(r.cagr * 100).toFixed(1)}%`}</td>
                        <td>{r.max_drawdown === null ? '—' : `${(r.max_drawdown * 100).toFixed(1)}%`}</td>
                        <td>{r.sharpe === null ? '—' : r.sharpe.toFixed(2)}</td>
                        <td>{r.calmar === null ? '—' : r.calmar.toFixed(2)}</td>
                        <td>{r.trades}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="page-sub" style={{ marginBottom: 20 }}>
              按"卡玛比率"(每承担一分回撤换多少年化收益) 选出历史最优; 点任意策略行查看它的详细回测。
              买入持有跑赢全部策略时, 说明这只票过去更适合拿住不折腾。
            </p>
          </>
        )}

        {/* ---- 回测 ---- */}
        {btError && <div className="error-box">{btError}</div>}
        {result && (
          <>
            <h2 className="symbol-title" style={{ marginTop: 22 }}>
              策略回测<span>{result.strategy}</span>
            </h2>
            <MetricCards m={result.metrics} b={result.benchmark_metrics} />

            <div className="chart-block">
              <div className="chart-title">
                K线与买卖点 <span>— 共买入 {nBuy} 次、卖出 {result.trades.length - nBuy} 次 (红↑买 绿↓卖)</span>
              </div>
              <div className="chart-box">
                <CandleChart candles={result.candles} trades={result.trades} />
              </div>
            </div>

            <div className="chart-block">
              <div className="chart-title">
                资金曲线 <span>— 金线=策略, 蓝虚线=买入持有, 底部红色阴影=回撤</span>
              </div>
              <div className="chart-box">
                <EquityChart equity={result.equity} benchmark={result.benchmark} drawdown={result.drawdown} />
              </div>
            </div>

            <details className="trades">
              <summary>成交明细 ({result.trades.length} 笔)</summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>日期</th><th>动作</th><th>股数</th><th>成交价</th><th>费用</th></tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i}>
                        <td>{t.date}</td>
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
