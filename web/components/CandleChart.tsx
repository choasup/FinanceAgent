'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

export type Candle = { time: string; open: number; high: number; low: number; close: number };
export type Trade = { date: string; side: 'BUY' | 'SELL'; shares: number; price: number };

const UP = '#ef5350'; // A股习惯: 红涨
const DOWN = '#26a69a';

export default function CandleChart({ candles, trades }: { candles: Candle[]; trades: Trade[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 420,
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
    chartRef.current = chart;

    const series = chart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });
    series.setData(candles as { time: Time; open: number; high: number; low: number; close: number }[]);

    const showText = trades.length <= 40; // 交易太多时只留箭头, 避免标签互相覆盖
    const markers: SeriesMarker<Time>[] = trades.map((t) => ({
      time: t.date as Time,
      position: t.side === 'BUY' ? 'belowBar' : 'aboveBar',
      color: t.side === 'BUY' ? UP : DOWN,
      shape: t.side === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: showText ? `${t.side === 'BUY' ? '买' : '卖'} ${t.price.toFixed(2)}` : undefined,
    }));
    series.setMarkers(markers);
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [candles, trades]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
