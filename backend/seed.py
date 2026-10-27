"""Synthetic demo brand ("FreshBrew") used for the demo and tests. No real company data."""

GUIDELINES = [
 {"id":"G1.1","key":"tone.shouting","title":"Friendly tone, never shouting",
  "text":"Our voice is warm and calm. Use at most one exclamation mark per post and avoid ALL-CAPS words.",
  "data":{"max_exclaim":1,"max_caps_words":1,"allow_caps":["PDF","FAQ","USA","UK","AI","OK"]}},
 {"id":"G1.2","key":"tone.hype","title":"No pushy sales language",
  "text":"Invite, don't pressure. Avoid urgency phrases such as 'buy now', 'act now' or 'hurry'.",
  "data":{"phrases":{"buy now":"take a look","act now":"have a look","hurry":"come by when you can","don't miss out":"we'd love to see you"}}},
 {"id":"G2.1","key":"terms","title":"Preferred terminology",
  "text":"We call our customers 'coffee lovers'. Never say 'users' or 'customers'. Say 'affordable', not 'cheap'.",
  "data":{"pairs":[{"bad":"users","good":"coffee lovers"},{"bad":"customers","good":"coffee lovers"},{"bad":"cheap","good":"affordable"}]}},
 {"id":"G3.2","key":"claims.superlative","title":"No unproven superlatives",
  "text":"Do not call FreshBrew 'the best', '#1' or 'world's finest' unless an approved fact (award, ranking) supports it.",
  "data":{"alternative":"made with care, from farm to cup"}},
 {"id":"G3.4","key":"claims.health","title":"No health or medical claims",
  "text":"Coffee must never be described as curing, treating or preventing any condition.",
  "data":{"alternative":"is a great pick-me-up"}},
 {"id":"G3.5","key":"claims.absolute","title":"No absolute promises",
  "text":"Avoid '100%' and 'guaranteed' unless an approved fact supports the exact promise.","data":{}},
 {"id":"G3.6","key":"claims.facts","title":"Every factual claim must match approved facts",
  "text":"Numbers, offers, certifications and delivery promises must match the Approved Facts Vault and must not be expired.","data":{}},
 {"id":"G4.1","key":"access.alt","title":"Images need alt-text",
  "text":"Every image must have a short alt-text describing it for screen-reader users.","data":{}},
 {"id":"G4.2","key":"access.contrast","title":"Readable contrast",
  "text":"Text on images must have enough contrast to be readable (WCAG ratio of at least 3:1 for large text).","data":{"min_ratio":3.0}},
 {"id":"G4.3","key":"access.readability","title":"Short, clear sentences",
  "text":"Keep sentences under 30 words so posts are easy to read.","data":{"max_words":30}},
 {"id":"G5.1","key":"visual.palette","title":"Brand colour palette",
  "text":"Images use our palette: espresso brown #4B2E1E, cream #F5E9D7 and caramel #C8873A. Avoid large areas of other colours.",
  "data":{"palette":["#4B2E1E","#F5E9D7","#C8873A"],"tolerance":80,"min_share":0.12}},
]

# unit: day|hour|month|year|pct|inr ; value is the approved number
FACTS = [
 {"id":"F1","topic":"Delivery time","keywords":["delivery","delivered","shipping","deliver"],"statement":"Standard delivery takes 2 days.","value":2,"unit":"day","source":"Operations policy v3","expires":None,"allows":[]},
 {"id":"F2","topic":"Free delivery threshold","keywords":["free delivery","free shipping","delivery is free","free on orders","free above","free over"],"statement":"Delivery is free on orders above ₹499.","value":499,"unit":"inr","source":"Operations policy v3","expires":None,"allows":[]},
 {"id":"F3","topic":"Organic certification","keywords":["organic","certified"],"statement":"Our beans are certified organic (certificate valid for 2026).","value":None,"unit":"","source":"Organic Cert. No. FB-2026","expires":None,"allows":[]},
 {"id":"F4","topic":"Award","keywords":["award","awarded","winner","ranked"],"statement":"FreshBrew won 'Best Cafe Brand' at the Metro Food Awards 2025.","value":None,"unit":"","source":"Metro Food Awards certificate","expires":None,"allows":["superlative"]},
 {"id":"F5","topic":"Diwali offer","keywords":["diwali","festive offer"],"statement":"Diwali offer: 20% off all beans.","value":20,"unit":"pct","source":"Marketing calendar","expires":"2026-09-30","allows":[]},
 {"id":"F6","topic":"Roast origin","keywords":["coorg","roasted in","origin"],"statement":"Our beans are grown and roasted in Coorg.","value":None,"unit":"","source":"Sourcing sheet","expires":None,"allows":[]},
]

SETTINGS = {"confidential_terms":["Project Mocha","Acme Retail","wholesale price list"]}

SAMPLES = [
 {"title":"Instagram post - the intern draft","channel":"Instagram",
  "text":"FreshBrew is the BEST coffee in the world!! 100% guaranteed to cure tiredness. Free delivery in 1 day. Our users love us."},
 {"title":"Festive offer","channel":"Facebook",
  "text":"Diwali offer: get 20% off all beans! Buy now, hurry, our cheap deals will not last."},
 {"title":"Clean post","channel":"Instagram",
  "text":"Fresh beans, roasted in Coorg. Free delivery on orders above ₹499. Come and have a look."},
 {"title":"Award brag","channel":"LinkedIn",
  "text":"We are proud to be the best cafe brand of the year. Our certified organic beans are roasted in Coorg."},
 {"title":"Wrong price promise","channel":"Website",
  "text":"Delivery is free on orders above ₹199 and arrives in 2 days. Our customers are happy."},
 {"title":"Health claim","channel":"Instagram",
  "text":"This blend helps prevent heart disease and boosts immunity. Coffee lovers, try it today."},
 {"title":"Unsupported claim","channel":"Twitter",
  "text":"Rated #1 by thousands of happy coffee lovers since 2010. Clinically proven to wake you up."},
 {"title":"Long sentence","channel":"Newsletter",
  "text":"Our new monthly subscription lets every coffee lover choose between several single origin roasts, adjust the grind size for their own brewing method, pause deliveries whenever travel plans change, and add special seasonal blends without ever paying extra for shipping."},
 {"title":"Shouting launch","channel":"Instagram",
  "text":"NEW LATTE BLEND IS HERE!!! TRY IT NOW! Our users are going to LOVE it."},
 {"title":"Delivery speed","channel":"Facebook",
  "text":"Order today and your beans are delivered in 3 days. Act now to get cheap shipping."},
]
