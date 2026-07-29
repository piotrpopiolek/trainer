import { useEffect } from "react";

import { bootstrapSync, syncNow } from "@/features/sync/bootstrap";
import { useAuthStore } from "@/stores/authStore";
import { useSyncStore } from "@/stores/syncStore";

/** Online listener + initial pull/flush after auth. */
export function SyncBootstrap() {
  const me = useAuthStore((s) => s.me);
  const setOnline = useSyncStore((s) => s.setOnline);

  useEffect(() => {
    const onOnline = () => {
      setOnline(true);
      if (me?.id) void syncNow(me.id, me.locale);
    };
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    setOnline(navigator.onLine);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [me?.id, me?.locale, setOnline]);

  useEffect(() => {
    if (!me?.id) return;
    void bootstrapSync(me.id, me.locale);
  }, [me?.id, me?.locale]);

  return null;
}
