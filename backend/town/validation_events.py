"""
validation_events.py — real events the town can be checked against.

Each event has two halves that must never be mixed up:

  inputs     what was imposed from outside (a lockdown, a price rise, a rate hike). These are fed to the
             town as its shock. They are NOT compared with anything.
  outcomes   what happened to people afterwards, as published (job losses, cutting food, borrowing,
             spending). The town is never told these; it has to produce them, and the scorecard compares.

Every outcome carries its source. Add an event by adding an entry to EVENTS; nothing else needs to change.
Figures are the published ones, rounded as the source rounded them. Where a survey covered only poorer
households or workers (the Azim Premji University one did), the outcome says which group of residents to
compare with: "low_income" = the residents the town classes as lower-income, "all" = everyone.

How the outcomes are measured in the town is defined in validation.py (MEASURES).
"""

from __future__ import annotations

from typing import Dict, List

EVENTS: List[dict] = [
    {
        "id": "covid-2020",
        "title": "COVID-19 national lockdown, India (March–May 2020)",
        "year": 2020,
        "summary": ("A nationwide stay-at-home order from 25 March 2020: only grocery shops, pharmacies and clinics stayed open. "
                    "The town is put under the same order and nothing else; the job losses, hunger and borrowing are left for it to produce."),
        "inputs": {
            "lockdown": True,
            "essential_cost": 0.0,
            "demand": 0.0,
            "credit_tightness": 0.0,
            "note": ("Stay-at-home order with only the essential shops open. No price rise, job cuts, income cut or credit squeeze "
                     "is applied: those are outcomes the town has to produce."),
        },
        "run": {"days": 30, "pace": "fast"},
        "outcomes": [
            {"measure": "jobless_rise", "group": "all", "real": 14.8,
             "label": "Rise in the share of workers without work",
             "source": "CMIE: unemployment rate 8.7% in March 2020 to 23.5% in April 2020",
             "url": "https://www.businesstoday.in/amp/latest/economy-politics/story/india-unemployment-rate-april-cmie-highest-257055-2020-05-01"},
            {"measure": "jobless_rise", "group": "workers_daily", "real": 67.0,
             "label": "Casual and self-employed workers who lost their work",
             "source": "Azim Premji University survey, May 2020: 67% of workers interviewed had lost employment",
             "url": "https://www.thenewsminute.com/news/covid-19-lockdown-has-devastated-livelihoods-azim-premji-uni-survey-124499"},
            {"measure": "food_short", "group": "low_income", "real": 74.0,
             "label": "Households that ate less than before",
             "source": "Azim Premji University phone survey of 3,970 households, 12+ states, May 2020: 74% consumed less food",
             "url": "https://www.thenewsminute.com/news/covid-19-lockdown-has-devastated-livelihoods-azim-premji-uni-survey-124499"},
            {"measure": "borrowed", "group": "low_income", "real": 37.0,
             "label": "Households that took informal loans",
             "source": "Azim Premji University survey, May 2020: 37% took loans from informal sources, including moneylenders",
             "url": "https://www.thenewsminute.com/news/covid-19-lockdown-has-devastated-livelihoods-azim-premji-uni-survey-124499"},
            {"measure": "income_change", "group": "workers_daily", "real": -47.0,
             "label": "Earnings of casual and self-employed workers",
             "source": "Azim Premji University survey: casual workers' weekly earnings fell from Rs 940 to Rs 495 (about -47%)",
             "url": "https://www.thequint.com/amp/story/coronavirus/67-workers-lost-livelihood-over-covid-19-lockdown-survey"},
            {"measure": "spending_change", "group": "all", "real": -26.7,
             "label": "Household spending",
             "source": "NSO: private final consumption expenditure fell 26.7% in April–June 2020 (real, year on year)",
             "url": "https://www.business-standard.com/amp/article/economy-policy/outlook-fraught-with-uncertainty-120083101341_1.html"},
        ],
        "caveats": ("The survey figures come from phone interviews with poorer households and workers, so they are compared with the town's "
                    "lower-income residents. Official consumption is for the whole April–June quarter, which includes the first reopening."),
    },
    {
        "id": "covid-2021",
        "title": "COVID-19 second wave, state lockdowns (April–May 2021)",
        "year": 2021,
        "summary": ("State-by-state restrictions in April and May 2021 shut most workplaces again. The town goes under a stay-at-home order; "
                    "only the rise in joblessness is compared, because that is the figure with a clean monthly series."),
        "inputs": {
            "lockdown": True,
            "essential_cost": 0.0,
            "demand": 0.0,
            "credit_tightness": 0.0,
            "note": "Stay-at-home order with only the essential shops open. No price, income or credit change is applied.",
        },
        "run": {"days": 30, "pace": "fast"},
        "outcomes": [
            {"measure": "jobless_rise", "group": "all", "real": 3.9,
             "label": "Rise in the share of workers without work",
             "source": "CMIE: unemployment rate 7.97% in April 2021 to 11.9% in May 2021",
             "url": "https://www.businesstoday.in/amp/latest/economy-politics/story/unemployment-rate-shoots-up-to-12-month-high-of-119-in-may-298103-2021-06-03"},
        ],
        "caveats": ("The second-wave restrictions were patchy and partial, while the town's order is total, so a town that loses more work than "
                    "reality is expected here."),
    },
]

BY_ID: Dict[str, dict] = {e["id"]: e for e in EVENTS}
