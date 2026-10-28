---
name: Data quality report
about: Report a problem with the published data, an event, or a coverage or status label
title: ""
labels: data quality
---

Tashwish reports observations only. It does not say who is responsible for interference. A report here is about whether the
data or a label is correct, not about attribution.

## Which data

- Release or dataset version (`manifest.json`, field `dataset_version`):
- File (for example `events.parquet`, `cell_buckets.parquet`, `daily_region.csv`):
- Day or days (UTC):
- Cell identifier (H3) and time bucket, if the problem is about one cell:
- Data class shown (observed or synthetic):

## What looks wrong

For example: an event that appears to be an artefact, a cell marked covered that had little traffic, a missing day, a
count that does not match another file.

## Evidence

Describe how you checked, and link to any public source you compared with. Do not include aircraft identifiers or
personal data.

## What you expected to see
