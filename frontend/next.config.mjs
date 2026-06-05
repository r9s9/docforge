/** @type {import('next').NextConfig} */

// In dev (and when self-hosting the Next server), proxy /api to the FastAPI
// backend so the browser and API share an origin. For a split deployment
// (e.g. Vercel + a separately hosted backend) set NEXT_PUBLIC_API_BASE_URL
// instead and the client will call the backend directly (see lib/api.ts).
const backend = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
