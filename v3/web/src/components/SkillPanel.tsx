/**
 * The skill half of connecting an AI app (SPEC-207 #3).
 *
 * Connecting gives an app palaia's tools; a skill teaches it to use them —
 * look things up before answering, save what is worth keeping. One skill is
 * the recommendation (palaia-memory); the others sit under "More skills".
 * Everything is collapsed: the connect flow above is the task, this is the
 * next layer (report §3.5). An app that cannot load a skill gets the reason
 * instead of a download it cannot use.
 *
 * Copy hands over the SKILL.md verbatim; download hands over the same bytes
 * as a file.
 */
import { useEffect, useMemo } from "react";

import type { SkillPackage } from "../lib/skills";
import { SKILLS, skillSupportFor } from "../lib/skills";
import { CopyIcon } from "../shell/icons";
import { Button } from "./Button";
import { Card, CardBody, CardHeader } from "./Card";
import { Disclosure } from "./Disclosure";
import { StatusPill } from "./StatusPill";
import { useToast } from "./Toast";

const RECOMMENDED = "palaia-memory";

function SkillDownload({ skill }: { skill: SkillPackage }) {
  // An object URL so the file arrives with a real name; revoked on unmount.
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

function SkillActions({ skill }: { skill: SkillPackage }) {
  const toast = useToast();
  function copy() {
    navigator.clipboard.writeText(skill.source).then(
      () => toast.show("Skill copied. Paste it into a file named SKILL.md."),
      () => toast.show("Couldn't copy. Open the skill text below and copy it yourself."),
    );
  }
  return (
    <div className="stack stack--3">
      <div className="row row--wrap">
        <Button size="sm" onClick={copy}>
          <CopyIcon className="icon--sm" />
          Copy the skill
        </Button>
        <SkillDownload skill={skill} />
      </div>
      <Disclosure summary="Show the skill text">
        <div className="snippet snippet--block">
          <code>{skill.source}</code>
        </div>
      </Disclosure>
    </div>
  );
}

export function SkillPanel({ clientId, clientName }: { clientId: string; clientName: string }) {
  const support = skillSupportFor(clientId);
  const recommended = SKILLS.find((skill) => skill.slug === RECOMMENDED) ?? SKILLS[0]!;
  const others = SKILLS.filter((skill) => skill !== recommended);

  if (support.kind === "unsupported") {
    return (
      <Card>
        <CardHeader
          title="Skills"
          description={`${clientName} can't load a skill.`}
          actions={<StatusPill tone="neutral">Not available</StatusPill>}
        />
        <CardBody>
          <p className="t-sm t-muted">{support.reason}</p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Recommended: install the palaia skill"
        description={`Teaches ${clientName} to look things up before answering and to save decisions.`}
      />
      <CardBody className="stack stack--4">
        <Disclosure summary="Install skill">
          {support.kind === "unknown" ? (
            <p>{support.note}</p>
          ) : (
            <div className="stack stack--3">
              <p className="t-strong">{support.install.headline}</p>
              <ol className="stack stack--2" style={{ listStyle: "decimal", paddingLeft: "var(--space-5)" }}>
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
          <p className="t-strong">{recommended.slug}</p>
          <SkillActions skill={recommended} />
        </Disclosure>
        <Disclosure summary="More skills">
          {others.map((skill) => (
            <div key={skill.slug} className="stack stack--2">
              <p className="t-strong">{skill.slug}</p>
              <p>{skill.audience}</p>
              <SkillActions skill={skill} />
            </div>
          ))}
        </Disclosure>
      </CardBody>
    </Card>
  );
}
