import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePref = "system" | "light" | "dark";

/** Validated categorical palette (fixed slot order) plus chart chrome, per mode. */
const PALETTES = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    other: "#b5b3ac",
    previous: "#a9a79f",
    grid: "#e1e0d9",
    axis: "#c3c2b7",
    muted: "#7a7873",
    surface: "#fcfcfb",
    ink: "#0b0b0b",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    other: "#5c5b57",
    previous: "#6d6b66",
    grid: "#2c2c2a",
    axis: "#383835",
    muted: "#95938c",
    surface: "#1a1a19",
    ink: "#f0efec",
  },
};
export type ChartPalette = (typeof PALETTES)["light"];

interface ThemeCtx {
  pref: ThemePref;
  setPref: (p: ThemePref) => void;
  mode: "light" | "dark";
  palette: ChartPalette;
}

const Ctx = createContext<ThemeCtx | null>(null);

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem("theme");
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readPref);
  const [systemDark, setSystemDark] = useState(() => matchMedia("(prefers-color-scheme: dark)").matches);

  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const mode = pref === "system" ? (systemDark ? "dark" : "light") : pref;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", mode === "dark");
  }, [mode]);

  const value = useMemo<ThemeCtx>(
    () => ({
      pref,
      mode,
      palette: PALETTES[mode],
      setPref: (p) => {
        setPrefState(p);
        try {
          localStorage.setItem("theme", p);
        } catch {
          /* storage unavailable */
        }
      },
    }),
    [pref, mode],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTheme outside ThemeProvider");
  return v;
}
