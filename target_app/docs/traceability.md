# Traceability: requirements to tests

The requirement IDs come from `agents/shared_context/requirements-login.md`. The tests are in `target_app/tests/`. Test names are shortened to `file::function`:

- `unit/val`: `tests/unit/test_validation.py`
- `unit/lock`: `tests/unit/test_lockout.py`
- `unit/db`: `tests/unit/test_database.py`
- `unit/static`: `tests/unit/test_frontend_static.py`
- `int`: `tests/integration/test_login_api.py`
- `e2e/page`: `tests/e2e/test_login_page.py`
- `e2e/flow`: `tests/e2e/test_login_flow.py`

`(×N)` means a parametrized test with N cases.

## Latest result

Run on 2026-10-09 with `.venv/bin/python -m pytest` from `target_app/`, using Python 3.14.8, pytest 9.1.1, and Chromium through pytest-playwright 0.10.0:

**267 passed, 0 failed, 0 skipped** (unit 94, integration 76, end-to-end 97). Every test listed below passed in this run.

## Validation rules

| Requirement | Tests | Result |
|---|---|---|
| VR-E1 to VR-E6 (email) | unit/val::test_vr_e_email_pattern_matches_spec, test_vr_e_valid_email_accepted (×5), test_vr_e2_to_e6_invalid_email_rejected (×16), test_vr_e1_empty_email_rejected (×2), test_vr_e4_local_part_max_64, test_vr_e2_email_max_254, test_vr_e_trailing_newline_does_not_sneak_past_pattern, test_vr_e_normalize_email_trims_and_lowercases · int::test_fr13_server_rejects_invalid_email (×16), test_fr13_server_rejects_empty_email (×2) · e2e/page::test_vr_e_page_accepts_valid_email (×5), test_vr_e_page_rejects_invalid_email (×16), test_vr_e1_whitespace_only_email_is_empty, test_ac3_invalid_email_shows_message_and_sends_nothing | Pass |
| VR-P1 to VR-P4 (password) | unit/val::test_vr_p_valid_password_accepted (×7), test_vr_p2_to_p4_invalid_password_rejected (×8), test_vr_p1_empty_password_rejected, test_vr_p2_password_max_128, test_vr_p3_password_needs_three_words, test_vr_p4_tabs_are_not_spaces, test_vr_p_password_is_not_trimmed_or_changed · int::test_fr13_server_rejects_invalid_password (×8) · e2e/page::test_vr_p_page_accepts_valid_password (×7), test_vr_p_page_rejects_invalid_password (×7), test_ac4_empty_password_shows_message_and_sends_nothing, test_ac5_two_word_password_shows_format_message | Pass |

## Functional requirements

