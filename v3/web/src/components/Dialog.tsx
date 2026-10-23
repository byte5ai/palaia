import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

import { CloseIcon } from "../shell/icons";
import { Button, IconButton } from "./Button";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A modal for one task: create something, or confirm something.
 *
 * Title and a close button on top, the form or message, then Cancel and one
 * primary action. Escape and the scrim close it; focus moves into it on open,
 * stays inside while it is open, and returns to whatever opened it. Below
 * 768 px it is a bottom sheet.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "default",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Usually Cancel + one primary button. */
  footer?: ReactNode;
  /** `form` is a little wider, for dialogs with several fields. */
  size?: "default" | "form";
}) {
  const titleId = useId();
  const descId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    // First field if there is one, otherwise the first control.
    const first =
      panel?.querySelector<HTMLElement>("input, select, textarea") ??
      panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        className={["dialog", size === "form" ? "dialog--form" : ""].filter(Boolean).join(" ")}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
      >
        <div className="dialog__head">
          <div>
            <h2 className="dialog__title" id={titleId}>
              {title}
            </h2>
            {description ? (
              <p className="dialog__desc" id={descId}>
                {description}
              </p>
            ) : null}
          </div>
          <IconButton title="Close" onClick={onClose}>
            <CloseIcon className="icon--sm" />
          </IconButton>
        </div>
        {children ? <div className="dialog__body">{children}</div> : null}
        {footer ? <div className="dialog__foot">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

/**
 * "Are you sure?" with the consequence spelled out. The confirm button
 * names the action ("Revoke access"), never just "OK"; a destructive
 * confirm is the one place a filled red button appears.
 */
export function ConfirmDialog({
  open,
  onCancel,
  onConfirm,
  title,
  children,
  confirmLabel,
  destructive = false,
  busy = false,
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  title: ReactNode;
  children?: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button onClick={onCancel}>Cancel</Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={onConfirm}
            loading={busy}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
