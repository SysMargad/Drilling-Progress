from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Tuple, Any


HISTORICAL_FUEL_ISSUED_L = 7075.0
HISTORICAL_ESTIMATED_LOAD_L = 8021.75
HISTORICAL_ALLOCATION_FACTOR = HISTORICAL_FUEL_ISSUED_L / HISTORICAL_ESTIMATED_LOAD_L


def allocate_fuel_to_shifts(issued_liters: float, estimated_by_shift: Mapping[str, float]) -> Tuple[float, Dict[str, float]]:
    """Allocate camp-issued fuel across verified shifts using Method B."""
    if not estimated_by_shift:
        raise ValueError('No estimated workload exists for the allocation window.')
    total_estimated = sum(float(value) for value in estimated_by_shift.values())
    if total_estimated <= 0:
        raise ValueError('Estimated fuel load must be positive.')
    factor = float(issued_liters) / total_estimated
    allocations = {shift: float(load) * factor for shift, load in estimated_by_shift.items()}
    return factor, allocations


def calculate_shift_fuel_load(shift_hours: Mapping[str, Mapping[str, float]], rates: Mapping[str, Mapping[str, float]]) -> Dict[str, float]:
    """Compute estimated relative workload for each shift from activity hours and rate table."""
    totals: Dict[str, float] = {}
    for shift_id, activity_hours in shift_hours.items():
        total = 0.0
        for code, hours in activity_hours.items():
            total += float(hours) * float(rates.get(code, {}).get(shift_id.split('|')[0], 0.0) if isinstance(rates.get(code), dict) else 0.0)
        totals[shift_id] = total
    return totals


def estimated_fuel_load_by_shift(shift_hours, rate_table):
    totals = {}
    for shift_id, activity_hours in shift_hours.items():
        rig = shift_id.split('|', 1)[0]
        totals[shift_id] = sum(float(hours) * float(rate_table.get(rig, {}).get(code, 0.0)) for code, hours in activity_hours.items())
    return totals


def daily_cost_per_meter(total_cost: Optional[float], drilled_meters: Optional[float]) -> Optional[float]:
    if drilled_meters in (None, 0):
        return None
    if total_cost is None:
        return None
    return float(total_cost) / float(drilled_meters)


def cumulative_cost_per_meter(costs: Iterable[Optional[float]], meters: Iterable[Optional[float]]) -> Optional[float]:
    cost_values = list(costs)
    meter_values = list(meters)
    if not cost_values or not meter_values:
        return None
    total_cost = sum(float(value) for value in cost_values if value is not None)
    total_meters = sum(float(value) for value in meter_values if value is not None)
    if total_meters == 0:
        return None
    return total_cost / total_meters


def day_over_day_percent(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return ((float(current) - float(previous)) / float(previous)) * 100.0


def food_cost_for_day(headcount: int = 21, cost_per_person: float = 35000.0) -> float:
    return float(headcount) * float(cost_per_person)


def cost_status(record: Mapping[str, Any]) -> str:
    values = [record.get(name) for name in ('fuel_cost', 'mud_cost', 'water_cost', 'labor_cost', 'food_cost')]
    if any(value is None for value in values):
        return 'MISSING'
    return 'ACTUAL'


def filter_daily_records(records: Iterable[Mapping[str, Any]], *, rig: Optional[str] = None, date: Optional[str] = None, hole_id: Optional[str] = None) -> List[Mapping[str, Any]]:
    result = []
    for record in records:
        if rig and record.get('rig') != rig:
            continue
        if date and record.get('date') != date:
            continue
        if hole_id and record.get('hole_id') != hole_id:
            continue
        result.append(record)
    return result


def build_daily_cost_rows(records: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    grouped: Dict[str, Dict[str, Any]] = {}
    for record in records:
        key = record['date']
        entry = grouped.setdefault(key, {'date': key, 'drilled_meters': 0.0, 'fuel_cost': 0.0, 'mud_cost': 0.0, 'water_cost': 0.0, 'labor_cost': 0.0, 'food_cost': 0.0, 'status': 'ACTUAL'})
        entry['drilled_meters'] += float(record.get('drilled_meters', 0.0) or 0.0)
        entry['fuel_cost'] += float(record.get('fuel_cost', 0.0) or 0.0)
        entry['mud_cost'] += float(record.get('mud_cost', 0.0) or 0.0)
        entry['water_cost'] += float(record.get('water_cost', 0.0) or 0.0)
        entry['labor_cost'] += float(record.get('labor_cost', 0.0) or 0.0)
        entry['food_cost'] += float(record.get('food_cost', 0.0) or 0.0)
    for key in sorted(grouped):
        row = grouped[key]
        row['total_cost'] = row['fuel_cost'] + row['mud_cost'] + row['water_cost'] + row['labor_cost'] + row['food_cost']
        row['daily_cost_per_meter'] = daily_cost_per_meter(row['total_cost'], row['drilled_meters'])
        rows.append(row)
    return rows


def summarise_cost_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    accumulated_cost = 0.0
    accumulated_meters = 0.0
    result = []
    for row in rows:
        total_cost = float(row.get('total_cost', 0.0) or 0.0)
        drilled_meters = float(row.get('drilled_meters', 0.0) or 0.0)
        accumulated_cost += total_cost
        accumulated_meters += drilled_meters
        previous = result[-1]['daily_cost_per_meter'] if result else None
        current = daily_cost_per_meter(total_cost, drilled_meters)
        summary = {
            'date': row['date'],
            'daily_cost_per_meter': current,
            'total_cost': total_cost,
            'drilled_meters': drilled_meters,
            'cumulative_cost_per_meter': None if accumulated_meters == 0 else accumulated_cost / accumulated_meters,
            'day_over_day_percent': day_over_day_percent(current, previous),
        }
        result.append(summary)
    return result
