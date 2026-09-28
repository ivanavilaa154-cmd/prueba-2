import type { NextConfig } from "next";

// Se exporta como sitio estático y lo sirve FastAPI en /retail (backend/app/retail/rutas.py).
const nextConfig: NextConfig = {
  output: "export",
  basePath: "/retail",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
