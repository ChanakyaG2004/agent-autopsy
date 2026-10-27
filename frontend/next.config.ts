import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.AGENT_AUTOPSY_PUBLIC_DEMO === "true" ? "export" : "standalone",
};

export default nextConfig;
