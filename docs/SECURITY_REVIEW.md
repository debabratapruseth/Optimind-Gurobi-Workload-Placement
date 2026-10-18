# Security and publication review

Reviewed 18 October 2026 for the selected research release. The review covers the exact publication file list, not all local files or historical Git objects. The release commit builds on the remote's LICENSE-only initial commit; old local publication commits are not ancestors of this release.

The selected files include source, configuration, notebook, documentation, tests/fixtures and the reviewed synthetic AI example. Explicit selection excludes local environments, caches, results/, raw runtime logs, personal research archives, credentials, tokens, license files and model weights. Pattern checks found no credential values, personal absolute paths or GPU hardware identifiers in the selected files. Notebook outputs are empty. A pattern scan is not a comprehensive security audit.

The public example's integrity manifest and its unchanged copies were verified against the original downloaded run. Its metadata describes the limitations: the original runtime/test receipt is absent, and the public subset omits raw prompts/responses, hardware records and original input snapshots. The included structured problem contains realized input values. Original downloaded and historical research evidence remains local and unchanged.

Generated Python is never executed. AI mode accepts a bounded data specification, compiles trusted code, and fails closed on invalid identities, incomplete equivalence checks or invalid placements. The public pipeline cannot silently switch from AI to reference mode.

No selected-file secret or privacy blocker was identified. Production hardening, a comprehensive dependency vulnerability audit, live provider validation and commercial licensing eligibility are not certified. See the [scoped third-party review](../LICENSE_REVIEW_REQUIRED.md). Future runtime outputs must be reviewed separately before sharing.
