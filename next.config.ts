import type { NextConfig } from "next";

// The pipeline API runs beside this server in the same container.
const PIPELINE = process.env.PIPELINE_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Development server only: hosts other than localhost that may load the
  // site (the loopback address, and GitHub Codespaces' forwarded ports).
  // Without this the dev server refuses them its scripts and pages stop
  // responding to clicks.
  allowedDevOrigins: ["127.0.0.1", "*.app.github.dev", "*.githubpreview.dev"],
  async rewrites() {
    return [
      { source: "/docs", destination: `${PIPELINE}/docs` },
      { source: "/openapi.json", destination: `${PIPELINE}/openapi.json` },
      // Built-in catalogue (CATALOG_BACKEND=local): data downloads and the
      // read-only data API are served through the site's own address, so
      // links work wherever the site is opened from. With CKAN as the
      // backend, resource links point at CKAN and these are simply unused.
      { source: "/datastore/:path*", destination: `${PIPELINE}/datastore/:path*` },
      { source: "/api/3/:path*", destination: `${PIPELINE}/api/3/:path*` },
    ];
  },
};

export default nextConfig;