| Requirement | Tests | Result |
|---|---|---|
| FR-1 Login page at `/` | unit/static::test_fr1_index_html_exists · int::test_fr1_get_root_returns_login_page · e2e/page::test_ac1_page_shows_fields_and_buttons | Pass |
| FR-2 Email field | e2e/page::test_fr2_email_field_attributes, test_nfr13_labels_linked_with_for, test_ac1_page_shows_fields_and_buttons | Pass |
| FR-3 Password field | e2e/page::test_fr3_password_field_attributes, test_ac7_fr5_show_password | Pass |
| FR-4 Element IDs | unit/static::test_fr4_every_element_id_appears_once · e2e/page::test_fr4_no_messages_on_load | Pass |
| FR-5 Show password | e2e/page::test_ac7_fr5_show_password | Pass |
| FR-6 Hide password | e2e/page::test_fr6_toggle_button_initial_state, test_ac8_fr6_hide_password_again | Pass |
| FR-7 Toggle keeps value, no submit, keyboard | e2e/page::test_ac8_fr6_hide_password_again, test_fr7_toggle_works_with_keyboard (×2: Enter, Space) | Pass |
| FR-8 Validate before sending | e2e/page::test_fr8_form_uses_page_validation_not_browser_popups, test_fr8_both_fields_invalid_shows_both_messages, test_fr8_enter_in_field_submits_and_validates, test_ac2_empty_email_shows_message_and_sends_nothing, test_ac3_…, test_ac4_…, test_ac5_…, test_ac6_both_empty_shows_both_errors_and_focuses_email | Pass |
| FR-9 Field error messages | unit/val::test_vr_e_valid_email_accepted, test_vr_e2_to_e6_invalid_email_rejected, test_vr_e1_empty_email_rejected, test_vr_p_valid_password_accepted, test_vr_p2_to_p4_invalid_password_rejected, test_vr_p1_empty_password_rejected (these check `email_error` / `password_error`) · int::test_fr13_both_fields_listed_when_both_invalid · e2e/page::test_ac2_…, test_ac3_…, test_ac4_…, test_ac5_… | Pass |
| FR-10 `aria-invalid`, focus, clearing | e2e/page::test_ac6_both_empty_shows_both_errors_and_focuses_email, test_fr10_focus_moves_to_first_invalid_field, test_fr10_field_error_clears_when_value_changes, test_nfr13_fields_point_to_their_error_text | Pass |
| FR-11 Validation is not an attempt | int::test_fr11_validation_errors_do_not_count_as_failures, test_ac18_invalid_email_returns_422_with_message_and_does_not_count, test_ac18_invalid_password_returns_422_with_message_and_does_not_count · e2e/page::test_ac2_… to test_ac5_… (no request sent) | Pass |
| FR-12 `POST /api/login`, button disabled | e2e/flow::test_fr12_sends_json_post_with_typed_values, test_fr12_button_disabled_while_request_in_progress | Pass |
| FR-13 Server validation, 422 | int::test_fr13_both_fields_listed_when_both_invalid, test_fr13_server_rejects_invalid_email (×16), test_fr13_server_rejects_empty_email (×2), test_fr13_server_rejects_invalid_password (×8), test_fr13_validation_is_checked_before_lock, test_fr13_malformed_body_returns_422 (×6), test_fr13_non_json_body_returns_422, test_ac18_… (×2) | Pass |
| FR-14 Normalized email, exact password | unit/db::test_fr14_get_user_by_email_normalizes, test_fr14_get_user_by_email_unknown_returns_none, test_fr14_authenticate_with_correct_password, test_fr14_authenticate_normalizes_email, test_fr14_authenticate_wrong_password_returns_none, test_fr14_authenticate_unknown_email_returns_none, test_fr14_password_is_case_sensitive, test_fr14_password_spaces_matter · int::test_ac9_email_is_trimmed_and_case_insensitive · e2e/flow::test_ac9_email_with_spaces_and_capitals_logs_in | Pass |
| FR-15 200, cookie, redirect | int::test_fr15_correct_credentials_return_ok_and_redirect, test_fr15_failed_login_sets_no_session · e2e/flow::test_ac9_seed_account_logs_in_and_sees_welcome, test_fr15_page_follows_redirect_from_response | Pass |
| FR-16 401 with attempts left | unit/lock::test_fr16_failures_return_attempts_remaining · int::test_ac10_first_failure_returns_two_attempts_remaining, test_ac12_second_failure_returns_one_attempt_remaining, test_ac11_unknown_email_same_response_as_wrong_password · e2e/flow::test_ac10_wrong_password_shows_two_attempts_left, test_ac11_unknown_email_same_message, test_ac12_second_failure_shows_one_attempt_left, test_fr16_page_uses_attempts_remaining_from_server | Pass |
| FR-17 Keep email, clear password | e2e/flow::test_ac10_fr17_keeps_email_clears_password_and_focuses_it | Pass |
| FR-18 Count per normalized email, on the server | unit/lock::test_new_email_has_no_failures_and_no_lock, test_fr18_each_failure_increases_count, test_fr18_counts_are_kept_per_email · int::test_fr18_unknown_email_is_counted_and_locked_like_known, test_fr18_failures_counted_on_normalized_email, test_fr18_failures_for_one_email_do_not_count_for_another, test_fr18_lock_does_not_affect_other_account · e2e/flow::test_ac20_count_survives_reload, test_fr18_lock_does_not_affect_other_account | Pass |
| FR-19 3rd failure: 423, 5 s | unit/lock::test_fr19_third_failure_starts_five_second_lock · int::test_ac13_fr19_third_failure_locks_for_five_seconds · e2e/flow::test_ac13_third_failure_locks_and_counts_down | Pass |
| FR-20 Refuse while locked, no extension | unit/lock::test_fr20_retry_after_is_remaining_seconds_rounded_up (×6), test_fr20_lock_ends_after_exactly_five_seconds, test_fr20_checking_lock_does_not_extend_it · int::test_ac14_correct_password_refused_during_lock, test_fr20_lock_applies_to_normalized_email, test_fr20_retry_after_counts_down, test_ac14_fr20_requests_during_lock_do_not_extend_it · e2e/flow::test_ac14_api_refuses_correct_password_while_locked | Pass |
| FR-21 Page lock message and countdown | e2e/flow::test_ac13_third_failure_locks_and_counts_down, test_fr21_fields_editable_and_enter_does_nothing_while_locked, test_fr21_fr22_page_counts_down_from_server_retry_after | Pass |
| FR-22 "You can try logging in again." | e2e/flow::test_ac15_lock_ends_with_try_again_message_and_three_attempts, test_fr21_fr22_page_counts_down_from_server_retry_after | Pass |
| FR-23 Count resets when the lock expires | unit/lock::test_fr23_count_resets_when_lock_expires, test_fr23_fresh_three_attempts_after_lock, test_fr23_reset_without_any_call_during_lock · int::test_ac15_fr23_three_attempts_again_after_lock, test_ac16_login_succeeds_after_lock_expires · e2e/flow::test_ac15_…, test_ac16_login_succeeds_after_lock_expires | Pass |
| FR-24 Success resets the count | unit/lock::test_fr24_success_resets_count · int::test_ac17_fr24_success_resets_count · e2e/flow::test_ac17_success_resets_count | Pass |
| FR-25 Failures don't expire on their own | unit/lock::test_fr25_failures_do_not_expire_on_their_own · int::test_fr25_failures_do_not_expire_on_their_own | Pass |
| FR-26 Welcome page | int::test_ac9_fr26_home_shows_welcome_with_stored_email · e2e/flow::test_ac9_seed_account_logs_in_and_sees_welcome | Pass |
| FR-27 `/home` without a session: 303 | int::test_ac19_fr27_home_without_session_redirects_to_root, test_fr27_home_with_forged_session_redirects_to_root · e2e/flow::test_ac19_home_without_session_goes_to_login | Pass |
| FR-28 Other errors | e2e/flow::test_ac21_server_or_network_error_message (×3: 500, 403, network) | Pass |
| FR-29 SQLite table and seed account | unit/db::test_fr29_init_db_creates_file_and_users_table, test_fr29_init_db_seeds_demo_account, test_fr29_init_db_is_idempotent, test_fr29_email_is_unique, test_fr29_create_user_returns_id_and_stores_normalized_email, test_fr29_get_user_by_email | Pass |

