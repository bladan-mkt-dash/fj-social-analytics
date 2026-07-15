# FJ Social Analytics

Five Journeys Meta organic analytics — Facebook & Instagram trends and top organic posts by views.

## Run locally

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then fill in secrets locally — never commit .env

streamlit run meta_organic_trends_report.py --server.port 8856
```

Open: http://127.0.0.1:8856/

## What it shows

- Monthly Facebook & Instagram trends (views, reach, followers, interactions, new followers) from Cross-Channel Tracker Google Sheets (2023–present)
- Top 5 all-time organic posts by views per platform (boosted/paid creatives excluded)

## Secrets (keep private)

Do **not** commit:

- `.env` (Meta tokens, ad account id)
- Google Sheets OAuth token at `~/.config/mcp-google-sheets/token.json`

Use `.env.example` as a template for required variable names only.
