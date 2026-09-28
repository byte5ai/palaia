import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardHead, CardSubject } from "./Card";

describe("CardHead", () => {
  it("keeps a head's actions at the right edge together with its meta", () => {
    // The marketplace's "Details" button sat in the middle of the head
    // whenever the card also had a meta label ("Remote server").
    const { container } = render(
      <CardHead title="ac.snag/snag" meta="Remote server">
        <button type="button">Details</button>
      </CardHead>,
    );
    const head = container.querySelector(".card__head");
    expect(head?.children).toHaveLength(2);
    const end = head?.querySelector(".card__head-end");
    expect(end?.textContent).toBe("Remote serverDetails");
  });

  it("leaves a head without a title as it was", () => {
    const { container } = render(
      <CardHead meta="3f2a">
        <CardSubject>Claude Code CLI</CardSubject>
      </CardHead>,
    );
    const head = container.querySelector(".card__head");
    expect(head?.querySelector(".card__head-end")).toBeNull();
    expect(head?.firstElementChild?.textContent).toBe("Claude Code CLI");
  });

  it("leaves a head with only a title and meta as it was", () => {
    const { container } = render(<CardHead title="clients" meta="last seen" />);
    expect(container.querySelector(".card__head-end")).toBeNull();
  });
});
