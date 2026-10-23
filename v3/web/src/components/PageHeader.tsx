import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ChevronLeftIcon } from "../shell/icons";

/**
 * The top of every page: the title, at most one line saying what the
 * page is for, and its one primary action on the right. A sub-page shows
 * where it belongs ("‹ Settings") above the title.
 */
export function PageHeader({
  title,
  description,
  back,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  back?: { to: string; label: string };
  actions?: ReactNode;
}) {
  return (
    <header className="pagehead">
      <div className="pagehead__text">
        {back ? (
          <Link className="pagehead__back" to={back.to}>
            <ChevronLeftIcon className="icon--sm" />
            {back.label}
          </Link>
        ) : null}
        <h1 className="pagehead__title">{title}</h1>
        {description ? <p className="pagehead__desc">{description}</p> : null}
      </div>
      {actions ? <div className="pagehead__actions">{actions}</div> : null}
    </header>
  );
}
