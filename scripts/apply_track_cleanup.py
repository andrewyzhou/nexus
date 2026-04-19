"""
Apply the manually-curated track-name cleanup to ticker_track.json.

This is NOT a general normalization script. The RENAMES dict is an
explicit per-track decision list built by going through all 1122
unique track names by hand and fixing what was obviously broken:
leading quote characters, typos, capitalization inconsistencies, and
duplicates-with-different-spellings.

Debatable cases are captured in DEBATABLE and left unchanged until a
human decides — the admin page at /nexus/admin is the long-term tool
for that.

Run:
    python scripts/apply_track_cleanup.py \\
        --in  ticker_track.json \\
        --out ticker_track_cleaned.json \\
        --report track_cleanup_report.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# Explicit per-track decisions.
#
# { "old name": "new name" }  — map one or many old spellings to the
# canonical form. If two old spellings map to the same new name they
# get merged (tickers from both go into the merged track).
#
# Decisions made going through the list in alphabetical order. Every
# entry is a manual judgment; categories:
#   - leading-quote typos (strip the literal ")
#   - simple spelling typos (deadlership → dealership, etc.)
#   - capitalization (airlines → Airlines when siblings are Title Case)
#   - trailing punctuation (trailing comma, double spaces)
#   - dup-with-different-spelling merges (cannabis + Cannabis)
#   - country-name normalization (Hongkong → Hong Kong, Brasil → Brazil,
#     Netherland → Netherlands, Switzland → Switzerland, Vietname → Vietnam)
# ─────────────────────────────────────────────────────────────────────
RENAMES: dict[str, str] = {
    # ── leading quote-character typos ──
    '"Building materials - Glass':  'Building Materials - Glass',
    '"Business Services - Tax':     'Business Services - Tax',
    '"Crypto Infra':                'Crypto Infra',
    '"Fragrance':                   'Fragrance',
    '"Major Drugs - Obesity':       'Major Drugs - Obesity',
    '"Solar - Tracker':             'Solar - Tracker',
    '"testing':                     'Testing',   # RAISED in report — what is this?
    '"Trading - Stock':             'Trading - Stock',

    # ── capitalization fixes (lowercase → Title Case to match siblings) ──
    '3D printing':                            '3D Printing',
    'adhesive & label':                       'Adhesive & Label',
    'aesthetic medical products':             'Aesthetic Medical Products',
    'AI data center + bitcoin miner':         'AI Data Center + Bitcoin Miner',
    'AI data center - large':                 'AI Data Center - Large',
    'AI drug discovery':                      'AI Drug Discovery',
    'AI security China':                      'AI Security - China',
    'AI software - large':                    'AI Software - Large',
    'AI-powered printing & tools':            'AI-Powered Printing & Tools',
    'airlines - europe':                      'Airlines - Europe',
    'apparel brands & retail':                'Apparel Brands & Retail',
    'appliance':                              'Appliance',
    'appliance - international - large':      'Appliance - International - Large',
    'asset management - medium':              'Asset Management - Medium',
    'auto deadlership':                       'Auto Dealership',          # typo: dealership
    'auto manufacturers - china':             'Auto Manufacturers - China',
    'auto parts manufacturers':               'Auto Parts Manufacturers',
    'autoimmune TYK2':                        'Autoimmune TYK2',
    'automobile - korea':                     'Automobile - Korea',
    'autonomous driving':                     'Autonomous Driving',
    'autonomous driving - china':             'Autonomous Driving - China',
    'autonomous driving - small':             'Autonomous Driving - Small',
    'banking software':                       'Banking Software',
    'banks - argentina':                      'Banks - Argentina',
    'banks - canada - 4-6':                   'Banks - Canada - 4-6',
    'banks - chile':                          'Banks - Chile',
    'banks - mid america':                    'Banks - Mid America',
    'banks big 4 - china':                    'Banks - China - Big4',
    'banks Hongkong - large':                 'Banks - Hong Kong - Large',
    'banks in greece':                        'Banks - Greece',
    'bdc - large':                            'BDC - Large',
    'bdc - medium':                           'BDC - Medium',
    'beauty and jewelry retail':              'Beauty & Jewelry Retail',
    'big data':                               'Big Data',
    'biomedical measurement':                 'Biomedical Measurement',
    'bitcoin miner':                          'Bitcoin Miner',
    'bitcoin mining':                         'Bitcoin Miner',            # merge with above
    'Bitcoin treasury':                       'Bitcoin Treasury',
    'Bitcoin treasury -small':                'Bitcoin Treasury - Small',
    'btc treasury - small':                   'Bitcoin Treasury - Small', # merge
    'brain chips':                            'Brain Chips',
    'brokerage - large':                      'Brokerage - Large',
    'building materials - Ceramic & Toilet':  'Building Materials - Ceramic & Toilet',
    'building materials - large':             'Building Materials - Large',
    'building service':                       'Building Service',
    'cannabis':                               'Cannabis',                 # merge with Cannabis
    'cement - usa':                           'Cement - USA',
    'cell therapies':                         'Cell Therapy',
    'cell therapy - small':                   'Cell Therapy - Small',
    'chemical distribution':                  'Chemical Distribution',
    'chemical for textile':                   'Chemical for Textile',
    'chips for phone/PC':                     'Chips for Phone / PC',
    'chips for video & image':                'Chips for Video & Image',
    'clothes retail - small':                 'Clothes Retail - Small',
    'cold storage':                           'Cold Storage',
    'commercial REIT - canada':               'Commercial REIT - Canada',
    'communication software':                 'Communication Software',   # merge
    'community banks - Virginia':             'Community Banks - Virginia',
    'consulting & insights':                  'Consulting & Insights',
    'copper miner':                           'Copper Miner',
    'copper miner - usa':                     'Copper Miner - USA',
    'credit card':                            'Credit Card',
    'cross-border remittance':                'Cross-Border Remittance',
    'cruise':                                 'Cruise',
    'danaher spinoff - industrial':           'Danaher Spinoff - Industrial',
    'defense - large -drone':                 'Defense - Large - Drone',
    'defense - security':                     'Defense - Security',
    'dental equipment':                       'Dental Equipment',
    'diagnostic testing - Under1B':           'Diagnostic Testing - Under 1B',
    'domain name':                            'Domain Name',
    'drainage & water treatment':             'Drainage & Water Treatment',
    'drone':                                  'Drone',
    'drone - small':                          'Drone - Small',
    'dry bulk shipping':                      'Dry Bulk Shipping',
    'elecronics retail':                      'Electronics Retail',       # typo: elecronics
    'electric bike manufacture':              'Electric Bike Manufacture',
    'electric equipment - japan':             'Electric Equipment - Japan',
    'electric utility - japan & korea':       'Electric Utility - Japan & Korea',
    'electrical distribution':                'Electrical Distribution',
    'electronic display':                     'Electronic Display',
    'electronics manufacturer':               'Electronics Manufacturer',
    'emission control & catalysis':           'Emission Control & Catalysis',
    'energy storage - battery':               'Energy Storage - Battery',
    'engineered materials':                   'Engineered Materials',
    'entertainment giants':                   'Entertainment Giants',
    'equipment - IOT - small':                'Equipment - IOT - Small',
    'equipment rental':                       'Equipment Rental',
    'ERP software':                           'ERP Software',
    'etch equipment - small':                 'Etch Equipment - Small',
    'etherum treasury':                       'Ethereum Treasury',        # typo: etherum
    'Ettherum Treasury':                      'Ethereum Treasury',        # typo: Ettherum; merge
    'europe games':                           'Games - Europe',
    'eye-care drugs':                         'Eye-Care Drugs',
    'fashio retail - discounted':             'Fashion Retail - Discounted',   # typo: fashio
    'fastcasual - grill':                     'Fast Casual - Grill',
    'fastfood - burges & sandwiches':         'Fast Food - Burgers & Sandwiches',  # typos
    'fiber & connectivity':                   'Fiber & Connectivity',
    'food distribution - medium':             'Food Distribution - Medium',
    'food distribution - Small':              'Food Distribution - Small',
    'fuze & electronics':                     'Fuze & Electronics',
    'gas & liquid equipment':                 'Gas & Liquid Equipment',
    'general construction':                   'General Construction',
    'gene therapy - small':                   'Gene Therapy - Small',
    'gold & silver':                          'Gold & Silver',
    'gold & silver royalty':                  'Gold & Silver Royalty',
    'gold - africa - small-2':                'Gold - Africa - Small 2',
    'gold - usa - small':                     'Gold - USA - Small',
    'gold america':                           'Gold - America',
    'gold miner - america':                   'Gold Miner - America',
    'Gold Miner - America':                   'Gold Miner - America',     # canonical
    'gold miner - america - large':           'Gold Miner - America - Large',
    'gold miner - australia':                 'Gold Miner - Australia',
    'gold miner - canada':                    'Gold Miner - Canada',
    'gold prospecting - america':             'Gold Prospecting - America',
    'gold prospecting - canada':              'Gold Prospecting - Canada',
    'gold royalty - medium':                  'Gold Royalty - Medium',
    'gold royalty - small':                   'Gold Royalty - Small',
    'grocery shopping -canada':               'Grocery Shopping - Canada',
    'health & leisure services':              'Health & Leisure Services',
    'health data platform':                   'Health Data Platform',
    'health insurance & analytics':           'Health Insurance & Analytics',
    'health insurance & PBM':                 'Health Insurance & PBM',
    'health insurance - large':               'Health Insurance - Large',
    'health services':                        'Health Services',
    'hematology':                             'Hematology',
    'hyperscaler':                            'Hyperscaler',
    'immunity biotech':                       'Immunity Biotech',
    'infectious diseases':                    'Infectious Diseases',
    'infracturacture construction - small':   'Infrastructure Construction - Small',  # typo
    'infrastructure construction - south':    'Infrastructure Construction - South',
    'ingredient & nutrition':                 'Ingredient & Nutrition',
    'installation of insulation':             'Installation of Insulation',
    'insurance broker - big4':                'Insurance Broker - Big4',
    'insurance broker - health':              'Insurance Broker - Health',
    'insurance broker - large':               'Insurance Broker - Large',
    'insurance broker - medium':              'Insurance Broker - Medium',
    'internet advertising':                   'Internet Advertising',
    'internet games - western':               'Internet Games - Western',
    'internet insurance - p&c':               'Internet Insurance - P&C',
    'intimate retail':                        'Intimate Retail',
    'investment banks - medium':              'Investment Banks - Medium',
    'investment track':                       'Investment Track',         # RAISED — meta?
    'IOT infrastructure':                     'IOT Infrastructure',
    'IP licensing':                           'IP Licensing',
    'japan & korean games':                   'Games - Japan & Korea',
    'large discount retailer':                'Large Discount Retailer',
    'legal software & service':               'Legal Software & Service',
    'less-lethal weapons':                    'Less-Lethal Weapons',
    'lighting':                               'Lighting',
    'location, map, navigation,':             'Location, Map, Navigation',  # trailing comma
    'logistics - integrated':                 'Logistics - Integrated',
    'logistics - LTL':                        'Logistics - LTL',
    'lubricants':                             'Lubricants',
    'machine vision':                         'Machine Vision',
    'machinery - japan':                      'Machinery - Japan',
    'marine shipping - LNG':                  'Marine Shipping - LNG',
    'marine shipping - LNG - small':          'Marine Shipping - LNG - Small',
    'marketing software':                     'Marketing Software',
    'medical device - small':                 'Medical Device - Small',   # merge with Title Case
    'medical diagnosis and measure':          'Medical Diagnosis & Measure',
    'medical imaging equipment':              'Medical Imaging Equipment',
    'metal conglomerate':                     'Metal Conglomerate',
    'metal packaging':                        'Metal Packaging',
    'meter':                                  'Meter',
    'metrology & PDC':                        'Metrology & PDC',
    'midstream - gas':                        'Midstream - Gas',
    'midstream - medium':                     'Midstream - Medium',
    'midstream - medium,':                    'Midstream - Medium',       # merge (trailing comma)
    'mobile home builder':                    'Mobile Home Builder',
    'mortgage finance - large':               'Mortgage Finance - Large',
    'motorcycles & RV':                       'Motorcycles & RV',
    'natural gas compression services':       'Natural Gas Compression Services',
    'network security':                       'Network Security',
    'networking - large':                     'Networking - Large',
    'neuroscience-focused':                   'Neuroscience-Focused',
    'News media':                             'News Media',
    'nuclear SMR':                            'Nuclear SMR',
    'offshore drilling':                      'Offshore Drilling',
    'offshore drilling  - small':             'Offshore Drilling - Small',  # double space
    'oil integrated - usa':                   'Oil Integrated - USA',
    'oilfield service - medium':              'Oilfield Service - Medium',
    'Oilfield service - Europe':              'Oilfield Service - Europe',
    'Oilfield service - Large':               'Oilfield Service - Large',
    'oncology - T-cell - small':              'Oncology - T-Cell - Small',
    'owning and chartering of containerships':'Containership Owner & Charter',  # shortened
    'packaged food - small':                  'Packaged Food - Small',
    'packaging & testing':                    'Packaging & Testing',
    'packaging - paper':                      'Packaging - Paper',
    'paints and coatings':                    'Paints & Coatings',
    'paints and coatings - international':    'Paints & Coatings - International',
    'Payment - large':                        'Payment - Large',
    'Payment - small':                        'Payment - Small',          # merge with Title Case
    'plantium miner':                         'Platinum Miner',            # typo
    'plastic packaging':                      'Plastic Packaging',
    'pool retail':                            'Pool Retail',
    'ports':                                  'Ports',
    'power chips - small':                    'Power Chips - Small',
    'power generator - large':                'Power Generator - Large',
    'power infracturacture':                  'Power Infrastructure',     # typo: infracturacture
    'powered engines':                        'Powered Engines',
    'probe card':                             'Probe Card',
    'productivity software - medium':         'Productivity Software - Medium',
    'pump & dump':                            'Pump & Dump',
    'pump & dump - agency':                   'Pump & Dump - Agency',
    'pump & dump - HK':                       'Pump & Dump - HK',
    'pump & dump - large':                    'Pump & Dump - Large',
    'pump & dump DGNX':                       'Pump & Dump - DGNX',
    'quatum - startup':                       'Quantum - Startup',         # typo: quatum
    'radio therapy':                          'Radio Therapy',
    'rare earth - critical':                  'Rare Earth - Critical',
    'rare earth - prospecting':               'Rare Earth - Prospecting',
    'rare earth - western':                   'Rare Earth - Western',
    'real estate - china':                    'Real Estate - China',
    'real estate brokerage':                  'Real Estate Brokerage',
    'recruiting':                             'Recruiting',
    'recycling':                              'Recycling',
    'regional banks - Alabama':               'Regional Banks - Alabama',
    'regional banks - Mississippi':           'Regional Banks - Mississippi',
    'regional banks - NY/NJ':                 'Regional Banks - NY / NJ',
    'regional banks - Virginia':              'Regional Banks - Virginia',
    'rental - medium':                        'Rental - Medium',
    'rental - small':                         'Rental - Small',
    'resorts':                                'Resorts',
    'respiratory equipment':                  'Respiratory Equipment',
    'restaurant - small':                     'Restaurant - Small',
    'road infrastructure':                    'Road Infrastructure',
    'robotics':                               'Robotics',
    'roll-on roll-off (RoRo)':                'Roll-On Roll-Off (RoRo)',
    'safety equipment':                       'Safety Equipment',
    'satelite communication':                 'Satellite Communication',   # typo: satelite
    'Satelite & Spacecraft - Medium':         'Satellite & Spacecraft - Medium',
    'Satelite Communication - Europe & America': 'Satellite Communication - Europe & America',
    'satelite communication - small':         'Satellite Communication - Small',
    'satelite image':                         'Satellite Image',
    'Satelite Launch & Manufacture':          'Satellite Launch & Manufacture',
    'security & protection service':          'Security & Protection Service',
    'semiconductor substrates':               'Semiconductor Substrates',
    'semicondutor bonding':                   'Semiconductor Bonding',    # typo
    'semicondutor equipments - large':        'Semiconductor Equipment - Large',  # typo + pluralization
    'semicondutor materials':                 'Semiconductor Materials',   # typo
    'semicondutor packaging':                 'Semiconductor Packaging',   # typo
    'seminconductor MEMS':                    'Semiconductor MEMS',        # typo
    'Chemical for Semicondutors':             'Chemical for Semiconductors',  # typo
    'shipbuilding - asia':                    'Ship Building - Asia',
    'shopping centers':                       'Shopping Centers',
    'shopping centers - medium':              'Shopping Centers - Medium',
    'silver - large':                         'Silver - Large',
    'silver miner - bolivia & mexico':        'Silver Miner - Bolivia & Mexico',
    'silver miner - latin america':           'Silver Miner - Latin America',
    'silver miner - usa':                     'Silver Miner - USA',
    'silver prospecting - usa':               'Silver Prospecting - USA',
    'smartphone & pc integrated':             'Smartphone & PC Integrated',
    'software - advertising - small':         'Software - Advertising - Small',
    'software - chip design':                 'Software - Chip Design',
    'software - education':                   'Software - Education',
    'software - IOT':                         'Software - IOT',
    'solar pane - usa':                       'Solar Panel - USA',         # typo: pane
    'Special Chemical Europe':                'Special Chemical - Europe',
    'speciality & children\'s retail':        'Specialty & Children\'s Retail',  # Speciality → Specialty
    'Speciality Insurance - Small':           'Specialty Insurance - Small',
    'Insurance - Speciality':                 'Insurance - Specialty',
    'Speciality Retail - Auction or Cars':    'Specialty Retail - Auction or Cars',
    'sports betting':                         'Sports Betting',
    'sports retail':                          'Sports Retail',
    'storytelling':                           'Storytelling',
    'student loans':                          'Student Loans',
    'supply chain software':                  'Supply Chain Software',
    'test & burn-in equipment':               'Test & Burn-In Equipment',
    'test equipment - small':                 'Test Equipment - Small',
    'thermal and light oil':                  'Thermal & Light Oil',
    'TV media':                               'TV Media',
    'TV media - medium':                      'TV Media - Medium',
    'ulcerative colitis':                     'Ulcerative Colitis',
    'uniforms rental & services':             'Uniforms Rental & Services',
    'us banks - large':                       'Banks - USA - Large',
    'used car retail':                        'Used Car Retail',
    'utility - diversified':                  'Utility - Diversified',
    'utility - electricity':                  'Utility - Electricity',
    'vertical softwares':                     'Vertical Software',
    'wafer cutting & cleaning tools':         'Wafer Cutting & Cleaning Tools',
    'water & pool equipments':                'Water & Pool Equipment',
    'water, hygiene, and pest control':       'Water, Hygiene & Pest Control',
    'wood products - canada':                 'Wood Products - Canada',
    'wood products - usa':                    'Wood Products - USA',
    'wound care and regenerative therapies':  'Wound Care & Regenerative Therapy',

    # ── country / region name normalization ──
    'Banks - Germany & Netherland':           'Banks - Germany & Netherlands',
    'Insurance - Diversified - Netherland':   'Insurance - Diversified - Netherlands',
    'Semiconductor Equipments - Netherland':  'Semiconductor Equipment - Netherlands',  # also plural fix
    'Banks - Hongkong - Medium':              'Banks - Hong Kong - Medium',
    'Telecom - Hongkong':                     'Telecom - Hong Kong',
    'Utilities - Hongkong':                   'Utilities - Hong Kong',
    'Insurance - Switzland - Diversified':    'Insurance - Switzerland - Diversified',
    'EV - US & Vietname':                     'EV - US & Vietnam',
    'Meat Processing - Brasil':               'Meat Processing - Brazil',  # merge with existing Meat Processing - Brazil
    'Oil & Gas Equipment & Services - Internatioinal': 'Oil & Gas Equipment & Services - International',  # typo
    'banks - canada - 4-6':                   'Banks - Canada - 4-6',

    # ── misc typos / spelling ──
    'Cable  & Media - US':                    'Cable & Media - US',       # double space
    'Chocalates':                             'Chocolates',
    'Chocalates - Small':                     'Chocolates - Small',
    'communcation device - medium':           'Communication Device - Medium',   # typo: communcation
    'communcation software - small':          'Communication Software - Small',
    'Crypto Treasure - small':                'Crypto Treasury - Small',  # typo: Treasure → Treasury
    'Crypto Treasury - large':                'Crypto Treasury - Large',
    'Cyrto Treasury - Small':                 'Crypto Treasury - Small',   # typo: Cyrto
    'Diary - China':                          'Dairy - China',             # typo
    'Diary Product - Europe':                 'Dairy Product - Europe',
    'Education Service - Profesional':        'Education Service - Professional',
    'Eyeclasses':                             'Eyeglasses',
    'Gas Compression Equiopment & Service':   'Gas Compression Equipment & Service',
    'Hard Disk Drive (HDD)':                  'Hard Disk Drive (HDD)',
    'Hear-Aid':                               'Hearing Aid',
    'Insurnace - P&C - US - Small':           'Insurance - P&C - US - Small',  # typo
    'Loans & Credit Car':                     'Loans & Credit Card',       # missing d
    'OEM  - medium':                          'OEM - Medium',              # double space
    'OEM - medium':                           'OEM - Medium',
    'Oilfield Service - MedSmalll - Pump&Proppant': 'Oilfield Service - MedSmall - Pump & Proppant',
    'Pearl Tea & Icecream':                   'Pearl Tea & Ice Cream',
    'Private Credit  & Equity':               'Private Credit & Equity',   # double space
    'Real Estate Service - Commerical':       'Real Estate Service - Commercial',
    'Sugar & Sweetner':                       'Sugar & Sweetener',
    'Tire Manufactures - Major':              'Tire Manufacturers - Major',
    'Trucks Manufactures - Large':            'Truck Manufacturers - Large',
    'Vacation - Tmeshare':                    'Vacation - Timeshare',
    'ETH - Cryto - Dividend':                 'ETH - Crypto - Dividend',
    'ATM & retail macines':                   'ATM & Retail Machines',
    'Airspace - Parts & Repair':              'Aerospace - Parts & Repair',
    'antibodies':                             'Antibodies',
    'antibody testing':                       'Antibody Testing',
    'antibody-based products':                'Antibody-Based Products',
    'Annuity (Spinoff)':                      'Annuity (Spinoff)',
    'Waste Management - small':               'Waste Management - Small',
    'Water Utilities - small':                'Water Utilities - Small',
    'Winter clothing':                        'Winter Clothing',
    'Sol Treasury':                           'Solana Treasury',           # SOL is Solana — raise? I think this is obvious
    'gaming electronics':                     'Gaming Electronics',
    'Games - China - Medium':                 'Games - China - Medium',
    'Food Distribution - International':      'Food Distribution - International',

    # ── capitalized versions to match already-capitalized siblings ──
    'cannabis':                               'Cannabis',   # duplicate key above, harmless
}


# Cases I couldn't cleanly decide on my own — flagged for your review
# in the admin page.
DEBATABLE: list[dict] = [
    {
        "question": "What is the 'testing' track (7 tickers originally as '\"testing')? "
                    "Is it semiconductor testing, drug testing, or genuine placeholder / "
                    "dev-only data?",
        "tracks": ['"testing'],
        "default": "Renamed to 'Testing' pending decision",
    },
    {
        "question": "'investment track' (5 tickers) — is this literal meta placeholder or "
                    "a real category? Same question for 'health services' (5 tickers).",
        "tracks": ['investment track', 'health services'],
        "default": "Renamed to title case; kept separate",
    },
    {
        "question": "'Crypto Infra' (formerly with leading quote, 7 tickers) vs "
                    "'Crypto Infrastructure' (4 tickers) — merge?",
        "tracks": ['"Crypto Infra', 'Crypto Infrastructure'],
        "default": "Kept separate — short form may be intentional",
    },
    {
        "question": "'Medical Device - Small' (merged, 7 tickers) vs 'Medical Devices - Small' "
                    "(3 tickers) — singular/plural, same category? Merge?",
        "tracks": ['Medical Device - Small', 'Medical Devices - Small'],
        "default": "Kept separate pending decision",
    },
    {
        "question": "'community banks - Virginia' (5) and 'regional banks - Virginia' (4) — "
                    "same or different? The 'community' vs 'regional' distinction may be "
                    "meaningful for the banking taxonomy.",
        "tracks": ['community banks - Virginia', 'regional banks - Virginia'],
        "default": "Kept separate — community vs regional banking is a real distinction",
    },
    {
        "question": "Asset Management numbered batches: 'Asset Management - Medium - 3', "
                    "'Asset Management - Medium - 4', 'Asset Management - Medium -2' — are "
                    "these meaningful or internal batch IDs? Clean up naming inconsistency "
                    "('Medium -2' vs 'Medium - 3') regardless.",
        "tracks": ['Asset Management - Medium -2', 'Asset Management - Medium - 3',
                   'Asset Management - Medium - 4'],
        "default": "Left as-is for now; spacing inconsistency flagged",
    },
    {
        "question": "'Beer - Batch2' (3 tickers) — 'Batch2' looks like internal seeding "
                    "metadata. Real track or placeholder?",
        "tracks": ['Beer - Batch2'],
        "default": "Left as-is",
    },
    {
        "question": "'Asset Management - Batch2' — same question (internal batch?)",
        "tracks": ['Asset Management - Batch2'],
        "default": "Left as-is",
    },
    {
        "question": "Several 'pump & dump' variants (pump & dump, - agency, - HK, - large, "
                    "DGNX). Is this actually a classification of pump-and-dump scheme "
                    "stocks? Do we want to expose these on the graph at all?",
        "tracks": ['pump & dump', 'pump & dump - agency', 'pump & dump - HK',
                   'pump & dump - large', 'pump & dump DGNX'],
        "default": "Kept, capitalized consistently",
    },
    {
        "question": "'Sol Treasury' (4) — assumed to mean Solana treasury and renamed to "
                    "'Solana Treasury'. Confirm?",
        "tracks": ['Sol Treasury'],
        "default": "Renamed to 'Solana Treasury'",
    },
    {
        "question": "'Cruise & Entertainment - Genting' (3) — very specific to Genting "
                    "Group. Real category or a one-off?",
        "tracks": ['Cruise & Entertainment - Genting'],
        "default": "Kept as-is",
    },
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in",  dest="in_path",  default="ticker_track.json")
    p.add_argument("--out", dest="out_path", default="ticker_track_cleaned.json")
    p.add_argument("--report", default="track_cleanup_report.md")
    args = p.parse_args()

    src = json.loads(Path(args.in_path).read_text())
    print(f"Loaded {len(src)} ticker→track mappings "
          f"({len(set(src.values()))} unique tracks).")

    renamed_count = 0
    merged_into: dict[str, set[str]] = {}
    out: dict[str, str] = {}
    for ticker, track in src.items():
        new = RENAMES.get(track, track)
        out[ticker] = new
        if new != track:
            renamed_count += 1
            merged_into.setdefault(new, set()).add(track)

    n_unique_after = len(set(out.values()))
    print(f"Renamed {renamed_count} ticker entries.")
    print(f"Unique tracks: {len(set(src.values()))} → {n_unique_after} "
          f"(merged {len(set(src.values())) - n_unique_after}).")

    Path(args.out_path).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {args.out_path}")

    # Report
    lines = ["# Track cleanup report",
             "",
             f"- Source: `{args.in_path}` — {len(src)} tickers, "
             f"{len(set(src.values()))} unique tracks",
             f"- Output: `{args.out_path}` — {len(out)} tickers, "
             f"{n_unique_after} unique tracks",
             f"- Ticker entries renamed: {renamed_count}",
             f"- Duplicate tracks merged: "
             f"{len(set(src.values())) - n_unique_after}",
             "",
             "## Renames applied",
             ""]
    grouped = Counter()
    for new_name, olds in sorted(merged_into.items()):
        for old in sorted(olds):
            grouped[new_name] += 0   # ensure key exists
            lines.append(f"- `{old}` → `{new_name}`")
    lines.append("")
    lines.append("## Debatable cases (left unchanged or defaulted — please review)")
    lines.append("")
    for i, d in enumerate(DEBATABLE, 1):
        lines.append(f"### {i}. {d['question']}")
        lines.append("")
        for t in d["tracks"]:
            lines.append(f"- `{t}`")
        lines.append("")
        lines.append(f"**Default applied:** {d['default']}")
        lines.append("")
    Path(args.report).write_text("\n".join(lines))
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
