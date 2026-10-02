# heat-ready-clients

Python and R client packages for the [HeatReady API](https://nishantkishore.com/workshop/api) — a
climate-data API that turns global reanalysis and satellite data into neighborhood-resolution heat-risk
metrics for disaster responders.

The HeatReady API is a single-endpoint action router (every request is a `POST` to `/evaluate` with an
`action` field selecting the operation). These packages wrap that envelope into ordinary function/method
calls in each language, so you write `client.list_projects()` instead of building the request body by hand.

- **[`python/`](python/)** — the `heatready` Python package
- **[`r/`](r/)** — the `heatready` R package
- **[`docs/quickstart.md`](docs/quickstart.md)** — a single walkthrough covering both languages, using the
  live public project `nyc-manhattan-brooklyn-2026`
- **[`walkthrough/`](walkthrough/)** — the workshop walkthrough: the analyses from the HeatReady
  presentation in Python and R, from one hot day to a project of your own

## Install

```bash
# Python
pip install "git+https://github.com/crisisready/heat-ready-clients.git#subdirectory=python"
```

```r
# R
remotes::install_github("crisisready/heat-ready-clients", subdir = "r")
```

## Getting an API key

At a workshop, claim one at [nishantkishore.com/workshop](https://nishantkishore.com/workshop). Otherwise,
contact [datascience_crisisready@harvard.edu](mailto:datascience_crisisready@harvard.edu), or redeem an
invite code if one was issued to you (see [Credential setup](docs/quickstart.md#credential-setup) in the
quick-start guide).

## Full API reference

Both packages are thin wrappers — for the authoritative per-action documentation (payload fields, response
shapes, rate limits, and the access-control model), see the
[HeatReady API reference](https://nishantkishore.com/workshop/api). The API does not return a project's boundaries once it has been
created. Boundary files for the public projects are linked from step 7 of the
[workshop walkthrough](https://nishantkishore.com/workshop/walkthrough#try-another-city).

## License

Apache-2.0 — see [LICENSE](LICENSE). Note this covers the client code here; use of the hosted HeatReady API
itself is governed separately by its own Terms of Use.
