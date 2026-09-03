# China Holiday Calendar

This repository scrapes the official State Council holiday notices for a rolling three-year window and publishes:

- nine ICS calendars in `zh-CN`, `en`, and `ru`
- a multilingual static JSON feed under `data/`
- localized static JSON feeds under `data/zh-CN/`, `data/en/`, and `data/ru/`
- source metadata in `calendars/metadata.json`

The generator includes `execution year - 1` through `execution year + 1` when the official notices are available.

## ICS feeds

### Chinese

- Holiday and compensate days: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/zh-CN/holiday-and-compensate.ics)
- Holidays only: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/zh-CN/holidays-only.ics)
- Compensate working days only: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/zh-CN/compensate-working-days-only.ics)

### English

- Holiday and compensate days: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/en/holiday-and-compensate.ics)
- Holidays only: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/en/holidays-only.ics)
- Compensate working days only: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/en/compensate-working-days-only.ics)

### Russian

- Holiday and compensate days: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/ru/holiday-and-compensate.ics)
- Holidays only: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/ru/holidays-only.ics)
- Compensate working days only: [Subscribe](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/calendars/ru/compensate-working-days-only.ics)

Use the raw GitHub URLs above in any calendar app that supports subscribing to an ICS feed.

## JSON feeds

### Multilingual

- Rolling window feed: [data/latest.json](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/data/latest.json)
- Per-year feed example: [data/years/2026.json](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/data/years/2026.json)

### Localized

- Chinese latest: [data/zh-CN/latest.json](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/data/zh-CN/latest.json)
- English latest: [data/en/latest.json](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/data/en/latest.json)
- Russian latest: [data/ru/latest.json](https://raw.githubusercontent.com/HankAviator/china-holiday-calendar/master/data/ru/latest.json)
- Per-year localized feeds follow the same pattern, for example `data/zh-CN/years/2026.json`, `data/en/years/2026.json`, and `data/ru/years/2026.json`.

Each JSON feed includes:

- notice source metadata
- normalized holiday arrangements with full holiday ranges and compensated working day ranges
- a flat day-by-day list for easy machine consumption

The top-level `data/latest.json` is multilingual. The localized feeds flatten the same data into the selected language.

## Feed behavior

Each generated feed:

- uses the official holiday arrangement notices published by the State Council
- automatically rechecks the rolling three-year window
- merges consecutive holiday dates into a single arrangement range
- preserves compensated working days separately
- is regenerated every 3 hours by GitHub Actions

GitHub Actions runs inside a prebuilt GitHub Container Registry image with Python, Playwright, and Chromium already installed. The workflows serialize scheduled updates and enforce a 10-minute timeout.

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
PYTHONPATH=src python -m china_holiday_calendar --output-dir calendars --data-output-dir data
```

`--year` is the anchor year. For example, `--year 2026` tries to include 2025, 2026, and 2027 if their official notices are available.

## Automation image

Scheduled updates use `ghcr.io/hankaviator/china-holiday-calendar-runner:latest`. Rebuild it by running the `Build Calendar Runner Image` workflow, or let it refresh automatically when `requirements.txt`, `.github/docker/calendar-runner/Dockerfile`, or the image workflow changes on `master`.
