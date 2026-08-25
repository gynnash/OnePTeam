import { createHashRouter, Navigate } from "react-router";
import App from "./App";
import { RouteError } from "./components/ui";

function RouteFallback() {
  return (
    <div className="route-loader" role="status" aria-live="polite">
      <span />
      正在加载工作台…
    </div>
  );
}

export const router = createHashRouter([
  {
    path: "/",
    Component: App,
    ErrorBoundary: RouteError,
    HydrateFallback: RouteFallback,
    children: [
      {
        index: true,
        lazy: async () => ({
          Component: (await import("./pages/studio-dashboard")).StudioDashboardPage,
        }),
      },
      {
        path: "projects",
        lazy: async () => ({
          Component: (await import("./pages/studio-projects")).StudioProjectsPage,
        }),
      },
      {
        path: "runs",
        lazy: async () => ({
          Component: (await import("./pages/studio-runs")).StudioRunsPage,
        }),
      },
      {
        path: "knowledge",
        lazy: async () => ({
          Component: (await import("./pages/studio-knowledge")).StudioKnowledgePage,
        }),
      },
      {
        path: "articles",
        lazy: async () => ({
          Component: (await import("./pages/articles")).ArticlesPage,
        }),
      },
      {
        path: "articles/:articleId",
        lazy: async () => ({
          Component: (await import("./pages/article-editor")).ArticleEditorPage,
        }),
      },
      {
        path: "settings",
        lazy: async () => ({
          Component: (await import("./pages/studio-settings")).StudioSettingsPage,
        }),
      },
      {
        path: "projects/:projectId/:section?",
        lazy: async () => ({
          Component: (await import("./pages/studio-project")).StudioProjectPage,
        }),
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
