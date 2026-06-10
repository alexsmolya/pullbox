# pullbox-data Contract Fixtures

These fixtures capture the `pullbox-data` release summary contract that Pullbox consumes for PD-6.

The current-week fixture mirrors `GET /api/v1/releases`. The upcoming fixture mirrors `GET /api/v1/releases?upcoming=true`.

Pullbox intentionally depends on these summary fields in v1:

- `locg_issue_id`, `locg_series_id`, and `locg_url`
- title, display title, issue number, cover URL, price, currency, store date, variant count
- community rating and community counts
- nested publisher name and LOCG publisher ID
- nested series title, LOCG series ID, LOCG URL, start year, and volume
- upcoming week grouping through `weeks` and `lookahead_weeks`

Release summaries do not include ComicVine, Metron, or GCD identifiers. Those richer identifiers are available from detail endpoints upstream, but PD-6 v1 is read-only and should not require them.
