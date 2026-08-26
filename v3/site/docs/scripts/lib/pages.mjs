import path from "node:path";
import { loadCatalog } from "./extract.mjs";
import { renderClientPage, renderIndexPage, slugFor } from "./render.mjs";

export const CONNECT_DIR = path.join("src", "content", "docs", "connect");
export const CLIENTS_DIR = path.join(CONNECT_DIR, "clients");

/** Every generated page, as a Map of path (relative to this project root)
 * -> file contents. The single place both the writer and the drift
 * checker call, so they can never disagree about what "generated" means. */
export async function buildGeneratedPages() {
  const catalog = await loadCatalog();
  const pages = new Map();
  pages.set(path.join(CONNECT_DIR, "index.md"), renderIndexPage(catalog.clients));
  for (const client of catalog.clients) {
    const support = catalog.skillSupportFor(client.id);
    pages.set(
      path.join(CLIENTS_DIR, `${slugFor(client)}.md`),
      renderClientPage(client, support),
    );
  }
  return pages;
}
