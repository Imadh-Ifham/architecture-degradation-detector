# C4 risk register

Status as of 2026-10-19. L / I = likelihood / impact (H, M, L). **Executed** = the corrective
action is already done and has evidence; **Open** = action planned, owner and date given.

| ID | Risk | L | I | Corrective action | Status | Evidence |
|---|---|---|---|---|---|---|
| R01 | C3 has no real events on real releases before PP1 | H | H | Consume C3's published `DegradationEventV2` unchanged; hand-designed fixtures covering every outcome; real events slot in through the same port | Executed | `tests/fixtures/degradation_scoring/` + README; C4-ADR-007; FR-01 tests |
| R02 | C2 provides no ADR violation links and no source paths yet | H | M | AV made optional and inactive without links (weights renormalise); manual `src/<service>/**` mapping for Online Boutique; labelled fixture ADR stand-in only for the T21 AV-on run | Executed | C4-ADR-011, C4-ADR-012 (+ T21 addendum); AV-off reports |
| R03 | Git mining too slow for a live demo | H | M | Mining cache in PostgreSQL behind the `MiningCache` port; warm once before the demo | Executed | C4-ADR-001; 599 s uncached → 4.5 s cached run (2026-10-19); `scripts/c4_demo.ps1 -Warm` |
| R04 | AHP weights are the author's own judgement | H | M | Labelled `provisional-author-elicited` in every report; CR ≤ 0.10 gate; supervisor elicitation session | Open (Y05, before Gate 2) | C4-ADR-014; `weights_provenance` in reports |
| R05 | Bug-fix keyword heuristic is imprecise; PR numbers inflated it | M | M | Issue/PR keys no longer count; declared threat to validity; ablation will measure the signal | Executed (rule) · Open (ablation, M6) | C4-ADR-009; T14 findings |
| R06 | Fixture or pilot numbers mistaken for findings | M | H | `data_provenance` in report, manifest and API; banners in HTML and UI; wording rules in the demo script | Executed | Report banners; `demo-script.md` notes |
| R07 | Plan slip: explanation and evaluation layers (Tier B) not ready for PP1 | H | M | Re-baseline: PP1 = Tier A only (moved to 22 Oct); Tier B scheduled after PP1; blast-radius slip already recovered by pulling M4 work forward | Executed (re-plan) | `TRACKER.md` §B; 22 Tier A tasks done |
| R08 | Merge conflicts in shared team files (`pyproject.toml`, `app/main.py`, migrations) | M | M | Fetch and check `origin/develop` every session; C4-only edits; migration renumbered 0004 → 0006 after C2's 0005; team told about C4 migrations | Executed | commit `6949296`; INSTRUCTIONS workflow |
| R09 | Live demo fails (database down, network, slow step) | M | H | One script prepares every run (each step ≤ 5 s); `-SkipDb` path; saved reports and gate report as fallbacks; backup recording | Executed (script) · Open (recording, Y09) | `scripts/c4_demo.ps1`; `demo-script.md` fallback column |
| R10 | Rankings unstable when the event set changes (rank reversal) | M | H | Fixed-reference TOPSIS; frozen normalisation bounds (calibration file) | Executed | C4-ADR-002; rank-reversal tests; T17 frozen-bounds test |
| R11 | Constant features distort criterion scores (0.5 for everyone) | M | M | Zero-range features left out of the criterion mean; all-constant criterion = 0; logged and marked | Executed | C4-ADR-015; `test_normalizer.py` |
| R12 | No team CI pipeline (team decision) | H | L | Local gate script with saved, timestamped reports per task | Executed (stand-in) · Open (team CI, C4-ADR-000 O6) | `docs/pp1/evidence/quality-gate-*.txt` |
| R13 | Validation shows no lift over baselines (Gate 3) | M | H | Baselines and ablation defined up front; honest partial/fail outcomes planned | Open (M5–M7) | `docs/pp1/validation-plan.md` §6 |
| R14 | RefactoringMiner is Java-only; Online Boutique is polyglot | H | M | Choose a Java evaluation repository; parser tests on a recorded sample meanwhile | Open (Y04b) | C4-ADR-000 O1 |
| R15 | LLM explanations invent facts or cost too much (Tier B) | M | H | Grounded generation + claim-level audit vs ungrounded baseline; MockLLM in tests; ≤ 20 real calls per session | Open (after PP1) | `CLAUDE.md` §5.9, NFR-06 |
| R16 | Group UI page not styled in time | M | L | Bare, working Severity page and handoff note delivered; demo step 9 optional | Executed | `frontend/src/pages/Severity.tsx`; `docs/pp1/frontend-handoff.md` |
| R17 | Secrets or run outputs committed | L | H | Outputs under git-ignored `artifacts/`; keys only in `backend/.env` | Executed | `.gitignore`; NFR-07 |
