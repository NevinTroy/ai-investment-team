import type { NextConfig } from "next";

// FastAPI (committee/api.py) stays the backend of record on :8000.
// Proxying /api/* and the app icon through the Next dev server keeps
// everything same-origin — no CORS configuration needed anywhere.
const API_ORIGIN = process.env.ARCHER_API_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {
  // The dev server proxies /api/* to FastAPI and buffers the request body,
  // capped at 10MB by default — which truncates larger deck uploads
  // (POST /api/analyze-deck) and corrupts the multipart body. Raise it to 100MB.
  // (Renamed to `proxyClientMaxBodySize` in Next 16; this is the 15.x name.)
  experimental: {
    middlewareClientMaxBodySize: "100mb",
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/app_icon.png", destination: `${API_ORIGIN}/app_icon.png` },
    ];
  },
};

export default nextConfig;
