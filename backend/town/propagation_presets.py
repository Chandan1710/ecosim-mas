"""
propagation_presets.py — how each of the seven ready-made scenarios spreads through the town.

These chains are written by hand to match what the simulator actually does (the shock, the rules in
scenarios.py, and the economy in economy.py), so the Event propagation page shows the mechanism the
agents really live through rather than a plausible-sounding story. Each node has:

    id, description (what happens), category, magnitude, confidence, depends_on (which earlier nodes it
    follows from; several parents = a merge, several children = a branch) and note (the mechanism, and
    what the simulator does with it).

Categories: prices | employment | credit | policy | consumer_behaviour | trade | other
"""

from __future__ import annotations

from typing import Dict, List


def _n(i, desc, cat, mag, conf, deps, note):
    return {"id": i, "description": desc, "category": cat, "magnitude": mag, "confidence": conf,
            "depends_on": list(deps), "note": note, "included": True, "added": False}


PRESET_CHAINS: Dict[str, dict] = {
    "severe": {
        "explain": (
            "A global supply shock sends crude oil up 30%. In a town that runs on petrol, diesel and trucked-in food, the "
            "first thing people see is the pump price; within days the same increase shows up in the price of vegetables, "
            "grain and milk because every one of them travels by road. Households with a vehicle, a loan or a daily wage feel "
            "it first.\n\n"
            "The second wave is behavioural. People who are paying more for essentials stop eating out, skip the mall and "
            "put off purchases, which cuts the income of café owners, restaurant staff, auto drivers and factory shifts. "
            "Banks respond to rising defaults by tightening personal loans, so the people who most need a bridge loan can't "
            "get one and some turn to the moneylender at 8% a week."),
        "watch": ["Petrol price index and groceries index on the bottom strip",
                  "Auto drivers and delivery riders (fuel is both their cost and their income)",
                  "Moneylender borrowers and defaults in the final tally",
                  "Whether the households that talk to each other cut spending earlier"],
        "nodes": [
            _n(1, "Crude oil jumps 30% after a supply shock", "prices", "major", 0.95, [],
               "The scenario's essential-cost shock (+45% at full strength). Pass-through to shop prices: petrol 1.3x, groceries 1.0x, medicine 0.5x, eating out 0.6x."),
            _n(2, "Petrol and diesel prices rise sharply at the pump", "prices", "major", 0.95, [1],
               "The fuel station raises its price every day as the shock ramps in. Agents with a scooter, car or auto see the price when they refuel and remember it."),
            _n(3, "Transport and freight costs climb for every trader", "trade", "major", 0.85, [2],
               "Cost pass-through: trucks carry food, so the fuel increase lands in the market and kirana prices."),
            _n(4, "Vegetable, grain and milk prices rise at local markets", "prices", "major", 0.85, [3],
               "Grocery prices ramp up over about eight days. Households with less than a week of food at home are exposed first."),
            _n(5, "Auto drivers and delivery riders keep less of what they earn", "employment", "moderate", 0.75, [2],
               "Fuel is a daily cost for drivers; with the demand shock there are also fewer fares. Daily-wage shifts become scarcer."),
            _n(6, "Households cut eating out, the mall and the cinema", "consumer_behaviour", "major", 0.85, [4],
               "The demand shock (-40%): discretionary spending falls. Agents who read the news or hear it from neighbours cut sooner."),
            _n(7, "Cafés, restaurants and the mall see fewer customers", "employment", "moderate", 0.80, [6],
               "Shop owners earn the day's margin on sales; fewer customers means lower owner income and thinner staffing."),
            _n(8, "Factories get fewer orders and cut daily-wage shifts", "employment", "major", 0.75, [3, 6],
               "Income shock (-20%). On the day the shock reaches full strength about 12% of TechPark and factory staff are laid off."),
            _n(9, "Banks tighten personal-loan approvals", "credit", "major", 0.80, [1],
               "Credit tightness +40%: the bank demands a higher credit score, lends less, caps EMI-to-income lower and charges more."),
            _n(10, "Households with EMIs and little cash start to struggle", "credit", "major", 0.75, [8, 9],
               "Bills (rent, utilities, school fees, EMIs) keep falling due on the same days while income drops."),
            _n(11, "Some borrow from the moneylender at 8% a week", "credit", "moderate", 0.70, [10],
               "An agent that can't get a bank loan may choose the moneylender. The weekly instalment then competes with food for cash."),
            _n(12, "Missed payments lower credit scores and trigger defaults", "credit", "moderate", 0.65, [11],
               "Two missed instalments on one loan is a default (score -120). A default blocks later bank loans."),
        ],
    },

    "pandemic": {
        "explain": (
            "A plant disease destroys the rice and wheat harvest, and because the infected crops cannot be grown again "
            "this is a lasting shortage, not a bad season. Grain and flour prices roughly double and shops limit how much "
            "each family may buy: only about 15% of the usual grain stock is on sale, and medicines run at 60%.\n\n"
            "People can no longer buy a week of food in one trip, so they shop in small amounts every day and pay "
            "more each time. Spending on everything else is squeezed out. Households with a chronic illness face a second "
            "problem as medicine runs short, and the only way many can keep eating is to borrow."),
        "watch": ["Days of food at home (the 'Low on food' counter)",
                  "Medicine for residents with chronic conditions",
                  "Shop credit (khata) and moneylender borrowing",
                  "Who learns where food is still available, and from whom"],
        "nodes": [
            _n(1, "A deadly plant disease spreads through the rice and wheat fields", "other", "major", 0.90, [],
               "The triggering event. Essential-cost shock +90% at full strength."),
            _n(2, "Harvests are lost and the crops cannot be grown again", "trade", "major", 0.90, [1],
               "A permanent supply loss: nothing in the model brings the stock back during the month."),
            _n(3, "Rice, wheat and flour prices roughly double", "prices", "major", 0.90, [2],
               "Grocery prices ramp up to about 1.9x. Income only falls 20%, so the real cost of food rises sharply."),
            _n(4, "Shops ration grain: only ~15% of the usual stock is on sale", "policy", "major", 0.85, [2],
               "Rule: groceries rationed to 15%. Each shop can only sell a fraction of its normal stock, so a family cannot stock up in one trip."),
            _n(5, "Families spend most of their income on food and cut everything else", "consumer_behaviour", "major", 0.85, [3, 4],
               "Demand shock -30%. Eating out, the mall and the cafe lose customers; essentials crowd out everything else."),
            _n(6, "Daily-wage and small-shop incomes fall as spending dries up", "employment", "moderate", 0.75, [5],
               "Income shock -20%: fewer shifts, thinner shop margins."),
            _n(7, "Hospitals fill up and medicines run short (about 60% of normal stock)", "policy", "moderate", 0.80, [1],
               "Rule: medicine rationed to 60%. Pharmacy purchases are capped per customer."),
            _n(8, "Residents with a chronic illness risk running out of medicine", "consumer_behaviour", "moderate", 0.80, [7],
               "Medicine is a stock that runs out; running out is recorded as a major event and costs reward in the learning loop."),
            _n(9, "Households borrow to eat: shop credit and the moneylender", "credit", "moderate", 0.75, [5, 6],
               "With bills due and food costing more, agents use khata credit at the kirana, then the moneylender."),
            _n(10, "Neighbours share news of which shop still has grain", "consumer_behaviour", "minor", 0.60, [4],
               "Conversations carry information: people who never read the news still hear about shortages from the people they meet."),
            _n(11, "Banks tighten credit as defaults rise", "credit", "moderate", 0.65, [9],
               "Credit tightness +30%. Late in the month more households are refused a loan."),
        ],
    },

    "war": {
        "explain": (
            "War between several major powers cuts oil and shipping routes. The town feels it as three separate shocks at "
            "once: fuel is rationed to about 30% of normal supply, imported goods disappear (groceries to 60% of "
            "normal, medicine to 70%), and the financial markets crash so banks freeze new lending.\n\n"
            "Prices climb daily, people who need fuel to work (drivers, delivery riders, commuters) lose income, and "
            "factories that depend on imports and exports close. Households hoard what they can, and the combination of "
            "falling income, rising prices and no credit pushes the weakest into debt spirals."),
        "watch": ["Fuel: who runs out first, and what happens to their work",
                  "Hoarding versus running out: agents who stocked early",
                  "Factory and office employment on the full-strength day",
                  "The credit freeze: bank refusals and moneylender borrowing"],
        "nodes": [
            _n(1, "War breaks out between several major countries", "policy", "major", 0.95, [],
               "The triggering event. The full shock: essential cost +55%, income -25%, credit tightness +45%, demand -35%."),
            _n(2, "Oil and shipping routes are cut", "trade", "major", 0.90, [1],
               "Everything imported becomes scarce at the same time."),
            _n(3, "Fuel is rationed: about 30% of normal supply", "policy", "major", 0.90, [2],
               "Rule: fuel rationed to 30%. Pump purchases are capped; a tank that is empty means no commute."),
            _n(4, "Imported goods vanish: groceries ~60%, medicine ~70% of normal stock", "trade", "major", 0.85, [2],
               "Rules: groceries 60%, medicine 70%."),
            _n(5, "Food and fuel prices climb every day", "prices", "major", 0.90, [3, 4],
               "Essential-cost shock +55% over eight days, so people watch prices rise as they shop."),
            _n(6, "Drivers, riders and commuters cannot work without fuel", "employment", "major", 0.85, [3],
               "An agent with an empty tank cannot reach work: lost pay, or a bus fare."),
            _n(7, "Markets crash and banks freeze new lending", "credit", "major", 0.85, [1],
               "Credit tightness +45%: refusals become the norm, and the moneylender is the only door left."),
            _n(8, "Factories close for lack of supplies and export orders", "employment", "major", 0.80, [4, 7],
               "Income shock -25%: on the full-strength day about 18% of TechPark and factory staff are laid off."),
            _n(9, "Households hoard food and cut every other expense", "consumer_behaviour", "moderate", 0.80, [5],
               "Demand shock -35%. Agents with cash buy a week or more at once; those without can't."),
            _n(10, "Debt spirals: moneylender loans, missed EMIs and defaults", "credit", "moderate", 0.75, [6, 8, 7],
               "Weekly moneylender instalments at 8% compete with food; two missed instalments mean a default."),
            _n(11, "Savings rise among those who can still hold cash", "consumer_behaviour", "minor", 0.55, [9],
               "Savings +20%: precautionary saving among households with a cushion."),
        ],
    },

    "disaster": {
        "explain": (
            "Floods and storms hit the town overnight. Unlike the other scenarios this one is mostly about places, not "
            "prices: the market, school, construction site and factory shut for a few days and the park for longer, so "
            "the people who work or sell there lose pay. Homes in the Labour Colony and Old Town need a ₹4,000 repair "
            "bill, which for a daily-wage household is more than a week of income.\n\n"
            "Prices rise less sharply (+20%) because trucks are held up, and the bank extends deadlines but lends little. "
            "The town recovers on its own as places reopen, so the question is who has a cushion for the first week."),
        "watch": ["The greyed-out places on the map and who was working there",
                  "Residents of the Labour Colony and Old Town (repair bills)",
                  "Whether households with savings recover faster",
                  "How word of help spreads through conversations"],
        "nodes": [
            _n(1, "Heavy floods hit the town overnight", "other", "major", 0.95, [],
               "The triggering event. A mild essential-cost shock (+20%) and income -12%."),
            _n(2, "The market, school, construction site and factory shut for days", "policy", "major", 0.90, [1],
               "Rule: closures (market and school 3 days, construction 4, park 5, factory 2). Workers there lose those days' pay; closed places are greyed out on the map."),
            _n(3, "Daily wagers and vendors lose several days of pay", "employment", "major", 0.85, [2],
               "No layoffs in this scenario, just lost days. A daily-wage household has almost no buffer."),
            _n(4, "Homes in the Labour Colony and Old Town need ₹4,000 of repairs", "consumer_behaviour", "major", 0.85, [1],
               "Rule: a one-off repair bill the morning after the flood for residents of those areas."),
            _n(5, "Supply trucks are held up; vegetable and milk prices rise", "prices", "moderate", 0.75, [2],
               "Essential-cost shock +20%: a smaller but visible price jump."),
            _n(6, "Households draw down savings and skip some bills", "consumer_behaviour", "moderate", 0.75, [3, 4],
               "An agent can deliberately skip a bill; the cost is a late fee and credit score."),
            _n(7, "Banks extend deadlines but approve few new loans", "credit", "moderate", 0.70, [4],
               "Credit tightness +15%."),
            _n(8, "Some borrow from the moneylender to pay for repairs", "credit", "moderate", 0.70, [6, 7],
               "Where the bank says no, an agent can borrow at 8% a week."),
            _n(9, "Places reopen in stages and work resumes", "other", "minor", 0.85, [2],
               "Closures end after a few days; routine plans resume."),
            _n(10, "Neighbours pass on where help and supplies are available", "consumer_behaviour", "minor", 0.60, [1],
               "Information spreads through conversations; people who talk to others hear about relief sooner."),
        ],
    },

    "hyperinflation": {
        "explain": (
            "The currency loses value and shopkeepers reprice twice a day. For the first stretch prices rise at "
            "about 2.2x the usual level while wages barely move, so everybody's real income shrinks and people rush "
            "to turn cash into goods. Savings lose their value overnight.\n\n"
            "Then the bubble bursts. A day after the boom reaches full strength the economy flips: prices fall, "
            "but demand collapses faster, shops slash prices and still stand empty, jobs vanish and banks refuse almost every "
            "loan. Debt taken during the boom is now heavier in real terms. This scenario needs at least seven days to reach "
            "the second half."),
        "watch": ["The groceries index peaking and then falling",
                  "Panic buying, then the empty shops",
                  "Falling incomes after the crash day",
                  "Who borrowed during the boom and how they cope after"],
        "nodes": [
            _n(1, "The currency loses value and the rupee tumbles", "prices", "major", 0.90, [],
               "First phase: essential cost +120%, income -10%, demand +5%, savings -10%."),
            _n(2, "Shopkeepers reprice twice a day; groceries cost double and more", "prices", "major", 0.90, [1],
               "Prices ramp quickly; the multiplier reaches about 2.2x."),
            _n(3, "Wages cannot keep up, so real incomes shrink", "employment", "major", 0.85, [2],
               "Nominal pay is roughly unchanged while prices double."),
            _n(4, "Panic buying: people rush to turn cash into goods", "consumer_behaviour", "major", 0.80, [2],
               "Demand holds up in the first phase (+5%): shoppers who see rising prices buy more now."),
            _n(5, "Savings lose their value and people stop saving", "consumer_behaviour", "moderate", 0.80, [2],
               "Savings shock -10% in the first phase."),
            _n(6, "Borrowers rush for loans while lenders tighten", "credit", "moderate", 0.70, [1],
               "Credit tightness +10% at first."),
            _n(7, "The bubble bursts: prices stop rising and start to fall", "prices", "major", 0.85, [4, 5],
               "Rule: a shift starts a few days after full strength. Essential cost falls to -35%."),
            _n(8, "Demand collapses; shops cut prices and still stand empty", "consumer_behaviour", "major", 0.85, [7],
               "Second phase demand -50%: customers stop coming."),
            _n(9, "Incomes collapse as firms cannot cover their costs", "employment", "major", 0.85, [8],
               "Second phase income -30%: fewer shifts and thinner pay (the one-off job cuts only follow the first phase, which is too mild to trigger them)."),
            _n(10, "Credit freezes: banks refuse almost every loan", "credit", "major", 0.85, [7, 6],
               "Credit tightness +60%."),
            _n(11, "Debts from the boom become heavier in real terms", "credit", "moderate", 0.75, [9, 10],
               "EMIs are fixed in rupees while income has fallen. Missed payments, defaults."),
        ],
    },

    "none": {
        "explain": (
            "Nothing unusual happens. Prices, wages and credit stay at their normal levels, so this run shows how the town "
            "behaves on an ordinary month: people go to work, shop, pay rent and EMIs on their due dates and meet the "
            "neighbours they usually meet.\n\n"
            "It is the control. Every other scenario should be compared against it, because it shows how much of any "
            "hardship comes from the shock and how much is just life: some people are always short before the 5th."),
        "watch": ["How many people are 'under strain' with no shock at all",
                  "Routine versus LLM-planned days (most days should be routine)",
                  "The reward curve of a resident across runs"],
        "nodes": [
            _n(1, "No shock: prices, wages and credit stay normal", "other", "minor", 1.0, [],
               "All five shock numbers are zero."),
            _n(2, "People follow their routines: work, shop, socialise", "consumer_behaviour", "minor", 0.95, [1],
               "Most agents skip the LLM and repeat yesterday's plan; the stream marks them 'routine'."),
            _n(3, "Bills fall due on their usual days", "credit", "minor", 0.95, [2],
               "Rent on day 5, utilities on day 10, EMIs and school fees on their dates."),
            _n(4, "Shops and employers earn their usual margins", "employment", "minor", 0.90, [2],
               "Owners earn the day's margin; salaried workers are paid on payday, wage workers per shift."),
            _n(5, "A few households still run short before payday", "credit", "minor", 0.60, [3, 4],
               "Even with no shock, someone with a loan and a thin buffer misses a payment."),
        ],
    },

    "lockdown": {
        "explain": (
            "An emergency strict lockdown is declared with no warning. Everyone has to stay inside their home except to "
            "buy essentials. The grocery shops, pharmacy and clinic stay open; offices, factories, the school, the "
            "market, the mall and every other place shut.\n\n"
            "Office staff and students carry on from home, but anyone who earns by turning up — daily-wage workers, "
            "drivers, vendors, shop staff — has no income from day one. Bills still fall due, so the squeeze is not "
            "price but cash: families draw down savings, buy food from the one shop they are allowed to reach, and the "
            "weakest borrow."),
        "watch": ["The greyed-out places during the lockdown",
                  "Daily-wage households and how fast their cash runs out",
                  "Owners of grocery shops and the pharmacy (they earn more)",
                  "Agents who stocked food on the first day versus those who waited"],
        "nodes": [
            _n(1, "An emergency is declared and a strict lockdown begins at once", "policy", "major", 0.95, [],
               "Rule: lockdown. Everybody replans the same morning."),
            _n(2, "Offices, factories, the school, mall and market shut", "policy", "major", 0.95, [1],
               "Every non-essential place closes; the map greys them out."),
            _n(3, "Only grocery shops, the pharmacy and the clinic stay open", "policy", "moderate", 0.95, [1],
               "Essential places: kirana, supermarket, pharmacy, clinic."),
            _n(4, "Office staff and students work and study from home", "employment", "minor", 0.85, [2],
               "Monthly-salary workers and students keep their income."),
            _n(5, "Daily-wage workers, drivers and vendors lose all pay", "employment", "major", 0.90, [2],
               "An agent whose trip is blocked loses that phase's income; no one is laid off, there is just no work."),
            _n(6, "Restaurants, the mall and cafés lose almost every customer", "consumer_behaviour", "major", 0.90, [2],
               "Demand shock -50%."),
            _n(7, "Queues form at the grocery shops and pantries run down", "consumer_behaviour", "moderate", 0.80, [3],
               "Agents who stock a week of food on the first day are safe; those who wait run into the same queues."),
            _n(8, "Household cash runs short while bills still fall due", "credit", "major", 0.85, [5, 6],
               "Income -30% with no change in rent, utilities or EMIs."),
            _n(9, "Some borrow from the moneylender or miss EMIs", "credit", "moderate", 0.75, [8],
               "Missed payments cost credit score; two missed instalments on a loan is a default."),
            _n(10, "Essential-shop owners stay at the shop all day and earn more", "employment", "minor", 0.80, [3],
               "A one-person shop is only open while its owner is there, so owners remain at work."),
        ],
    },
}


def preset_nodes(preset_id: str) -> List[dict]:
    return [dict(n) for n in PRESET_CHAINS[preset_id]["nodes"]]
