/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  async rewrites() {
    // 前端同源 /api/* 代理到 Python 后端 (docker 网络里是 api:8000)
    const api = process.env.API_URL || 'http://localhost:8000';
    return [
      { source: '/api/:path*', destination: `${api}/api/:path*` },
      // 兼容旧 Streamlit 健康检查地址 (quickstart.sh / 运维脚本在用)
      { source: '/_stcore/health', destination: `${api}/api/health` },
    ];
  },
};

export default nextConfig;
