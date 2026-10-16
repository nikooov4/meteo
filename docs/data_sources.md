# Source checks, 2026-10-16

* [DWD description v24.03](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/DESCRIPTION_obsgermany_climate_hourly_precipitation_en.pdf):
  hourly precipitation in mm, missing codes/QN and CC-BY-4.0. Three historical
  archives yield 168 rows per station for 2023-01-01..07. Their embedded parameter
  metadata explicitly says UTC. Source URLs and raw/subset SHA256 are preserved
  in data/manifests/dwd-subset.json. Exact end-label is pending for this product.
* [NCAR registry](https://registry.opendata.aws/nsf-ncar-era5/) and
  [UCAR terms](https://www.ucar.edu/terms-of-use/data): anonymous S3 listing/HEAD
  was actually tested. The January 2023 accumu folder contains LSP and CP but no
  expected TP object. The checked profile selects `.128_142_lsp.`, not unrelated
  pressure-level fields and not an invented total-precipitation mirror.
  One 269320412-byte NetCDF was downloaded with SHA256, ETag/version/URL metadata.
  Dimensions are initialization × 12 hourly steps × 721 × 1440, unit m.
  [ERA5 temporal documentation](https://confluence.ecmwf.int/pages/viewpage.action?pageId=85415489)
  establishes previous-hour accumulation for HRES. Initializations stay separate;
  raw LSP is not de-accumulated as if cumulative from step zero.
* [CERRA guide](https://confluence.ecmwf.int/spaces/CKB/pages/272323672/Copernicus+European+Regional+ReAnalysis+CERRA+product+user+guide)
  describes precipitation cumulative from forecast start. No CDS credentials or
  downloaded CERRA/ERA5-Land data are claimed. The permitted local-file alternative
  is data/fixtures/local-cumulative.csv with explicit reset baseline and provenance.
* [CF 1.12](https://cfconventions.org/Data/cf-conventions/cf-conventions-1.12/cf-conventions.html)
  motivates explicit time bounds/cell_methods. Generic scalar CF import requires
  bounds and user-declared SeriesKey; multidimensional native NCAR uses its checked
  adapter. Unknown calendars do not silently become Gregorian.

No cross-product equalities, no spatial averaging into a hidden truth, no physical
independence claim for provider mirrors. DWD raw ZIPs are cached outside tracked
fixtures; small permitted excerpts/manifests suffice to replay the offline cases.
NCAR real-200GB is separate from synthetic-scale acceptance and remains not_run
unless an actual real-scale report says otherwise.

The separate 200-GB profile was exercised as a metadata-only dry-run on
2026-10-16: 735 LSP objects passed LIST/HEAD size checks, totaling
200208579407 bytes. The pinned object plan, ETags, versions where available,
configuration and source snapshot are in
data/manifests/ncar-200gb-download-plan.json; reports/ncar-profile.json summarizes
the check. Disk resource assessment passed at planning time. This establishes a
sufficient selected scope, not downloaded bytes or a real-200GB scan. Only the
separate 269320412-byte native object has actually been downloaded and inspected.
