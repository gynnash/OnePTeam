import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

type UIState = {
  theme: Theme;
  density: Density;
  sidebarCollapsed: boolean;
  inspectorOpen: boolean;
  composerOpen: boolean;
  setTheme: (theme: Theme) => void;
  setDensity: (density: Density) => void;
  toggleSidebar: () => void;
  setInspectorOpen: (open: boolean) => void;
  setComposerOpen: (open: boolean) => void;
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
      sidebarCollapsed: false,
      inspectorOpen: true,
      composerOpen: false,
      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
      setDensity: (density) => {
        document.documentElement.dataset.density = density;
        set({ density });
      },
      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setInspectorOpen: (inspectorOpen) => set({ inspectorOpen }),
      setComposerOpen: (composerOpen) => set({ composerOpen }),
    }),
    {
      name: "onep-ui",
      version: 1,
      partialize: ({ theme, density, sidebarCollapsed, inspectorOpen }) => ({
        theme,
        density,
        sidebarCollapsed,
        inspectorOpen,
      }),
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
