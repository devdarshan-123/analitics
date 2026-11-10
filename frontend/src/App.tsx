import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Header, TABS, type TabId } from "./components/Header";
import { ErrorState, Skeleton } from "./components/ui";
import { useAuth, useProperties } from "./hooks/queries";
import { loadSavedProperty, pickProperty, PropertyContext, saveProperty, type PropertyContextValue } from "./lib/property";
import { PRESETS, presetRange, type RangeState } from "./lib/range";
import { Acquisition } from "./pages/Acquisition";
import { Behaviour } from "./pages/Behaviour";
import { Content } from "./pages/Content";
import { Events } from "./pages/Events";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Settings } from "./pages/Settings";

function tabFromHash(): TabId {
  const h = window.location.hash.replace("#", "");
  return (TABS.find((t) => t.id === h)?.id ?? "overview") as TabId;
}

function loadRange(): RangeState {
  try {
    const saved = JSON.parse(localStorage.getItem("range") ?? "null");
    if (saved?.preset && PRESETS.some((p) => p.key === saved.preset)) return { ...saved, ...presetRange(saved.preset) };
    if (saved?.preset === "custom" && saved?.start && saved?.end) return saved;
  } catch {
    /* ignore */
  }
  return { preset: "30d", ...presetRange("30d"), compare: true };
}

export default function App() {
  const qc = useQueryClient();
  const auth = useAuth();
  const [tab, setTab] = useState<TabId>(tabFromHash);
  const [range, setRange] = useState<RangeState>(loadRange);
  const [savedProperty, setSavedProperty] = useState<string | null>(loadSavedProperty);
  const properties = useProperties(!!auth.data?.authenticated);

  const propertyCtx = useMemo<PropertyContextValue>(() => {
    const selected = properties.data ? pickProperty(properties.data, savedProperty) : null;
    return {
      propertyId: selected?.propertyId ?? null,
      property: selected,
      ready: properties.isSuccess || properties.isError,
      setPropertyId: (id: string) => {
        setSavedProperty(id);
        saveProperty(id);
      },
    };
  }, [properties.data, properties.isSuccess, properties.isError, savedProperty]);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    const onExpired = () => qc.setQueryData(["auth"], { authenticated: false, mock_mode: auth.data?.mock_mode ?? false });
    window.addEventListener("hashchange", onHash);
    window.addEventListener("auth:expired", onExpired);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("auth:expired", onExpired);
    };
  }, [qc, auth.data?.mock_mode]);

  const changeTab = (t: TabId) => {
    window.location.hash = t;
    setTab(t);
  };
  const changeRange = (r: RangeState) => {
    setRange(r);
    try {
      localStorage.setItem("range", JSON.stringify(r));
    } catch {
      /* ignore */
    }
  };

  if (auth.isLoading) {
    return (
      <div className="mx-auto max-w-7xl p-6">
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (auth.error) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <ErrorState error={auth.error} onRetry={() => auth.refetch()} />
      </div>
    );
  }
  if (!auth.data?.authenticated) return <Login />;

  return (
    <PropertyContext.Provider value={propertyCtx}>
    <div className="min-h-screen">
      <Header
        tab={tab}
        onTab={changeTab}
        range={range}
        onRange={changeRange}
        mockMode={auth.data.mock_mode}
        properties={{ list: properties.data, isLoading: properties.isLoading, error: properties.error }}
      />
      <main className="mx-auto max-w-7xl px-4 py-5 sm:px-6 sm:py-6">
        {tab === "overview" && <Overview range={range} />}
        {tab === "acquisition" && <Acquisition range={range} />}
        {tab === "content" && <Content range={range} />}
        {tab === "behaviour" && <Behaviour range={range} />}
        {tab === "events" && <Events range={range} />}
        {tab === "settings" && <Settings key={propertyCtx.propertyId ?? "default"} />}
      </main>
    </div>
    </PropertyContext.Provider>
  );
}
