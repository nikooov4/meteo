# Requirements traceability (v2.1)

The user request governs this implementation. The supplied documents are source
requirements/context; commands printed in them were not treated as already
implemented features or existing experimental results. No code was copied from
the unrelated geology reference repository.

| Requirement | Implementation / evidence |
|---|---|
| Domain, one physical series, units/calendar checks | domain.py, semantics.py; tests/test_core.py |
| Independent increment LP vs rational graph | oracle.py vs graph.py; Gate A |
| Full H, conservative top-k handling | Case.h_complete; incomplete-h omission fixture |
| Proofs/conflicts/attaining witnesses/rays | certificates.py independent of compiler/search |
| Enumeration, bounded whole-effect LRU, shared candidate | services.py, shared.py; algorithm_delta.md |
| Same policy information/actions/stopping | acquisition.py, experiments.py; saved full outcome traces |
| VOI/DRD and tiny optimal baseline | one-step VOI, two-step Bayes VOI2, EC2 specialization, exact finite tree |
| DWD + accumulation/local file | data/real/dwd; local-cumulative.csv; NCAR LSP native reader |
| Shared CLI/SDK/UI/API/client | services.py, ui/app.py, api.py, examples/integration_client.py |
| Chunked storage/projection/partition selection | readers.py, scale_data.py; 4096-observation working model |
| Four scale scripts, dry-run/resume/budgets | scripts/*scale*.py; configs/scale; scale reports |
| Independent real annotation, Gate B | pending, explicitly not supplied by Codex |
| Large experiment | actual status and byte counts in reports/scale/scale_report.json |

No LLM, GPU, map/CDN, general matcher, large connector framework or distributed
service is needed. The current core handles interval amount/mean rate/cumulative,
not arbitrary linear objectives, rain-hour counts, min/max or signed energy flux.
