import { EmptyState } from "../components";

/** Every nav destination this SPEC does not build a screen for still
 * resolves to a real, honest page rather than a broken link — feature
 * screens are SPEC-110's (this SPEC's non-goal), but a shell with dead
 * links is not a shell. */
export function ComingSoon({ label }: { label: string }) {
  return (
    <EmptyState
      mark={
        <svg
          className="icon--lg"
          viewBox="0 0 24 24"
          aria-hidden="true"
          stroke="currentColor"
          fill="none"
          strokeWidth={1.5}
          strokeLinecap="round"
        >
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 8v5l3 2" />
        </svg>
      }
      title={`${label} isn't built yet.`}
    >
      This screen is coming in a later phase. The shell around it — navigation, health, live
      updates — already works.
    </EmptyState>
  );
}
