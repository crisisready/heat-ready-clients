# Workshop walkthrough

The analyses from the HeatReady presentation, step by step, in Python and R, on the census tracts of
Manhattan and Brooklyn. It ends with bringing in your own data and creating a project of your own.

- Read it on the web, with Python and R side by side: [nishantkishore.com/workshop/walkthrough](https://nishantkishore.com/workshop/walkthrough)
- Run it in Jupyter: [`python/heatready-walkthrough.ipynb`](python/heatready-walkthrough.ipynb)
- Run it in RStudio: [`r/heatready-walkthrough.Rmd`](r/heatready-walkthrough.Rmd)
- Read it here: [`walkthrough.md`](walkthrough.md)

You need a HeatReady key. At a workshop, claim one at [nishantkishore.com/workshop](https://nishantkishore.com/workshop).

## Data files

- `data/nyc-tracts.geojson`: the 1,114 census tracts of the `nyc-manhattan-brooklyn-2026` project,
  with each tract's API name, 2020 GEOID, borough, and Neighborhood Tabulation Area name (NYC Open
  Data, [2020 Census Tracts to 2020 NTAs](https://data.cityofnewyork.us/d/hm78-6dwm)).
  Coordinates rounded to 5 decimal places.
- `data/nyc-older-adult-centers.csv`: the 301 older adult centers in NYC Aging's
  [list of providers with sites open to the public](https://data.cityofnewyork.us/d/u7wp-np5k),
  copied on 30 September 2026.

`figures/` holds the three maps from the Python run, shown in `walkthrough.md` and on the web page as
the result to expect. Redraw them after a change that alters a map.

## Editing

`walkthrough.md` is the one source. After changing it, run `python3 walkthrough/build.py` to rewrite
the notebook, the R Markdown file, and `walkthrough.json` (read by the web page).
`python3 walkthrough/build.py --check` fails when they are out of date.

To test against the live API, set `HEATREADY_USERNAME` and `HEATREADY_KEY` and run
`python3 walkthrough/build.py --run py` or `--run r`. Step 6 creates a project called
`my-first-project` and the script deletes it afterwards; add `--skip-create` to stop before step 6.
The Python run needs `jupyter nbconvert`; the R run needs `knitr`.
