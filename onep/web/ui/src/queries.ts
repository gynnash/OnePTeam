import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, api } from "./api";

const readCapabilities = new Set([
  "capability.list",
  "project.list",
  "project.detail",
  "run.status",
  "artifact.list",
  "artifact.read",
  "candidate.list",
  "memory.status",
  "memory.search",
  "settings.global.read",
  "project.settings.read",
  "project.test_commands.discover",
  "analysis.export",
]);

export function isReadActivity(event: Pick<Activity, "type" | "payload">) {
  return (
    event.type.startsWith("action.") &&
    readCapabilities.has(String(event.payload?.capability_id || ""))
  );
}

export const keys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  jobs: ["jobs"] as const,
  activities: ["activities"] as const,
  detail: (project: string) => ["project", project, "detail"] as const,
  logs: (project: string) => ["project", project, "logs"] as const,
  candidates: (project: string) => ["project", project, "candidates"] as const,
  notes: (project: string) => ["project", project, "notes"] as const,
  projectSettings: (project: string) =>
    ["project", project, "settings"] as const,
  globalSettings: ["global-settings"] as const,
};

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: api.projects });
}
export function useJobs() {
  return useQuery({ queryKey: keys.jobs, queryFn: () => api.jobs(100) });
}
export function useActivities() {
  return useQuery({
    queryKey: keys.activities,
    queryFn: () => api.activities(),
  });
}
export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: api.health,
    refetchInterval: 10_000,
  });
}

export function useProjectData(project: string) {
  const detail = useQuery({
    queryKey: keys.detail(project),
    queryFn: () => api.detail(project),
  });
  const logs = useQuery({
    queryKey: keys.logs(project),
    queryFn: () => api.logs(project),
  });
  const candidates = useQuery({
    queryKey: keys.candidates(project),
    queryFn: () => api.candidates(project),
  });
  const notes = useQuery({
    queryKey: keys.notes(project),
    queryFn: () => api.notes(project),
  });
  const settings = useQuery({
    queryKey: keys.projectSettings(project),
    queryFn: () => api.projectSettings(project),
  });
  return { detail, logs, candidates, notes, settings };
}

export function useLiveEvents() {
  const client = useQueryClient();
  const [connection, setConnection] = useState<
    "connected" | "reconnecting" | "offline"
  >("reconnecting");
  useEffect(() => {
    const stream = new EventSource("/api/v1/events/stream");
    let timer = 0;
    const refresh = (eventType: string, projectId?: string) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (eventType.startsWith("job.") || eventType.startsWith("run.")) {
          client.invalidateQueries({ queryKey: keys.jobs });
        }
        if (projectId) {
          if (eventType === "workflow.output") {
            client.invalidateQueries({ queryKey: keys.logs(projectId) });
          } else {
            client.invalidateQueries({ queryKey: ["project", projectId] });
            client.invalidateQueries({ queryKey: keys.projects });
          }
        } else if (!eventType.startsWith("workflow.")) {
          client.invalidateQueries({ queryKey: keys.projects });
        }
      }, 180);
    };
    stream.onopen = () => setConnection("connected");
    stream.onerror = () =>
      setConnection(navigator.onLine ? "reconnecting" : "offline");
    stream.onmessage = (event) => {
      setConnection("connected");
      try {
        const value = JSON.parse(event.data) as Activity;
        if (!value.type || value.type === "heartbeat" || isReadActivity(value))
          return;
        client.setQueryData<{ events: Activity[] }>(
          keys.activities,
          (current) => {
            if (
              !current ||
              current.events.some((item) => item.sequence === value.sequence)
            )
              return current;
            return { events: [...current.events, value].slice(-500) };
          },
        );
        refresh(value.type, value.project_id);
      } catch {
        client.invalidateQueries({ queryKey: keys.jobs });
      }
    };
    return () => {
      window.clearTimeout(timer);
      stream.close();
    };
  }, [client]);
  return connection;
}
