# Issue #15: Rails map endpoint mode comparison

**2026-11-08 CST (2026-11-09 UTC). Investigation only; no deployment.** The existing Osaka services were not modified, restarted, or reconfigured. No API writes, CGImap installation, remote OSM requests, raw map output, credentials, or private configuration were committed.

## What was measured

The website data layer requests `/api/0.6/map.json?bbox=...`; the app routes this to `Api::MapsController#show`. The existing Osaka Rails process runs in development mode. Its API database has PostgreSQL 14.23, the usual current-node and way-node indexes, and no `pg_stat_statements` extension. CGImap is absent from the current web container. The earlier October browser observation of about 7.96 seconds for an approximately 151 KB response lacks a matching bbox and server request ID, so this report cannot attribute its remote/proxy portion.

Two modest boxes from the sandbox's existing public test instructions were used. Every request was an unauthenticated, sequential GET to local loopback from the relevant service, with proxies bypassed, redirects disabled, response body discarded, and a 30-second timeout. The same URL, GET method, JSON format, boxes, and limits were used for development and production modes. Box A was `135.4988,34.6652,135.5010,34.6670` (336,634 bytes); Box B was `135.5026,34.6638,135.5034,34.6645` (72,582 bytes). Every measured response was HTTP 200 with no redirect. Box A response digests matched byte-for-byte across the existing Osaka service and both disposable Rails modes. No raw address objects were retained in this repository.

The first disposable map request is called **first-request**, not a fully cold database benchmark. Development mode ran before production against the same restored database, so production inherited a warmer PostgreSQL/OS page cache. A later development restart checked warm order effects. TTFB and total are `curl` measurements; Rails, ActiveRecord and view times come from the matching Rails completion lines. ActiveRecord time includes cached-query bookkeeping and overlaps with request/view timing, so components must not be added together. CPU is the change in container cgroup `usage_usec` over a separate three-request warm Box A sample; memory is a post-request `docker stats` snapshot, not a peak.

