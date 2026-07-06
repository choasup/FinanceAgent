'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function Nav() {
  const path = usePathname();
  return (
    <>
      <div className="brand">FINANCE&nbsp;AGENT</div>
      {/* 最小化导航: 只留自选入口, 个股页承载回测+Agent。
          批量对比页保留在 /backtest 与 /agent, 需要时直接访问 */}
      <nav className="nav">
        <Link href="/" className={path === '/' ? 'active' : ''}>
          自选
        </Link>
        <Link href="/paper" className={path === '/paper' ? 'active' : ''}>
          模拟盘
        </Link>
      </nav>
    </>
  );
}
