import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button, Modal } from "@/components/ui";
import { syncNow } from "@/features/sync/bootstrap";
import { acknowledgeConflict } from "@/lib/db/cache";
import {
  canRecoverConflict,
  recoverConflictAsNewEntity,
} from "@/lib/sync/recoverConflict";
import { conflictKindI18nKey } from "@/lib/sync/conflictKind";
import { useAuthStore } from "@/stores/authStore";
import { useSyncStore } from "@/stores/syncStore";

/** FR-073a: mandatory modal for conflict_tie / session_immutable (+ batch queue). */
export function ConflictSurface() {
  const { t } = useTranslation();
  const me = useAuthStore((s) => s.me);
  const current = useSyncStore((s) => s.modalConflictQueue[0] ?? null);
  const queueLen = useSyncStore((s) => s.modalConflictQueue.length);
  const dismiss = useSyncStore((s) => s.dismissModalConflict);
  const refresh = useSyncStore((s) => s.refresh);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!me || !current) return null;

  const recoverable = canRecoverConflict(current);
  const kindLabel = t(conflictKindI18nKey(current.conflict_kind));

  const ackOnly = async () => {
    setBusy(true);
    setError(null);
    try {
      await acknowledgeConflict(me.id, current.id);
      dismiss();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const recover = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await recoverConflictAsNewEntity(me.id, current);
      if (!result.ok) {
        setError(t("sync.recoverFailed"));
        return;
      }
      dismiss();
      await refresh();
      if (navigator.onLine) {
        await syncNow(me.id, me.locale);
      }
    } catch {
      setError(t("sync.recoverFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={t("sync.conflictModalTitle")}
      onClose={() => {
        if (!busy) void ackOnly();
      }}
      actions={
        <>
          <Button variant="secondary" disabled={busy} onClick={() => void ackOnly()}>
            {t("sync.conflictKeepWinner")}
          </Button>
          {recoverable ? (
            <Button disabled={busy} onClick={() => void recover()}>
              {t("sync.conflictRecover")}
            </Button>
          ) : null}
        </>
      }
    >
      <div className="flex flex-col gap-2">
        {queueLen > 1 ? (
          <p className="text-xs text-slate-500">
            {t("sync.conflictBatchHint", { n: queueLen })}
          </p>
        ) : null}
        <p>{t("sync.conflictModalBody", { kind: kindLabel })}</p>
        <p className="text-xs text-slate-500">
          {current.entity_type}
          {current.entity_id
            ? ` · ${String(current.entity_id).slice(0, 8)}…`
            : ""}
          {current.winning_revision != null
            ? ` · rev ${current.winning_revision}`
            : ""}
        </p>
        <p className="text-sm">
          <Link className="text-teal-800 underline" to="/settings">
            {t("sync.conflictListLink")}
          </Link>
        </p>
        {error ? <p className="text-sm text-rose-700">{error}</p> : null}
      </div>
    </Modal>
  );
}
