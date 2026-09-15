# FRED Macro Dashboard

Modular US macro dashboard built on FRED data. The same Python modules drive both:

- **Streamlit** — production dashboard interface (`app.py`)
- **Google Colab** — research / testing notebooks (`notebooks/`)

`core/` and `sections/` are the single source of truth. Neither imports Streamlit, so they run identically in both environments.

## Layout

```
fred_macro/
├── core/
│   ├── config.py         # key loading + defaults
│   ├── fred_client.py    # cached FRED fetcher
│   ├── bls_client.py     # cached BLS API fetcher (CPI relative-importance weights)
│   ├── bea_client.py     # cached BEA API fetcher (monthly PCE detail, tables 2.4.4U/2.4.5U)
│   ├── inflation_tables.py # CPI/PCE monthly breakdown tables (calc + Styler formatting)
│   ├── transforms.py     # diff, rolling MA, diffusion index, cyclical split
│   └── plotting.py       # layout helpers + grid builder
├── sections/
│   └── labor.py          # NFP, claims, JOLTS, diffusion, cyclical view
├── notebooks/
│   ├── labor.ipynb       # Colab workbench mirroring sections/labor.py
│   ├── inflation.ipynb
│   └── income.ipynb
├── app.py                # Streamlit entry
├── .streamlit/secrets.toml  # FRED_API_KEY + BLS_API_KEY (gitignored)
└── requirements.txt
```

## Local setup

```bash
pip install -r requirements.txt
pip install -e .          # makes `from core...` and `from sections...` work everywhere
streamlit run app.py
```

## Colab setup

In the first cell of any notebook:

```python
!git clone <your-repo-url> /content/fred_macro
%cd /content/fred_macro
!pip install -q -e .
import os
os.environ["FRED_API_KEY"] = "your_key_here"   # or use Colab user secrets
os.environ["BLS_API_KEY"] = "your_key_here"    # needed for the CPI contribution chart
```

## API key resolution order

`core.config.get_fred_key()`, `get_bls_key()` and `get_bea_key()` try, in order:

1. `st.secrets["FRED_API_KEY"]` / `st.secrets["BLS_API_KEY"]` (when running under Streamlit)
2. `os.environ[...]`
3. `.env` file in the project root (via `python-dotenv`)

The BLS key (free, https://data.bls.gov/registrationEngine/) is only needed for the
CPI contribution chart, which uses BLS relative-importance weights that FRED does not carry.
If it is missing, that one chart shows a warning and the rest of the Inflation tab still renders.
The BEA key (free, https://apps.bea.gov/API/signup/) is only needed for the PCE monthly breakdown table.

## Notebook code export ("</> Code")

Every chart and table has a `</> Code` popover with a short notebook snippet
that reproduces its data with the shared `core/` and `sections/` functions,
plus a "Download all notebook snippets" button in the sidebar. Both come from
one registry, `core/chart_code_registry.py`. To add a chart to the export,
add one `_add("<section>_<entry id>", ...)` entry there — `app.py` looks it
up by the chart's `id` in `sections/<x>.build()`; a missing entry only logs a
warning. `tests/test_chart_code.py` fails if a rendered chart has no entry.

## Adding a new section

1. Create `sections/<name>.py` with chart functions returning `go.Figure` and a `build()` function returning the section dict.
2. Add a tab in `app.py`.
3. Create `notebooks/<name>.ipynb` as a research mirror.

Keep `streamlit` imports out of `core/` and `sections/`. If you need Streamlit-specific caching, wrap calls in `app.py`.