## Non-functional requirements

| Requirement | Tests | Result |
|---|---|---|
| NFR-1 Salted slow hash, no plain text | unit/db::test_ac22_no_column_contains_plain_password, test_ac22_nfr1_stored_value_is_salted_pbkdf2_hash, test_nfr1_hash_password_uses_random_salt, test_nfr1_verify_password · int::test_nfr1_password_never_in_response_or_log (×4), test_nfr1_password_not_echoed_in_malformed_422 · e2e/flow::test_nfr1_password_not_in_url_or_server_log | Pass |
| NFR-2 `hmac.compare_digest` | unit/db::test_nfr2_hashes_compared_with_compare_digest | Pass |
| NFR-3 Parameterized SQL | unit/db::test_nfr3_sql_injection_in_email_has_no_effect (×3) | Pass |
| NFR-4 Credentials only in the POST body | int::test_nfr4_credentials_in_query_string_are_not_accepted, test_nfr4_get_login_is_not_allowed · e2e/flow::test_fr12_sends_json_post_with_typed_values, test_nfr1_password_not_in_url_or_server_log | Pass |
| NFR-5 Same error for email and password | int::test_ac11_unknown_email_same_response_as_wrong_password · e2e/flow::test_ac11_unknown_email_same_message | Pass |
| NFR-6 Session cookie | int::test_nfr6_session_cookie_flags, test_nfr6_session_cookie_secure_over_https, test_nfr6_session_cookie_not_secure_over_http, test_nfr6_session_tokens_are_random | Pass |
| NFR-7 The server enforces the lock | int::test_nfr7_lock_applies_to_every_client, test_ac14_correct_password_refused_during_lock · e2e/flow::test_nfr7_reload_does_not_bypass_lock, test_ac14_api_refuses_correct_password_while_locked | Pass |
| NFR-8 Over-long values get 422 | int::test_nfr8_overlong_values_rejected | Pass |
| NFR-9 Plain, exact messages | No test of its own. The exact texts are checked by the FR-9, FR-16, FR-21, FR-22, and FR-28 tests | Pass (exact texts only) |
| NFR-10 Keyboard only | e2e/flow::test_nfr10_keyboard_only_login, test_nfr10_enter_in_either_field_logs_in (×2) · e2e/page::test_ac23_tab_order_and_visible_focus | Pass |
| NFR-11 Response within 1 s | int::test_nfr11_login_responds_within_one_second (×2) | Pass |
| NFR-12 320 to 1920 px, no horizontal scroll | e2e/page::test_nfr12_no_horizontal_scroll (×2) | Pass |
| NFR-13 Labels and `aria-describedby` | e2e/page::test_nfr13_labels_linked_with_for, test_nfr13_fields_point_to_their_error_text, test_ac23_tab_order_and_visible_focus | Pass |
| NFR-14 Announced messages | e2e/page::test_nfr14_form_message_is_announced | Pass for the first half. The second half (countdown not announced every second) isn't tested automatically (see Gaps) |
| NFR-15 Text errors, 4.5:1 contrast | e2e/page::test_nfr15_text_contrast_at_least_4_5 (×6), test_nfr15_form_message_contrast_at_least_4_5 | Pass |
| NFR-16 Visible focus | e2e/page::test_ac23_tab_order_and_visible_focus | Pass |
| NFR-17 `lang="en"`, title `Login` | unit/static::test_nfr17_html_lang_en · e2e/page::test_nfr17_lang_and_title | Pass |
| NFR-18 Tech stack, no build step | unit/static::test_nfr18_no_build_step_scripts_are_plain_files (the rest of the suite runs the app on FastAPI and SQLite) | Pass |
| NFR-19 Named constants | unit/lock::test_nfr19_named_constants, test_nfr19_defaults_use_the_constants | Pass |

