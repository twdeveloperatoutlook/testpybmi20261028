import json
import math
import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from html import escape, unescape
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree

from app import HEALTH_SOURCES, app, bmi_gauge, bmi_guidance, history_chart, load_history, save_record


class BmiAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = patch.dict(app.config, DATA_DIR=self.directory.name, TESTING=True)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = app.test_client()

    def calculate(self, height="170", weight="65", name="測試使用者"):
        return self.client.post(
            "/", data={"name": name, "height": height, "weight": weight},
            follow_redirects=True,
        )

    def test_initial_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("了解自己的<br><em>健康情形。</em>", page)
        self.assertIn("計算你的 BMI", page)
        self.assertNotIn('class="health-tips"', page)
        self.assertNotIn('class="advice-sources"', page)
        self.assertIn('id="name"', page)
        self.assertNotIn('class="bmi-chart"', page)
        self.assertNotIn('class="bmi-gauge"', page)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])
        self.assertIn('href="/users"', page)

    def test_users_page_with_no_records(self):
        for directory in (
            self.directory.name, str(Path(self.directory.name) / "not-created"),
        ):
            with self.subTest(directory=directory):
                app.config["DATA_DIR"] = directory
                response = self.client.get("/users")
                self.assertEqual(response.status_code, 200)
                page = response.get_data(as_text=True)
                self.assertIn("目前尚無用戶紀錄", page)
                self.assertNotIn('class="users-list"', page)
                self.assertIn("所有訪客都能查看", page)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_users_list_is_unique_sorted_and_links_to_latest_history(self):
        older = save_record("Alice", 100, 20, 20)
        other = save_record("Bob", 100, 30, 30)
        latest = save_record("Alice", 100, 24, 24)
        for record, timestamp in (
            (older, "2026-10-12T11:00:01+00:00"),
            (other, "2026-10-12T12:00:00+00:00"),
            (latest, "2026-10-12T20:00:02+08:00"),
        ):
            record["recorded_at"] = timestamp
            path = Path(self.directory.name) / f'{record["id"]}.json'
            path.write_text(json.dumps(record), encoding="utf-8")
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertEqual(page.count(">Alice</a>"), 1)
        self.assertEqual(page.count(">Bob</a>"), 1)
        self.assertLess(page.index(">Alice</a>"), page.index(">Bob</a>"))
        link = f'/?record={latest["id"]}#history-title'
        self.assertIn(f'href="{link}"', page)
        history_page = self.client.get(link).get_data(as_text=True)
        self.assertIn("Alice 的 BMI 趨勢", history_page)
        self.assertIn('class="result-number">24.0</span>', history_page)
        self.assertIn('class="history-details" open', history_page)
        self.assertIn("<td>2026/10/12 19:00:01</td>", history_page)
        self.assertIn("<td>2026/10/12 20:00:02</td>", history_page)
        self.assertIn("<td>20.0</td>", history_page)
        self.assertIn("<td>24.0</td>", history_page)
        self.assertLess(history_page.index("<td>20.0</td>"), history_page.index("<td>24.0</td>"))
        self.assertNotIn("Bob", history_page)
        self.assertNotIn("<td>30.0</td>", history_page)
        self.assertEqual(len(list(Path(self.directory.name).glob("*.json"))), 3)

    def test_users_list_escapes_names_and_ignores_temporary_files(self):
        name = '../<script>alert("x")</script>'
        record = save_record(name, 100, 20, 20)
        (Path(self.directory.name) / "incomplete.tmp").write_text("{broken", encoding="utf-8")
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn(name, unescape(page))
        self.assertIn(f'href="/?record={record["id"]}#history-title"', page)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 2)

    def test_users_list_reports_corrupt_records_without_partial_results(self):
        save_record("Alice", 100, 20, 20)
        path = Path(self.directory.name) / f"{uuid4()}.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.get("/users")
        self.assertEqual(response.status_code, 503)
        page = response.get_data(as_text=True)
        self.assertIn("無法讀取用戶名單", page)
        self.assertNotIn('class="users-list"', page)
        self.assertNotIn("目前尚無用戶紀錄", page)
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_users_list_reports_storage_permission_errors(self):
        with patch("app.Path.iterdir", side_effect=PermissionError("test")), self.assertLogs(
            app.logger, level="ERROR",
        ):
            response = self.client.get("/users")
        self.assertEqual(response.status_code, 503)
        self.assertIn("無法讀取用戶名單", response.get_data(as_text=True))

    def test_calculation_and_advice(self):
        response = self.calculate()
        page = response.get_data(as_text=True)
        self.assertIn("22.5", page)
        self.assertIn("健康體位", page)
        self.assertIn("維持均衡飲食", page)

    def test_gauge_geometry_and_category_boundaries(self):
        for bmi, category in (
            (0, "體重過輕"), (18.4, "體重過輕"), (18.5, "健康體位"),
            (23.9, "健康體位"), (24, "體重過重"), (26.9, "體重過重"),
            (27, "肥胖"), (40, "肥胖"), (40.1, "肥胖"), (1.7e308, "肥胖"),
        ):
            with self.subTest(bmi=bmi):
                gauge = bmi_gauge(bmi)
                self.assertAlmostEqual(gauge["angle"], min(bmi, 40) / 40 * 180, places=4)
                self.assertEqual(gauge["out_of_range"], bmi > 40)
                self.assertTrue(math.isfinite(gauge["angle"]))
                self.assertEqual([tick["value"] for tick in gauge["ticks"]], [0, 18.5, 24, 27, 40])
                self.assertEqual([segment["label"] for segment in gauge["segments"]], [
                    "體重過輕", "健康體位", "體重過重", "肥胖",
                ])
                segment = next(
                    segment for segment in gauge["segments"]
                    if segment["start"] <= min(bmi, 40) < segment["end"]
                    or (segment["end"] == 40 and bmi >= 40)
                )
                self.assertEqual(segment["label"], category)
                for segment in gauge["segments"]:
                    self.assertRegex(segment["path"], r"^M [\d.]+ [\d.]+ A 130 130 0 0 1 [\d.]+ [\d.]+$")

    def test_gauge_uses_displayed_bmi_and_accessible_svg(self):
        for weight, displayed, category in (
            ("18.46", "18.5", "健康體位"), ("23.96", "24.0", "體重過重"),
            ("26.96", "27.0", "肥胖"), ("0.01", "0.0", "體重過輕"),
            ("40", "40.0", "肥胖"), ("40.1", "40.1", "肥胖"),
        ):
            with self.subTest(weight=weight):
                page = self.calculate(height="100", weight=weight).get_data(as_text=True)
                svg_text = re.search(
                    r'<figure class="bmi-gauge">\s*(<svg.*?</svg>)', page, re.DOTALL,
                ).group(1)
                svg = ElementTree.fromstring(svg_text)
                self.assertEqual(svg.attrib["role"], "img")
                self.assertEqual(svg.attrib["viewBox"], "0 0 360 200")
                self.assertEqual(svg.attrib["aria-labelledby"], "gauge-title gauge-description")
                self.assertIn(f"BMI {displayed}，{category}", svg.find("desc").text)
                needle = svg.find("./line[@class='gauge-needle']")
                self.assertEqual(
                    needle.attrib["transform"],
                    f'rotate({bmi_gauge(float(displayed))["angle"]} 180 170)',
                )
                self.assertEqual(len(svg.findall("path")), 4)
                self.assertEqual(len(svg.findall("text")), 5)
                self.assertEqual('class="gauge-notice"' in page, float(displayed) > 40)
                self.assertIn("成人 BMI 體位參考", page)
                for label in ("體重過輕", "健康體位", "體重過重", "肥胖"):
                    self.assertIn(f"<span>{label}<small>", page)

    def test_gauge_updates_on_recalculation_and_history_lookup(self):
        first = self.calculate(height="100", weight="20")
        first_url = first.history[0].headers["Location"]
        second = self.calculate(height="100", weight="30")
        self.assertIn('transform="rotate(135.0 180 170)"', second.get_data(as_text=True))
        self.assertNotIn('transform="rotate(90.0 180 170)"', second.get_data(as_text=True))
        page = self.client.get(first_url).get_data(as_text=True)
        self.assertIn('transform="rotate(90.0 180 170)"', page)
        self.assertIn("BMI 20.0，健康體位", page)
        invalid = self.calculate(height="0").get_data(as_text=True)
        self.assertNotIn('class="bmi-gauge"', invalid)
        self.assertEqual(len(load_history("測試使用者")), 2)

    def test_health_tips_and_sources_for_each_category(self):
        for bmi, category in [
            (18.4, "體重過輕"),
            (18.5, "健康體位"),
            (23.9, "健康體位"),
            (24.0, "體重過重"),
            (26.9, "體重過重"),
            (27.0, "肥胖"),
        ]:
            with self.subTest(bmi=bmi):
                response = self.calculate(height="100", weight=str(bmi))
                page = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'<strong>{category}</strong>', page)
                for tip in bmi_guidance(bmi)["tips"]:
                    self.assertIn(tip["title"], page)
                    self.assertIn(tip["text"], page)
                self.assertIn("每週至少 150 分鐘", page)
                self.assertIn("非個人化診斷或治療處方", page)
                for source in HEALTH_SOURCES:
                    self.assertIn(f'href="{escape(source["url"])}"', page)
                    self.assertIn(source["title"], page)
                self.assertEqual(page.count('rel="noopener noreferrer"'), len(HEALTH_SOURCES))

    def test_displayed_bmi_still_determines_guidance(self):
        response = self.calculate(height="100", weight="23.96")
        page = response.get_data(as_text=True)
        self.assertIn('class="result-number">24.0</span>', page)
        self.assertIn("<strong>體重過重</strong>", page)
        self.assertIn(bmi_guidance(24.0)["tips"][0]["text"], page)

    def test_taiwan_adult_thresholds(self):
        for bmi, category in [
            (18.4, "體重過輕"),
            (18.5, "健康體位"),
            (23.9, "健康體位"),
            (24.0, "體重過重"),
            (26.9, "體重過重"),
            (27.0, "肥胖"),
        ]:
            with self.subTest(bmi=bmi):
                self.assertEqual(bmi_guidance(bmi)["label"], category)

    def test_obese_bmi_numbers_are_red_on_all_surfaces(self):
        for weight, displayed, obese in [
            ("24", "24.0", False),
            ("26.9", "26.9", False),
            ("27", "27.0", True),
            ("30", "30.0", True),
            ("26.96", "27.0", True),
        ]:
            with self.subTest(weight=weight):
                response = self.calculate(height="100", weight=weight, name=weight)
                page = response.get_data(as_text=True)
                suffix = " bmi-obese" if obese else ""
                self.assertIn(f'class="result-number{suffix}">{displayed}</span>', page)
                self.assertIn(f'class="chart-value{suffix}"', page)
                cell_class = ' class="bmi-obese"' if obese else ""
                self.assertIn(f"<td{cell_class}>{displayed}</td>", page)
                if not obese:
                    self.assertNotIn("bmi-obese", page)

    def test_history_retains_each_records_color(self):
        self.calculate(height="100", weight="27", name="顏色測試")
        response = self.calculate(height="100", weight="26.9", name="顏色測試")
        page = response.get_data(as_text=True)
        self.assertIn('class="result-number">26.9</span>', page)
        self.assertEqual(page.count('class="chart-value bmi-obese"'), 1)
        self.assertIn('<td class="bmi-obese">27.0</td>', page)
        self.assertIn("<td>26.9</td>", page)

    def test_invalid_fields_do_not_produce_result(self):
        for height, weight in [("", "65"), ("0", "65"), ("abc", "65"), ("170", "-2"), ("inf", "65"), ("170", "nan"), ("1e-300", "65"), ("1e308", "65"), ("1", "1e308")]:
            with self.subTest(height=height, weight=weight):
                response = self.calculate(height=height, weight=weight)
                page = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn('aria-invalid="true"', page)
                self.assertNotIn("YOUR RESULT", page)
                self.assertNotIn('class="bmi-gauge"', page)
                self.assertNotIn('class="health-tips"', page)
                self.assertNotIn('class="advice-sources"', page)
                self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_input_is_escaped(self):
        response = self.calculate(height='<script>alert(1)</script>')
        page = response.get_data(as_text=True)
        self.assertNotIn("<script>", page)
        self.assertIn("請輸入大於 0", page)

    def test_records_persist_with_expected_json_fields(self):
        response = self.calculate(name="  小明  ")
        self.assertEqual(response.status_code, 200)
        files = list(Path(self.directory.name).glob("*.json"))
        self.assertEqual(len(files), 1)
        record = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(set(record), {
            "id", "name", "recorded_at", "height_cm", "weight_kg", "bmi", "category",
        })
        self.assertEqual(files[0].stem, record["id"])
        self.assertEqual(record["name"], "小明")
        self.assertEqual(record["height_cm"], 170)
        self.assertEqual(record["weight_kg"], 65)
        self.assertEqual(record["bmi"], 22.5)
        self.assertEqual(record["category"], "健康體位")
        self.assertTrue(record["recorded_at"].endswith("+00:00"))
        self.assertEqual(load_history("小明"), [record])
        self.assertIn("小明 的 BMI 趨勢", response.get_data(as_text=True))
        self.assertIn("目前只有一筆紀錄", response.get_data(as_text=True))

    def test_history_is_sorted_and_isolated_by_name(self):
        self.calculate(weight="60", name="小明")
        self.calculate(weight="90", name="小美")
        response = self.calculate(weight="70", name="小明")
        history = load_history("小明")
        self.assertEqual([record["weight_kg"] for record in history], [60, 70])
        page = response.get_data(as_text=True)
        self.assertIn("已儲存 2 筆紀錄", page)
        self.assertNotIn("小美", page)
        chart = history_chart(history)
        self.assertEqual(len(chart["points"]), 2)
        self.assertEqual(len(chart["line"].split()), 2)
        self.assertLess(chart["points"][0]["x"], chart["points"][1]["x"])
        self.assertGreater(chart["points"][0]["y"], chart["points"][1]["y"])
        self.assertIn(f'points="{chart["line"]}"', page)
        self.assertIn('class="healthy-band"', page)
        self.assertIn("UTC+8", page)

    def test_refresh_and_history_lookup_do_not_add_records(self):
        response = self.calculate()
        self.assertEqual(response.history[0].status_code, 303)
        result_url = response.history[0].headers["Location"]
        self.client.get(result_url)
        self.client.get(result_url)
        self.client = app.test_client()
        response = self.client.post(
            "/", data={"name": "測試使用者", "action": "history"},
            follow_redirects=True,
        )
        self.assertIn("22.5", response.get_data(as_text=True))
        self.assertEqual(len(load_history("測試使用者")), 1)

    def test_empty_history_and_invalid_names(self):
        response = self.client.post("/", data={"name": "新使用者", "action": "history"})
        self.assertIn("尚無 BMI 紀錄", response.get_data(as_text=True))
        for name in ("", "   ", "字" * 81, "小\x00明", "小\n明"):
            with self.subTest(name=name):
                response = self.calculate(name=name)
                self.assertIn('id="name-error"', response.get_data(as_text=True))
                self.assertNotIn("YOUR RESULT", response.get_data(as_text=True))
                response = self.client.post("/", data={"name": name, "action": "history"})
                self.assertIn('id="name-error"', response.get_data(as_text=True))
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_name_cannot_become_a_path_or_html(self):
        name = '../<script>alert("x")</script>'
        response = self.calculate(name=name)
        page = response.get_data(as_text=True)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn(name, unescape(page))
        files = list(Path(self.directory.name).glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(load_history(name)[0]["name"], name)

    def test_corrupt_record_is_not_overwritten(self):
        path = Path(self.directory.name) / f"{uuid4()}.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.calculate()
        self.assertEqual(response.status_code, 503)
        self.assertIn("本次紀錄未儲存", response.get_data(as_text=True))
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/", data={"name": "測試使用者", "action": "history"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("無法讀取歷史紀錄", response.get_data(as_text=True))

    def test_storage_failure_reports_unsaved_result(self):
        with patch("app.os.replace", side_effect=PermissionError("test")), self.assertLogs(
            app.logger, level="ERROR"
        ):
            response = self.calculate()
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 503)
        self.assertIn("22.5", page)
        self.assertIn("本次紀錄未儲存", page)
        self.assertIn('class="bmi-gauge"', page)
        self.assertIn('transform="rotate(101.25 180 170)"', page)
        self.assertNotIn('class="bmi-chart"', page)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_invalid_record_schema_is_reported(self):
        record = save_record("測試使用者", 170, 65, 22.5)
        path = Path(self.directory.name) / f'{record["id"]}.json'
        for field, value in [
            ("name", None), ("height_cm", "170"), ("weight_kg", -1),
            ("bmi", float("nan")), ("bmi", -1), ("category", "錯誤分類"),
            ("recorded_at", "2026-10-12T12:00:00"), ("id", "invalid"),
        ]:
            with self.subTest(field=field, value=value):
                path.write_text(json.dumps({**record, field: value}), encoding="utf-8")
                with self.assertLogs(app.logger, level="ERROR"):
                    response = self.client.get(f'/?record={record["id"]}')
                self.assertEqual(response.status_code, 503)
                self.assertIn("無法讀取 BMI 紀錄", response.get_data(as_text=True))

    def test_concurrent_writes_and_new_data_directory(self):
        app.config["DATA_DIR"] = str(Path(self.directory.name) / "data")
        with ThreadPoolExecutor(max_workers=4) as executor:
            records = list(executor.map(
                lambda index: save_record("同一使用者", 100, 20 + index, 20 + index),
                range(12),
            ))
        history = load_history("同一使用者")
        self.assertEqual(len(history), 12)
        self.assertEqual({record["id"] for record in records}, {record["id"] for record in history})
        self.assertEqual(list(Path(app.config["DATA_DIR"]).glob("*.tmp")), [])

    def test_missing_or_invalid_record_link(self):
        response = self.client.get(f"/?record={uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertIn("找不到這筆", response.get_data(as_text=True))
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.get("/?record=../../app.py")
        self.assertEqual(response.status_code, 503)
        self.assertIn("無法讀取 BMI 紀錄", response.get_data(as_text=True))

    def test_chart_supports_identical_and_extreme_values(self):
        for weight in ("20", "0.01", "1.7e308"):
            with self.subTest(weight=weight):
                response = self.calculate(height="100", weight=weight, name=weight)
                self.assertEqual(response.status_code, 200)
                chart = history_chart(load_history(weight))
                self.assertEqual(len(chart["points"]), 1)
                self.assertGreaterEqual(chart["points"][0]["y"], chart["top"])
                self.assertLessEqual(chart["points"][0]["y"], chart["bottom"])
                for tick in chart["ticks"]:
                    self.assertGreaterEqual(tick["y"], chart["top"])
                    self.assertLessEqual(tick["y"], chart["bottom"])
        self.calculate(height="100", weight="20", name="20")
        points = history_chart(load_history("20"))["points"]
        self.assertEqual(points[0]["y"], points[1]["y"])
        self.assertNotEqual(points[0]["x"], points[1]["x"])


if __name__ == "__main__":
    unittest.main()
