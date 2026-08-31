# Preparing a UTM audit export

The linter needs the complete URLs people clicked or landed on, including their query
strings. It does not need access to the advertising or analytics account.

## Best input

- CSV or TSV with one URL per row in a column such as `url`, `page_location`,
  `landing_page` or `link`.
- JSON Lines, a server log, or a plain text file with one complete URL per line.

For CSV, this is enough:

```csv
date,url
2026-08-01,https://shop.test/pricing?utm_source=linkedin&utm_medium=paid_social&utm_campaign=q3-demand
2026-08-02,https://shop.test/demo?utm_source=email&utm_medium=email&utm_campaign=august-demo
```

Do not export only the already-parsed source/medium report: it can hide duplicate
parameters, whitespace, click IDs and internal campaign tags. Preserve the original URL.

## Useful sources

- Landing-page or page-location exports from analytics.
- Final-URL/link exports from ad, email and social platforms.
- Server access logs when redirects may be changing tags.
- A campaign spreadsheet containing the final links that were actually shipped.

Provide the organization's own domain when possible so `--site` can identify internal
links incorrectly tagged as campaigns. A clean result covers only the supplied URL corpus;
it does not prove that every live creative or historical link follows the taxonomy.
