# Branch audit, 25 September 2026

Origin was fetched before base selection. Initial dirty master remained at
13fa71ff9f22c7f9133bb6522be6f9f02ffe051a, with 223 status entries.
No checkout/reset/stash of that directory was performed.

The full inventory in `branch-inventory.json` contains 113 local/remote refs
(including the new migration branch), grouped into 68 distinct combinations of
participant/backend/Android/web Git trees. This records every ref's source identity;
it is not a claim that every one of those implementations was freshly tested.

The historical f45f0b1 checkpoint was compared with release-curation 9d188cf and
the local integration 522f3f8. Curation explicitly preserves c2504bc as a historical
performance baseline but records unsafe authority/visual cases. Its underlying
26fb022 runtime is not a qualified release either. The 78-addition/15-deletion
participant runtime delta between curation and 522f3f8 was inspected, including
array recipients, dictated bodies, bound subtree leaves and natural dates.

Selected migration base: 522f3f82ac7cec508eaa49297af638de6c674c63. It retains those
general authority repairs. This does not promote it on legacy scores or assert
superiority over c2504bc. No cherry-picks or branch merges were needed.
Its known compound-value truncation was independently reproduced with new wording,
then fixed on this migration branch with positive and negative regression controls.

Fresh baseline: 1160 Python tests passed; browser audio/live audio checks passed;
workspace renderer 72 checks passed; 50-seed legacy deterministic replay passed.
After initial integration and the compound fix: 1175 tests passed. Later focused
tests and final exact-code counts are in RELEASE_EVIDENCE.md and raw logs.
These are engineering results, not FDB-v3 qualification or an Android build.
