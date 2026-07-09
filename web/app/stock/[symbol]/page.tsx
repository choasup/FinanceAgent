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

type Factor = { name: string; value: string; score: number; max: number; note: string };
type Dossier = {
  symbol: string;
  as_of: string;
  price: number;
  score: number;
  rating: string;
  scorecard: Factor[];
  ma: { alignment: string | null };
  risk: {
    vol20_ann: number;
    vol_percentile_1y: number | null;
    beta_vs_spy_1y: number | null;
    drawdown_from_peak: number;
    worst_day: { date: string; ret: number };
  };
  relative: Record<string, number | null>;
  levels: Record<string, number | null>;
  triggers: string[];
  volume_events: { date: string; ret: number; vol_ratio: number }[];
};

const badgeClass = (rating: string) =>
  rating.includes('看多') ? 'bull' : rating.includes('看空') ? 'bear' : 'flat';

const pctRet = (v: number | null) => (v === null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(0)}%`);

function BattleReport({ m, b, strat }: { m: Metrics; b: Metrics; strat: string }) {
  const sr = m.total_return ?? 0;
  const br = b.total_return ?? 0;
  const gap = Math.round((sr - br) * 100);
  const win = sr >= br;
  // max_drawdown 是负数, 更接近 0 = 更抗跌
  const ddBetter = (m.max_drawdown ?? 0) >= (b.max_drawdown ?? 0);
  let note: React.ReactNode;
  if (win) {
    note = <>结论: <b>{strat} 跑赢了买入持有</b> —— 主动操作在这只票上历史有效, 值得进一步验证。</>;
  } else if (ddBetter) {
    note = <>结论: 策略<b>少赚但更抗跌</b> —— 牛市跟不上、下跌时护身, 属于"保险型"打法。</>;
  } else {
    note = <>结论: 策略<b>既没多赚、回撤也没更小</b> —— 这只票过去更适合买入后拿住, 别折腾。</>;
  }
  return (
    <>
      <div className="battle">
        <div className="verdict-cell">
          <span className="vtag">这个策略 VS 躺平不动</span>
          <span className={`vhead ${win ? 'win' : 'lose'}`}>
            {win ? '↑ 跑赢' : '↓ 跑输'} {Math.abs(gap)} 个百分点
          </span>
        </div>
        <div>
          <div className="col-label">策略累计</div>
          <div className={`col-val ${win ? '' : ''}`} style={{ color: win ? 'var(--good)' : 'var(--text)' }}>{pctRet(m.total_return)}</div>
        </div>
        <div>
          <div className="col-label">躺平累计</div>
          <div className="col-val dim">{pctRet(b.total_return)}</div>
        </div>
        <div>
          <div className="col-label">策略最大回撤</div>
          <div className="col-val" style={{ color: ddBetter ? 'var(--good)' : 'var(--bad)' }}>{pctRet(m.max_drawdown)}</div>
        </div>
        <div>
          <div className="col-label">躺平最大回撤</div>
          <div className="col-val dim">{pctRet(b.max_drawdown)}</div>
        </div>
      </div>
      <div className="battle-note">{note}</div>
    </>
  );
}

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
  const [verdict, setVerdict] = useState<Dossier | null>(null);
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
          await fetch('/api/agent/deep', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol }),
          })
        ).json();
        setVerdict(d?.symbol ? d : null);
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

        {/* ---- Agent 深度档案 ---- */}
        <div className="verdict-card">
          {agentLoading ? (
            <div style={{ color: 'var(--muted)', fontSize: 13.5 }}>Agent 深度分析中 (因子记分 → 价位 → 风险画像)…</div>
          ) : verdict ? (
            <>
              <div className="verdict-head">
                <span style={{ fontSize: 14, fontWeight: 700 }}>Agent 深度档案</span>
                <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>数据截至 {verdict.as_of}</span>
              </div>

              <h4 style={{ fontSize: 12.5, color: 'var(--muted)', margin: '10px 0 6px' }}>因子记分卡 (每一分都可溯源)</h4>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>因子</th><th>取值</th><th>得分</th><th>说明</th></tr></thead>
                  <tbody>
                    {verdict.scorecard.map((f) => (
                      <tr key={f.name}>
                        <td>{f.name}</td>
                        <td>{f.value}</td>
                        <td style={{ color: f.score > 0 ? 'var(--up)' : f.score < 0 ? 'var(--down)' : 'var(--muted)' }}>
                          {f.score > 0 ? '+' : ''}{f.score}/{f.max}
                        </td>
                        <td style={{ color: 'var(--muted)', fontSize: 12, textAlign: 'left' }}>{f.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="verdict-cols" style={{ marginTop: 14 }}>
                <div>
                  <h4>关键价位与信号</h4>
                  <ul>
                    <li>20日支撑 ${verdict.levels.support_20d} / 阻力 ${verdict.levels.resistance_20d}</li>
                    {verdict.levels.sma50 && <li>50日均线 ${verdict.levels.sma50}</li>}
                    {verdict.levels.sma200 && <li>200日均线 ${verdict.levels.sma200}</li>}
                    <li>52周区间 ${verdict.levels.low_52w} ~ ${verdict.levels.high_52w}</li>
                    {verdict.triggers.map((t, i) => <li key={i} style={{ color: 'var(--gold)' }}>{t}</li>)}
                  </ul>
                </div>
                <div>
                  <h4>风险画像</h4>
                  <ul>
                    <li>年化波动 {(verdict.risk.vol20_ann * 100).toFixed(0)}%
                      {verdict.risk.vol_percentile_1y !== null && ` (一年 ${(verdict.risk.vol_percentile_1y * 100).toFixed(0)}% 分位)`}</li>
                    {verdict.risk.beta_vs_spy_1y !== null && <li>贝塔 {verdict.risk.beta_vs_spy_1y} (大盘动 1% 它动 {verdict.risk.beta_vs_spy_1y}%)</li>}
                    <li>距高点回撤 {(verdict.risk.drawdown_from_peak * 100).toFixed(0)}%</li>
                    <li>最惨单日 {verdict.risk.worst_day.date} ({(verdict.risk.worst_day.ret * 100).toFixed(1)}%)</li>
                    {verdict.relative.vs_SPY_3m !== undefined && verdict.relative.vs_SPY_3m !== null && (
                      <li>3月跑{verdict.relative.vs_SPY_3m >= 0 ? '赢' : '输'}大盘 {(Math.abs(verdict.relative.vs_SPY_3m) * 100).toFixed(0)}%</li>
                    )}
                  </ul>
                </div>
              </div>

              {verdict.volume_events.length > 0 && (
                <>
                  <h4 style={{ fontSize: 12.5, color: 'var(--muted)', margin: '12px 0 6px' }}>量能异动事件日 (近90天, 放量&gt;2.5倍且波动&gt;5%)</h4>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {verdict.volume_events.map((e) => (
                      <span key={e.date} className="chip" style={{ color: e.ret >= 0 ? 'var(--up)' : 'var(--down)' }}>
                        {e.date} {e.ret >= 0 ? '+' : ''}{(e.ret * 100).toFixed(1)}% ({e.vol_ratio}x量)
                      </span>
                    ))}
                  </div>
                </>
              )}
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

            <BattleReport m={result.metrics} b={result.benchmark_metrics} strat={result.strategy} />
            <MetricCards m={result.metrics} b={result.benchmark_metrics} />

            <div className="chart-block">
              <div className="chart-title">
                资金曲线 <span>— 金线=按策略操作, 蓝虚线=一直拿着不动; 线越高越赚。底部红色=策略的回撤(离高点多远)</span>
              </div>
              <div className="chart-box">
                <EquityChart equity={result.equity} benchmark={result.benchmark} drawdown={result.drawdown} />
              </div>
            </div>

            <div className="chart-block">
              <div className="chart-title">
                K线与买卖点 <span>— 策略在这只票上的每一次操作: 红↑买入 绿↓卖出, 共 {nBuy} 买 {result.trades.length - nBuy} 卖</span>
              </div>
              <div className="chart-box">
                <CandleChart candles={result.candles} trades={result.trades} />
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
