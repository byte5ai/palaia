import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Field, Input, LabeledInput, Segmented } from "./Field";

describe("Field labels its control (issue 383)", () => {
  it("associates a plain <input> child with the label", () => {
    render(
      <Field label="To" hint="An agent's ID">
        <input className="input" />
        <datalist id="handles" />
      </Field>,
    );
    expect(screen.getByLabelText("To")).toBeInstanceOf(HTMLInputElement);
  });

  it("associates our own Input and a <select> too", () => {
    render(
      <>
        <Field label="Username">
          <Input />
        </Field>
        <Field label="Vault">
          <select>
            <option>work</option>
          </select>
        </Field>
      </>,
    );
    expect(screen.getByLabelText("Username")).toBeInstanceOf(HTMLInputElement);
    expect(screen.getByLabelText("Vault")).toBeInstanceOf(HTMLSelectElement);
  });

  it("keeps an id the control already has", () => {
    render(
      <Field label="Name">
        <input id="given" />
      </Field>,
    );
    expect(screen.getByLabelText("Name")).toHaveAttribute("id", "given");
  });

  it("LabeledInput renders exactly one label, not a label inside a label", () => {
    const { container } = render(<LabeledInput label="Search" />);
    expect(container.querySelectorAll("label")).toHaveLength(1);
    expect(screen.getByLabelText("Search")).toBeInstanceOf(HTMLInputElement);
  });

  it("Segmented can be named", () => {
    render(
      <Segmented
        options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]}
        value="a"
        onChange={() => {}}
        ariaLabel="Source"
      />,
    );
    expect(screen.getByRole("radiogroup", { name: "Source" })).toBeInTheDocument();
  });
});