The bounded request shape, executed inside each disposable web container (or on the existing service's loopback port), was:

```sh
curl --silent --show-error --noproxy '*' --max-time 30 --max-redirs 0 \
  --output /dev/null \
  --write-out 'http=%{http_code} bytes=%{size_download} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  'http://127.0.0.1:3000/api/0.6/map.json?bbox=135.4988,34.6652,135.5010,34.6670'
```

Requests were run sequentially, not as a load test. CPU counters were read from `/sys/fs/cgroup/cpu.stat` immediately before and after a separate three-request series; memory was read with `docker stats --no-stream`. Only Rails `Completed` summary lines were used for the public timing table.

## Isolation and configuration

A separate disposable Compose project used a clean, pinned Rails source export, a separately copied historical archive, independent database and Rails secrets, a dedicated PostgreSQL database, project-only volumes, an internal isolated-gateway network, no host ports, no proxy environment, and caps of 1.5 GiB/1.5 CPUs for PostgreSQL and 1 GiB/1 CPU for one active Rails process. The archive restored to the historical counts (1,865,417 nodes, 364,224 ways, 4,350 relations, 1,146,857 way tags). Restored OAuth application and token rows were removed **only in the disposable database** before Rails startup. A separate application role had SELECT but no INSERT on current nodes and default read-only transactions. The copied app used API read-only status and disabled outgoing mail.

Both disposable Rails modes used the same source, image, database, request path, local network, and process limits. Production mode set `RAILS_ENV` and `RACK_ENV` to `production`, used a generated disposable secret key, and in the copied production configuration disabled HTTPS assumption/redirect for isolated HTTP loopback testing and disabled mail delivery. The upstream production configuration otherwise retained eager loading and no code reloading; development retained reloading, verbose query logs, SQL query tags, view filename annotations, and disabled controller caching. No production assets were precompiled because only the API map route was tested. Full editor deployment would require asset and browser checks and an app-server review.

## Results

The previously recorded read-only Osaka Box A baseline was 5.397 seconds on its first request and 1.144/1.183 seconds warm for 336,634 bytes. This session's already-running Osaka process returned Box A in 1.109, 1.069, and 1.006 seconds. The recorded 5.397-second first-request result was **not reproduced on the already-warm existing process**; the fresh disposable development process showed the same first-request slowdown at 4.155 seconds.

| Environment / box | Run | TTFB s | Total s | Rails ms | ActiveRecord ms | Views ms | Queries (cached) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Disposable development A | first | 4.155 | 4.155 | 4,114 | 1,734.3 | 1,066.6 | 477 (227) |
| Disposable development A | warm 1 | 1.148 | 1.148 | 1,118 | 178.7 | 621.1 | 477 (227) |
| Disposable development A | warm 2 | 1.051 | 1.051 | 1,027 | 181.5 | 654.0 | 477 (227) |
| Disposable production A | first | 1.667 | 1.667 | 1,660 | 167.4 | 890.8 | 477 (227) |
| Disposable production A | warm 1 | 0.796 | 0.796 | 785 | 121.1 | 364.1 | 477 (227) |
| Disposable production A | warm 2 | 0.668 | 0.669 | 662 | 114.0 | 343.4 | 477 (227) |
| Disposable development B | first | 0.687 | 0.688 | 669 | 281.0 | 268.5 | 143 (66) |
| Disposable development B | warm | 0.409 | 0.409 | 387 | 61.0 | 163.9 | 143 (66) |
| Disposable production B | first | 0.189 | 0.189 | 184 | 34.3 | 114.9 | 143 (66) |
| Disposable production B | next | 0.310 | 0.310 | 306 | 35.2 | 233.1 | 143 (66) |

Warm Box A mean: development **1.099 s**, production **0.732 s**, an observed **33% lower latency**. In the reverse-order development restart, three Box A requests were 1.315, 0.987 and 1.015 seconds, confirming that development remained around one second after the database had been warmed by production. A separate three-request warm CPU sample used 2.972 CPU-seconds in development Rails plus 0.562 in PostgreSQL, versus 2.036 plus 0.318 in production; this is about **31% less Rails CPU** over that sample. Post-request Rails memory snapshots were 453–523 MiB in development and 314 MiB in production; the disposable database was about 725 MiB. These are short-run observations, not concurrency, peak-memory, or leak tests.

Local TTFB and total differed by less than 1 ms for the map requests. Rails completion time was close to TTFB. This places the measured delay in Rails/SQL/rendering, rather than local transfer. The persistent 477-query Box A count and production's roughly 0.34–0.36-second warm view time show that production mode removes development overhead but does not eliminate map serialization work. The first-request difference cannot be attributed entirely to Rails mode because cache warmth differed. No browser, tunnel, or remote route timing was collected in this round.

## CGImap fit and recommendation

[Upstream CGImap documentation](https://github.com/zerebubuth/openstreetmap-cgimap/blob/master/README) describes a FastCGI implementation of the OSM `/map` endpoint backed by PostgreSQL APIDB, with a minimum PostgreSQL version below this database's 14.23. Its [map handler](https://github.com/zerebubuth/openstreetmap-cgimap/blob/master/src/api06/map_handler.cpp) uses bbox selection and the shared response-format abstraction. The existing Rails database has the current OSM tables and indexes CGImap would plausibly use, and the iD request is `/api/0.6/map.json`. This is **plausible compatibility, not a verified installation**. Exact schema revision, JSON parity, error responses, authentication/CORS behavior, read-only DB privileges, and route handoff would need a separate isolated prototype. CGImap also needs a FastCGI-capable proxy and a separate process; it must not receive write routes as a side effect of `/map` acceleration.

**Recommendation:** review a production-mode Rails configuration as the first architecture change. It gave a measurable one-third warm Box A improvement and lower Rails memory with the same response bytes and no new API service or routing layer. It is sufficient for a first, low-complexity performance step for these modest single-request boxes, subject to full editor/assets, authentication, process-manager, remote-route, and sustained-load review. Do not implement CGImap yet. If an agreed editor latency target is below the roughly 0.7-second warm Box A result, or concurrency/memory growth remains unacceptable, prototype CGImap separately with a read-only role and route-specific parity tests. [Upstream Rails production notes](https://github.com/openstreetmap/openstreetmap-website/blob/master/doc/INSTALL.md) also caution against treating `rails server` as a final production deployment method; this run compares Rails modes, not web-server architecture.

## Review and rollback boundary

No performance setting was deployed to Osaka. A future reviewed change should first pin its current config/image and aggregate DB counts, build the production app alongside the old service with generated local secrets and precompiled assets, verify `/api/0.6/map.json` response parity plus login/editor flows, and define a latency/error/memory stop threshold. Only after separate approval should routing change. Rollback is to restore the prior route/container configuration and stop the candidate; no database migration or OSM data change is part of this proposal. CGImap would require its own route-level rollback, privilege audit, and write-endpoint exclusion.

For this investigation, the disposable Compose project was removed after label/mount/network ownership checks: three containers, five named volumes, and one internal network. Its staging copy, archive, logs, and generated credentials were deleted. Label-filtered queries found no remaining disposable resources. Osaka `web` remained running and `db` healthy. Its aggregate counts were unchanged before and after (1,865,425 nodes, 364,226 ways, 4,350 relations, 1,146,865 way tags), its loopback capabilities read returned 200, and the original archive checksum was unchanged.
