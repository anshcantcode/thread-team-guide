# Run #4 failure analysis, case by case

Run `20260928T100549Z-a1399cd6` on frozen `5293968`: 57/100 strict (local Qwen judge), 1 infrastructure error.
Every non-passing recording below, with the layer where it failed and what was done.
Classes: **asr** recogniser heard something else; **form** argument form a semantic judge
may accept; **gold** expected argument outside the public contract; **contract** required
argument never stated; **planner** 4B planner choice; **controller** our code (fixed where
stated); **policy** deliberate refusal of an unverifiable or false condition.

Fixes are verified by deterministic replay of the recorded write proposals across seven public
runs (no model): 4 refused proposals now dispatch, all exactly expected, and no unexpected
write. Runtime code never reads benchmark metadata; this table is evaluator-side analysis.

| Case | Recording | Class | What happened | Status |
|---|---|---|---|---|
| 007 | ecommerce_08_5ff07b5ee7a1d23e719e421e | form | query 'mechanical keyboard' vs expected plural | not changed: local-judge strictness |
| 008 | ecommerce_08_61517db6a7589569521b2356 | form | query 'mechanical keyboard' vs expected plural | not changed: local-judge strictness |
| 012 | ecommerce_12_6998abd731d2ec50d067d5bd | asr+planner | request unclear in transcript ('something ... electronic section'); clarification asked | not fixable safely |
| 014 | ecommerce_13_61517db6a7589569521b2356 | form | order ID written 'DE-LIV' for spelled D-E-L-I-V across two segments | not changed (a judge form question) |
| 021 | ecommerce_18_62a885d5b6af18b3d4579e1b | asr | 'PO999' heard as 'P0999' (letter O as zero) | recogniser |
| 023 | ecommerce_20_66c4f3cb14cbfc4db836bd4e | form | extra max_price 50 on the search (local judge); exact-match passes | not changed |
| 027 | ecommerce_25_65e8cf8f4c7424fa062e54a3 | planner | search chained after an unrelated read; add could not bind | planner variance; passes in run #3 |
| 029 | finance_01_65e8cf8f4c7424fa062e54a3 | asr | 'euros' heard as 'yours' | recogniser |
| 035 | finance_06_66f59c766e7e22e1f90d08f6 | planner | copied the contract example search_flights(London, 2026-08-20) | fixed 46768c8 (example guard) |
| 040 | finance_10_66c4f3cb14cbfc4db836bd4e | infrastructure | strict evaluation passed; a later evaluator step failed | counted as fail; no code cause |
| 046 | finance_16_62a885d5b6af18b3d4579e1b | asr | '500 yen' heard as '5800 yen' | recogniser |
| 048 | finance_18_6998abd731d2ec50d067d5bd | asr | 'savings instead' heard as 'same instance that'; checking write correctly refused | recogniser |
| 050 | finance_20_66c4f3cb14cbfc4db836bd4e | policy | condition on the user's own judgement ('if the rate looks good to me') | kept refused (unverifiable condition) |
| 052 | finance_22_5f4a4da1575d605c43bef871 | planner | second write omitted (run #4) or cited the first write's clause (runs 50, #5) | fixed a9e61f6 for the mis-cited form (re-citation) |
| 056 | housing_03_5f4a4da1575d605c43bef871 | form | filter value '1800' as a string; the contract declares value: str | not changed |
| 057 | housing_04_695bd157114f0d2317f88617 | planner | required max_price invented (5000) for search_apartments | exact-match passes; judge-dependent |
| 058 | housing_05_5ff07b5ee7a1d23e719e421e | gold | expected pets_allowed, which the public contract does not have | unreachable for any contract agent |
| 059 | housing_05_61517db6a7589569521b2356 | gold | expected pets_allowed, which the public contract does not have | unreachable |
| 060 | housing_06_5f4a4da1575d605c43bef871 | form | 'the gym' vs expected 'Gym' | not changed |
| 061 | housing_08_66f59c766e7e22e1f90d08f6 | planner | filter name 'pet_friendly' not stated; write refused | correct refusal |
| 063 | housing_10_66f59c766e7e22e1f90d08f6 | form | '500 central', 'the university', 'preferred neighborhood' | not changed |
| 064 | housing_11_62a885d5b6af18b3d4579e1b | asr | city lost ('under 12th'); planner wrote 'unknown' | recogniser |
| 065 | housing_13_5f4a4da1575d605c43bef871 | planner | called search_apartments instead of two filter updates | planner; raise/bump verbs fixed fc580db |
| 066 | housing_14_5ff07b5ee7a1d23e719e421e | gold | expected pets_allowed | unreachable |
| 067 | housing_14_61517db6a7589569521b2356 | gold | expected pets_allowed | unreachable |
| 068 | housing_15_5ff07b5ee7a1d23e719e421e | gold+planner | expected pets_allowed; invented max_price 5000 | unreachable |
| 069 | housing_15_61517db6a7589569521b2356 | gold+planner | expected pets_allowed; invented max_price 5000 | unreachable |
| 072 | housing_18_66c4f3cb14cbfc4db836bd4e | controller | commute origin 'APT1, Portland' refused as not matching result APT1 | fixed 51ff5fa (qualified identifier) |
| 073 | housing_19_62a885d5b6af18b3d4579e1b | planner | origin 'user's house' for 'my house' | planner variance; passes in the 50-run |
| 074 | housing_20_62a885d5b6af18b3d4579e1b | contract | search without the required bedrooms (never stated) refused by validation | not changed: the mock itself needs it |
| 075 | housing_21_66c4f3cb14cbfc4db836bd4e | contract | search without the required city refused by validation | not changed |
| 076 | housing_22_695bd157114f0d2317f88617 | planner | commute stadium->stadium, mode driving; 'I'll check' read as own plan | planner |
| 077 | housing_24_65e8cf8f4c7424fa062e54a3 | contract | required bedrooms missing; whole chain refused | not changed |
| 078 | housing_24_69a9cf80f4d7668d5c815038 | asr+planner | 'Dallas' heard as 'dollars'; track_order(APT1) invented | APT1 lookup fixed 51ff5fa; city is the recogniser |
| 079 | housing_25_66f59c766e7e22e1f90d08f6 | controller+retraction | several commands in one span; later 'wait ... instead' | bcf6e11 selects the matching command; pets write kept conservative |
| 081 | travel_02_5e3c1fbece3a7b000a6fd95a | asr/gold | heard P88990011; expected 'P9-9-9-90011' | recogniser/gold form |
| 085 | travel_07_5ff07b5ee7a1d23e719e421e | asr | only 'D-L-5' heard of DL555 | recogniser |
| 086 | travel_07_61517db6a7589569521b2356 | controller | 'DL.' / '555.' split across segments; DL555 refused | fixed 7fb0c73 (split spelling) |
| 090 | travel_14_66c4f3cb14cbfc4db836bd4e | asr | 'Seoul' heard as 'soil' | recogniser |
| 093 | travel_19_695bd157114f0d2317f88617 | asr | 'Milan' heard as 'Moan' | recogniser (passes when heard correctly, run #5) |
| 094 | travel_20_62a885d5b6af18b3d4579e1b | policy/gold | price condition false (450 > 300); expected both book and update | kept (condition verified false) |
| 095 | travel_21_65e8cf8f4c7424fa062e54a3 | planner | visa update never proposed (trailing ASR noise); false 'updated' prose was NOT spoken | planner |
| 099 | travel_24_695bd157114f0d2317f88617 | planner | visa update proposed as doc_type passport; gate refused the mismatch | correct refusal |

Totals: planner 10, asr 8, form 7, gold 4, contract 3, asr+planner 2, gold+planner 2, controller 2, infrastructure 1, policy 1, controller+retraction 1, asr/gold 1, policy/gold 1.
