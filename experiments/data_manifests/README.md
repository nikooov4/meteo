# Measured dataset manifests

Byte-identical snapshots of the local synthetic dataset manifests accompany the
saved scale reports. Original paths and raw SHA256 checksums are recorded in
index.json. Shard paths inside each manifest are relative to its ORIGINAL data
directory, not this provenance directory. The actual numeric arrays are excluded
from Git and remain local; committing a manifest does not publish the archive.

The 200-GB experiment evidence remains reports/scale/scale_report.json and
acceptance.json. A clone contains scripts/configuration/checksums, not 200 GB of
data. Generate a fresh dataset in a new output directory or restore original
shards before attempting a full data verification. Smoke tests create small
temporary datasets; CI never generates/scans 200 GB automatically.
