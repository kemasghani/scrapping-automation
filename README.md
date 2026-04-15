# GrabFood Menu Scraper

Setup:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Run:

```bash
python scraper.py
python scraper.py "<grabfood_url>"
python scraper.py --headful
python scraper.py --from-raw out/raw_<ts>.json
```

Output: `out/<merchant>_menu.xlsx` (sheets: Summary, Merchant, Menu, Modifiers, Promotions, Dietary, Field Guide).
