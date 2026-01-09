# Skill Tool Usage Analysis

**Total Skills Analyzed:** 55

**Total Unique Tools Used:** 170


## Tools Used Per Skill

### appinterface_check.yaml
- **Tool Count:** 6
- **Tools:** appinterface_diff, appinterface_get_saas, appinterface_resources, gitlab_mr_list, kubectl_get, kubectl_get_deployments

### beer.yaml
- **Tool Count:** 5
- **Tools:** bonfire_namespace_list, git_branch_list, git_log, git_status, gitlab_mr_list

### cancel_pipeline.yaml
- **Tool Count:** 6
- **Tools:** memory_session_log, tkn_pipelinerun_cancel, tkn_pipelinerun_delete, tkn_pipelinerun_describe, tkn_pipelinerun_list, tkn_taskrun_list

### check_ci_health.yaml
- **Tool Count:** 4
- **Tools:** gitlab_ci_lint, gitlab_ci_list, gitlab_ci_trace, gitlab_ci_view

### check_integration_tests.yaml
- **Tool Count:** 3
- **Tools:** konflux_get_test_results, konflux_list_integration_tests, konflux_list_snapshots

### check_mr_feedback.yaml
- **Tool Count:** 3
- **Tools:** gitlab_mr_comments, gitlab_mr_list, memory_session_log

### check_my_prs.yaml
- **Tool Count:** 4
- **Tools:** gitlab_mr_list, gitlab_mr_view, memory_session_log, skill_run

### check_secrets.yaml
- **Tool Count:** 3
- **Tools:** kubectl_describe_deployment, kubectl_get_configmaps, kubectl_get_secrets

### ci_retry.yaml
- **Tool Count:** 5
- **Tools:** gitlab_ci_status, memory_session_log, tkn_pipelinerun_describe, tkn_pipelinerun_list, tkn_pipelinerun_logs

### cleanup_branches.yaml
- **Tool Count:** 5
- **Tools:** git_branch_delete, git_branch_list, git_fetch, git_remote, memory_session_log

### clone_jira_issue.yaml
- **Tool Count:** 5
- **Tools:** jira_add_link, jira_assign, jira_clone_issue, jira_view_issue, memory_session_log

### close_issue.yaml
- **Tool Count:** 8
- **Tools:** git_branch_list, git_log, gitlab_list_mrs, jira_add_comment, jira_get_issue, jira_get_transitions, jira_transition_issue, memory_session_log

### close_mr.yaml
- **Tool Count:** 4
- **Tools:** gitlab_mr_close, gitlab_mr_view, jira_add_comment, memory_session_log

### coffee.yaml
- **Tool Count:** 7
- **Tools:** alertmanager_alerts, bonfire_namespace_list, git_log, gitlab_mr_comments, gitlab_mr_list, gitlab_mr_view, jira_search

### create_jira_issue.yaml
- **Tool Count:** 7
- **Tools:** jira_assign, jira_create_issue, jira_link_issues, jira_transition, jira_update_issue, jira_view_issue, memory_session_log

### create_mr.yaml
- **Tool Count:** 19
- **Tools:** code_format, code_lint, git_fetch, git_log, git_merge, git_merge_abort, git_push, git_status, gitlab_ci_lint, gitlab_file_read, gitlab_mr_create, gitlab_mr_list, jira_add_comment, jira_set_status, jira_view_issue, memory_append, memory_session_log, memory_update, skill_run

### debug_prod.yaml
- **Tool Count:** 20
- **Tools:** alertmanager_alerts, grafana_dashboard_get, grafana_dashboard_list, kibana_search_logs, kubectl_describe_pod, kubectl_get, kubectl_get_deployments, kubectl_get_events, kubectl_get_pods, kubectl_logs, kubectl_saas_deployments, kubectl_saas_pipelines, kubectl_top_pods, memory_session_log, prometheus_grafana_link, prometheus_pod_health, prometheus_query, prometheus_query_range, prometheus_rules, slack_channel_read

### deploy_to_ephemeral.yaml
- **Tool Count:** 7
- **Tools:** bonfire_apps_dependencies, bonfire_deploy, bonfire_namespace_reserve, bonfire_pool_list, kubectl_get_pods, kubectl_rollout_status, memory_session_log

