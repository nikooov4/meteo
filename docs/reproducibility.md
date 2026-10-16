# Reproducibility

Python 3.12.13 and uv.lock pin the runtime/dependencies. Run metadata records
library versions, hardware/RAM, OS, exact source hash and a ZIP snapshot of
Python source plus lock/project metadata. Initial experiment snapshots cover
src/scripts; final delivery snapshots additionally cover ui/tests and declare
their source_scope. Old source hashes and snapshots remain unchanged. There was
no Git repository, so revision
is explicitly `not_a_git_repository`, never a fabricated commit hash.
Case hashes include Query, H/completeness, assumptions, provenance and revision.
Volatile run times are outside Case and generated shard config hashes.

Gate A raw runs include LP results, all graph proofs/witnesses, checker results,
cold/warm repetitions, operation counters, public priors/action costs, entire
finite simulator support and action traces. The initial run is retained alongside
the final run; protocol amendments are in pilot-final.yaml. No retuned candidate
or cherry-picked benchmark replaces a negative H3 result.

Scale reports distinguish actual serialized bytes, logical array bytes, allocated
bytes, indexes/checkpoints and source/cache data. Full verification recomputes
all shard SHA256; sample mode explicitly cannot establish full byte verification.
The full streaming scan and its normalized digest are separate from the small
batch of solved Queries. First/repeated process queries have uncontrolled OS
cache; we do not claim true cold-cache measurements without evicting that cache.

Memory is 50-ms sampled sum of coordinator/descendant RSS, excluding OS filesystem
cache. Sampling can miss very brief peaks. Budgets also constrain chunk sizes and
worker counts and are checked between bounded batches. Native allocation inside
a batch cannot be preempted instantaneously. No hard OS job/cgroup limit is claimed.

Codex's restricted Windows sandbox intermittently hung on SciPy native extension
initialization. The same LP and validation ran outside the agent sandbox with
normal local-user runtime. This is distinct from admin privileges or a dependency
on network credentials. OPENBLAS_NUM_THREADS=1 and OMP_NUM_THREADS=1 are used in
validation to control native thread counts. Ordinary CI runs smoke only.

The scale experiment was explicitly paused and resumed by the user. Completed
normalization checkpoints are reused with the same normalization version and
subset digest; source file SHA256 is rechecked. The pre-pause report is retained
in reports/scale/archive. Finalization records both source environments rather
than attributing all accumulated scan time to the latest invocation. Subsequent
UI selection and dry-run report persistence fixes do not change the frozen
Gate A method or the scale data/normalization. See validation XML and history for
separate checks of the final delivery code.
