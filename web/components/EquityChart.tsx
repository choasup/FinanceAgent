'use client';

import { useEffect, useRef } from 'react';
import { createChart, ColorType, type Time } from 'lightweight-charts';

export type Point = { time: string; value: number | null };

export default function EquityChart({
  equity,
  benchmark,
  drawdown,
}: {
  equity: Point[];
  benchmark: Point[];
  drawdown?: Point[];
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 300,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#9aa3b8',
      },
      grid: {
        vertLines: { color: 'rgba(154,163,184,0.1)' },
        horzLines: { color: 'rgba(154,163,184,0.1)' },
      },
      timeScale: { borderVisible: false },
      rightPriceScale: { borderVisible: false },
      autoSize: true,
    });

    const clean = (pts: Point[]) =>
      pts.filter((p) => p.value !== null) as { time: Time; value: number }[];

    const strat = chart.addLineSeries({ color: '#e6b450', lineWidth: 2, title: '策略' });
    strat.setData(clean(equity));
    const bench = chart.addLineSeries({
      color: '#5b7fff',
      lineWidth: 1,
      title: '买入持有',
      lineStyle: 2,
    });
    bench.setData(clean(benchmark));

    if (drawdown) {
      const dd = chart.addAreaSeries({
        priceScaleId: 'dd',
        topColor: 'rgba(248,113,113,0.0)',
        bottomColor: 'rgba(248,113,113,0.25)',
        lineColor: 'rgba(248,113,113,0.6)',
        lineWidth: 1,
      });
      dd.setData(clean(drawdown));
      chart.priceScale('dd').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 }, visible: false });
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [equity, benchmark, drawdown]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
