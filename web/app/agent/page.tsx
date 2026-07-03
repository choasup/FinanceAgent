'use client';

import { useState } from 'react';
import Nav from '@/components/Nav';

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

export default function AgentPage() {
  const [symbols, setSymbols] = useState('AAPL, MSFT, NVDA, SPY');
  const [withFund, setWithFund] = useState(false);
  const [loading, setLoading] = useState(false);
  const [verdicts, setVerdicts] = useState<Verdict[]>([]);
  const [error, setError] = useState('');
  const [ran, setRan] = useState(false);

  const run = async () => {
    setLoading(true);
    setRan(true);
    setError('');
    try {
      const res = await fetch('/api/agent/rank', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
          with_fundamentals: withFund,
        }),
      });
      const data = await res.json();
      setVerdicts(data.verdicts ?? []);
    } catch {
      setError('请求失败, 请检查后端服务');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="shell">
      <aside className="side">
        <Nav />
        <div className="field">
          <label>标的代码 (逗号分隔)</label>
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} />
        </div>
        <div className="field">
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={withFund}
              onChange={(e) => setWithFund(e.target.checked)}
              style={{ width: 'auto' }}
            />
            包含基本面 (需联网, 稍慢)
          </label>
        </div>
        <button className="btn-primary" onClick={run} disabled={loading}>
          {loading && <span className="spinner" />}
          {loading ? '分析中…' : '开始分析'}
        </button>
      </aside>

      <main className="main">
        <h1 className="page-title">多因子分析</h1>
        <p className="page-sub">
          自动完成: 拉数据 → 技术面体检 → 回测验证信号 → 综合评级。仅供研究, 不构成投资建议。
        </p>

        {error && <div className="error-box">{error}</div>}

        {!ran && (
          <div className="notice">
            输入几只股票代码, 点 <b>开始分析</b>, 会得到每只股票的技术面体检
            (RSI / 动量 / 距 52 周高点)、回测验证过的信号、以及综合评级排序。约需 10~30 秒。
          </div>
        )}

        {verdicts.length > 1 && (
          <div className="table-wrap" style={{ marginBottom: 24 }}>
            <table>
              <thead>
                <tr>
                  <th>标的</th>
                  <th>评级</th>
                  <th>得分</th>
                  <th>RSI(14)</th>
                  <th>3月动量</th>
                  <th>距52周高点</th>
                </tr>
              </thead>
              <tbody>
                {verdicts.map((v) => (
                  <tr key={v.symbol}>
                    <td><b>{v.symbol}</b></td>
                    <td>
                      <span className={`badge ${badgeClass(v.rating)}`}>{v.rating}</span>
                    </td>
                    <td>{v.score === null ? '—' : v.score.toFixed(0)}</td>
                    <td>{v.technicals?.rsi14 ?? '—'}</td>
                    <td>{v.technicals?.momentum_3m ?? '—'}</td>
                    <td>{v.snapshot?.pct_below_52w_high ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {verdicts.map((v) => (
          <div className="verdict-card" key={v.symbol}>
            <div className="verdict-head">
              <span className="sym">{v.symbol}</span>
              <span className={`badge ${badgeClass(v.rating)}`}>{v.rating}</span>
              <span style={{ color: 'var(--muted)', fontSize: 13 }}>
                综合得分 {v.score === null ? '—' : `${v.score >= 0 ? '+' : ''}${v.score.toFixed(0)}`} / ±100
                （{v.as_of}）
              </span>
            </div>
            <div className="verdict-cols">
              <div>
                <h4>依据</h4>
                <ul>{(v.reasons.length ? v.reasons : ['(无明显看多信号)']).map((r, i) => <li key={i}>{r}</li>)}</ul>
              </div>
              <div>
                <h4>风险</h4>
                <ul>{(v.risks.length ? v.risks : ['(无明显风险信号)']).map((r, i) => <li key={i}>{r}</li>)}</ul>
              </div>
            </div>
          </div>
        ))}
      </main>
    </div>
  );
}
