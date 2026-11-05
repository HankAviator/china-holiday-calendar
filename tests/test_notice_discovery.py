import unittest
from datetime import date
from unittest.mock import Mock, patch

from china_holiday_calendar.main import (
    build_localized_notice_line,
    discover_notice_urls_with_bing_html,
    parse_notice_line,
)


class NoticeDiscoveryTests(unittest.TestCase):
    def test_discovers_both_official_url_formats(self):
        urls = [
            "https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm",
            "https://www.gov.cn/zhengce/content/202611/content_7085101.htm",
        ]
        response = Mock()
        response.text = "<main>" + "".join(f'<a href="{url}">notice</a>' for url in urls) + "</main>"
        session = Mock()
        session.get.return_value = response

        self.assertEqual(discover_notice_urls_with_bing_html(session, "notice"), urls)

    def test_discovers_new_format_in_raw_search_response(self):
        url = "https://www.gov.cn/zhengce/content/202611/content_7085101.htm"
        response = Mock()
        response.text = f"<script>var url = '{url}';</script>"
        session = Mock()
        session.get.return_value = response

        self.assertEqual(discover_notice_urls_with_bing_html(session, "notice"), [url])


class ChineseParsingTests(unittest.TestCase):
    def test_parses_chinese_before_generating_localized_output(self):
        source = "二、春节：2月5日至13日放假调休，共9天。1月31日、2月14日上班。"
        with patch("china_holiday_calendar.main.translate_holiday_name", side_effect=AssertionError):
            line = parse_notice_line(source, 2027, 1)

        self.assertEqual((line.holiday_dates[0], line.holiday_dates[-1]),
                         (date(2027, 2, 5), date(2027, 2, 13)))
        self.assertEqual(line.workday_dates, (date(2027, 1, 31), date(2027, 2, 14)))
        self.assertEqual(build_localized_notice_line(line, "zh-CN"), source)
        self.assertIn("Spring Festival", build_localized_notice_line(line, "en"))
        self.assertIn("Праздник весны", build_localized_notice_line(line, "ru"))


if __name__ == "__main__":
    unittest.main()
