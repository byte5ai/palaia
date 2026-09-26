// Gives every issue and PR exactly one track label: `v2` or `v3`.
//
// Called from .github/workflows/track-label.yml via actions/github-script.
// An item that already carries `v2` or `v3` is never touched, so a label set
// by hand always wins over the guess made here.
//
// PRs:    base `v2-maintenance` -> v2. Otherwise v3, unless every changed file
//         is v2 code at the repo root (CONTRIBUTING.md, "Two development
//         tracks") -> v2.
// Issues: a title that starts with "v2" or the v2 plugin prefix "openclaw:"
//         -> v2. Otherwise a title that names v3 -> v3, one that names
//         "v2-maintenance" -> v2. Anything else -> v3: v2 is retired, so a v2
//         issue says so up front.

const TRACKS = ['v2', 'v3'];

const V2_PATHS = [
  /^palaia\//,
  /^tests\//,
  /^packages\//,
  /^docs\//,
  /^skills\//,
  /^script\//,
  /^pyproject\.toml$/,
  /^MANIFEST\.in$/,
  /^SKILL\.md$/,
  /^mkdocs\.yml$/,
  /^\.clawhubignore$/,
  /^\.github\/workflows\/(ci|publish)\.yml$/,
];

function hasTrack(labels) {
  return labels.some((l) => TRACKS.includes(typeof l === 'string' ? l : l.name));
}

function classifyPr(baseRef, files) {
  if (baseRef === 'v2-maintenance') return 'v2';
  if (files.length > 0 && files.every((f) => V2_PATHS.some((re) => re.test(f)))) return 'v2';
  return 'v3';
}

function classifyIssue(title) {
  if (/^\s*(v2\b|openclaw:)/i.test(title)) return 'v2';
  if (/\bv3\b/i.test(title)) return 'v3';
  if (/\bv2-maintenance\b/i.test(title)) return 'v2';
  return 'v3';
}

async function trackFor(github, owner, repo, item) {
  if (!item.pull_request) return classifyIssue(item.title);
  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: item.number });
  const files = await github.paginate(github.rest.pulls.listFiles, {
    owner,
    repo,
    pull_number: item.number,
    per_page: 100,
  });
  return classifyPr(pr.base.ref, files.map((f) => f.filename));
}

async function label(github, core, owner, repo, item) {
  if (hasTrack(item.labels)) return;
  const track = await trackFor(github, owner, repo, item);
  await github.rest.issues.addLabels({ owner, repo, issue_number: item.number, labels: [track] });
  core.info(`#${item.number} -> ${track}`);
}

module.exports = async ({ github, context, core }) => {
  const { owner, repo } = context.repo;
  const item = context.payload.pull_request || context.payload.issue;
  if (item) {
    // A pull_request payload has no `pull_request` key of its own.
    if (context.payload.pull_request) item.pull_request = {};
    await label(github, core, owner, repo, item);
    return;
  }
  // schedule / workflow_dispatch: sweep everything still missing a track,
  // which includes PRs into v2-maintenance (pull_request_target runs the
  // workflow from the base branch, and this file only lives on main).
  const items = await github.paginate(github.rest.issues.listForRepo, {
    owner,
    repo,
    state: 'all',
    per_page: 100,
  });
  for (const it of items) await label(github, core, owner, repo, it);
};

module.exports.classifyPr = classifyPr;
module.exports.classifyIssue = classifyIssue;
module.exports.hasTrack = hasTrack;
