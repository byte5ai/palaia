import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MarketConfigSchema } from "../lib/api/client";
import { ConfigSchemaForm, missingRequiredFields } from "./ConfigSchemaForm";

const SCHEMA: MarketConfigSchema = {
  type: "object",
  properties: {
    api_key: { type: "secret", title: "Access token" },
    region: { type: "string", title: "Region", enum: ["us", "eu"] },
    port: { type: "number", title: "Port" },
    verbose: { type: "boolean", title: "Verbose logging" },
    mount_path: { type: "string", title: "Folder to expose", format: "path" },
  },
  required: ["api_key"],
};

describe("ConfigSchemaForm (SPEC-304 deliverable #2)", () => {
  it("renders nothing to configure when the schema has no properties", () => {
    render(<ConfigSchemaForm schema={null} values={{}} onChange={vi.fn()} />);

    expect(screen.getByText(/ready to connect/i)).toBeInTheDocument();
  });

  it("renders every field kind and reports value changes", () => {
    const onChange = vi.fn();
    render(<ConfigSchemaForm schema={SCHEMA} values={{}} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText(/access token/i), {
      target: { value: "sk-secret" },
    });
    expect(onChange).toHaveBeenCalledWith({ api_key: "sk-secret" });

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "eu" } });
    expect(onChange).toHaveBeenCalledWith({ region: "eu" });

    fireEvent.change(screen.getByLabelText(/^port/i), { target: { value: "8080" } });
    expect(onChange).toHaveBeenCalledWith({ port: 8080 });

    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith({ verbose: true });

    // The password field never shows a previous value — a config form is
    // always opened blank (the hub never echoes a stored secret back).
    expect(screen.getByLabelText(/access token/i)).toHaveAttribute("type", "password");
  });

  it("marks a required field's label and flags it as missing until filled", () => {
    render(<ConfigSchemaForm schema={SCHEMA} values={{}} onChange={vi.fn()} />);

    expect(screen.getByText(/access token \(required\)/i)).toBeInTheDocument();
    expect(missingRequiredFields(SCHEMA, {})).toEqual(["api_key"]);
    expect(missingRequiredFields(SCHEMA, { api_key: "x" })).toEqual([]);
  });

  it("hints that a path field is a shared folder", () => {
    render(<ConfigSchemaForm schema={SCHEMA} values={{}} onChange={vi.fn()} />);

    expect(screen.getByText(/shared with the add-on/i)).toBeInTheDocument();
  });
});
