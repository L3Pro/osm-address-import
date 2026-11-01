# Security policy

This is pre-production planning software. There is no supported live-upload service or production editing capability.

## Report security concerns

Please do **not** publish access tokens, credentials, non-public address data or exploitable details in public issues. Contact the repository owner privately through GitHub (or use GitHub's private vulnerability-reporting feature if it is enabled). No guaranteed SLA is offered yet.

## Never commit

OSM OAuth tokens, passwords, private keys, dotenv configuration with secrets, database dumps, private access details, large NAD/OSM datasets, or employer-restricted code.

## Safe defaults

Automated tests are local and must not contact the OSM production API. Source and import rights must be checked separately. Future upload functionality requires an explicit threat model, authentication and production authorization review.