### environment_overview.yaml
- **Tool Count:** 5
- **Tools:** k8s_environment_summary, k8s_namespace_health, kubectl_get_ingress, kubectl_get_pods, kubectl_get_services

### extend_ephemeral.yaml
- **Tool Count:** 4
- **Tools:** bonfire_namespace_describe, bonfire_namespace_extend, bonfire_namespace_list, memory_session_log

### hotfix.yaml
- **Tool Count:** 10
- **Tools:** git_blame, git_branch_list, git_checkout, git_cherry_pick, git_diff, git_fetch, git_push, git_tag, jira_add_comment, memory_session_log

### investigate_alert.yaml
- **Tool Count:** 11
- **Tools:** alertmanager_list_silences, k8s_namespace_health, kibana_search_logs, kubectl_get_events, kubectl_get_pods, kubectl_top_pods, memory_session_log, prometheus_alerts, prometheus_grafana_link, prometheus_query_range, skill_run

### investigate_slack_alert.yaml
- **Tool Count:** 6
- **Tools:** jira_create_issue, jira_search, kubectl_get_pods, kubectl_logs, memory_session_log, slack_send_message

### jira_hygiene.yaml
- **Tool Count:** 6
- **Tools:** jira_set_epic, jira_set_priority, jira_set_status, jira_set_story_points, jira_view_issue_json, memory_session_log

### konflux_status.yaml
- **Tool Count:** 5
- **Tools:** konflux_failed_pipelines, konflux_list_applications, konflux_namespace_summary, konflux_running_pipelines, konflux_status

### learn_pattern.yaml
- **Tool Count:** 1
- **Tools:** memory_session_log

### mark_mr_ready.yaml
- **Tool Count:** 9
- **Tools:** code_format, code_lint, gitlab_mr_update, gitlab_mr_view, jira_set_status, memory_session_log, memory_update, skill_run, slack_post_team

### memory_cleanup.yaml
- **Tool Count:** 2
- **Tools:** memory_read, memory_session_log

### memory_edit.yaml
- **Tool Count:** 1
- **Tools:** memory_session_log

### memory_init.yaml
- **Tool Count:** 1
- **Tools:** memory_session_log

### memory_view.yaml
- **Tool Count:** 0
- **Tools:** (none - all compute steps)

### notify_mr.yaml
- **Tool Count:** 4
- **Tools:** gitlab_mr_view, jira_view_issue, memory_session_log, slack_post_team

### notify_team.yaml
- **Tool Count:** 4
- **Tools:** memory_session_log, slack_get_user, slack_list_channels, slack_post_message

### rebase_pr.yaml
- **Tool Count:** 14
- **Tools:** git_add, git_branch_list, git_checkout, git_fetch, git_log, git_pull, git_push, git_rebase, git_reset, git_stash, git_status, gitlab_mr_view, lint_python, memory_session_log

### release_aa_backend_prod.yaml
- **Tool Count:** 14
- **Tools:** git_add, git_branch_list, git_checkout, git_commit, git_fetch, git_log, git_push, git_rebase, git_status, gitlab_mr_create, jira_add_comment, jira_create_issue, memory_session_log, quay_get_tag

### release_to_prod.yaml
- **Tool Count:** 11
- **Tools:** appinterface_validate, grafana_annotation_create, konflux_create_release, konflux_get_component, konflux_get_release, konflux_list_components, konflux_list_releases, memory_session_log, quay_check_image_exists, quay_get_vulnerabilities, slack_post_message

### review_all_prs.yaml
- **Tool Count:** 6
- **Tools:** gitlab_mr_approve, gitlab_mr_comment, gitlab_mr_list, gitlab_mr_view, memory_session_log, skill_run

### review_pr.yaml
- **Tool Count:** 23
- **Tools:** docker_compose_status, docker_compose_up, docker_cp, docker_exec, git_blame, git_checkout, git_diff, git_fetch, gitlab_ci_status, gitlab_ci_trace, gitlab_commit_list, gitlab_mr_approve, gitlab_mr_approvers, gitlab_mr_comment, gitlab_mr_diff, gitlab_mr_list, gitlab_mr_view, jira_add_comment, jira_view_issue, konflux_list_pipelines, make_target, memory_session_log, slack_dm_gitlab_user

