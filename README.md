# China Holiday Calendar

This repository scrapes the latest official State Council holiday notice for mainland China and publishes six ICS calendars:

- `calendars/zh-CN/holiday-and-compensate.ics`
- `calendars/zh-CN/holidays-only.ics`
- `calendars/zh-CN/compensate-working-days-only.ics`
- `calendars/en/holiday-and-compensate.ics`
- `calendars/en/holidays-only.ics`
- `calendars/en/compensate-working-days-only.ics`

Each calendar:

- uses the official holiday arrangement notice published by the State Council,
- merges consecutive dates into a single all-day event,
- includes the relevant announcement line in each event description,
- is regenerated every 12 hours by GitHub Actions.

## Local usage

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
PYTHONPATH=src python -m china_holiday_calendar
```

Optional flags:

```bash
PYTHONPATH=src python -m china_holiday_calendar --year 2026
PYTHONPATH=src python -m china_holiday_calendar --notice-url https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm
PYTHONPATH=src python -m china_holiday_calendar --output-dir calendars
```

The generator writes metadata to `calendars/metadata.json`.
