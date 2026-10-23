import { type ReactNode, useEffect } from "react";

import { CheckIcon, PalaiaMark } from "../shell/icons";

/**
 * A step's state comes from the hub, never from how far the person has
 * clicked: `done` only once the server confirms it, `attention` when it
 * was done and is not any more (or needs a restart).
 */
export type StepState = "todo" | "current" | "done" | "skipped" | "attention";

/** Spoken after a clickable step's name: the ticks are not only visual. */
const STATE_SUFFIX: Record<StepState, string> = {
  todo: "",
  current: "",
  done: " (done)",
  skipped: " (skipped)",
  attention: " (needs attention)",
};

export interface StepperStep {
  id: string;
  label: ReactNode;
  state: StepState;
}

/**
 * A full-page flow without the app's sidebar (first-run setup): a bar with
 * the wordmark and "Step 2 of 5", a 4 px progress line, the list of steps
 * on the left from 1024 px, and one centred 640 px panel. The page scrolls
 * to the top whenever the step changes.
 */
export function Stepper({
  steps,
  currentIndex,
  barEnd,
  onSelect,
  children,
}: {
  steps: StepperStep[];
  /** Zero-based index of the step on screen. */
  currentIndex: number;
  /** Something for the right end of the bar (e.g. "Skip setup"). */
  barEnd?: ReactNode;
  /** Makes finished steps (and the current one) clickable, to look back. */
  onSelect?: (index: number) => void;
  /** Usually one `StepperPanel`. */
  children: ReactNode;
}) {
  useEffect(() => {
    try {
      window.scrollTo({ top: 0 });
    } catch {
      // jsdom and very old browsers: nothing to scroll
    }
  }, [currentIndex]);

  const total = steps.length;
  const position = Math.min(Math.max(currentIndex, 0), total - 1) + 1;
  return (
    <div className="stepper">
      <div className="stepper__bar">
        <span className="brand">
          <PalaiaMark className="brand__mark" />
          <span className="brand__name">palaia</span>
        </span>
        <span className="row">
          <span className="stepper__count">
            Step {position} of {total}
          </span>
          {barEnd}
        </span>
      </div>
      <div
        className="stepper__progress"
        role="progressbar"
        aria-label="Setup progress"
        aria-valuemin={1}
        aria-valuemax={total}
        aria-valuenow={position}
      >
        <div className="stepper__progress-fill" style={{ width: `${(position / total) * 100}%` }} />
      </div>
      <div className="stepper__layout">
        <ol className="stepper__steps" aria-label="Steps">
          {steps.map((step, index) => (
            <li
              key={step.id}
              className={`stepper__step stepper__step--${step.state}`}
              aria-current={index === currentIndex ? "step" : undefined}
            >
              <span className="stepper__marker" aria-hidden="true">
                {step.state === "done" ? (
                  <CheckIcon className="icon--sm" />
                ) : step.state === "attention" ? (
                  "!"
                ) : step.state === "skipped" ? (
                  "–"
                ) : (
                  index + 1
                )}
              </span>
              {onSelect && (step.state !== "todo" || index === currentIndex) ? (
                <button
                  type="button"
                  className="stepper__link"
                  onClick={() => onSelect(index)}
                  aria-label={`${String(step.label)}${STATE_SUFFIX[step.state]}`}
                >
                  {step.label}
                </button>
              ) : (
                <span>
                  {step.label}
                  {step.state === "done" ? <span className="sr-only"> (done)</span> : null}
                  {step.state === "attention" ? (
                    <span className="sr-only"> (needs attention)</span>
                  ) : null}
                </span>
              )}
            </li>
          ))}
        </ol>
        {children}
      </div>
    </div>
  );
}

/** One step's content: its title, one line of context, the fields, and a
 * footer with Back on the left and the primary action on the right. */
export function StepperPanel({
  title,
  description,
  children,
  back,
  primary,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  back?: ReactNode;
  primary?: ReactNode;
}) {
  return (
    <section className="stepper__panel" aria-labelledby="stepper-title">
      <div className="stack stack--2">
        <h1 className="stepper__title" id="stepper-title">
          {title}
        </h1>
        {description ? <p className="t-muted">{description}</p> : null}
      </div>
      {children}
      {back || primary ? (
        <div className="stepper__foot">
          {back ?? <span />}
          {primary}
        </div>
      ) : null}
    </section>
  );
}
