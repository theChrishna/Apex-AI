{{- define "meshheal.fullname" -}}
{{- printf "%s-controlplane" (.Release.Name | trunc 40 | trimSuffix "-") -}}
{{- end -}}

{{- define "meshheal.labels" -}}
app.kubernetes.io/name: meshheal
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "meshheal.target" -}}
{{- required "set targetNamespace to the namespace of the application to watch (--set targetNamespace=...)" .Values.targetNamespace -}}
{{- end -}}

{{- define "meshheal.scorer" -}}
{{- $s := default "baseline" .Values.scorer -}}
{{- if not (has $s (list "baseline" "edge")) -}}
{{- fail "scorer must be baseline or edge" -}}
{{- end -}}
{{- $s -}}
{{- end -}}

{{- define "meshheal.alertRules" -}}
groups:
  - name: meshheal-controller
    rules:
      - alert: MeshHealControllerDown
        expr: absent(meshheal_loops_total{ {{- printf "namespace=%q" .Release.Namespace -}} }) or up{ {{- printf "namespace=%q" .Release.Namespace -}}, app_kubernetes_io_name="meshheal"} == 0
        for: 5m
        labels: {severity: critical}
        annotations:
          summary: The MeshHeal controller is not reporting metrics.
          description: No metrics from the controller for 5 minutes. A reroute in place stays in place until it is back (or until someone restores the weights).
      - alert: MeshHealLoopStalled
        expr: time() - meshheal_last_loop_timestamp_seconds > 120
        for: 2m
        labels: {severity: critical}
        annotations:
          summary: The MeshHeal control loop has not finished an iteration for over 2 minutes.
      - alert: MeshHealLoopErrors
        expr: increase(meshheal_loop_errors_total[10m]) > 0
        labels: {severity: warning}
        annotations:
          summary: The MeshHeal control loop raised unexpected errors (LOOP_ERROR in the audit log).
      - alert: MeshHealActionFailed
        expr: increase(meshheal_events_total{event="ACTION_FAILED"}[15m]) > 0
        labels: {severity: warning}
        annotations:
          summary: A MeshHeal write was refused (ambiguous route, 409 conflict or API error). Nothing was changed; check the audit log.
      - alert: MeshHealTooManyReroutes
        expr: increase(meshheal_events_total{event="REROUTE"}[1h]) >= 4
        labels: {severity: warning}
        annotations:
          summary: Four or more reroutes in the last hour. Either something keeps failing or the scorer is flapping.
      - alert: MeshHealRerouteActiveLong
        expr: meshheal_active_reroutes > 0
        for: 45m
        labels: {severity: warning}
        annotations:
          summary: A reroute has been in place for 45 minutes. The fault is still there, or the release is blocked.
      - alert: MeshHealPaused
        expr: meshheal_paused == 1
        for: 30m
        labels: {severity: info}
        annotations:
          summary: MeshHeal has been paused for 30 minutes (control ConfigMap). It scores but does not act.
      - alert: MeshHealStateNeedsAHuman
        expr: increase(meshheal_events_total{event=~"RECONCILE_ORPHAN|RECONCILE_FAILED"}[1h]) > 0
        labels: {severity: warning}
        annotations:
          summary: MeshHeal found reroute state it cannot interpret on a VirtualService; it left it alone. Check the meshheal.io/state annotations.
      - alert: MeshHealSnapshotsRejected
        expr: increase(meshheal_events_total{event="SNAPSHOT_REJECTED"}[10m]) > 20
        labels: {severity: warning}
        annotations:
          summary: Most MeshHeal snapshots in the last 10 minutes were rejected (stale or bad data). Check the collector and Prometheus.
{{- end -}}

{{- define "meshheal.mode" -}}
{{- if not (has .Values.mode (list "shadow" "act")) -}}
{{- fail "mode must be shadow or act" -}}
{{- end -}}
{{- .Values.mode -}}
{{- end -}}