### review_pr_multiagent.yaml
- **Tool Count:** 3
- **Tools:** gitlab_mr_comment, gitlab_mr_diff, gitlab_mr_view

### review_pr_multiagent_test.yaml
- **Tool Count:** 1
- **Tools:** gitlab_mr_diff

### rollout_restart.yaml
- **Tool Count:** 5
- **Tools:** kubectl_describe_deployment, kubectl_get_pods, kubectl_rollout_restart, kubectl_rollout_status, memory_session_log

### scale_deployment.yaml
- **Tool Count:** 5
- **Tools:** kubectl_get_deployments, kubectl_get_pods, kubectl_rollout, kubectl_scale, memory_session_log

### scan_vulnerabilities.yaml
- **Tool Count:** 4
- **Tools:** memory_session_log, quay_check_image_exists, quay_get_manifest, quay_get_vulnerabilities

### schedule_meeting.yaml
- **Tool Count:** 7
- **Tools:** google_calendar_check_mutual_availability, google_calendar_find_meeting, google_calendar_list_events, google_calendar_quick_meeting, google_calendar_schedule_meeting, google_calendar_status, memory_session_log

### silence_alert.yaml
- **Tool Count:** 5
- **Tools:** alertmanager_alerts, alertmanager_create_silence, alertmanager_delete_silence, alertmanager_list_silences, memory_session_log

### slack_daemon_control.yaml
- **Tool Count:** 0
- **Tools:** (none - all compute steps)

### sprint_planning.yaml
- **Tool Count:** 2
- **Tools:** jira_list_blocked, jira_list_issues

### standup_summary.yaml
- **Tool Count:** 9
- **Tools:** git_config_get, git_log, gitlab_mr_list, google_calendar_list_events, jira_my_issues, jira_search, memory_read, memory_session_log, slack_channel_read

### start_work.yaml
- **Tool Count:** 19
- **Tools:** git_branch_create, git_branch_list, git_checkout, git_fetch, git_pull, git_stash, git_status, gitlab_ci_status, gitlab_mr_comments, gitlab_mr_list, gitlab_mr_view, jira_assign, jira_set_status, jira_transition, jira_view_issue, memory_append, memory_session_log, memory_update, slack_post_message

### suggest_patterns.yaml
- **Tool Count:** 0
- **Tools:** (none - all compute steps)

### sync_branch.yaml
- **Tool Count:** 9
- **Tools:** code_format, code_lint, git_fetch, git_log, git_push, git_rebase, git_stash, git_status, memory_session_log

### test_error_recovery.yaml
- **Tool Count:** 0
- **Tools:** (none - all compute steps)

### test_mr_ephemeral.yaml
- **Tool Count:** 25
- **Tools:** bonfire_deploy_aa, bonfire_namespace_release, bonfire_namespace_reserve, bonfire_namespace_wait, git_diff_tree, git_rev_parse, git_show, gitlab_ci_status, gitlab_mr_view, jira_get_issue, konflux_get_build_logs, konflux_get_snapshot, konflux_list_builds, konflux_list_snapshots, kubectl_cp, kubectl_describe_pod, kubectl_exec, kubectl_get_events, kubectl_get_pods, kubectl_get_secret_value, memory_session_log, quay_get_tag, tkn_pipelinerun_describe, tkn_pipelinerun_list, tkn_pipelinerun_logs

### update_docs.yaml
- **Tool Count:** 1
- **Tools:** memory_session_log

### weekly_summary.yaml
- **Tool Count:** 7
- **Tools:** git_log, gitlab_mr_list, jira_my_issues, konflux_list_releases, memory_read, quay_list_aa_tags, slack_search_messages


## Tool Usage by Module

### aa_alertmanager
- **Total Tools:** 7
- **Used in Skills:** 4
- **Unused:** 3
- **Used Tools:** alertmanager_alerts, alertmanager_create_silence, alertmanager_delete_silence, prometheus_grafana_link
- **Unused Tools:** alertmanager_receivers, alertmanager_silences, alertmanager_status

