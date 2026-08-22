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
          Component: (await import("./pages/dashboard")).DashboardPage,
        }),
      },
      {
        path: "projects",
        lazy: async () => ({
          Component: (await import("./pages/projects")).ProjectsPage,
        }),
      },
      {
        path: "tasks",
        lazy: async () => ({
          Component: (await import("./pages/tasks")).TasksPage,
        }),
      },
      {
        path: "knowledge",
        lazy: async () => ({
          Component: (await import("./pages/knowledge")).KnowledgePage,
        }),
      },
      {
        path: "settings",
        lazy: async () => ({
          Component: (await import("./pages/settings")).GlobalSettingsPage,
        }),
      },
      {
        path: "projects/:projectId/:section?",
        lazy: async () => ({
          Component: (await import("./pages/project")).ProjectPage,
        }),
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
