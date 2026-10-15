# BAGUSMAX Armored V1.2 Prototype Handoff

**REVIEW_REQUIRED / UNRESOLVED MECHANICAL BLOCKER**. Stage B did not pass. No final V1.2 .blend or GLB was created. These are rejected engineering prototypes, not a finished candidate.

## A. Root Cause

V1.1 pauldron is Chest-parented, pivot x=0.37m, z=1.36m. Its medial/lower rim intersects chest/collar already at neutral. Its existing -0.64*elevation rotation sweeps into the chest/helmet; shifting the pivot alone changes the swept envelope but does not remove intersections. Shoulder liner also crosses upperarm, and the broader audit finds backpack/cap contact.

Independent of the cap, UpperArm_L shell crosses CHEST_COLLAR at S90/E130 and HELMET_EAR_L at S145/E130. A pauldron-only transform cannot remove those independent contacts. Actual object names, anchors, parent, local/world matrices, axes and contact bounds are in failure_diagnostics.json. Bounds and polygon pairs are not penetration depth.

## B. Geometry Trials

Local 4mm-expanded convex chest envelope trims medial pauldron/liner lips; 1.5mm rim bevel. Chest/White/helmet/legs/wings unchanged. Neutral cap/chest contact is removed, but raised poses fail. No guard deletion or global subdivision. Geometry edits exist only in disposable Blender memory.

## C. Mechanical Trials

Rebased left pauldron pivot to (0.52,0,1.36)m preserving neutral child world geometry. Evaluated pivot only, then pivot plus lip relief. Bounded search then tested X0..0.12m, Y0..0.08m, Z0..0.16m and three rest-axis rotation fractions (0,+0.25,-0.15). Values are explicit search bounds, not an approved runtime motion. Selection minimizes sampled intersecting polygon pairs, not penetration. Some isolated cap samples clear; no continuous full-arm mapping was obtained.

## D. Comparison

![Left prototype](../../reports/bagusmax_3d/armored_v1_2/sheet_b_left_prototype.png)

## E. Shoulder Results

| Option | Evaluated left poses | FAIL | LIMIT |
|---|---:|---:|---:|
| baseline | 29 | 29 | 0 |
| pivot_only | 29 | 29 | 0 |
| pivot_inner_lip | 29 | 29 | 0 |

## F. Combined Matrix

All 12 required combined pairs were tested for the left side in each trial. See pose_matrix.json and collision_report.json. Right-side, dense full grid, symmetric/asymmetric full-body and adaptive continuous sweeps are **NOT_TESTED**, deliberately deferred by the Stage B gate.

## G. Elbow Regression

V1.1 standalone elbow result remains historical baseline evidence, not a new V1.2 PASS. No elbow geometry was changed or rebuilt. New full elbow regression was not run after failed shoulder prototype.

## H. Guard Finishing

NOT_TESTED / deferred. The V1.1 guard remains unchanged. No cosmetic cleanup used to hide failed articulation.

## I. Wing/Backpack

New diagnostic reveals cap/backpack contact in V1.1 neutral. Complete V1.2 wing regression not run. No wing or backpack geometry edited.

## J. Export Validation

V1.1 re-evaluated from actual GLB: Khronos 0 errors / 0 warnings; 45 independent poses, max 0.001237289mm. This is not validation of an unexported V1.2.

Export now requires explicit destination; existing baseline outputs are rejected. Default V1 rebuild is disabled; explicit legacy build rejects an existing source. V1.2-only replacement requires explicit replace and stages to a temporary GLB before validator/hash checks and os.replace. Negative overwrite tests were exercised; successful atomic export branch is **NOT_TESTED** because local mechanical acceptance failed. No final source save was attempted.

## K. Statistics

Actual V1.1 baseline: 200,782 triangles; 108,304 exported vertices; 130 meshes; 132 primitives; 7 materials; joints [32]; 3,909,556 bytes; 0 clips. V1.2 statistics/load/CPU/FPS/VRAM NOT_TESTED. No claims from an in-memory cap trial are presented as final asset metrics.

## L. Integrity

All initially protected hashes unchanged; see asset_hashes.json and preservation_before/after.json. Extra rollback .blend1 hash captured at closeout before any asset save/export, not before code edits; this limitation is explicit. No reference film pixels copied.

## M. Known Blocker And Next Operation

Exact reproducible failure: load V1.1, anatomical rest-axis UpperArm_L=(0,-pi/2,0), Forearm_L=(-130deg,0,0), evaluate existing helpers and armor controls. Upperarm/collar and pauldron/arm contacts remain. Bounded cap search still cannot clear S90/E130. This is not proof that no different mechanical design can work.

Next operation: evaluate a two-piece hinged medial pauldron leaf together with localized proximal upper-arm C-shell clearance. Both remain untested options, not implemented runtime features. Keep neutral silhouette and existing elbow swept relief; prove on left S90/E130 and S145/E130 before mirror. Do not repeat V1 construction or full renders.

![Failure pairs](../../reports/bagusmax_3d/armored_v1_2/sheet_a_failure_localization.png)

## N. Git

```text
## feat/bagusmax-3d-art
?? assets/bagusmax/
?? docs/bagusmax_3d/
?? reports/bagusmax_3d/
?? tools/
```

Only build_armored.py / review_armored.py and V1.2 diagnostic reports/docs changed. No stage, commit, merge, branch change or push. No Voice/Data/AgentHarness/CLI/renderer/lighting edits.

## O. Review Files

Review index: reports/bagusmax_3d/armored_v1_2/index.html. Prototype source and GLB outputs: NOT_CREATED. CHECKPOINT.md contains exact resume commands. Private film references remain in V1.1 external-reference index; no public stills copied.

## P. Visual Decision

User review requested: may the trimmed medial inner-lip silhouette shown in the neutral prototype remain as the visual direction for a future segmented mechanism? This is not approval of the failing raised poses or a production asset.
