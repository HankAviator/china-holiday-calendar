from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


USER_AGENT = (
    "Mozilla/5.0 (compatible; china-holiday-calendar/1.0; "
    "+https://github.com/)"
)
NOTICE_TITLE_TEMPLATE_ZH = "国务院办公厅关于{year}年部分节假日安排的通知"
NOTICE_TITLE_TEMPLATE_EN = (
    "General Office of the State Council Notice on the {year} Public Holiday Arrangements"
)
KNOWN_NOTICE_URLS = {
    2025: "https://www.gov.cn/zhengce/zhengceku/202411/content_6986383.htm",
    2026: "https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm",
}
HOLIDAY_NAME_TRANSLATIONS = {
    "元旦": "New Year's Day",
    "春节": "Spring Festival",
    "清明节": "Qingming Festival",
    "劳动节": "Labour Day",
    "端午节": "Dragon Boat Festival",
    "中秋节": "Mid-Autumn Festival",
    "国庆节": "National Day",
}
DATE_RE = re.compile(
    r"(?:(?P<year>\d{4})年)?(?:(?P<month>\d{1,2})月)?(?P<day>\d{1,2})日"
)
BULLET_RE = re.compile(
    r"^(?P<ordinal>[一二三四五六七八九十]+)、(?P<name>[^：:]+)[：:](?P<body>.+)$"
)
PUBLISHED_RE = re.compile(r"发布日期[:：]\s*(\d{4})年(\d{1,2})月(\d{1,2})日")


@dataclass(frozen=True)
class NoticeLine:
    ordinal_zh: str
    holiday_name_zh: str
    holiday_name_en: str
    line_zh: str
    line_en: str
    holiday_dates: tuple[date, ...]
    workday_dates: tuple[date, ...]


@dataclass(frozen=True)
class Notice:
    holiday_year: int
    title_zh: str
    title_en: str
    source_url: str
    published_at: date
    lines: tuple[NoticeLine, ...]


@dataclass(frozen=True)
class CalendarEvent:
    start: date
    end: date
    summary: str
    description: str
    uid_seed: str


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT})
        notices = fetch_notices(session, args.year, args.notice_url)

    write_calendars(notices, output_dir)
    write_metadata(notices, output_dir)
    return 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate China holiday ICS calendars from the official State Council notice."
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Anchor year for the output window. The generator fetches anchor year - 1 through anchor year + 1.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("calendars"),
        help="Directory where ICS files and metadata are written.",
    )
    parser.add_argument(
        "--notice-url",
        help="Explicit official notice URL to use instead of automatic discovery.",
    )
    return parser.parse_args(argv)


def fetch_notices(
    session: requests.Session,
    requested_year: int | None,
    notice_url: str | None,
) -> tuple[Notice, ...]:
    if notice_url:
        return (parse_notice_page(session, notice_url, requested_year),)

    anchor_year = requested_year or datetime.now(timezone.utc).year
    target_years = [anchor_year - 1, anchor_year, anchor_year + 1]
    notices: list[Notice] = []

    for year in target_years:
        try:
            url = discover_notice_url(session, year)
            notices.append(parse_notice_page(session, url, year))
        except Exception:
            continue

    if not notices:
        raise RuntimeError("Unable to discover any official holiday notices for the requested window.")
    return tuple(sorted(notices, key=lambda notice: notice.holiday_year))


def discover_notice_url(session: requests.Session, year: int) -> str:
    title = NOTICE_TITLE_TEMPLATE_ZH.format(year=year)
    known_url = KNOWN_NOTICE_URLS.get(year)
    if known_url and notice_page_matches(session, known_url, title):
        return known_url

    query = f"site:gov.cn {title}"
    candidates = discover_notice_urls(session, query)

    for candidate in candidates:
        if notice_page_matches(session, candidate, title):
            return candidate

    raise RuntimeError(f"Could not find an official notice URL for {year}.")


