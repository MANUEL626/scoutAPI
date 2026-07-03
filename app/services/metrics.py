from prometheus_client import Counter, Histogram

jobs_total = Counter("scoutapi_jobs_total", "ScoutAPI jobs by status", ["status"])
leads_total = Counter("scoutapi_leads_total", "ScoutAPI leads by source and qualification", ["source", "qualification"])
fetch_errors_total = Counter("scoutapi_fetch_errors_total", "ScoutAPI fetch errors by domain and status", ["domain", "status"])
job_duration_seconds = Histogram("scoutapi_job_duration_seconds", "ScoutAPI job duration in seconds")