## Acceptance criteria

| AC | Tests | Result |
|---|---|---|
| AC-1 | e2e/page::test_ac1_page_shows_fields_and_buttons | Pass |
| AC-2 | e2e/page::test_ac2_empty_email_shows_message_and_sends_nothing | Pass |
| AC-3 | e2e/page::test_ac3_invalid_email_shows_message_and_sends_nothing | Pass |
| AC-4 | e2e/page::test_ac4_empty_password_shows_message_and_sends_nothing | Pass |
| AC-5 | e2e/page::test_ac5_two_word_password_shows_format_message | Pass |
| AC-6 | e2e/page::test_ac6_both_empty_shows_both_errors_and_focuses_email | Pass |
| AC-7 | e2e/page::test_ac7_fr5_show_password | Pass |
| AC-8 | e2e/page::test_ac8_fr6_hide_password_again | Pass |
| AC-9 | int::test_ac9_email_is_trimmed_and_case_insensitive, test_ac9_fr26_home_shows_welcome_with_stored_email · e2e/flow::test_ac9_seed_account_logs_in_and_sees_welcome, test_ac9_email_with_spaces_and_capitals_logs_in | Pass |
| AC-10 | int::test_ac10_first_failure_returns_two_attempts_remaining · e2e/flow::test_ac10_wrong_password_shows_two_attempts_left, test_ac10_fr17_keeps_email_clears_password_and_focuses_it | Pass |
| AC-11 | int::test_ac11_unknown_email_same_response_as_wrong_password · e2e/flow::test_ac11_unknown_email_same_message | Pass |
| AC-12 | int::test_ac12_second_failure_returns_one_attempt_remaining · e2e/flow::test_ac12_second_failure_shows_one_attempt_left | Pass |
| AC-13 | int::test_ac13_fr19_third_failure_locks_for_five_seconds · e2e/flow::test_ac13_third_failure_locks_and_counts_down | Pass |
| AC-14 | int::test_ac14_correct_password_refused_during_lock, test_ac14_fr20_requests_during_lock_do_not_extend_it · e2e/flow::test_ac14_api_refuses_correct_password_while_locked | Pass |
| AC-15 | int::test_ac15_fr23_three_attempts_again_after_lock · e2e/flow::test_ac15_lock_ends_with_try_again_message_and_three_attempts | Pass |
| AC-16 | int::test_ac16_login_succeeds_after_lock_expires · e2e/flow::test_ac16_login_succeeds_after_lock_expires | Pass |
| AC-17 | int::test_ac17_fr24_success_resets_count · e2e/flow::test_ac17_success_resets_count | Pass |
| AC-18 | int::test_ac18_invalid_email_returns_422_with_message_and_does_not_count, test_ac18_invalid_password_returns_422_with_message_and_does_not_count | Pass |
| AC-19 | int::test_ac19_fr27_home_without_session_redirects_to_root · e2e/flow::test_ac19_home_without_session_goes_to_login | Pass |
| AC-20 | e2e/flow::test_ac20_count_survives_reload | Pass |
| AC-21 | e2e/flow::test_ac21_server_or_network_error_message (×3) | Pass |
| AC-22 | unit/db::test_ac22_no_column_contains_plain_password, test_ac22_nfr1_stored_value_is_salted_pbkdf2_hash | Pass |
| AC-23 | e2e/page::test_ac23_tab_order_and_visible_focus | Pass |

## Gaps

- **NFR-14, second half.** No test checks that the countdown isn't announced every second. In the code, `frontend/login.js` updates only the number inside a `<span aria-live="off">` within `#form-message`, as the spec suggests.
- **NFR-9.** The tests check that the messages match the spec exactly. Whether they are plain and helpful was judged when the spec was written; it can't be tested automatically.
