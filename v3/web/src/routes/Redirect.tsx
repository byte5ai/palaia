import { Navigate, useLocation } from "react-router-dom";

/** Send an old address to its new place, keeping the query string and hash
 * (`/explorer?focus=search`, `/marketplace?install=…`). */
export function Redirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} replace />;
}
