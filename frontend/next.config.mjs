/** @type {import('next').NextConfig} */

// In dev (and when self-hosting the Next server), proxy /api to the FastAPI
// backend so the browser and API share an origin. For a split deployment
// (e.g. Vercel + a separately hosted backend) set NEXT_PUBLIC_API_BASE_URL
// instead and the client will call the backend directly (see lib/api.ts).
//
// Use 127.0.0.1 (not "localhost"): on Windows/Node "localhost" can resolve to
// IPv6 ::1 first, but the backend binds to IPv4 127.0.0.1 — so a "localhost"
// target makes the server-side proxy hang ~2s on ::1 then fail, surfacing as an
// "internal server error after a couple of seconds" in the browser.
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
