#!/usr/bin/env python3
"""
Mock Data Generator for Smart Water Analytics Dashboard
Generates structurally identical but fully fictional data for portfolio demo.
"""

import json
import random
import math
import os
from datetime import datetime, timedelta

random.seed(42)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend', 'data', 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === Configuration ===
DMA_ZONES = ['Zone-1', 'Zone-2', 'Zone-3', 'Zone-4', 'Unclassified']
DMA_WEIGHTS = [0.35, 0.25, 0.20, 0.15, 0.05]

PROPERTY_TYPES = [
    '001:Residential', '002:Commercial', '003:Hotel',
    '004:Restaurant', '005:Office', '006:Industrial',
    '007:Government', '008:Education', '009:Healthcare',
    '010:Recreation', '011:Swimming Pool', '012:Fire System',
    '013:Public Facility', '014:Green Space', '015:Transport'
]

BUILDING_NAMES = {
    'Zone-1': [
        'North Tower Residence', 'Central Plaza Hotel', 'Harbour View Office',
        'City Center Mall', 'East Wing Apartments', 'Riverside Condo',
        'Metro Station Complex', 'Government Administration Building',
        'District Hospital', 'Community College', 'Central Library',
        'Fire Station HQ', 'Water Treatment Plant', 'Public Market'
    ],
    'Zone-2': [
        'Bayshore Resort', 'Marina Bay Hotel', 'Coastal Tower',
        'Seaside Apartments', 'Beach Club Complex', 'Lighthouse Office Park',
        'Harbour Hospital', 'Maritime Academy', 'Yacht Club',
        'Convention Center', 'Exhibition Hall', 'Seafood Market'
    ],
    'Zone-3': [
        'Grand Resort & Spa', 'Casino Complex North', 'Entertainment Tower',
        'Luxury Hotel East', 'Garden Villas', 'Convention Hotel',
        'Theme Park Facility', 'Shopping Arcade', 'Dining Pavilion',
        'Theater Complex', 'Sports Arena', 'Wellness Center'
    ],
    'Zone-4': [
        'University Campus A', 'Research Laboratory', 'Tech Park Building',
        'Innovation Center', 'Student Dormitory', 'Faculty Building',
        'Campus Hospital', 'Sports Complex', 'Library Building',
        'Administrative Office', 'Engineering Workshop'
    ],
    'Unclassified': [
        'Miscellaneous Facility', 'Storage Warehouse', 'Temporary Structure'
    ]
}