def discover_notice_urls(session: requests.Session, query: str) -> list[str]:
    candidates = discover_notice_urls_with_bing_html(session, query)
    if candidates:
        return candidates
    return discover_notice_urls_with_playwright(query)


def discover_notice_urls_with_bing_html(session: requests.Session, query: str) -> list[str]:
    response = session.get(
        "https://cn.bing.com/search",
        params={"q": query, "rdr": "1", "mkt": "zh-CN"},
        headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    candidates: list[str] = []
    for anchor in soup.select("main a[href], #b_results a[href]"):
        href = anchor.get("href", "")
        if href.startswith("https://www.gov.cn/zhengce/zhengceku/") and "content_" in href:
            candidates.append(href)

    if not candidates:
        candidates = re.findall(
            r"https://www\.gov\.cn/zhengce/zhengceku/\d+/content_\d+\.htm",
            response.text,
        )

    return dedupe(candidates)


def discover_notice_urls_with_playwright(query: str) -> list[str]:
    search_url = f"https://cn.bing.com/search?q={quote_plus(query)}&rdr=1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="zh-CN")
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("main, #b_results", timeout=15000)
            page.wait_for_timeout(1500)
            urls = page.locator(
                "main a[href^='https://www.gov.cn/zhengce/zhengceku/'][href*='content_'], "
                "#b_results a[href^='https://www.gov.cn/zhengce/zhengceku/'][href*='content_']"
            ).evaluate_all("elements => elements.map(element => element.href)")
            return dedupe(urls)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Timed out while discovering the official notice URL.") from exc
        finally:
            browser.close()


def infer_holiday_year_from_page(soup: BeautifulSoup) -> int:
    page_text = normalize_text(soup.get_text(" ", strip=True))
    match = re.search(r"关于(\d{4})年部分节假日安排的通知", page_text)
    if match:
        return int(match.group(1))
    raise RuntimeError("Could not infer the holiday year from the official notice page.")


def notice_page_matches(session: requests.Session, url: str, expected_title: str) -> bool:
    soup = fetch_html_soup(session, url)
    title = normalize_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    if expected_title in title:
        return True

    body_text = normalize_text(soup.get_text(" ", strip=True))
    return expected_title in body_text


def parse_notice_page(session: requests.Session, url: str, holiday_year: int | None) -> Notice:
    soup = fetch_html_soup(session, url)

    resolved_year = holiday_year or infer_holiday_year_from_page(soup)
    title_zh = NOTICE_TITLE_TEMPLATE_ZH.format(year=resolved_year)
    title_en = NOTICE_TITLE_TEMPLATE_EN.format(year=resolved_year)
    published_at = parse_published_date(soup)
    content_root = find_content_root(soup)
    paragraphs = [
        normalize_text(paragraph.get_text(" ", strip=True))
        for paragraph in content_root.select("p")
        if normalize_text(paragraph.get_text(" ", strip=True))
    ]

    lines = tuple(
        parse_notice_line(paragraph, resolved_year, index)
        for index, paragraph in enumerate(paragraphs)
        if BULLET_RE.match(paragraph)
    )
    if not lines:
        raise RuntimeError("No holiday arrangement lines were found in the official notice.")

    return Notice(
        holiday_year=resolved_year,
        title_zh=title_zh,
        title_en=title_en,
        source_url=url,
        published_at=published_at,
        lines=lines,
    )


def fetch_html_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def parse_published_date(soup: BeautifulSoup) -> date:
    page_text = normalize_text(soup.get_text(" ", strip=True))
    match = PUBLISHED_RE.search(page_text)
    if not match:
        raise RuntimeError("Could not find the notice publication date.")
    year, month, day = (int(value) for value in match.groups())
    return date(year, month, day)


def find_content_root(soup: BeautifulSoup) -> BeautifulSoup:
    for selector in (
        "#UCAP-CONTENT .trs_editor_view",
        ".pages_content .trs_editor_view",
        ".trs_editor_view",
    ):
        node = soup.select_one(selector)
        if node is not None:
            return node
    raise RuntimeError("Could not find the official notice article body.")


def parse_notice_line(line_zh: str, holiday_year: int, index: int) -> NoticeLine:
    match = BULLET_RE.match(line_zh)
    if not match:
        raise ValueError(f"Invalid notice line: {line_zh}")

    holiday_name_zh = normalize_text(match.group("name"))
    body_zh = normalize_text(match.group("body"))
    holiday_dates = tuple(parse_holiday_dates(body_zh, holiday_year, holiday_name_zh, index))
    workday_dates = tuple(parse_workday_dates(body_zh, holiday_year, holiday_name_zh, index))
    holiday_name_en = translate_holiday_name(holiday_name_zh)
    line_en = build_english_line(holiday_name_en, holiday_dates, workday_dates)

    return NoticeLine(
        ordinal_zh=match.group("ordinal"),
        holiday_name_zh=holiday_name_zh,
        holiday_name_en=holiday_name_en,
        line_zh=line_zh,
        line_en=line_en,
        holiday_dates=holiday_dates,
        workday_dates=workday_dates,
    )


def parse_holiday_dates(body_zh: str, holiday_year: int, holiday_name_zh: str, index: int) -> list[date]:
    holiday_segment = body_zh.split("放假", 1)[0]
    parsed_dates = parse_dates_from_text(holiday_segment, holiday_year, holiday_name_zh, index)
    if not parsed_dates:
        raise RuntimeError(f"Could not parse holiday dates from line: {body_zh}")
    if "至" in holiday_segment and len(parsed_dates) >= 2:
        return expand_date_range(parsed_dates[0], parsed_dates[-1])
    return sorted(set(parsed_dates))


def parse_workday_dates(body_zh: str, holiday_year: int, holiday_name_zh: str, index: int) -> list[date]:
    workdays: list[date] = []
    for sentence in split_sentences(body_zh):
        if "上班" not in sentence:
            continue
        date_text = sentence.split("上班", 1)[0]
        workdays.extend(parse_dates_from_text(date_text, holiday_year, holiday_name_zh, index))
    return sorted(set(workdays))


def parse_dates_from_text(
    text: str,
    holiday_year: int,
    holiday_name_zh: str,
    index: int,
) -> list[date]:
    parsed_dates: list[date] = []
    last_month: int | None = None
    last_year: int | None = None

    for match in DATE_RE.finditer(text):
        explicit_year = match.group("year")
        explicit_month = match.group("month")
        day = int(match.group("day"))

        if explicit_month is not None:
            month = int(explicit_month)
            resolved_year = (
                int(explicit_year)
                if explicit_year is not None
                else infer_year(month, holiday_year, holiday_name_zh, index)
            )
            last_month = month
            last_year = resolved_year
        else:
            if last_month is None or last_year is None:
                raise RuntimeError(f"Could not infer month/year for date fragment in: {text}")
            month = last_month
            resolved_year = last_year

        parsed_dates.append(date(resolved_year, month, day))

    return parsed_dates


def infer_year(month: int, holiday_year: int, holiday_name_zh: str, index: int) -> int:
    if index == 0 and "元旦" in holiday_name_zh and month >= 11:
        return holiday_year - 1
    return holiday_year


def build_english_line(
    holiday_name_en: str,
    holiday_dates: Sequence[date],
    workday_dates: Sequence[date],
) -> str:
    parts = [f"{holiday_name_en}: {describe_holiday_dates_en(holiday_dates)}."]
    if workday_dates:
        parts.append(f"Compensated working day(s): {describe_date_ranges_en(workday_dates)}.")
    return " ".join(parts)


def describe_holiday_dates_en(holiday_dates: Sequence[date]) -> str:
    merged_ranges = merge_consecutive_dates(holiday_dates)
    if len(merged_ranges) == 1 and merged_ranges[0][0] == merged_ranges[0][1]:
        return f"holiday on {format_date_en(merged_ranges[0][0])}"
    return f"holiday from {describe_merged_ranges_en(merged_ranges)}"


def describe_date_ranges_en(dates: Sequence[date]) -> str:
    return describe_merged_ranges_en(merge_consecutive_dates(dates))


def describe_merged_ranges_en(ranges: Sequence[tuple[date, date]]) -> str:
    if not ranges:
        return ""
    pieces = [format_date_span_en(start, end) for start, end in ranges]
    if len(pieces) == 1:
        return pieces[0]
    return ", ".join(pieces[:-1]) + f", and {pieces[-1]}"


def translate_holiday_name(holiday_name_zh: str) -> str:
    pieces = re.split(r"[、，,/]", holiday_name_zh)
    translated = [HOLIDAY_NAME_TRANSLATIONS.get(piece.strip(), piece.strip()) for piece in pieces if piece.strip()]
    return " / ".join(translated)


def write_calendars(notices: Sequence[Notice], output_dir: Path) -> None:
    variants = [
        ("holiday-and-compensate", "zh-CN", True, True),
        ("holidays-only", "zh-CN", True, False),
        ("compensate-working-days-only", "zh-CN", False, True),
        ("holiday-and-compensate", "en", True, True),
        ("holidays-only", "en", True, False),
        ("compensate-working-days-only", "en", False, True),
    ]
    for slug, language, include_holidays, include_workdays in variants:
        language_dir = output_dir / language
        language_dir.mkdir(parents=True, exist_ok=True)
        path = language_dir / f"{slug}.ics"
        events = build_events(notices, language, include_holidays, include_workdays)
        calendar_name = build_calendar_name(notices, language, slug)
        write_ics_file(path, calendar_name, events)


def build_events(
    notices: Sequence[Notice],
    language: str,
    include_holidays: bool,
    include_workdays: bool,
) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []

    for notice in notices:
        for line in notice.lines:
            if include_holidays:
                for start, end in merge_consecutive_dates(line.holiday_dates):
                    events.append(
                        CalendarEvent(
                            start=start,
                            end=end,
                            summary=build_summary(line, language, "holiday"),
                            description=build_description(notice, line, language, "holiday"),
                            uid_seed=(
                                f"{language}:holiday:{notice.holiday_year}:{line.holiday_name_zh}:"
                                f"{start.isoformat()}:{end.isoformat()}"
                            ),
                        )
                    )

            if include_workdays:
                for start, end in merge_consecutive_dates(line.workday_dates):
                    events.append(
                        CalendarEvent(
                            start=start,
                            end=end,
                            summary=build_summary(line, language, "workday"),
                            description=build_description(notice, line, language, "workday"),
                            uid_seed=(
                                f"{language}:workday:{notice.holiday_year}:{line.holiday_name_zh}:"
                                f"{start.isoformat()}:{end.isoformat()}"
                            ),
                        )
                    )

    return sorted(events, key=lambda event: (event.start, event.end, event.summary))


def build_summary(line: NoticeLine, language: str, event_type: str) -> str:
    if language == "zh-CN":
        if event_type == "holiday":
            return line.holiday_name_zh
        return f"{line.holiday_name_zh} 调休上班"

    if event_type == "holiday":
        return line.holiday_name_en
    return f"{line.holiday_name_en} Compensated Working Day"


def build_description(notice: Notice, line: NoticeLine, language: str, event_type: str) -> str:
    if language == "zh-CN":
        description_lines = [
            f"类型：{'节假日' if event_type == 'holiday' else '调休上班'}",
            f"依据：{notice.title_zh}",
            f"相关原文：{line.line_zh}",
            f"来源：{notice.source_url}",
            f"发布日期：{notice.published_at.isoformat()}",
        ]
        return "\n".join(description_lines)

    description_lines = [
        f"Type: {'Holiday' if event_type == 'holiday' else 'Compensated working day'}",
        f"Source notice: {notice.title_en}",
        f"Relevant announcement line: {line.line_en}",
        f"Original Chinese line: {line.line_zh}",
        f"Source URL: {notice.source_url}",
        f"Published: {notice.published_at.isoformat()}",
    ]
    return "\n".join(description_lines)


def build_calendar_name(notices: Sequence[Notice], language: str, slug: str) -> str:
    first_year = min(notice.holiday_year for notice in notices)
    last_year = max(notice.holiday_year for notice in notices)
    year_label = str(first_year) if first_year == last_year else f"{first_year}-{last_year}"

    zh_names = {
        "holiday-and-compensate": f"中国法定节假日与调休上班 {year_label}",
        "holidays-only": f"中国法定节假日 {year_label}",
        "compensate-working-days-only": f"中国调休上班 {year_label}",
    }
    en_names = {
        "holiday-and-compensate": f"China Holidays and Compensated Working Days {year_label}",
        "holidays-only": f"China Holidays {year_label}",
        "compensate-working-days-only": f"China Compensated Working Days {year_label}",
    }
    return zh_names[slug] if language == "zh-CN" else en_names[slug]


def write_ics_file(path: Path, calendar_name: str, events: Sequence[CalendarEvent]) -> None:
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//china-holiday-calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(calendar_name)}",
    ]

    for event in events:
        uid_hash = hashlib.sha256(event.uid_seed.encode("utf-8")).hexdigest()[:24]
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid_hash}@china-holiday-calendar",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART;VALUE=DATE:{event.start.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(event.end + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{escape_ics_text(event.summary)}",
                f"DESCRIPTION:{escape_ics_text(event.description)}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    content = "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"
    path.write_text(content, encoding="utf-8")


