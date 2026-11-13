import { createContext, useContext } from "react";

export interface UIContextValue {
  openPalette: () => void;
  openShortcuts: () => void;
}

export const UIContext = createContext<UIContextValue>({ openPalette: () => {}, openShortcuts: () => {} });

export const useUI = () => useContext(UIContext);

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const MOD = isMac ? "⌘" : "Ctrl";
