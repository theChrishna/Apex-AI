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

{{- define "meshheal.mode" -}}
{{- if not (has .Values.mode (list "shadow" "act")) -}}
{{- fail "mode must be shadow or act" -}}
{{- end -}}
{{- .Values.mode -}}
{{- end -}}
