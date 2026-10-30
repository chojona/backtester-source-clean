# Source export boundary

Only reviewed source, dependency metadata, empty configuration templates, and tests with constructed inputs belong in this repository. The repository starts with a new root commit and has no parent history, imported branches, tags, pull requests, or copied Git objects.

Do not import historical workflow modules: source code can itself embed observed quotes, provider metadata, or fitted coefficients. Generated fixtures and reports also stay outside Git, including synthetic output files.

The original repository is not sanitized by this export. Review every future change against this boundary before pushing. Ignore rules do not protect files already tracked or files added with force.
