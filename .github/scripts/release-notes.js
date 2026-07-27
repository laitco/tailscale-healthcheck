// Shared by both jobs in .github/workflows/release.yaml (the release-PR
// preview and the final published release), via actions/github-script's
// `require()` support.
//
// GitHub's repos.generateReleaseNotes only ever includes each merged PR's
// *title* under its category heading (from .github/release.yml) - never the
// PR description. That's fine for routine changes, but for a PR labeled
// "breaking-change" the whole point of writing a detailed "## ⚠️ Breaking
// Changes" section in the PR body is for operators to actually read it
// before upgrading - a single title line doesn't cut it. This appends each
// such PR's own Breaking Changes section (verbatim) to the generated notes.

async function generateReleaseNotesWithBreakingChangeDetails(github, context, core, { tag_name, previous_tag_name }) {
  const owner = context.repo.owner;
  const repo = context.repo.repo;

  const payload = { owner, repo, tag_name, target_commitish: context.sha };
  if (previous_tag_name) payload.previous_tag_name = previous_tag_name;
  const notes = await github.rest.repos.generateReleaseNotes(payload);
  let body = notes.data.body || '';

  // PR numbers referenced by the generated "What's Changed" list, e.g.
  // "... by @user in https://github.com/o/r/pull/50".
  const prNumbers = [...new Set([...body.matchAll(/\/pull\/(\d+)/g)].map((m) => parseInt(m[1], 10)))];

  const details = [];
  for (const number of prNumbers) {
    let pr;
    try {
      pr = await github.rest.pulls.get({ owner, repo, pull_number: number });
    } catch (e) {
      core.warning(`release-notes: could not fetch PR #${number}: ${e.message}`);
      continue;
    }
    const labels = (pr.data.labels || []).map((l) => l.name);
    if (!labels.includes('breaking-change')) continue;

    const prBody = pr.data.body || '';
    // Everything from a "## ... Breaking Changes" heading up to the next
    // "## " heading (or end of body). Tolerant of the emoji/exact wording
    // varying slightly, but expects the section to exist - a breaking-
    // change PR without one just contributes nothing extra here.
    const match = prBody.match(/##[^\n]*Breaking Changes[^\n]*\n([\s\S]*?)(?=\n##\s|$)/i);
    if (match && match[1].trim()) {
      details.push(`### #${number}: ${pr.data.title}\n\n${match[1].trim()}`);
    }
  }

  if (details.length) {
    // Prepended, not appended - breaking changes are the thing an operator
    // upgrading needs to see first, not buried below the routine changelog.
    body = `## ⚠️ Breaking Changes\n\n${details.join('\n\n---\n\n')}\n\n---\n\n${body}`;
  }

  return body;
}

module.exports = { generateReleaseNotesWithBreakingChangeDetails };
