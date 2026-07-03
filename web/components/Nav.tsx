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
          策略回测
        </Link>
        <Link href="/agent" className={path === '/agent' ? 'active' : ''}>
          Agent 分析
        </Link>
      </nav>
    </>
  );
}
