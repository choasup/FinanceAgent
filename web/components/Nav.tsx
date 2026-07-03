'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function Nav() {
  const path = usePathname();
  return (
    <>
      <div className="brand">FINANCE&nbsp;AGENT</div>
      <nav className="nav">
        <Link href="/" className={path === '/' ? 'active' : ''}>
          自选
        </Link>
        <Link href="/backtest" className={path === '/backtest' ? 'active' : ''}>
          回测
        </Link>
        <Link href="/agent" className={path === '/agent' ? 'active' : ''}>
          Agent
        </Link>
      </nav>
    </>
  );
}
