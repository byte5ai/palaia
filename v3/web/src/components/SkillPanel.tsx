/**
 * The skill half of connecting a client (SPEC-207 #3).
 *
 * Connecting a client gives an agent the memory's tools. That is not the
 * same as the agent using them: an assistant with a memory it never opens
 * behaves exactly like one without a memory. So the connect page offers the
 * skill packages next to the token, and it does so only for clients that can
 * load one — a client with no skill loader gets the honest reason instead of
 * a download it cannot use, the same rule the not-yet connect cards follow.
 *
 * Copy hands over the SKILL.md verbatim; download hands over the same bytes
 * as a file, for the clients whose install path is "put this file there".
 */
import { useEffect, useMemo, useState } from "react";

import type { SkillPackage } from "../lib/skills";
import { SKILLS, skillSupportFor } from "../lib/skills";
import { CopyIcon, InfoIcon, SparkleIcon, WarningIcon } from "../shell/icons";
import { Button } from "./Button";
import { Card, CardBody, CardFoot, CardHead, CardSubject } from "./Card";
import { useToast } from "./Toast";

function SkillDownload({ skill }: { skill: SkillPackage }) {
  // An object URL rather than a data: URI so the file arrives with a real
  // name; revoked on unmount so a long-lived dashboard session does not
  // accumulate them.
  const href = useMemo(
    () => URL.createObjectURL(new Blob([skill.source], { type: "text/markdown" })),
    [skill.source],
  );
  useEffect(() => () => URL.revokeObjectURL(href), [href]);
  return (
    <a className="btn btn--sm" href={href} download="SKILL.md">
      Download SKILL.md
    </a>
  );
}

function SkillCard({ skill }: { skill: SkillPackage }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);

  function copy() {
    navigator.clipboard.writeText(skill.source).then(
      () => toast.show("Skill copied — paste it into a SKILL.md file."),
      () => toast.show("Could not copy — open it below and copy manually."),
    );
  }

  return (
    <Card variant="flat">
      <CardHead>
        <div>
          <CardSubject>{skill.slug}</CardSubject>
          <p className="t-xs t-muted" style={{ marginTop: 2 }}>
            {skill.audience}
          </p>
        </div>
      </CardHead>
      <CardBody className="stack stack--3">
        <p className="t-sm t-muted">{skill.summary}</p>
        <div className="row row--wrap">
          <Button size="sm" onClick={copy}>
            <CopyIcon className="icon--sm" />
            Copy the skill
          </Button>
          <SkillDownload skill={skill} />
          <Button size="sm" variant="quiet" onClick={() => setOpen((was) => !was)}>
            {open ? "Hide it" : "Read it first"}
          </Button>
        </div>
        {open ? (
          <div className="snippet snippet--block">
            <code>{skill.source}</code>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function SkillPanel({ clientId, clientName }: { clientId: string; clientName: string }) {
  const support = skillSupportFor(clientId);

  if (support.kind === "unsupported") {
    return (
      <Card>
        <CardHead>
          <div>
            <CardSubject>Teaching it to use the memory</CardSubject>
            <p className="t-xs t-muted" style={{ marginTop: 2 }}>
              {clientName} cannot load a skill package
            </p>
          </div>
          <span className="badge">not applicable</span>
        </CardHead>
        <CardBody>
          <div className="banner banner--warn">
            <WarningIcon className="icon icon--sm" />
            <p className="t-sm t-muted">{support.reason}</p>
          </div>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHead>
        <div>
          <CardSubject>Teaching it to use the memory</CardSubject>
          <p className="t-xs t-muted" style={{ marginTop: 2 }}>
            Optional, and the difference between an agent that has a memory and one that uses it.
          </p>
        </div>
        <span className="badge">
          <SparkleIcon className="icon--sm" style={{ marginRight: 4 }} />
          {SKILLS.length} skills
        </span>
      </CardHead>
      <CardBody className="stack">
        {support.kind === "unknown" ? (
          <div className="banner">
            <InfoIcon className="icon icon--sm" />
            <p className="t-sm t-muted">{support.note}</p>
          </div>
        ) : (
          <div className="stack stack--3">
            <p className="t-sm">{support.install.headline}</p>
            <ol className="stack stack--3 t-sm t-muted">
              {support.install.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
            {support.install.command ? (
              <div className="snippet snippet--wrap">
                <code>{support.install.command}</code>
              </div>
            ) : null}
          </div>
        )}
        <div className="stack stack--3">
          {SKILLS.map((skill) => (
            <SkillCard key={skill.slug} skill={skill} />
          ))}
        </div>
      </CardBody>
      <CardFoot>
        <span className="t-xs t-subtle">
          Take one or both. They only ever read and write through this hub, so nothing changes for
          the client except what it thinks to do.
        </span>
      </CardFoot>
    </Card>
  );
}