### aa_appinterface
- **Total Tools:** 7
- **Used in Skills:** 4
- **Unused:** 3
- **Used Tools:** appinterface_diff, appinterface_get_saas, appinterface_resources, appinterface_validate
- **Unused Tools:** appinterface_clusters, appinterface_get_user, appinterface_search

### aa_bonfire
- **Total Tools:** 20
- **Used in Skills:** 10
- **Unused:** 10
- **Used Tools:** bonfire_apps_dependencies, bonfire_deploy, bonfire_deploy_aa, bonfire_namespace_describe, bonfire_namespace_extend, bonfire_namespace_list, bonfire_namespace_release, bonfire_namespace_reserve, bonfire_namespace_wait, bonfire_pool_list
- **Unused Tools:** bonfire_apps_list, bonfire_deploy_aa_from_snapshot, bonfire_deploy_aa_local, bonfire_deploy_env, bonfire_deploy_iqe_cji, bonfire_deploy_with_reserve, bonfire_full_test_workflow, bonfire_process, bonfire_process_env, bonfire_process_iqe_cji

### aa_dev_workflow
- **Total Tools:** 9
- **Used in Skills:** 0
- **Unused:** 9
- **Used Tools:** (none)
- **Unused Tools:** workflow_check_deploy_readiness, workflow_create_branch, workflow_daily_standup, workflow_handle_review, workflow_monitor_pipelines, workflow_prepare_mr, workflow_review_feedback, workflow_run_local_checks, workflow_start_work

### aa_git
- **Total Tools:** 30
- **Used in Skills:** 27
- **Unused:** 3
- **Used Tools:** code_format, code_lint, docker_compose_status, docker_compose_up, docker_cp, docker_exec, git_add, git_branch_create, git_branch_list, git_checkout, git_commit, git_config_get, git_diff, git_diff_tree, git_fetch, git_log, git_merge, git_merge_abort, git_pull, git_push, git_rebase, git_reset, git_rev_parse, git_show, git_stash, git_status, make_target
- **Unused Tools:** docker_compose_down, git_clean, git_remote_info

### aa_gitlab
- **Total Tools:** 30
- **Used in Skills:** 16
- **Unused:** 14
- **Used Tools:** gitlab_ci_lint, gitlab_ci_list, gitlab_ci_status, gitlab_ci_trace, gitlab_ci_view, gitlab_list_mrs, gitlab_mr_approve, gitlab_mr_approvers, gitlab_mr_close, gitlab_mr_comment, gitlab_mr_comments, gitlab_mr_create, gitlab_mr_diff, gitlab_mr_list, gitlab_mr_update, gitlab_mr_view
- **Unused Tools:** gitlab_ci_cancel, gitlab_ci_retry, gitlab_ci_run, gitlab_issue_create, gitlab_issue_list, gitlab_issue_view, gitlab_label_list, gitlab_mr_merge, gitlab_mr_rebase, gitlab_mr_reopen, gitlab_mr_revoke, gitlab_release_list, gitlab_repo_view, gitlab_user_info

### aa_google_calendar
- **Total Tools:** 6
- **Used in Skills:** 6
- **Unused:** 0
- **Used Tools:** google_calendar_check_mutual_availability, google_calendar_find_meeting, google_calendar_list_events, google_calendar_quick_meeting, google_calendar_schedule_meeting, google_calendar_status
- **Unused Tools:** (none)

### aa_jira
- **Total Tools:** 28
- **Used in Skills:** 17
- **Unused:** 11
- **Used Tools:** jira_add_comment, jira_add_link, jira_assign, jira_clone_issue, jira_create_issue, jira_get_issue, jira_list_blocked, jira_list_issues, jira_my_issues, jira_search, jira_set_epic, jira_set_priority, jira_set_status, jira_set_story_points, jira_transition, jira_view_issue, jira_view_issue_json
- **Unused Tools:** jira_add_flag, jira_add_to_sprint, jira_ai_helper, jira_block, jira_lint, jira_remove_flag, jira_remove_sprint, jira_set_summary, jira_show_template, jira_unassign, jira_unblock

