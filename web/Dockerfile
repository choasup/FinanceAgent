# FinanceAgent Web (Next.js) 多阶段构建
# NPM_REGISTRY 可通过 build-arg 覆盖; 国内服务器建议 https://registry.npmmirror.com

FROM node:20-alpine AS deps
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm config set registry ${NPM_REGISTRY} && npm ci

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# rewrites 在构建期固化, API 地址必须在 build 时注入 (compose 网络里是 http://api:8000)
ARG API_URL=http://api:8000
ENV API_URL=${API_URL} NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD wget -q -O /dev/null http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
