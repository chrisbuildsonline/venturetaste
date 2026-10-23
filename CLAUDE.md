# How to build VentureTaste

Quality beats speed: a judge who hits one broken flow stops reading. Project docs (STATE.md, TODO.md, RULES.md, LOG.md) live in the hackathons MCP: get_project, write_project_doc, log_progress.

## Roles
- **Opus (main session) plans and signs off.** It reads the rules, splits the work into small features in TODO.md (each with acceptance criteria and the test types it needs), sends each feature to a builder, reviews the report and decides. Opus does not write feature code.
- **Sonnet agents build** (Agent tool, model sonnet, one feature per agent; independent features can run in parallel). Each reports back to Opus: files changed, tests added, the full test output and anything it is unsure of.
- **No self-approval.** Opus checks the report against the acceptance criteria and reruns the tests itself before ticking the box.

## Rules first
Before any code: read the full official rules, overview and updates (fetch_page) and write RULES.md (write_project_doc) with every hard requirement as a checkbox: who can enter, required tech or APIs, submission parts (video length, repo visibility, license, write-up, screenshots), deadline with timezone, judging criteria and prize tracks. Build to the judging criteria, not to taste.

## One feature at a time
For each feature in TODO.md, in order:
1. **Red:** write the failing test first (TDD) from the acceptance criteria. Run it and see it fail for the right reason.
2. **Green:** write the least code that makes it pass.
3. **Regression:** run the whole suite, not just the new test. All green.
4. **Fit extra tests to the risk:** Playwright end to end for every user-facing flow (click through it, take a screenshot, check the console has no errors); integration tests for APIs, databases and services; fuzz tests for parsers and untrusted input; Given/When/Then acceptance tests for the demo flow; load tests only if the demo depends on speed. Smoke-test after every build.
5. **Sign-off:** Opus verifies, ticks the item in TODO.md, logs it (log_progress) and commits. Only then start the next feature.

## Commits
- Commit small and often: after every few changes that work (a test going green, a fix, a style tweak, a doc update). Several commits per feature, never one big commit at the end. Only commit states where the tests pass.
- Messages are short and sound like a person typed them: lowercase, under 50 characters, one line, plain words. Good: "add ghost sprites", "fix tombstone on relative links", "slow the marquee down", "readme: how to load it". Never: "feat:" style prefixes, bodies or bullet lists, emoji, "This commit...", "Implement X per spec task 3.2", or any mention of agents, models, phases or task numbers.
- Never add a Co-Authored-By line, a "Generated with" line or any other AI attribution to a commit, in any project. This is a hard rule.
- Real timestamps only: never backdate, squash or rewrite history.

A failing test, a skipped test (.skip or .only), a stub or a TODO in the code means the feature is not done. If a feature cannot go green, log a blocker; do not move on and leave it broken.

## Hard stop: Needs fix (keys and accounts only)
Stop a feature only for what needs the user's own accounts: an API key (request_secret), or a login, paid plan or 2FA (log_progress a blocker that starts with "Needs fix:" and says exactly what is missing). Everything else you get yourself, so it is never a blocker:
- **Images and sample data: generate them.** Synthetic people (thispersondoesnotexist.com faces, adults only), bodies, products and scenes from the sponsor's own generation APIs or other generators, procedural/SVG/canvas art, or CC0 sources (Wikimedia Commons, Met Open Access). Note the source and license in a LICENSE.txt next to them.
- **Anything that needs the web or a browser** (rules pages, API docs, downloads, examples): `bun /home/chris/projects/hackathons/web.js "<task>" --out <dir in this repo>`. It runs cursor-agent, which has a browser, in a scratch dir and copies the files it saves into --out. Only if it says cursor-agent is logged out is that a Needs fix ("run cursor-agent login").
- **A tool your shell may not run:** wrap it in a package.json script and use bun run.
Do not fake it with a mock and call it done, do not tick it, do not judge. get_project lists the open items in needs_fix; judge_project refuses while any are open. Carry on with features that do not depend on it, and log_progress done once it is fixed.

## Before submitting
Smoke-test a fresh clone by following the README; full suite green; Playwright run through the whole demo script; re-read the updates page; every RULES.md box ticked. Then the jury loop.

## Jury loop (aim: 10/10)
1. Commit, then judge_project. Wait for it (judge_status every few minutes; it takes 20-60 min), then get_verdict.
2. Do what get_verdict's loop says. **fix:** confirmed blockers first, then top_fixes, each through the feature gate above (every bug a juror found becomes a failing test first), commit, judge again. **final:** judge_project with fresh: true for an unanchored score. **stop:** you are done judging.
3. The server decides when to stop: 10/10 with no blockers, 5 rounds, no improvement in 2 rounds, or under 24 hours to the deadline. A project with a target score keeps going until it reaches the target with no blockers (round limits off). Never argue with the jurors in the repo or write to them; fix the product. Feedback about the idea itself (originality, sponsor fit) goes to the user with add_note.