### aa_k8s
- **Total Tools:** 28
- **Used in Skills:** 22
- **Unused:** 6
- **Used Tools:** k8s_environment_summary, k8s_namespace_health, kubectl_cp, kubectl_describe_deployment, kubectl_describe_pod, kubectl_exec, kubectl_get, kubectl_get_configmaps, kubectl_get_deployments, kubectl_get_events, kubectl_get_ingress, kubectl_get_pods, kubectl_get_secret_value, kubectl_get_secrets, kubectl_get_services, kubectl_logs, kubectl_rollout_restart, kubectl_rollout_status, kubectl_saas_deployments, kubectl_saas_pipelines, kubectl_scale, kubectl_top_pods
- **Unused Tools:** k8s_list_deployments, k8s_list_ephemeral_namespaces, k8s_list_pods, kubectl_delete_pod, kubectl_saas_logs, kubectl_saas_pods

### aa_kibana
- **Total Tools:** 9
- **Used in Skills:** 1
- **Unused:** 8
- **Used Tools:** kibana_search_logs
- **Unused Tools:** kibana_error_link, kibana_get_errors, kibana_get_link, kibana_get_pod_logs, kibana_index_patterns, kibana_list_dashboards, kibana_status, kibana_trace_request

### aa_konflux
- **Total Tools:** 35
- **Used in Skills:** 22
- **Unused:** 13
- **Used Tools:** konflux_failed_pipelines, konflux_get_build_logs, konflux_get_component, konflux_get_release, konflux_get_snapshot, konflux_get_test_results, konflux_list_applications, konflux_list_builds, konflux_list_components, konflux_list_integration_tests, konflux_list_pipelines, konflux_list_releases, konflux_list_snapshots, konflux_namespace_summary, konflux_running_pipelines, konflux_status, tkn_pipelinerun_cancel, tkn_pipelinerun_delete, tkn_pipelinerun_describe, tkn_pipelinerun_list, tkn_pipelinerun_logs, tkn_taskrun_list
- **Unused Tools:** konflux_get_application, konflux_get_pipeline, konflux_list_environments, konflux_list_release_plans, tkn_describe_pipelinerun, tkn_logs, tkn_pipeline_describe, tkn_pipeline_list, tkn_pipeline_start, tkn_task_describe, tkn_task_list, tkn_taskrun_describe, tkn_taskrun_logs

### aa_lint
- **Total Tools:** 7
- **Used in Skills:** 1
- **Unused:** 6
- **Used Tools:** lint_python
- **Unused Tools:** lint_dockerfile, lint_yaml, precommit_run, security_scan, test_coverage, test_run

### aa_prometheus
- **Total Tools:** 13
- **Used in Skills:** 5
- **Unused:** 8
- **Used Tools:** prometheus_alerts, prometheus_pod_health, prometheus_query, prometheus_query_range, prometheus_rules
- **Unused Tools:** prometheus_check_health, prometheus_error_rate, prometheus_get_alerts, prometheus_labels, prometheus_namespace_metrics, prometheus_pre_deploy_check, prometheus_series, prometheus_targets

### aa_quay
- **Total Tools:** 7
- **Used in Skills:** 5
- **Unused:** 2
- **Used Tools:** quay_check_image_exists, quay_get_manifest, quay_get_tag, quay_get_vulnerabilities, quay_list_aa_tags
- **Unused Tools:** quay_get_repository, quay_list_tags

### aa_slack
- **Total Tools:** 9
- **Used in Skills:** 6
- **Unused:** 3
- **Used Tools:** slack_dm_gitlab_user, slack_get_user, slack_list_channels, slack_post_team, slack_search_messages, slack_send_message
- **Unused Tools:** slack_add_reaction, slack_get_channels, slack_list_messages

### aa_workflow
- **Total Tools:** 0
- **Used in Skills:** 0
- **Unused:** 0
- **Used Tools:** (none)
- **Unused Tools:** (none)


## Summary Statistics

- **Total Tools Available:** 245
- **Tools Used in Skills:** 170
- **Tools Unused:** 75
- **Usage Rate:** 69.4%
