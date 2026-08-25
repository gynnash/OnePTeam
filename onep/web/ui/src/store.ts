import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";
export type ComposerDraft = {
  goal?: string;
  source?: string;
  branch?: string;
};

type UIState = {
  theme: Theme;
  density: Density;
  developerMode: boolean;
  inspectorOpen: boolean;
  composerOpen: boolean;
  composerDraft: ComposerDraft;
  setTheme: (theme: Theme) => void;
  setDensity: (density: Density) => void;
  setDeveloperMode: (enabled: boolean) => void;
  setInspectorOpen: (open: boolean) => void;
  setComposerOpen: (open: boolean) => void;
  openComposer: (draft?: ComposerDraft) => void;
};

export function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      theme: "system",
      density: "comfortable",
      developerMode: false,
      inspectorOpen: true,
      composerOpen: false,
      composerDraft: {},
      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
      setDensity: (density) => {
        document.documentElement.dataset.density = density;
        set({ density });
      },
      setDeveloperMode: (developerMode) => set({ developerMode }),
      setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
      setComposerOpen: (composerOpen) => set({ composerOpen }),
      openComposer: (composerDraft = {}) =>
        set({ composerOpen: true, composerDraft }),
    }),
    {
      name: "onep-ui",
      version: 3,
      partialize: ({ theme, density, developerMode, inspectorOpen }) => ({
        theme,
        density,
        developerMode,
        inspectorOpen,
      }),
      migrate: (persisted) => {
        const previous = persisted as Partial<UIState>;
        return {
          theme: previous.theme || "system",
          density: previous.density || "comfortable",
          developerMode: previous.developerMode ?? false,
          inspectorOpen: previous.inspectorOpen ?? true,
        };
      },
      onRehydrateStorage: () => (state) => {
        if (state) {
          applyTheme(state.theme);
          document.documentElement.dataset.density = state.density;
        }
      },
    },
  ),
);

if (typeof matchMedia !== "undefined") {
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    const theme = useUIStore.getState().theme;
    if (theme === "system") applyTheme(theme);
  });
}
