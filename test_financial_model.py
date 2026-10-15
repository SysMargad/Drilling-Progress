import unittest
from pathlib import Path

from financial_model import (
    HISTORICAL_ALLOCATION_FACTOR,
    allocate_fuel_to_shifts,
    build_daily_cost_rows,
    cost_status,
    daily_cost_per_meter,
    day_over_day_percent,
    filter_daily_records,
    food_cost_for_day,
    summarise_cost_rows,
)

ROOT = Path(__file__).resolve().parent


class FinancialModelTests(unittest.TestCase):
    def test_historical_allocation_checkpoint(self):
        factor, allocations = allocate_fuel_to_shifts(7075.0, {'C-1800': 5202.0, 'CSD-1300': 2819.75})
        self.assertAlmostEqual(factor, HISTORICAL_ALLOCATION_FACTOR, places=4)
        self.assertAlmostEqual(sum(allocations.values()), 7075.0, places=2)

    def test_zero_meter_shifts(self):
        self.assertIsNone(daily_cost_per_meter(200000.0, 0))
        self.assertIsNone(daily_cost_per_meter(200000.0, None))

    def test_daily_and_cumulative_cost_per_meter(self):
        rows = [
            {'date': '2026-10-01', 'drilled_meters': 50.0, 'total_cost': 250000.0},
            {'date': '2026-10-02', 'drilled_meters': 100.0, 'total_cost': 600000.0},
        ]
        summary = summarise_cost_rows(rows)
        self.assertAlmostEqual(summary[0]['daily_cost_per_meter'], 5000.0)
        self.assertAlmostEqual(summary[1]['cumulative_cost_per_meter'], 5666.666666666667)

    def test_day_over_day_percentage_change(self):
        self.assertAlmostEqual(day_over_day_percent(200000.0, 160000.0), 25.0, places=4)
        self.assertIsNone(day_over_day_percent(200000.0, 0.0))

    def test_food_counted_once_per_calendar_day(self):
        self.assertEqual(food_cost_for_day(), 735000.0)
        daily_rows = build_daily_cost_rows([
            {'date': '2026-10-10', 'drilled_meters': 20.0, 'fuel_cost': 200000.0, 'mud_cost': 0.0, 'water_cost': 0.0, 'labor_cost': 0.0, 'food_cost': 735000.0},
            {'date': '2026-10-10', 'drilled_meters': 25.0, 'fuel_cost': 100000.0, 'mud_cost': 0.0, 'water_cost': 0.0, 'labor_cost': 0.0, 'food_cost': 735000.0},
        ])
        self.assertEqual(len(daily_rows), 1)
        self.assertEqual(daily_rows[0]['food_cost'], 1470000.0)

    def test_missing_mud_and_water_inputs_are_marked(self):
        self.assertEqual(cost_status({'fuel_cost': 500000.0, 'mud_cost': None, 'water_cost': 50000.0, 'labor_cost': 450000.0, 'food_cost': 735000.0}), 'MISSING')

    def test_filtering_by_rig_date_and_hole_works(self):
        records = [
            {'date': '2026-10-10', 'rig': 'C-1800', 'hole_id': 'DTDH2603', 'drilled_meters': 40.0},
            {'date': '2026-10-10', 'rig': 'CSD-1300', 'hole_id': 'ZHDH2604', 'drilled_meters': 50.0},
            {'date': '2026-10-11', 'rig': 'C-1800', 'hole_id': 'DTDH2603', 'drilled_meters': 60.0},
        ]
        self.assertEqual(len(filter_daily_records(records, rig='C-1800')), 2)
        self.assertEqual(len(filter_daily_records(records, date='2026-10-10')), 2)
        self.assertEqual(len(filter_daily_records(records, hole_id='DTDH2603')), 2)

    def test_public_artifacts_do_not_expose_sensitive_financial_data(self):
        public_text = (ROOT / 'dist' / 'app.js').read_text(encoding='utf-8', errors='ignore').lower()
        for forbidden in ('salary', 'payroll', 'employee', 'google_drive_service_account_json'):
            self.assertNotIn(forbidden, public_text)


if __name__ == '__main__':
    unittest.main()
