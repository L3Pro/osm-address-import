# Contributing

Contributions are welcome, especially reproducible tests, source-provenance analysis, regional address knowledge, conflation QA and community outreach suggestions.

1. Read [Master Plan](docs/MASTER_PLAN.md), [Class A rules](docs/CLASS_A_RULES.md), and [QA gates](docs/QA_PLAN.md).
2. Open or comment on a GitHub issue before significant changes. Keep pull requests small and tied to an acceptance test.
3. Prefer synthetic/licensed fixtures and deterministic output. Explain uncertainty, rejected cases and the impact on existing OSM contributions.
4. Run: python -m unittest discover -s tests -v.
5. Do not include real-world bulk address datasets, personal data, secrets, employer-restricted code, or credentials.
6. Never submit OSM production edits as part of a code contribution or test run. Only the OSM community-approved workflow may ever authorize such edits.

Use respectful communication, acknowledge corrections and raise safety/ethics concerns early. For vulnerabilities, follow [SECURITY.md](SECURITY.md).
