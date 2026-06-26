"use client";

import { useEffect } from "react";

import { applySiteSettings, useSiteSettingsStore } from "@/lib/site-settings";

export function SiteSettingsProvider() {
  const settings = useSiteSettingsStore((state) => state.settings);
  const load = useSiteSettingsStore((state) => state.load);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    applySiteSettings(settings);
  }, [settings]);

  return null;
}
