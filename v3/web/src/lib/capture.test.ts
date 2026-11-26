import { describe, expect, it } from "vitest";

import { parseCapture } from "./capture";

// The exact shape `compose_capture_body` writes on the server.
const BODY =
  "Changes who to ask\n\n" +
  "- [entity] Billing service\n" +
  "- [why] Changes who to ask\n" +
  "- [raw] From December the billing service is owned by the payments team.\nNot platform.\n" +
  "- [source] chat\n" +
  "- [capture_hash] e2432368920442cb\n";

describe("parseCapture", () => {
  it("reads what a capture concerns, why it was kept, its text and its source", () => {
    expect(parseCapture(BODY)).toEqual({
      about: "Billing service",
      why: "Changes who to ask",
      text: "From December the billing service is owned by the payments team.\nNot platform.",
      source: "chat",
    });
  });

  it("leaves a note that is not a capture alone, also one that quotes a tag", () => {
    expect(parseCapture("Keep seven daily backups.")).toBeNull();
    expect(parseCapture("- [source] inbox capture cap-12\n\nOwns invoices.")).toBeNull();
  });
});