def write_metadata(notices: Sequence[Notice], output_dir: Path) -> None:
    first_year = min(notice.holiday_year for notice in notices)
    last_year = max(notice.holiday_year for notice in notices)
    metadata = {
        "year_window": {
            "start": first_year,
            "end": last_year,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notices": [
            {
                "holiday_year": notice.holiday_year,
                "title_zh": notice.title_zh,
                "title_en": notice.title_en,
                "source_url": notice.source_url,
                "published_at": notice.published_at.isoformat(),
                "holiday_lines": [
                    {
                        "holiday_name_zh": line.holiday_name_zh,
                        "holiday_name_en": line.holiday_name_en,
                        "line_zh": line.line_zh,
                        "line_en": line.line_en,
                        "holiday_dates": [value.isoformat() for value in line.holiday_dates],
                        "workday_dates": [value.isoformat() for value in line.workday_dates],
                    }
                    for line in notice.lines
                ],
            }
            for notice in notices
        ],
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_consecutive_dates(dates: Sequence[date]) -> list[tuple[date, date]]:
    unique_dates = sorted(set(dates))
    if not unique_dates:
        return []

    merged: list[tuple[date, date]] = []
    start = unique_dates[0]
    end = unique_dates[0]
    for current in unique_dates[1:]:
        if current == end + timedelta(days=1):
            end = current
            continue
        merged.append((start, end))
        start = current
        end = current
    merged.append((start, end))
    return merged


def expand_date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise RuntimeError(f"Invalid date range: {start} -> {end}")
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def split_sentences(text: str) -> list[str]:
    pieces = [normalize_text(piece) for piece in re.split(r"[。；]", text)]
    return [piece for piece in pieces if piece]


def normalize_text(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def format_date_en(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def format_date_span_en(start: date, end: date) -> str:
    if start == end:
        return format_date_en(start)
    return f"{format_date_en(start)} to {format_date_en(end)}"


def escape_ics_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def fold_ics_line(line: str, limit: int = 73) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= limit:
        return line

    chunks: list[str] = []
    remaining = encoded
    while len(remaining) > limit:
        split_at = limit
        while split_at > 0 and (remaining[split_at] & 0xC0) == 0x80:
            split_at -= 1
        chunks.append(remaining[:split_at].decode("utf-8"))
        remaining = remaining[split_at:]
    chunks.append(remaining.decode("utf-8"))
    return "\r\n ".join(chunks)
