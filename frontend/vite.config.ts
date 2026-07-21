import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { readFileSync } from "node:fs";

const packageJson = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8"));

const PROXY_PATHS = [
  "/health",
  "/sessions",
  "/swarm/presets",
  "/swarm/runs",
  "/settings/llm",
  "/settings/data-sources",
  "/mandate",
  "/live",
  "/upload",
  "/shadow-reports",
  "/api",
];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_URL || "http://127.0.0.1:8899";
  const apiProxy = { target: apiTarget, changeOrigin: true };
  const apiProxyWithHtmlFallback = {
    ...apiProxy,
    bypass(req: { headers: { accept?: string } }) {
      if (req.headers.accept?.includes("text/html")) {
        return "/index.html";
      }
    },
  };

  return {
    plugins: [react()],
    define: {
      __APP_VERSION__: JSON.stringify(packageJson.version),
    },
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      host: true, // 监听所有网卡,允许手机等局域网设备访问
      // 允许通过稳定的 Bonjour 主机名访问(如 Liangs-MacBook-Air.local),
      // 否则 Vite 的 host 校验会对 .local 域名返回 403
      allowedHosts: [".local"],
      port: 5899,
      proxy: {
        ...Object.fromEntries(PROXY_PATHS.map((p) => [p, apiProxy])),
        // SPA RunDetail page — only the two-segment ``/runs/{id}``
        // form should fall back to ``index.html`` on browser navigation.
        // ``/runs/{id}/code`` and ``/runs/{id}/pine`` are API-only and
        // must keep proxying to the backend even when Accept is text/html.
        "^/runs/[^/]+/?$": apiProxyWithHtmlFallback,
        "/runs": apiProxy,
        "/correlation": apiProxyWithHtmlFallback,
        "^/alpha(?:/|$)": apiProxy,
        "/market-indices": apiProxy,
        "/watchlist": apiProxy,
        "^/stock/": apiProxy,
        "/opportunities": apiProxy,
        "/historical-events": apiProxy,
        "^/news-center/": apiProxy,
        "^/scan/": apiProxy,
        "^/research-analysis/": apiProxy,
        "^/paper-trading/": apiProxy,
        "^/asset-management/": apiProxy,
        "^/research/": apiProxy,
        "^/forecast/": apiProxy,
        "^/hstech/": apiProxy,
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            "vendor-react": ["react", "react-dom", "react-router-dom"],
            "vendor-charts": ["echarts"],
          },
        },
      },
    },
  };
});
