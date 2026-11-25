# Test report

Run: `pytest -v` against PostgreSQL 16 · Django 5.2 · Python 3.13 · **65 tests, 65 passed** (about 33 s).

## Acceptance criteria → evidence

| Acceptance criterion | Result | Tests |
|---|---|---|
| Report submission completes in under 60 seconds on mobile | ✅ Single-screen form: only title, category and location are required; time defaults to now; camera capture; map picker; suggested hidden-detail questions pre-filled. End-to-end form post with a photo is tested. Timing should be confirmed in UAT with real users (see note below). | `test_report_form_end_to_end_with_photo` |
| Match suggestions returned for ≥ 70% of seeded matching pairs | ✅ **20 / 20 = 100% in top 5; 20 / 20 ranked first** (5 unrelated distractor items included) | `test_seeded_pairs_match_rate_at_least_70_percent` |
| Private details never appear in any public response – proven exhaustively | ✅ 10 item states × 9 public endpoints × 2 visitor types = 180 checked responses, plus a real end-to-end workflow, claimant pages, and API create | `test_private_leak.py` (14 tests), `test_structure.py` (9 tests) |
| Claim requires passing the verification challenge before handover is permitted | ✅ Approval, scheduling and completion each re-check that verification passed | `TestApprovalRules` |
| Handover recorded with custody chain and proof | ✅ OTP or signature, a proof photo (required), the supervising guard, and a hash-chained custody record; tampering is detected | `TestHandover`, `TestCustodyChain` |
| Unclaimed items age into the disposal queue at the configured interval | ✅ Warning at (retention − 7 days), queued at the retention limit; set per category; items with open claims are skipped | `TestAgeing` |

Also covered by the spec's testing section: **competing claims** (`TestCompetingClaims`, including a database constraint), **verification scoring** (`TestScoring`, `TestChallengeFlow`), **handover requires the security role** (`test_handover_requires_security_role`, which checks the service layer, the web UI and the API), and **EXIF/GPS stripping** (`test_exif_and_gps_are_stripped_before_storage`).

**Note on the 60-second criterion:** this is a UX measure. Do a timed run with 5 or more students on their own phones during UAT (milestone M4) and record the times here.

## Full test list

```
test_ageing_imaging_views.py::TestAgeing::test_item_ages_then_enters_disposal_queue  ✅
test_ageing_imaging_views.py::TestAgeing::test_retention_is_configurable_per_category  ✅
test_ageing_imaging_views.py::TestAgeing::test_item_with_open_claim_does_not_age  ✅
test_ageing_imaging_views.py::TestAgeing::test_disposal_recorded_in_custody_chain  ✅
test_ageing_imaging_views.py::test_exif_and_gps_are_stripped_before_storage  ✅
test_ageing_imaging_views.py::test_invalid_image_rejected  ✅
test_ageing_imaging_views.py::test_found_report_requires_hidden_details  ✅
test_ageing_imaging_views.py::test_report_form_end_to_end_with_photo  ✅
test_ageing_imaging_views.py::TestPagesAndRoles::test_pages_render_for_each_role  ✅
test_ageing_imaging_views.py::TestPagesAndRoles::test_claim_via_web_flow  ✅
test_claims_handover.py::TestApprovalRules::test_cannot_approve_unverified_claim  ✅
test_claims_handover.py::TestApprovalRules::test_only_security_can_approve  ✅
test_claims_handover.py::TestApprovalRules::test_cannot_schedule_handover_before_approval  ✅
test_claims_handover.py::TestApprovalRules::test_cannot_complete_handover_if_verification_not_passed  ✅
test_claims_handover.py::TestCompetingClaims::test_two_verified_claims_only_one_approved  ✅
test_claims_handover.py::TestCompetingClaims::test_database_constraint_blocks_two_winners  ✅
test_claims_handover.py::TestCompetingClaims::test_rejecting_last_claim_reopens_item  ✅
test_claims_handover.py::TestHandover::test_full_handover_with_otp_records_custody_and_proof  ✅
test_claims_handover.py::TestHandover::test_handover_requires_security_role  ✅
test_claims_handover.py::TestHandover::test_handover_requires_proof_photo  ✅
test_claims_handover.py::TestHandover::test_wrong_otp_is_counted_and_rejected  ✅
test_claims_handover.py::TestHandover::test_signature_instead_of_otp  ✅
test_claims_handover.py::TestHandover::test_otp_not_returned_by_api  ✅
test_claims_handover.py::TestCustodyChain::test_records_are_append_only  ✅
test_claims_handover.py::TestCustodyChain::test_tampering_is_detected  ✅
test_claims_handover.py::TestCustodyChain::test_only_security_records_intake  ✅
test_matching.py::test_seeded_pairs_match_rate_at_least_70_percent  ✅
test_matching.py::test_suggestions_generated_on_report_creation  ✅
test_matching.py::test_no_match_when_found_long_before_lost  ✅
test_matching.py::test_location_score_tree  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[open]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[in_custody]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[claim_pending]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[claim_approved]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[returned]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[resolved]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[ageing]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[disposal_queue]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[disposed]  ✅
test_private_leak.py::test_no_private_field_on_public_endpoints_in_any_state[withdrawn]  ✅
test_private_leak.py::test_no_leak_through_full_real_workflow  ✅
test_private_leak.py::test_claimant_never_sees_answers  ✅
test_private_leak.py::test_unrelated_user_cannot_open_private_item_page  ✅
test_private_leak.py::test_reporting_api_does_not_echo_private_details  ✅
test_structure.py::test_default_manager_is_locked  ✅
test_structure.py::test_private_details_encrypted_at_rest  ✅
test_structure.py::test_public_dto_is_exactly_the_allow_list  ✅
test_verification.py::TestChallengeFlow::test_challenge_created_with_three_questions  ✅
test_verification.py::TestChallengeFlow::test_correct_paraphrased_answers_pass  ✅
test_verification.py::TestChallengeFlow::test_wrong_answers_then_locked  ✅
test_verification.py::TestChallengeFlow::test_borderline_goes_to_security_review  ✅
test_verification.py::TestChallengeFlow::test_finder_cannot_claim_own_found_item  ✅
test_verification.py::TestChallengeFlow::test_only_claimant_can_answer  ✅
test_matching.py::test_component_scores  ✅
test_structure.py::test_public_modules_do_not_import_the_vault[apps/board/public.py]  ✅
test_structure.py::test_public_modules_do_not_import_the_vault[apps/board/views.py]  ✅
test_structure.py::test_public_modules_do_not_import_the_vault[apps/board/search.py]  ✅
test_structure.py::test_public_modules_do_not_import_the_vault[apps/board/urls.py]  ✅
test_structure.py::test_item_has_no_relation_to_private_details  ✅
test_structure.py::test_private_detail_not_in_admin  ✅
test_verification.py::TestScoring::test_exact_and_case_insensitive  ✅
test_verification.py::TestScoring::test_paraphrase_gets_credit  ✅
test_verification.py::TestScoring::test_wrong_answer_scores_zero  ✅
test_verification.py::TestScoring::test_shotgun_answers_are_penalised  ✅
test_verification.py::TestScoring::test_overall_score_is_mean  ✅
```
