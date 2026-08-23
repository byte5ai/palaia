import { useId, type InputHTMLAttributes, type ReactNode } from "react";

/** label + control + hint — hints explain *why*, not *what*
 * (system.md §2, Forms). */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <span className="field__label">{label}</span>
      {children}
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
  ...inputProps
}: { label: ReactNode; hint?: ReactNode; error?: ReactNode } & InputProps) {
  const id = useId();
  return (
    <Field label={<label htmlFor={id}>{label}</label>} hint={hint} error={error}>
      <Input id={id} {...inputProps} />
    </Field>
  );
}

/** A switch is one of the few places the accent is allowed to be a fill
 * (system.md §2, Forms). */
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
        className={["switch", checked ? "switch--on" : ""].filter(Boolean).join(" ")}
        onClick={() => onChange(!checked)}
      />
      <span className="stack stack--2">
        <span className="field__label">{label}</span>
        {consequence ? <span className="field__hint">{consequence}</span> : null}
      </span>
    </label>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="radiogroup">
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
