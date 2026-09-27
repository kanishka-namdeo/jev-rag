import type { NextConfig } from "next";

const BACKEND_ORIGIN = process.env.JEVRAG_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  async rewrites() {
    // Proxy the Python FastAPI backend through the Next.js server so the
    // frontend always uses relative URLs. Works both when accessed directly
    // (localhost:3000) and through the sandbox gateway. The backend also
    // serves the same routes under /api/* for direct access.
    return [
      {
        source: "/backend-api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
