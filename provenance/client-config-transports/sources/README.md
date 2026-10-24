# Preserved client source inputs

These are **unmodified original Git blob bytes** selected from the revisions in
`../source-manifest.json`. The source and original license/notice files are
preserved locally so these fixture checks do not require the upstream repositories
or pull requests to remain available. Git itself is not required to run the checks.
This is the import/bundle closure of the exercised adapters, not complete copies
of Aider, Continue, or Cline, and not an installed editor/application distribution.

The authorship and licensing of these sources remain with their original authors.
Each retained file records its source URL, Git blob identity, SHA-256 and byte
length. Original license text is kept in each repository directory. Our fixture
scripts execute the selected adapters; generated JavaScript bundles are local
test artifacts, not redistributed upstream application builds.

Python/npm dependencies remain separately installed from the committed locks.
In particular, Zod is not vendored: the schema build resolves the lockfile's
Continue-specific version. Source-hash verification runs before Aider imports
and before JavaScript bundling.
