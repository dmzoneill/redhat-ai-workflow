#!/usr/bin/env bash
# Delete all comments from ANSTRAT-1848 refinement issues and add the single desired comment.
# Run from repo root with: bash docs/meetings/anstrat1848-fix-comments.sh
# Requires: rh-issue (jira-creator with delete-comment --all and add-comment).

set -e

run() {
  local key="$1"
  echo "=== $key ==="
  rh-issue delete-comment "$key" --all || true
  shift
  local comment_file="$1"
  rh-issue add-comment "$key" -t "$(cat "$comment_file")" --no-ai
  echo ""
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMENTS_DIR="$SCRIPT_DIR/anstrat1848-comments"
mkdir -p "$COMMENTS_DIR"

# Epic
cat > "$COMMENTS_DIR/66639.txt" << 'EPIC'
Refinement meeting 2026-03-05 (Shane McDonald, David O Neill, Zvika Sadeh).

Reviewed all refinement action tasks for Stage Connectivity Initiative (1848). Decisions:
- Keep open: Architecture Definition (SDP in progress), Test Plan (to be addressed in SDP/proposals), Downstream CI/CD (pending SAS side changes).
- Close with detailed comments: Kickoff, Engage with Docs, Engage with UX, Security (see Security task), Build and Release, Installer, Release Eng, Perf and Scale, Cloud Assessment.

Meeting notes: https://docs.google.com/document/d/1ILmwwMW2tiYcHGHgtLC6en_Iep_Fpev_Q54gzNwqg4Y/edit
SDP: https://github.com/ansible/handbook/pull/1223
EPIC

# Task comments (from plan)
cat > "$COMMENTS_DIR/66640.txt" << 'T66640'
Refinement 2026-03-05: Closing as complete.

* Kickoff — Satisfied: Multiple prior calls between Razique and the SAS team are considered the kickoff; ongoing coordination is in place.
* Communication plan — Satisfied: Coordination via existing channels; no separate recurring sync, slack, weekly comment, or Jira view required for this refinement initiative.
* SME review / scope & rank — Satisfied: Feature scope and approach confirmed in those discussions. No additional SME review needed before exiting refinement.
T66640

cat > "$COMMENTS_DIR/66641.txt" << 'T66641'
Refinement 2026-03-05: Keeping open – in progress.

* SDP — Satisfied (in progress): Open (handbook PR #1223). May need slight tweaks based on ongoing discussions.
* Blocking proposals — Gap: Not all approved/merged yet. Outstanding questions; we are engaging; proposals will follow once we have more clarity. This task stays open until blocking proposals are done.
* Design epic / stories — Satisfied (in progress): SDP work will be story-pointed and assigned to current sprint. Close this task when SDP is approved/merged and blocking proposals are done.
T66641

cat > "$COMMENTS_DIR/66642.txt" << 'T66642'
Refinement 2026-03-05: Closing.

* Collaborate with Docs team — Satisfied: We confirmed no customer-facing documentation is required for this initiative.
* Doc work in JIRA / Issue Links — N/A: No doc work required for analytics team; no doc issues to create or link.
* Doc ownership — N/A: Internal docs (hub–spoke, private link) are the responsibility of the SAS team; they own the infrastructure. Analytics team will not own this architecture. Consider creating an epic for SAS team changes and documentation.
T66642

cat > "$COMMENTS_DIR/66643.txt" << 'T66643'
Refinement 2026-03-05: Closing.

* UX involvement / additional UX effort — N/A: This initiative is purely network connectivity with no UI changes. No UX engagement required.
* UX or UI contact — N/A: No contact needed; no UI impact.
T66643

cat > "$COMMENTS_DIR/66644.txt" << 'T66644'
Refinement 2026-03-05: Keeping open – security review pending.

* AC (1) Security work needed — Gap (in progress): Security assessment is necessary; opening external IPs could present risk. Same restrictions as normal inbound interface apply. Plan to consult Thomas Eagle (product security architect, Ansible) once the plan is in place. After review we will reflect in Feature AC and create child issue(s) if needed, or confirm no actions needed.
* AC (2) Comment linking to issue(s) or confirm no actions — Gap: Will add that comment when we close this task after Thomas Eagle review.
T66644

cat > "$COMMENTS_DIR/66645.txt" << 'T66645'
Refinement 2026-03-05: Keeping open – test plan to be captured in SDP/proposals.

* QA contact — Satisfied: Identified (engineers; per refinement discussion).
* Test plan / verification — Gap (in progress): Phase 1 = establish connectivity and confirm we receive data; Prometheus/Grafana for telemetry; non-firing alerts as validation for now. Phase 2 (end-to-end / data accuracy) out of scope. "Receive" to be qualified in proposal (e.g. billing code vs subwatch). Test plan is part of the SDP (handbook PR #1223). Task stays open until proposal outlines mechanics of Phase 1 verification.
T66645

cat > "$COMMENTS_DIR/66646.txt" << 'T66646'
Refinement 2026-03-05: Keeping open – pending SAS side.

* AC (1) Pipeline automation to validate feature — N/A for AAP: We do not have AAP downstream pipeline automation for this feature. Open question: Do SAS nightly pipelines need to be updated to include assertions that data is successfully showing up in the staging service? Task stays open until SAS side changes are understood; may be handed to SAS team (they are part of the initiative).
* AC (2) New pipeline job configurations — N/A for AAP: No new AAP pipeline job configs for this initiative.
* AC (3) Notify PDE — N/A: No new AAP issues to create; notifying PDE is not applicable. We use CI/CD for build/deploy, not monitoring. Will add comment when SAS pipeline needs are clear; then close or reassign.
T66646

cat > "$COMMENTS_DIR/66647.txt" << 'T66647'
Refinement 2026-03-05: Closing.

* AC (1) Review build/release documentation — N/A: This initiative does not involve functionality that will be released in the traditional sense. No build or release process changes required; review not applicable.
* AC (2) Tracking epic and comment — Satisfied: No build or release needs identified; no tracking epic required. This comment serves as the required comment: no build/release actions needed for this initiative.
T66647

cat > "$COMMENTS_DIR/66648.txt" << 'T66648'
Refinement 2026-03-05: Closing.

* AC (1) Child issue(s) for installer changes — N/A: No installer changes required for this initiative (no new component, new settings, component interaction changes, or additional infra for this connectivity work).
* AC (2) Comment — Satisfied: This comment states why no installer changes are needed: no installer impact for this initiative.
T66648

cat > "$COMMENTS_DIR/66649.txt" << 'T66649'
Refinement 2026-03-05: Closing.

* AC (1) Tracking epic/issues if engagement needed — N/A: No Release Engineering engagement is needed for this initiative.
* AC (2) Closing comment explaining WHY — Satisfied: No engagement needed because this initiative does not publish content on access.redhat.com/downloads and does not create entitlement for customers other than "all current & future AAP customers." No RHDH/Portal or other non-AAP release content; not relevant to this initiative.
T66649

cat > "$COMMENTS_DIR/66650.txt" << 'T66650'
Refinement 2026-03-05: Closing.

* Performance KPIs/SLOs, observability, scale targets — N/A: Not required for the initial pass. Current focus is testing connectivity in the stage environment. No Perf/Scale consultation needed for this refinement exit.
* Perf/Scale engagement — N/A: Performance/scale testing may be considered in a later initiative.
T66650

cat > "$COMMENTS_DIR/66651.txt" << 'T66651'
Refinement 2026-03-05: Closing.

* Cloud/managed-offerings assessment — Satisfied: Cloud team is already part of the overall project; we are already engaging with them. Assessment is in progress as part of the initiative.
* Contact / engagement — Satisfied: No separate refinement task needed; engagement covered by existing project participation.
T66651

# Epic (already done via MCP; uncomment to re-run)
# run AAP-66639 "$COMMENTS_DIR/66639.txt"

# Tasks: delete all comments then add desired comment
for n in 40 41 42 43 44 45 46 47 48 49 50 51; do
  run "AAP-666$n" "$COMMENTS_DIR/666$n.txt"
done

echo "Done. Epic AAP-66639 was already updated via MCP; if you need to reset it too, run:"
echo "  rh-issue delete-comment AAP-66639 --all"
echo "  rh-issue add-comment AAP-66639 -t \"\$(cat $COMMENTS_DIR/66639.txt)\" --no-ai"
