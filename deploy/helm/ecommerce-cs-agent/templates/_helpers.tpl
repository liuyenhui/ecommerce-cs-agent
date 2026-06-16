{{- define "ecommerce-cs-agent.name" -}}
ecommerce-cs-agent
{{- end -}}

{{- define "ecommerce-cs-agent.labels" -}}
app.kubernetes.io/name: {{ include "ecommerce-cs-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
