import { createContext, useContext } from "react";
import type { PropertyInfo } from "../types";

export interface PropertyContextValue {
  /** Selected GA4 property ID; null while the list loads or if it couldn't be loaded (backend default applies). */
  propertyId: string | null;
  property: PropertyInfo | null;
  /** True once the property list has loaded or failed — data queries wait for this. */
  ready: boolean;
  setPropertyId: (id: string) => void;
}

export const PropertyContext = createContext<PropertyContextValue>({
  propertyId: null,
  property: null,
  ready: false,
  setPropertyId: () => undefined,
});

export const useSelectedProperty = () => useContext(PropertyContext);

const KEY = "propertyId";

export function loadSavedProperty(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function saveProperty(id: string) {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
}

/** The saved choice if it's still in the list, else the backend's default, else the first property. */
export function pickProperty(list: PropertyInfo[], saved: string | null): PropertyInfo | null {
  return list.find((p) => p.propertyId === saved) ?? list.find((p) => p.isDefault) ?? list[0] ?? null;
}

/** Append ?propertyId= to an API path (path may already have a query string). */
export function withProperty(path: string, propertyId: string | null): string {
  if (!propertyId) return path;
  return `${path}${path.includes("?") ? "&" : "?"}propertyId=${encodeURIComponent(propertyId)}`;
}
