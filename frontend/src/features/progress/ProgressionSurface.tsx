import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button, Modal } from "@/components/ui";
import type { ProgressionEvent } from "@/lib/schemas";
import { useSeenEventsStore } from "@/stores/seenEventsStore";

function titleKey(eventType: string): string {
  if (eventType === "advance" || eventType === "satellite_advance") {
    return "progress.advanceTitle";
  }
  if (eventType === "satellite_regress_confirmed") {
    return "progress.satelliteRegressConfirmedTitle";
  }
  return "progress.regressTitle";
}

function bodyKey(eventType: string): string {
  if (eventType === "advance" || eventType === "satellite_advance") {
    return "progress.advanceBody";
  }
  if (eventType === "satellite_regress_confirmed") {
    return "progress.satelliteRegressConfirmedBody";
  }
  return "progress.regressBody";
}

export function ProgressionSurface({
  events,
  names,
}: {
  events: ProgressionEvent[];
  names: Record<string, string>;
}) {
  const { t } = useTranslation();
  const filterUnseen = useSeenEventsStore((s) => s.filterUnseen);
  const markSeen = useSeenEventsStore((s) => s.markSeen);
  const queue = useMemo(() => filterUnseen(events), [events, filterUnseen]);
  const current = queue[0];

  if (!current) return null;

  const name = names[current.exercise_id] ?? t("progress.unknownExercise");

  return (
    <Modal
      open
      title={t(titleKey(current.event_type))}
      onClose={() => markSeen(current.id)}
      actions={
        <Button onClick={() => markSeen(current.id)}>{t("progress.ack")}</Button>
      }
    >
      <p>
        {t(bodyKey(current.event_type), {
          name,
          from: current.from_step,
          to: current.to_step,
        })}
      </p>
    </Modal>
  );
}
