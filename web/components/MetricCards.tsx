export type Metrics = {
  total_return: number | null;
  cagr: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  calmar: number | null;
  win_rate: number | null;
};

const pct = (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null) => (v === null ? '—' : v.toFixed(2));

export default function MetricCards({ m, b }: { m: Metrics; b: Metrics }) {
  const retGap =
    m.total_return !== null && b.total_return !== null
      ? (m.total_return - b.total_return) * 100
      : null;
  const ddGap =
    m.max_drawdown !== null && b.max_drawdown !== null
      ? (m.max_drawdown - b.max_drawdown) * 100
      : null;

  return (
    <div className="metric-grid">
      <div className="metric">
        <div className="label">累计收益</div>
        <div className="value">{pct(m.total_return)}</div>
        {retGap !== null && (
          <div className={`delta ${retGap >= 0 ? 'good' : 'bad'}`}>
            {retGap >= 0 ? '↑ 跑赢' : '↓ 落后'}买入持有 {Math.abs(retGap).toFixed(0)} 个百分点
          </div>
        )}
      </div>
      <div className="metric">
        <div className="label">最大回撤</div>
        <div className="value">{pct(m.max_drawdown)}</div>
        {ddGap !== null && (
          <div className={`delta ${ddGap >= 0 ? 'good' : 'bad'}`}>
            {ddGap >= 0 ? '↑ 更抗跌' : '↓ 跌得更狠'} (买持 {pct(b.max_drawdown)})
          </div>
        )}
      </div>
      <div className="metric">
        <div className="label">年化收益</div>
        <div className="value">{pct(m.cagr)}</div>
        <div className="sub">买持 {pct(b.cagr)}</div>
      </div>
      <div className="metric">
        <div className="label">夏普比率</div>
        <div className="value">{num(m.sharpe)}</div>
        <div className="sub">&gt;1 算不错</div>
      </div>
      <div className="metric">
        <div className="label">卡玛比率</div>
        <div className="value">{num(m.calmar)}</div>
        <div className="sub">收益 / 最大回撤</div>
      </div>
      <div className="metric">
        <div className="label">日胜率</div>
        <div className="value">{pct(m.win_rate)}</div>
        <div className="sub">上涨交易日占比</div>
      </div>
    </div>
  );
}
