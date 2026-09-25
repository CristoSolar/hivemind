import unittest
from datetime import datetime

from hivemind.schedule import describe, next_run, short_when, validate


class ScheduleTest(unittest.TestCase):
    def test_every_hours(self):
        self.assertEqual(next_run({"every_hours": 3}, datetime(2026, 9, 25, 10, 15)), datetime(2026, 9, 25, 13, 15))

    def test_daily_before_and_after_time(self):
        s = {"daily": "09:00"}
        self.assertEqual(next_run(s, datetime(2026, 9, 25, 8, 59)), datetime(2026, 9, 25, 9, 0))
        self.assertEqual(next_run(s, datetime(2026, 9, 25, 9, 0)), datetime(2026, 9, 26, 9, 0))

    def test_daily_month_and_year_end(self):
        self.assertEqual(next_run({"daily": "00:30"}, datetime(2026, 12, 31, 23, 0)), datetime(2027, 1, 1, 0, 30))
        self.assertEqual(next_run({"daily": "07:00"}, datetime(2026, 2, 28, 8, 0)), datetime(2026, 3, 1, 7, 0))

    def test_weekly_across_week_boundary(self):
        s = {"weekly": {"days": [0, 3], "time": "09:00"}}  # lunes y jueves
        # 2026-09-25 is a Friday
        self.assertEqual(next_run(s, datetime(2026, 9, 25, 12, 0)), datetime(2026, 9, 28, 9, 0))
        self.assertEqual(next_run(s, datetime(2026, 9, 28, 9, 0)), datetime(2026, 10, 1, 9, 0))
        self.assertEqual(next_run(s, datetime(2026, 9, 28, 8, 0)), datetime(2026, 9, 28, 9, 0))

    def test_validate_rejects_bad_input(self):
        for bad in ({"every_hours": 0}, {"every_hours": 169}, {"every_hours": "3"}, {"daily": "25:00"},
                    {"daily": "9"}, {"weekly": {"days": [], "time": "09:00"}},
                    {"weekly": {"days": [7], "time": "09:00"}}, {}, {"daily": "09:00", "every_hours": 1}):
            with self.assertRaises(ValueError, msg=bad):
                validate(bad)

    def test_validate_normalizes(self):
        self.assertEqual(validate({"daily": "9:05"}), {"daily": "09:05"})
        self.assertEqual(validate({"weekly": {"days": [3, 0, 3], "time": "18:30"}}),
                         {"weekly": {"days": [0, 3], "time": "18:30"}})

    def test_describe(self):
        self.assertEqual(describe({"every_hours": 1}), "Cada hora")
        self.assertEqual(describe({"every_hours": 3}), "Cada 3 horas")
        self.assertEqual(describe({"daily": "09:00"}), "Todos los días 09:00")
        self.assertEqual(describe({"weekly": {"days": [0, 3], "time": "09:00"}}), "Lunes y Jueves 09:00")
        self.assertEqual(describe({"weekly": {"days": [0, 2, 4], "time": "07:30"}}), "Lunes, Miércoles y Viernes 07:30")

    def test_short_when_is_spanish(self):
        self.assertEqual(short_when(datetime(2026, 9, 26, 8, 30).timestamp()), "sáb 26 08:30")
        self.assertEqual(short_when(datetime(2026, 9, 28, 10, 0).timestamp()), "lun 28 10:00")
        self.assertEqual(short_when(None), "—")


if __name__ == "__main__":
    unittest.main()
