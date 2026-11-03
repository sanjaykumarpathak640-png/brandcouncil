"""Measured accuracy of the rule-based council on a labelled set of posts.
Each case lists the guideline ids a careful human reviewer would flag. We compare to what the engine flags."""
import engine

D = [  # (text, expected guideline ids)
 ("FreshBrew is the BEST coffee in the world!! 100% guaranteed to cure tiredness. Free delivery in 1 day. Our users love us.", {"G3.2","G3.4","G3.5","G3.6","G2.1","G1.1"}),
 ("Diwali offer: get 20% off all beans! Buy now, hurry, our cheap deals will not last.", {"G3.6","G1.2","G2.1"}),
 ("Fresh beans, roasted in Coorg. Free delivery on orders above ₹499. Come and have a look.", set()),
 ("We are proud to be the best cafe brand of the year. Our certified organic beans are roasted in Coorg.", set()),
 ("Delivery is free on orders above ₹199 and arrives in 2 days. Our customers are happy.", {"G3.6","G2.1"}),
 ("This blend helps prevent heart disease and boosts immunity. Coffee lovers, try it today.", {"G3.4"}),
 ("Rated #1 by thousands of happy coffee lovers since 2010. Clinically proven to wake you up.", {"G3.2","G3.4","G3.6"}),
 ("NEW LATTE BLEND IS HERE!!! TRY IT NOW! Our users are going to LOVE it.", {"G1.1","G2.1"}),
 ("Order today and your beans are delivered in 3 days. Act now to get cheap shipping.", {"G3.6","G1.2","G2.1"}),
 ("Our cheap and cheerful filter coffee is back.", {"G2.1"}),
 ("Coffee lovers, our new blend is a great pick-me-up for slow mornings.", set()),
 ("Standard delivery takes 2 days anywhere in India.", set()),
 ("Standard delivery takes 5 days anywhere in India.", {"G3.6"}),
 ("Hurry! Last chance to try the new roast.", {"G1.2"}),
 ("Don't miss out on our monthly tasting evening.", {"G1.2"}),
 ("The world's finest espresso, brewed daily.", {"G3.2"}),
 ("Our coffee detoxes your body and cures headaches.", {"G3.4"}),
 ("Our beans are certified organic and roasted in Coorg.", set()),
 ("Join thousands of customers who love our roasts.", {"G2.1","G3.6"}),
 ("Free delivery on orders above ₹499, always.", set()),
 ("Free delivery on orders above ₹250.", {"G3.6"}),
 ("Save 20% with the Diwali offer today.", {"G3.6"}),
 ("Warm mugs, slow mornings and a fresh cup waiting for you.", set()),
 ("Visit us this weekend. We would love to see you.", set()),
 ("Try our new cold brew. It is smooth, bold and made with care.", set()),
 ("AMAZING DEALS TODAY ONLY!", {"G1.1"}),
 ("Our users can pause deliveries any time.", {"G2.1"}),
 ("We guarantee your satisfaction.", {"G3.5"}),
 ("The best coffee you will ever taste.", {"G3.2"}),
 ("Award-winning: we won Best Cafe Brand at the Metro Food Awards 2025.", set()),
 ("Delivered in two days, straight to your door.", set()),
 ("Delivered in four days, straight to your door.", {"G3.6"}),
 ("Meet the farmers behind our Coorg beans.", set()),
 ("Cheap and fast delivery in 1 day!", {"G2.1","G3.6"}),
]
DATASET = D
AGENT = {"G1":"Tone Agent","G2":"Terminology Agent","G3":"Claims Agent","G4":"Accessibility Agent"}


def evaluate(guideline_rows, facts, today=None):
    G = {g["key"]: g for g in guideline_rows if g.get("enabled", True)}
    ids = {g["id"]: g for g in guideline_rows}
    tp = fp = fn = exact = 0
    by_g, missed, false_alarms = {}, [], []
    for text, exp in DATASET:
        got = {f["guideline_id"] for f in engine.coordinate(engine.run_rules(text, G, facts, today)[0])[0]}
        exp = {e for e in exp if e in ids}
        t, p, n = got & exp, got - exp, exp - got
        tp += len(t); fp += len(p); fn += len(n); exact += (not p and not n)
        for g in exp | got:
            s = by_g.setdefault(g, {"tp": 0, "fp": 0, "fn": 0})
            s["tp"] += g in t; s["fp"] += g in p; s["fn"] += g in n
        for g in n: missed.append({"text": text, "guideline_id": g})
        for g in p: false_alarms.append({"text": text, "guideline_id": g})
    def pr(tp, fp, fn):
        return {"precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn}
    ag = {}
    for g, s in by_g.items():
        a = ag.setdefault(AGENT.get(g[:2], "Other"), {"tp": 0, "fp": 0, "fn": 0})
        for k in a: a[k] += s[k]
    return {"posts": len(DATASET), "posts_exact": exact, "overall": pr(tp, fp, fn),
            "by_agent": {k: pr(**v) for k, v in sorted(ag.items())},
            "by_guideline": {k: {**pr(**v), "title": ids[k]["title"] if k in ids else k} for k, v in sorted(by_g.items())},
            "missed": missed, "false_alarms": false_alarms}
