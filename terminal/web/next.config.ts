import type { NextConfig } from "next";
const config: NextConfig = {
  async rewrites() {
    return [
      {source: "/research/:path*", destination: `${process.env.NQ_API_URL || "http://127.0.0.1:8000"}/research/:path*`},
      {
        source: "/api/:path*",
        destination: `${process.env.NQ_API_URL || "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
};
export default config;
