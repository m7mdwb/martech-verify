## What changed

Describe the user-visible problem and the smallest change that addresses it.

## Evidence

Explain the fixture, counts, or behavior that proves the change is correct. State what the
result still cannot prove.

## Checklist

- [ ] Tests cover the faulty case and a clean case, or this is documentation-only.
- [ ] `python tests/run_all.py` passes.
- [ ] Generated fixtures and README assets are current.
- [ ] Runtime code remains Python 3.9+ standard-library only.
- [ ] No connector, API key, service, or production-system write was added.
- [ ] Examples and fixtures contain no real customer data, credentials, or personal data.
- [ ] Sensitive values remain redacted in text, JSON, locations, examples, and errors.
