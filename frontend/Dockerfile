# DocForge frontend (Next.js 14). Runs the Next server; /api is proxied to the
# backend service via BACKEND_URL (see next.config.mjs).
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

ENV PORT=3000
EXPOSE 3000

CMD ["npm", "run", "start"]
