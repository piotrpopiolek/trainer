import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Input, Modal, Select } from "@/components/ui";
import { CC_STEP_COUNT } from "@/lib/ccProgress";

export function OverrideStepModal({
  open,
  exerciseName,
  currentStep,
  onClose,
  onConfirm,
  pending,
  errorMessage,
}: {
  open: boolean;
  exerciseName: string;
  currentStep: number;
  onClose: () => void;
  onConfirm: (toStep: number, reason: string) => void;
  pending?: boolean;
  errorMessage?: string | null;
}) {
  const { t } = useTranslation();
  const offline = typeof navigator !== "undefined" && !navigator.onLine;
  const [toStep, setToStep] = useState(String(currentStep));
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!open) return;
    setToStep(String(currentStep));
    setReason("");
  }, [open, currentStep]);

  return (
    <Modal
      open={open}
      title={t("progress.overrideModalTitle", { name: exerciseName })}
      onClose={onClose}
      actions={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={pending || offline}
            onClick={() => {
              const n = Number(toStep);
              if (!Number.isInteger(n) || n < 1 || n > CC_STEP_COUNT) return;
              onConfirm(n, reason.trim());
            }}
          >
            {t("progress.overrideConfirm")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm text-slate-600">{t("progress.overrideConfirmBody")}</p>
        {offline ? (
          <p className="text-sm text-amber-800" role="status">
            {t("progress.overrideRequiresOnline")}
          </p>
        ) : null}
        <Select
          label={t("progress.toStep")}
          value={toStep}
          onChange={(e) => setToStep(e.target.value)}
          disabled={offline}
        >
          {Array.from({ length: CC_STEP_COUNT }, (_, i) => {
            const n = i + 1;
            return (
              <option key={n} value={n}>
                {n}
              </option>
            );
          })}
        </Select>
        <Input
          label={t("progress.overrideReason")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={200}
          disabled={offline}
          placeholder={t("progress.overrideReasonPlaceholder")}
        />
        {errorMessage ? (
          <p className="text-sm text-rose-700" role="alert">
            {errorMessage}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
