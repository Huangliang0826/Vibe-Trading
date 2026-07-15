import { Suspense, lazy, type ComponentType } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";

const Agent = lazy(() => import("@/pages/Agent").then((m) => ({ default: m.Agent })));
const RunDetail = lazy(() =>
  import("@/pages/RunDetail").then((m) => ({ default: m.RunDetail })),
);
const Compare = lazy(() =>
  import("@/pages/Compare").then((m) => ({ default: m.Compare })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
const Correlation = lazy(() =>
  import("@/pages/Correlation").then((m) => ({ default: m.Correlation })),
);
const AlphaZoo = lazy(() =>
  import("@/pages/AlphaZoo").then((m) => ({ default: m.AlphaZoo })),
);
const Scanner = lazy(() =>
  import("@/pages/Scanner").then((m) => ({ default: m.Scanner })),
);
const NewsCenter = lazy(() =>
  import("@/pages/NewsCenter").then((m) => ({ default: m.NewsCenter })),
);
const Overview = lazy(() =>
  import("@/pages/Overview").then((m) => ({ default: m.Overview })),
);
const Forecast = lazy(() =>
  import("@/pages/Forecast").then((m) => ({ default: m.Forecast })),
);
const HSTech = lazy(() =>
  import("@/pages/HSTech").then((m) => ({ default: m.HSTech })),
);
const ResearchAnalysis = lazy(() =>
  import("@/pages/ResearchAnalysis").then((m) => ({ default: m.ResearchAnalysis })),
);
const PaperTrading = lazy(() =>
  import("@/pages/PaperTrading").then((m) => ({ default: m.PaperTrading })),
);
function PageLoader() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
      Loading…
    </div>
  );
}

function wrap(Component: ComponentType) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/overview", element: wrap(Overview) },

      { path: "/", element: <Navigate to="/overview" replace /> },
      { path: "/agent", element: wrap(Agent) },
      { path: "/settings", element: wrap(Settings) },
      { path: "/runs/:runId", element: wrap(RunDetail) },
      { path: "/compare", element: wrap(Compare) },
      { path: "/correlation", element: wrap(Correlation) },
      { path: "/scanner", element: wrap(Scanner) },
      { path: "/news-center", element: wrap(NewsCenter) },
      { path: "/research-analysis", element: wrap(ResearchAnalysis) },
      { path: "/forecast", element: wrap(Forecast) },
      { path: "/hstech", element: wrap(HSTech) },
      { path: "/paper-trading", element: wrap(PaperTrading) },
      { path: "/video-generation", element: <Navigate to="/settings?tab=video-generation" replace /> },
      { path: "/analytics", element: <Navigate to="/settings?tab=analytics" replace /> },
      { path: "/alpha-zoo", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/bench", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/compare", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/:alphaId", element: wrap(AlphaZoo) },
    ],
  },
]);
