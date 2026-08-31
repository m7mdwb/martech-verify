# Preparing a PII scan export

Use a local export that contains the values actually sent to analytics. Do not paste raw
URLs containing customer data into chat; let the bundled scanner read the local file and
return only redacted examples.

## Best input

- CSV or TSV with one page view or event per row and the full URL/query string in a column
  such as `page_location`, `url`, `request` or `request_uri`.
- JSON Lines from a warehouse export. Each non-empty line must be one JSON object.
- A server access log, or a plain text file with one URL per line.

For CSV, this is enough:

```csv
date,page_location
2026-08-01,https://shop.test/pricing?utm_source=google
2026-08-01,https://shop.test/contact?email=customer%40mail.test
```

Keep URL query strings and paths intact. Aggregating URLs, stripping parameters, or
exporting only page titles removes the evidence this scanner needs.

## Where to obtain it

- **GA4:** export Pages and screens or an Explore containing page location/path and any
  event-parameter values you want checked.
- **GA4 BigQuery:** export rows containing `page_location` and relevant event parameters as
  CSV or JSON Lines.
- **Server/CDN logs:** include the request path and query string.
- **Tag-manager preview:** export or copy the resolved URL/event values, not only tag names.

The result covers only the supplied period and fields. A clean month-long page-location
export does not prove that every event parameter or historical period is clean.
