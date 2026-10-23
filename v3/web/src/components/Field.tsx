import {
  Children,
  cloneElement,
  isValidElement,
  useId,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

const CONTROL_TAGS = new Set(["input", "select", "textarea"]);

/** Is `node` a form control this field should label — a native control
 * element, or our own `Input` wrapper around one? */
function isControl(node: unknown): node is ReactElement<{ id?: string }> {
  if (!isValidElement(node)) return false;
  return (
    (typeof node.type === "string" && CONTROL_TAGS.has(node.type)) ||
    node.type === Input
  );
}

/** Label above, control, helper below; an error replaces the helper
 * (system.md §2, Forms). Mark a field `optional` and its label says so;
 * required fields carry no marker, so the form reads as "everything is
 * needed except what says Optional".
 *
 * The label is a real `<label htmlFor>` (issue 383): the first form control
 * among `children` gets a generated id when it has none, so a screen
 * reader announces the label with the control and clicking the label
 * focuses it. Pass `controlId` when the control already carries an id.
 */
export function Field({
  label,
  hint,
  error,
  optional = false,
  children,
  controlId,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  optional?: boolean;
  children: ReactNode;
  controlId?: string;
}) {
  const generated = useId();
  const items = Children.toArray(children);
  const controlIndex = items.findIndex(isControl);
  const control =
    controlIndex === -1
      ? null
      : (items[controlIndex] as ReactElement<{ id?: string }>);
  const htmlFor = control
    ? (control.props.id ?? controlId ?? generated)
    : controlId;
  const content =
    control && !control.props.id
      ? items.map((item, index) =>
          index === controlIndex
            ? cloneElement(control, { id: htmlFor, key: control.key ?? index })
            : item,
        )
      : items;
  const labelContent = (
    <>
      {label}
      {optional ? <span className="field__optional">Optional</span> : null}
    </>
  );
  return (
    <div className="field">
      {htmlFor ? (
        <label className="field__label" htmlFor={htmlFor}>
          {labelContent}
        </label>
      ) : (
        <span className="field__label">{labelContent}</span>
      )}
      {content}
      {error ? (
        <span className="field__error">{error}</span>
      ) : hint ? (
        <span className="field__hint">{hint}</span>
      ) : null}
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  readOnly?: boolean;
  invalid?: boolean;
}

export function Input({ className, readOnly, invalid, ...rest }: InputProps) {
  return (
    <input
      className={[
        "input",
        readOnly ? "input--readonly" : "",
        invalid ? "input--error" : "",
        className ?? "",
      ]
        .filter(Boolean)
        .join(" ")}
      readOnly={readOnly}
      aria-invalid={invalid ? "true" : undefined}
      {...rest}
    />
  );
}

/** A field's label + control, pre-wired with a generated id — the
 * convenience wrapper most call sites want over composing `Field` and
 * `Input` by hand. */
export function LabeledInput({
  label,
  hint,
  error,
  optional,
  ...inputProps
}: { label: ReactNode; hint?: ReactNode; error?: ReactNode; optional?: boolean } & InputProps) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} optional={optional} controlId={id}>
      <Input id={id} {...inputProps} />
    </Field>
  );
}

/** An on/off switch. Give it a visible label through `labelledBy` (the id
 * of the row title next to it) or an `ariaLabel`. */
export function Switch({
  checked,
  onChange,
  disabled,
  labelledBy,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  labelledBy?: string;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      aria-label={labelledBy ? undefined : ariaLabel}
      disabled={disabled}
      className={["switch", checked ? "switch--on" : ""].filter(Boolean).join(" ")}
      onClick={() => onChange(!checked)}
    />
  );
}

/** A switch with its label and consequence in a bordered box (the earlier
 * form; settings lists use `ListRow setting` with a `Switch`). */
export function SwitchRow({
  label,
  consequence,
  checked,
  onChange,
}: {
  label: ReactNode;
  consequence?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="switchrow">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        className={["switch", checked ? "switch--on" : ""]
          .filter(Boolean)
          .join(" ")}
        onClick={() => onChange(!checked)}
      />
      <span className="stack stack--2">
        <span className="field__label">{label}</span>
        {consequence ? (
          <span className="field__hint">{consequence}</span>
        ) : null}
      </span>
    </label>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  /** What this group of choices is, for a screen reader (issue 383). */
  ariaLabel?: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className={[
            "segmented__item",
            option.value === value ? "segmented__item--on" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
