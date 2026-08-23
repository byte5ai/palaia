import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ToastProvider } from "../components/Toast";
import { Clients } from "./Clients";

describe("Clients (connect-a-client)", () => {
  it("lists every §6-matrix client and explains a not-yet one when selected", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Clients />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /claude code cli/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^chatgpt/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^chatgpt/i }));

    // A not-yet client never dead-ends: it gets a truthful, specific reason.
    expect(await screen.findByText(/not available yet/i)).toBeInTheDocument();
  });

  it("selects a guided client by default and offers to issue it a token", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Clients />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: /issue token/i })).toBeInTheDocument();
  });
});