# Date range: 90 days
START_DATE = datetime(2026, 1, 1)
NUM_DAYS = 90
DATES = [(START_DATE + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(NUM_DAYS)]

# Generate meter pool
NUM_METERS = 500
NUM_CONTRACTS = 400
NUM_BUILDINGS = 60

def gen_id(n):
    return str(random.randint(10**(n-1), 10**n - 1))

def gen_building_pool():
    """Generate building pool with metadata."""
    buildings = []
    for dma in DMA_ZONES:
        names = BUILDING_NAMES[dma]
        for name in names:
            btype = random.choice(PROPERTY_TYPES)
            is_res = btype.startswith('001:')
            buildings.append({
                'name': name,
                'dma': dma,
                'type': btype,
                'isResidential': is_res
            })
    return buildings

def gen_meters(buildings):
    """Generate meters assigned to buildings. Main meters have mainCode=None, sub-meters have mainCode=mainMeterId."""
    meters = []
    used_contracts = set()
    used_ids = set()

    # First pass: generate main meters (no mainCode)
    main_meter_count = int(NUM_METERS * 0.2)
    for i in range(main_meter_count):
        b = random.choice(buildings)
        while True:
            cid = gen_id(7)
            if cid not in used_contracts:
                used_contracts.add(cid)
                break
        while True:
            mid = gen_id(7)
            if mid not in used_ids:
                used_ids.add(mid)
                break
        meters.append({
            'id': mid,
            'contractId': cid,
            'building': b['name'],
            'dma': b['dma'],
            'propertyType': b['type'],
            'isResidential': b['isResidential'],
            'supplyMode': 'DIRECT' if random.random() < 0.8 else 'INDIRECT',
            'mainCode': None
        })

    # Second pass: generate sub meters (reference a random main meter)
    for i in range(NUM_METERS - main_meter_count):
        b = random.choice(buildings)
        while True:
            cid = gen_id(7)
            if cid not in used_contracts:
                used_contracts.add(cid)
                break
        while True:
            mid = gen_id(7)
            if mid not in used_ids:
                used_ids.add(mid)
                break
        # Pick a random main meter to reference
        main_meter = random.choice(meters[:main_meter_count])
        meters.append({
            'id': mid,
            'contractId': cid,
            'building': b['name'],
            'dma': b['dma'],
            'propertyType': b['type'],
            'isResidential': b['isResidential'],
            'supplyMode': 'INDIRECT',
            'mainCode': main_meter['id']
        })

    return meters

def gen_consumption(meter, day_idx):
    """Generate daily consumption for a meter based on property type."""
    base = meter['propertyType']
    if 'Hotel' in base or 'Resort' in base:
        base_val = random.uniform(80, 300)
    elif 'Residential' in base:
        base_val = random.uniform(2, 15)
    elif 'Commercial' in base or 'Office' in base:
        base_val = random.uniform(20, 80)
    elif 'Restaurant' in base:
        base_val = random.uniform(30, 120)
    elif 'Industrial' in base or 'Factory' in base:
        base_val = random.uniform(50, 200)
    elif 'Hospital' in base or 'Healthcare' in base:
        base_val = random.uniform(40, 150)
    elif 'Education' in base:
        base_val = random.uniform(10, 50)
    else:
        base_val = random.uniform(5, 40)

    # Add weekly pattern (weekends slightly different)
    dow = (START_DATE + timedelta(days=day_idx)).weekday()
    if dow >= 5:  # weekend
        base_val *= random.uniform(0.85, 1.15)
    else:
        base_val *= random.uniform(0.9, 1.1)

    # Add some trend
    trend = 1.0 + (day_idx / NUM_DAYS) * random.uniform(-0.1, 0.1)
    base_val *= trend

    # Add noise
    noise = random.gauss(1.0, 0.15)
    base_val *= max(0.1, noise)

    return round(max(0, base_val), 2)

def gen_rainfall():
    """Generate rainfall data."""
    rain = {}
    for d in DATES:
        if random.random() < 0.15:
            rain[d] = round(random.uniform(0.5, 25), 1)
        else:
            rain[d] = 0
    return rain

def inject_anomalies(meters, all_consumption):
    """Inject anomaly events into the data."""
    anomalies = []
    num_anomalies = random.randint(30, 50)

    for _ in range(num_anomalies):
        meter = random.choice(meters)
        day_idx = random.randint(14, NUM_DAYS - 8)
        date = DATES[day_idx]
        mid = meter['id']

        if mid not in all_consumption or date not in all_consumption[mid]:
            continue

        actual = all_consumption[mid][date]
        # Compute past mean
        past_dates = DATES[max(0, day_idx-14):day_idx]
        past_vals = [all_consumption[mid].get(d, 0) for d in past_dates if d in all_consumption[mid]]
        past_mean = sum(past_vals) / len(past_vals) if past_vals else 1
        past_std = max(1, (sum((v - past_mean)**2 for v in past_vals) / len(past_vals)) ** 0.5) if len(past_vals) > 1 else 1

        atype = random.choice(['spike', 'drop', 'zero', 'watch'])
        if atype == 'spike':
            new_val = past_mean * random.uniform(3, 6)
            reason = f"Spike: {new_val:.0f}m3, {random.randint(200,400)}% above mean {past_mean:.0f}m3"
            score = round(random.uniform(0.5, 0.95), 2)
        elif atype == 'drop':
            new_val = past_mean * random.uniform(0.1, 0.4)
            reason = f"Drop: {new_val:.0f}m3, {random.randint(50,80)}% below mean {past_mean:.0f}m3"
            score = round(random.uniform(0.4, 0.85), 2)
        elif atype == 'zero':
            new_val = 0
            reason = f"Zero consumption after mean {past_mean:.0f}m3"
            score = round(random.uniform(0.6, 0.9), 2)
        else:
            new_val = past_mean * random.uniform(1.5, 2.5)
            reason = f"Watch: {new_val:.0f}m3, {random.randint(50,150)}% above mean {past_mean:.0f}m3"
            score = round(random.uniform(0.2, 0.5), 2)

        all_consumption[mid][date] = round(new_val, 2)

        anomalies.append({
            'date': date,
            'meterId': mid,
            'total': round(new_val, 2),
            'contractId': meter['contractId'],
            'dma': meter['dma'],
            'buildingName': meter['building'],
            'reason': reason,
            'type': atype,
            'anomalyScore': score,
            'pastMean': round(past_mean, 2),
            'pastStd': round(past_std, 2),
            'windowDays': 14
        })

    return anomalies

def build_daily_dma(all_consumption, meters, rainfall):
    """Build daily DMA summaries."""
    meter_map = {m['id']: m for m in meters}
    result = []
    for date in DATES:
        dmas = {}
        for dma in DMA_ZONES:
            dmas[dma] = {'total': 0, 'residential': 0, 'nonResidential': 0,
                         'resCount': 0, 'nonResCount': 0, 'meterCount': 0, 'rain': 0}
        for mid, dates in all_consumption.items():
            if date not in dates:
                continue
            info = meter_map.get(mid)
            if not info:
                continue
            dma = info['dma']
            val = dates[date]
            dmas[dma]['total'] += val
            dmas[dma]['meterCount'] += 1
            if info['isResidential']:
                dmas[dma]['residential'] += val
                dmas[dma]['resCount'] += 1
            else:
                dmas[dma]['nonResidential'] += val
                dmas[dma]['nonResCount'] += 1
        for dma in DMA_ZONES:
            dmas[dma]['total'] = round(dmas[dma]['total'], 2)
            dmas[dma]['residential'] = round(dmas[dma]['residential'], 2)
            dmas[dma]['nonResidential'] = round(dmas[dma]['nonResidential'], 2)
            dmas[dma]['rain'] = rainfall.get(date, 0)
        result.append({'date': date, 'dmas': dmas, 'rain': rainfall.get(date, 0)})
    return result

def build_top20_daily(all_consumption, meters, meter_map):
    """Build daily top 20 meters."""
    result = []
    for date in DATES:
        day_vals = [(mid, dates.get(date, 0)) for mid, dates in all_consumption.items() if date in dates]
        day_vals.sort(key=lambda x: -x[1])
        top20 = []
        for mid, val in day_vals[:20]:
            info = meter_map.get(mid, {})
            top20.append({
                'meterId': mid,
                'total': round(val, 2),
                'dma': info.get('dma', 'Unclassified'),
                'contractId': info.get('contractId', ''),
                'propertyType': info.get('propertyType', ''),
                'buildingName': info.get('building', '')
            })
        result.append({'date': date, 'top20': top20})
    return result

def build_top20_by_dma(all_consumption, meter_map):
    """Build daily top 20 per DMA."""
    result = []
    for date in DATES:
        by_dma = {dma: [] for dma in DMA_ZONES}
        for mid, dates in all_consumption.items():
            if date not in dates:
                continue
            info = meter_map.get(mid, {})
            dma = info.get('dma', 'Unclassified')
            by_dma[dma].append({
                'meterId': mid,
                'total': round(dates[date], 2),
                'contractId': info.get('contractId', ''),
                'propertyType': info.get('propertyType', ''),
                'buildingName': info.get('building', '')
            })
        for dma in DMA_ZONES:
            by_dma[dma].sort(key=lambda x: -x['total'])
            by_dma[dma] = by_dma[dma][:20]
        result.append({'date': date, 'byDma': by_dma})
    return result

def build_daily_total_by_dma(daily_dma):
    """Build daily total by DMA."""
    result = []
    for day in daily_dma:
        dmas = {}
        for dma in DMA_ZONES:
            dmas[dma] = round(day['dmas'][dma]['total'], 0)
        result.append({'date': day['date'], 'dmas': dmas, 'rain': day['rain']})
    return result

def build_monthly_diff(all_consumption, meters, meter_map):
    """Build monthly main-sub meter diff. Sub-meters have mainCode pointing to main meter ID."""
    months = sorted(set(d[:7] for d in DATES))

    # Group sub-meters by their mainCode (main meter ID)
    sub_by_main = {}
    for m in meters:
        main_code = m.get('mainCode')
        if main_code:
            sub_by_main.setdefault(main_code, []).append(m['id'])

    # Find actual main meters (those that have sub-meters)
    main_meters = [m for m in meters if m['id'] in sub_by_main]

    result = []
    for month in months:
        diffs = []
        for main in main_meters:
            mid = main['id']
            subs = sub_by_main[mid]
            month_dates = [d for d in DATES if d.startswith(month)]
            main_total = sum(all_consumption.get(mid, {}).get(d, 0) for d in month_dates)
            subs_total = sum(
                sum(all_consumption.get(s, {}).get(d, 0) for d in month_dates)
                for s in subs
            )
            diff = main_total - subs_total
            diff_pct = round(diff / main_total * 100, 1) if main_total > 0 else 0
            diffs.append({
                'mainMeterId': mid,
                'mainContractId': main['contractId'],
                'mainBuilding': main['building'],
                'dma': main['dma'],
                'subs': subs,
                'mainTotal': round(main_total, 2),
                'subsTotal': round(subs_total, 2),
                'diff': round(diff, 2),
                'diffPercent': diff_pct
            })
        diffs.sort(key=lambda x: -abs(x['diff']))
        result.append({'month': month, 'diffs': diffs[:30]})
    return result

def build_rank_changes(all_consumption, meters, meter_map):
    """Build rank changes (meters that appeared in top 20)."""
    # Track how many days each meter was in top 20
    meter_days = {}
    for date in DATES:
        day_vals = [(mid, dates.get(date, 0)) for mid, dates in all_consumption.items() if date in dates]
        day_vals.sort(key=lambda x: -x[1])
        for rank, (mid, val) in enumerate(day_vals[:20], 1):
            if mid not in meter_days:
                meter_days[mid] = {'days': 0, 'total': 0, 'ranks': []}
            meter_days[mid]['days'] += 1
            meter_days[mid]['total'] += val
            meter_days[mid]['ranks'].append(rank)

    result = []
    for mid, data in meter_days.items():
        info = meter_map.get(mid, {})
        avg_rank = sum(data['ranks']) / len(data['ranks'])
        avg_total = data['total'] / data['days']
        trend = 'up' if avg_rank < 10 else 'down'
        result.append({
            'meterId': mid,
            'contractId': info.get('contractId', ''),
            'buildingName': info.get('building', ''),
            'dma': info.get('dma', ''),
            'propertyType': info.get('propertyType', ''),
            'daysInTop20': data['days'],
            'avgTotal': round(avg_total, 2),
            'avgRank': round(avg_rank, 1),
            'trend': trend
        })
    result.sort(key=lambda x: -x['daysInTop20'])
    return result[:50]

def build_search_index(meters):
    """Build search index."""
    return [
        {
            'id': m['id'],
            'contract': m['contractId'],
            'building': m['building'],
            'dma': m['dma'],
            'type': m['propertyType']
        }
        for m in meters
    ]

def build_cotai_calendar(all_consumption, meter_map):
    """Build Cotai calendar (non-residential top consumers per day)."""
    result = []
    for date in DATES:
        day_vals = []
        for mid, dates in all_consumption.items():
            if date not in dates:
                continue
            info = meter_map.get(mid, {})
            if info.get('isResidential'):
                continue
            if info.get('dma') != 'Zone-3':
                continue
            day_vals.append({
                'meterId': mid,
                'total': round(dates[date], 0),
                'buildingName': info.get('building', ''),
                'contractId': info.get('contractId', '')
            })
        day_vals.sort(key=lambda x: -x['total'])
        result.append({'date': date, 'items': day_vals[:15]})
    return result

def build_weekly(daily_dma, rainfall):
    """Build weekly aggregation."""
    weeks = []
    week_start = 0
    while week_start < NUM_DAYS:
        week_end = min(week_start + 6, NUM_DAYS - 1)
        week_dates = DATES[week_start:week_end + 1]

        total_by_dma = {dma: 0 for dma in DMA_ZONES}
        wd_totals = {dma: {'res': 0, 'nonRes': 0, 'wd_count': 0, 'we_count': 0} for dma in DMA_ZONES}
        daily_totals = []

        for d in week_dates:
            day = next((x for x in daily_dma if x['date'] == d), None)
            if not day:
                continue
            for dma in DMA_ZONES:
                v = day['dmas'][dma]
                total_by_dma[dma] += v['total']
                dow = (datetime.strptime(d, '%Y-%m-%d')).weekday()
                if dow < 5:
                    wd_totals[dma]['res'] += v['residential']
                    wd_totals[dma]['nonRes'] += v['nonResidential']
                    wd_totals[dma]['wd_count'] += 1
                else:
                    wd_totals[dma]['res'] += v['residential']
                    wd_totals[dma]['nonRes'] += v['nonResidential']
                    wd_totals[dma]['we_count'] += 1
            daily_totals.append({'date': d, 'total': round(sum(day['dmas'][dma]['total'] for dma in DMA_ZONES), 2)})

        grand_total = sum(total_by_dma.values())
        rain_total = sum(rainfall.get(d, 0) for d in week_dates)

        wd_by_dma_res = {}
        for dma in DMA_ZONES:
            wd_count = max(1, wd_totals[dma]['wd_count'])
            we_count = max(1, wd_totals[dma]['we_count'])
            wd_by_dma_res[dma] = {
                'resWdAvg': round(wd_totals[dma]['res'] / wd_count, 2),
                'resWeAvg': round(wd_totals[dma]['res'] / we_count, 2),
                'nonResWdAvg': round(wd_totals[dma]['nonRes'] / wd_count, 2),
                'nonResWeAvg': round(wd_totals[dma]['nonRes'] / we_count, 2)
            }

        label_start = (START_DATE + timedelta(days=week_start)).strftime('%m-%d')
        label_end = (START_DATE + timedelta(days=week_end)).strftime('%m-%d')

        weeks.append({
            'weekStart': DATES[week_start],
            'weekEnd': DATES[week_end],
            'label': f"{label_start}~{label_end}",
            'dates': week_dates,
            'totalByDma': {dma: round(v, 0) for dma, v in total_by_dma.items()},
            'grandTotal': round(grand_total, 0),
            'weekdayAvg': round(grand_total / max(1, sum(1 for d in week_dates if datetime.strptime(d, '%Y-%m-%d').weekday() < 5)), 2),
            'weekendAvg': round(grand_total / max(1, sum(1 for d in week_dates if datetime.strptime(d, '%Y-%m-%d').weekday() >= 5)), 2),
            'wdByDmaRes': wd_by_dma_res,
            'rain': round(rain_total, 1),
            'dailyTotals': daily_totals
        })
        week_start += 7
    return weeks

def build_predictions(all_consumption, meters, meter_map):
    """Build predictions for top 50 meters by consumption."""
    # Rank meters by total consumption
    meter_totals = {}
    for mid, dates in all_consumption.items():
        meter_totals[mid] = sum(dates.values())
    top50 = sorted(meter_totals.items(), key=lambda x: -x[1])[:50]

    predictions = []
    for mid, total in top50:
        info = meter_map.get(mid, {})
        # Generate fitted values (historical)
        fitted = []
        historical_dates = DATES[:NUM_DAYS - 7]
        avg = total / len(historical_dates) if historical_dates else 1
        for d in historical_dates:
            actual = all_consumption.get(mid, {}).get(d, avg)
            noise = random.gauss(0, avg * 0.1)
            fitted_val = actual + noise
            fitted.append({'date': d, 'actual': round(actual, 2), 'fitted': round(max(0, fitted_val), 2)})

        # Generate future predictions
        preds = []
        slope = random.uniform(-0.02, 0.02) * avg
        for i in range(7):
            d = DATES[NUM_DAYS - 7 + i]
            val = avg + slope * i + random.gauss(0, avg * 0.05)
            preds.append({'date': d, 'value': round(max(0, val), 2)})

        model_score = round(random.uniform(0.5, 0.95), 4)
        trend = 'up' if slope > 0 else 'down'

        predictions.append({
            'meterId': mid,
            'fitted': fitted,
            'predictions': preds,
            'modelScore': model_score,
            'avgHistorical': round(avg, 2),
            'trend': trend,
            'totalHistorical': round(total, 2),
            'info': {
                'dma': info.get('dma', ''),
                'propertyType': info.get('propertyType', ''),
                'buildingName': info.get('building', '')
            }
        })

    return {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'historicalRange': {'start': DATES[0], 'end': DATES[NUM_DAYS - 8], 'days': NUM_DAYS - 7},
        'predictionDays': 7,
        'totalMeters': 50,
        'predictions': predictions
    }

def build_predictions_by_building(all_consumption, meters, meter_map):
    """Build predictions aggregated by building for Zone-3."""
    # Group meters by building in Zone-3
    buildings = {}
    for m in meters:
        if m['dma'] != 'Zone-3':
            continue
        bname = m['building']
        buildings.setdefault(bname, {'meters': [], 'type': m['propertyType']})
        buildings[bname]['meters'].append(m['id'])

    predictions = []
    for bname, bdata in buildings.items():
        mids = bdata['meters']
        # Aggregate consumption
        building_total = 0
        building_daily = {}
        for d in DATES:
            day_total = sum(all_consumption.get(mid, {}).get(d, 0) for mid in mids)
            building_daily[d] = day_total
            building_total += day_total

        avg = building_total / NUM_DAYS if NUM_DAYS else 1
        fitted = []
        for d in DATES[:NUM_DAYS - 7]:
            actual = building_daily.get(d, avg)
            noise = random.gauss(0, avg * 0.08)
            fitted.append({'date': d, 'actual': round(actual, 2), 'fitted': round(max(0, actual + noise), 2)})

        preds = []
        slope = random.uniform(-0.015, 0.015) * avg
        for i in range(7):
            d = DATES[NUM_DAYS - 7 + i]
            val = avg + slope * i + random.gauss(0, avg * 0.04)
            preds.append({'date': d, 'value': round(max(0, val), 2)})

        predictions.append({
            'building': bname,
            'fitted': fitted,
            'predictions': preds,
            'modelScore': round(random.uniform(0.55, 0.92), 4),
            'avgHistorical': round(avg, 2),
            'trend': 'up' if slope > 0 else 'down',
            'totalHistorical': round(building_total, 2),
            'meterCount': len(mids),
            'propertyType': bdata['type']
        })

    predictions.sort(key=lambda x: -x['totalHistorical'])

    return {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'dma': 'Zone-3',
        'historicalRange': {'start': DATES[0], 'end': DATES[NUM_DAYS - 8], 'days': NUM_DAYS - 7},
        'predictionDays': 7,
        'totalBuildings': len(predictions),
        'predictions': predictions
    }

def build_meter_monthly(all_consumption, meters):
    """Build meter monthly aggregation."""
    result = {}
    months = sorted(set(d[:7] for d in DATES))
    for m in meters:
        mid = m['id']
        monthly = {}
        for month in months:
            month_dates = [d for d in DATES if d.startswith(month)]
            total = sum(all_consumption.get(mid, {}).get(d, 0) for d in month_dates)
            monthly[month] = round(total, 2)
        result[mid] = monthly
    return result

def build_meter_daily(all_consumption):
    """Build meter daily data (same as all_consumption)."""
    return {mid: {d: round(v, 2) for d, v in dates.items()} for mid, dates in all_consumption.items()}

def main():
    print("Generating mock data...")

    # Generate base data
    buildings = gen_building_pool()
    meters = gen_meters(buildings)
    meter_map = {m['id']: m for m in meters}
    rainfall = gen_rainfall()

    # Generate consumption
    all_consumption = {}
    for m in meters:
        mid = m['id']
        all_consumption[mid] = {}
        for i, date in enumerate(DATES):
            all_consumption[mid][date] = gen_consumption(m, i)

    # Inject anomalies
    anomalies = inject_anomalies(meters, all_consumption)
    print(f"  Anomalies: {len(anomalies)}")

    # Build all output files
    daily_dma = build_daily_dma(all_consumption, meters, rainfall)
    print("  daily_dma.json")

    daily_top20 = build_top20_daily(all_consumption, meters, meter_map)
    print("  daily_top20.json")

    daily_top20_by_dma = build_top20_by_dma(all_consumption, meter_map)
    print("  daily_top20_by_dma.json")

    daily_total_by_dma = build_daily_total_by_dma(daily_dma)
    print("  daily_total_by_dma.json")

    monthly_diff = build_monthly_diff(all_consumption, meters, meter_map)
    print("  monthly_main_sub_diff.json")

    rank_changes = build_rank_changes(all_consumption, meters, meter_map)
    print("  rank_changes.json")

    search_index = build_search_index(meters)
    print("  search_index.json")

    cotai_calendar = build_cotai_calendar(all_consumption, meter_map)
    print("  cotai_calendar.json")

    weekly = build_weekly(daily_dma, rainfall)
    print("  weekly.json")

    predictions = build_predictions(all_consumption, meters, meter_map)
    print("  predictions.json")

    predictions_by_building = build_predictions_by_building(all_consumption, meters, meter_map)
    print("  predictions_by_building.json")

    meter_monthly = build_meter_monthly(all_consumption, meters)
    print("  meterMonthly (in all_data)")

    meter_daily = build_meter_daily(all_consumption)
    print("  meterDaily (in all_data)")

    # Build all_data.json (combined)
    all_data = {
        'dma': daily_dma,
        'top20': daily_top20,
        'top20dma': daily_top20_by_dma,
        'diff': monthly_diff,
        'dates': DATES,
        'rank': rank_changes[:50],
        'anomalies': anomalies,
        'cotai': cotai_calendar,
        'trend': daily_total_by_dma,
        'search': search_index,
        'meterMonthly': meter_monthly,
        'meterDaily': meter_daily,
        'weekly': weekly
    }

    # Write all files
    files = {
        'all_data.json': all_data,
        'predictions.json': predictions,
        'predictions_by_building.json': predictions_by_building,
        'anomalies.json': anomalies,
        'available_dates.json': DATES,
        'cotai_calendar.json': cotai_calendar,
        'daily_dma.json': daily_dma,
        'daily_top20.json': daily_top20,
        'daily_top20_by_dma.json': daily_top20_by_dma,
        'daily_total_by_dma.json': daily_total_by_dma,
        'meter_info.json': {m['id']: {
            'dma': m['dma'],
            'propertyType': m['propertyType'],
            'isResidential': m['isResidential'],
            'contractId': m['contractId'],
            'buildingName': m['building'],
            'supplyMode': m['supplyMode'],
            'mainCode': m['mainCode']
        } for m in meters},
        'meter_daily.json': meter_daily,
        'monthly_main_sub_diff.json': monthly_diff,
        'rank_changes.json': rank_changes,
        'search_index.json': search_index,
        'weekly.json': weekly
    }

    for fname, data in files.items():
        fpath = os.path.join(OUTPUT_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        size = os.path.getsize(fpath)
        print(f"  Written: {fname} ({size/1024:.0f}KB)")

    print(f"\nDone! {len(DATES)} days, {len(meters)} meters, {len(anomalies)} anomalies")
    print(f"Output: {OUTPUT_DIR}")

if __name__ == '__main__':
    main()
