# Rails/iD read-only performance baseline — 2026-11-07

This is the bounded observation for [Issue #15](https://github.com/L3Pro/osm-address-import/issues/15), separate from Gate G0 acceptance. No database write, service restart, load test, configuration change, CGImap installation, or production OSM operation occurred.

## Actual request path and runtime

The website's index data layer in `app/assets/javascripts/index/layers/data.js` requests `/api/${OSM.API_VERSION}/map.json?bbox=...`. Rails `config/routes.rb` maps the API `map` resource to `Api::MapsController#show`; that controller performs node, way, relation and tag queries and renders JSON or XML. The local route used below is `/api/0.6/map.json`. This confirms the server path; the exact JavaScript call site in the earlier iD browser observation was not captured. Compose starts `bundle exec rails s`; `RAILS_ENV` and `RACK_ENV` are unset in the container, so Rails uses development mode. `cgimap` was absent from the web container's PATH and no CGImap route was found. The app source recommends considering CGImap for `/map`, but this audit did not install or assess its runtime compatibility.

## Sequential local measurements

All requests used `curl --noproxy '*' --max-redirs 0 --output /dev/null` to host loopback, with no auth token. The boxes come from the sandbox README and contain no published address records. Their approximate areas are 0.039 km² (A) and 0.005 km² (B) at latitude 34.66°. One request completed before the next began.

| Box | Bbox (lon,lat,lon,lat) | Run | Status | Bytes | TTFB s | Total s | Rails completed ms | ActiveRecord ms | Views ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | `135.4988,34.6652,135.5010,34.6670` | 1 | 200 | 336,634 | 5.397 | 5.397 | 5,305 | 3,174.6 | 1,106.3 |
| A | same | 2 | 200 | 336,634 | 1.144 | 1.144 | 1,116 | 185.4 | 668.6 |
| A | same | 3 | 200 | 336,634 | 1.182 | 1.183 | 1,158 | 165.2 | 605.5 |
| B | `135.5026,34.6638,135.5034,34.6645` | 1 | 200 | 72,582 | 0.835 | 0.836 | 818 | 521.6 | 217.4 |
| B | same | 2 | 200 | 72,582 | 0.317 | 0.317 | 300 | 58.3 | 164.5 |

The Rails lines were read from the existing `development.log`; request parameters, IDs and raw objects were omitted. Box A had 477 ActiveRecord queries (227 logged as cached) per request; B had 143 (66 cached). These component timings overlap and do not add to total wall time. No `pg_stat_statements` extension is installed. Relevant `current_nodes_tile_idx` and `current_way_nodes_node_idx` indexes exist. At the snapshot, host load average was 0.12/0.06/0.01 with about 4.2 GiB memory available.

Reproduce a bounded local check only while service health is normal:

```text
curl --silent --show-error --noproxy '*' --max-time 30 --max-redirs 0 --output /dev/null --write-out 'http=%{http_code} remote=%{remote_ip} bytes=%{size_download} ttfb=%{time_starttransfer} total=%{time_total}\n' 'http://127.0.0.1:3002/api/0.6/map.json?bbox=135.4988,34.6652,135.5010,34.6670'
```

## Attribution and follow-up

The local Rails `Completed` durations closely track curl TTFB; the measured local network/transfer contribution is small. The first request to each box was slower, with a large ActiveRecord reduction on repetition, consistent with warm database or application caches but not proof of the precise cause. The prior October 28 browser observation was about 7.96 seconds for approximately 151 KB, including about 7.58 seconds waiting; its exact bbox, Rails request ID, proxy timing and client timing are unavailable here. Remote/browser timing was not repeated during this G0 audit, so proxy and browser contributions remain unknown.

Ranked next observations: (1) correlate a consented remote request with a Rails request ID and tunnel/proxy timing, without exposing addresses or tokens; (2) use existing query logs or an approved disposable replica to inspect the repeated map queries; (3) assess development-mode rendering and asset behavior; (4) evaluate CGImap compatibility, resource use and rollback in a separate proposal. No optimization or routing change is authorized by this baseline.
