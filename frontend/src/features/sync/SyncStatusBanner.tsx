import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { syncNow } from "@/features/sync/bootstrap";
import { acknowledgeConflict } from "@/lib/db/cache";
import { useAuthStore } from "@/stores/authStore";
import { pendingOutboxTotal, useSyncStore } from "@/stores/syncStore";

export function SyncStatusBanner() {
  const { t } = useTranslation();
  const me = useAuthStore((s) => s.me);
  const online = useSyncStore((s) => s.online);
  const persisted = useSyncStore((s) => s.persisted);
  const pending = useSyncStore((s) => s.pending);
  const quarantine = useSyncStore((s) => s.quarantine);
  const transportFailStreak = useSyncStore((s) => s.transportFailStreak);
  const lastConflictToast = useSyncStore((s) => s.lastConflictToast);
  const setLastConflictToast = useSyncStore((s) => s.setLastConflictToast);
  const refresh = useSyncStore((s) => s.refresh);
  const total = useSyncStore(pendingOutboxTotal);

  if (!me) return null;

  const showPersist =
    persisted === false && (pending > 0 || quarantine > 0);
  const showPending = pending > 0 || !online;
  const showQuarantine = quarantine > 0;
  const showTransport = transportFailStreak >= 5;

  if (!showPersist && !showPending && !showQuarantine && !showTransport && !lastConflictToast) {
    return null;
  }

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-2 px-4 pt-3">
      {showPersist ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          {t("sync.persistWarning")}
        </div>
      ) : null}
      {showPending ? (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-950">
          <span>
            {!online ? t("sync.offline") : t("sync.pending", { count: total })}
          </span>
          {online ? (
            <Button
              variant="secondary"
              onClick={() => void syncNow(me.id, me.locale)}
            >
              {t("sync.syncNow")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {showQuarantine ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-950">
          {t("sync.quarantine", { count: quarantine })}
        </div>
      ) : null}
      {showTransport ? (
        <div className="rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-950">
          {t("sync.transportEscalation")}
        </div>
      ) : null}
      {lastConflictToast ? (
        <div className="flex items-start justify-between gap-2 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-950">
          <span>{t("sync.conflictToast", { kind: lastConflictToast.conflict_kind })}</span>
          <Button
            variant="ghost"
            onClick={() => {
              void acknowledgeConflict(me.id, lastConflictToast.id).then(() => {
                setLastConflictToast(null);
                return refresh();
              });
            }}
          >
            {t("common.close")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
