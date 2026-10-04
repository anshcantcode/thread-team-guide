# Failure dossier summary for 20261003T192003Z-cf861d7d

Strict 63/100, window 63, infrastructure errors 0. Source 4e88d4b74b00d1a70578504733f72f0931c77efa. Judge: local Qwen diagnostic.

| domain | pass |
|---|---|
| ecommerce | 19/29 |
| finance | 23/25 |
| housing | 8/26 |
| travel | 13/20 |

## Failures by primary layer

| layer | count | meaning |
|---|---|---|
| PLANNER_WRONG_VALUE | 8 | argument value differs and the heard text had the right value |
| ARG_NOT_IN_CONTRACT | 7 | expected argument is not declared in the public tool contract |
| PROPOSED_NOT_DISPATCHED | 5 | planner proposed the call but it was superseded, cancelled or never admitted |
| JUDGE_STRICT | 5 | argument differs only in form (case, article, number/boolean as text); a lenient judge may pass it |
| ASR_VALUE | 3 | an argument is wrong because THREAD misheard it |
| GATE_BLOCKED | 2 | planner proposed the expected call; the write/authorization gate refused it |
| ARG_OMITTED | 1 | a declared argument the user stated was left out |
| UNCLASSIFIED | 1 | no rule matched; read the timeline |
| PLANNER_ASKED | 1 | planner chose to ask a question instead of acting |
| VALIDATION_BLOCKED | 1 | planner proposed the call; schema validation turned it into a question |
| PLANNER_MISSED_CALL | 1 | the heard text had what was needed, but the planner never proposed this call |
| PREMATURE_PLAN | 1 | planning ran before the user finished (correction still arriving) |
| ASR_MISSING_VALUE | 1 | a value the call needs is in the reference dialogue but not in what THREAD heard |

## Versus baseline 20261003T161424Z-1c340f9d: gained 5, lost 5
gained: 003, 045, 048, 056, 061
lost: 010, 027, 038, 093, 099

## Every failure

| case | recording | diff. | layer | detail |
|---|---|---|---|---|
| 007 | ecommerce_08_5ff07b5ee7a1d23e719e421e | easy | PLANNER_WRONG_VALUE | search_products.query: expected 'mechanical keyboards', sent 'mechanical keyboard' |
| 008 | ecommerce_08_61517db6a7589569521b2356 | easy | PLANNER_WRONG_VALUE | search_products.query: expected 'mechanical keyboards', sent 'mechanical keyboard' |
| 010 | ecommerce_10_6998abd731d2ec50d067d5bd | medium | ARG_OMITTED | search_products.max_price: expected 150, not sent |
| 012 | ecommerce_12_6998abd731d2ec50d067d5bd | medium | ARG_NOT_IN_CONTRACT | search_products.category: expected 'electronics', not sent (+1 more) |
| 014 | ecommerce_13_61517db6a7589569521b2356 | medium | ASR_VALUE | track_order.order_id: expected 'DELIV', sent 'DLIV' |
| 016 | ecommerce_14_61517db6a7589569521b2356 | medium | PROPOSED_NOT_DISPATCHED | add_to_cart proposed as [('add_to_cart', {'product_id': 'P5-2', 'quantity': 2})] |
| 021 | ecommerce_18_62a885d5b6af18b3d4579e1b | hard | PLANNER_WRONG_VALUE | add_to_cart.product_id: expected '$RESULT_0.cheapest_product_id', sent 'PROD1' (+1 more) |
| 023 | ecommerce_20_66c4f3cb14cbfc4db836bd4e | hard | UNCLASSIFIED | Wrong arguments for: ['search_products'] |
| 025 | ecommerce_21_69a9cf80f4d7668d5c815038 | hard | PROPOSED_NOT_DISPATCHED | search_products proposed as [('search_products', {'query': 'watch', 'max_price': 200})] (+1 more) |
| 027 | ecommerce_25_65e8cf8f4c7424fa062e54a3 | hard | PROPOSED_NOT_DISPATCHED | search_products proposed as [('search_products', {'query': 'cat food', 'max_price': 100})] (+1 more) |
| 038 | finance_08_65e8cf8f4c7424fa062e54a3 | easy | ASR_VALUE | get_exchange_rate.from_currency: expected 'EUR', sent 'ROSE' |
| 050 | finance_20_66c4f3cb14cbfc4db836bd4e | hard | PLANNER_ASKED | modify_autopay: asked 'Please explicitly confirm the action and its target before I change anything.' |
| 058 | housing_05_5ff07b5ee7a1d23e719e421e | easy | ARG_NOT_IN_CONTRACT | search_apartments.pets_allowed: expected True, not sent |
| 059 | housing_05_61517db6a7589569521b2356 | easy | ARG_NOT_IN_CONTRACT | search_apartments.pets_allowed: expected True, not sent |
| 060 | housing_06_5f4a4da1575d605c43bef871 | easy | JUDGE_STRICT | calculate_commute.destination_address: expected 'Gym', sent 'the gym' |
| 063 | housing_10_66f59c766e7e22e1f90d08f6 | medium | JUDGE_STRICT | calculate_commute.destination_address: expected 'University', sent 'the University' (+1 more) |
| 064 | housing_11_62a885d5b6af18b3d4579e1b | medium | PLANNER_WRONG_VALUE | search_apartments.city: expected 'Austin', sent None |
| 065 | housing_13_5f4a4da1575d605c43bef871 | medium | PLANNER_WRONG_VALUE | update_search_filter.filter_name: expected 'min_bedrooms', sent 'bedrooms' |
| 066 | housing_14_5ff07b5ee7a1d23e719e421e | medium | ARG_NOT_IN_CONTRACT | search_apartments.pets_allowed: expected True, not sent |
| 067 | housing_14_61517db6a7589569521b2356 | medium | ARG_NOT_IN_CONTRACT | search_apartments.pets_allowed: expected True, not sent |
| 068 | housing_15_5ff07b5ee7a1d23e719e421e | medium | ARG_NOT_IN_CONTRACT | search_apartments.pets_allowed: expected True, not sent |
| 069 | housing_15_61517db6a7589569521b2356 | medium | ARG_NOT_IN_CONTRACT | search_apartments.pets_allowed: expected True, not sent |
| 072 | housing_18_66c4f3cb14cbfc4db836bd4e | hard | ASR_VALUE | search_apartments.max_price: expected 1800, sent 800 |
| 073 | housing_19_62a885d5b6af18b3d4579e1b | hard | JUDGE_STRICT | calculate_commute.destination_address: expected 'the gym', sent 'gym' |
| 074 | housing_20_62a885d5b6af18b3d4579e1b | hard | GATE_BLOCKED | update_search_filter: ["unverified condition: if it's under 15 minutes, that's perfect"] / said: Please explicitly confirm the action and its target before I ch |
| 075 | housing_21_66c4f3cb14cbfc4db836bd4e | hard | VALIDATION_BLOCKED | search_apartments: ['args.city: missing required argument', 'args.max_price: missing required argument'] / said: Could you tell me the destination city and the  (+1 more) |
| 076 | housing_22_695bd157114f0d2317f88617 | hard | PLANNER_MISSED_CALL | calculate_commute{"origin_address": "$RESULT_1.apartments[0].address", "destination_address": "the stadium", "mode": "transit"} never proposed |
| 077 | housing_24_65e8cf8f4c7424fa062e54a3 | hard | JUDGE_STRICT | calculate_commute.destination_address: expected 'the grocery store', sent 'grocery store' (+1 more) |
| 078 | housing_24_69a9cf80f4d7668d5c815038 | hard | JUDGE_STRICT | calculate_commute.destination_address: expected 'the grocery store', sent 'grocery store' (+1 more) |
| 079 | housing_25_66f59c766e7e22e1f90d08f6 | hard | PREMATURE_PLAN | update_search_filter: ['later correction in clause 1.6 with nothing cited after: wait'] / said: Please explicitly confirm the action and its target before I cha (+2 more) |
| 081 | travel_02_5e3c1fbece3a7b000a6fd95a | easy | PLANNER_WRONG_VALUE | update_identity_doc.doc_number: expected 'P9-9-9-90011', sent 'P88990011' |
| 090 | travel_14_66c4f3cb14cbfc4db836bd4e | medium | PLANNER_WRONG_VALUE | search_flights.date: expected 'March 22', sent '2026-03-22' (+1 more) |
| 093 | travel_19_695bd157114f0d2317f88617 | hard | PLANNER_WRONG_VALUE | search_flights.date: expected 'June 3', sent '2026-06-03' (+1 more) |
| 094 | travel_20_62a885d5b6af18b3d4579e1b | hard | ASR_MISSING_VALUE | book_flight: passenger_name='Riley Kim' not in heard text (+1 more) |
| 095 | travel_21_65e8cf8f4c7424fa062e54a3 | hard | GATE_BLOCKED | update_identity_doc: ['command names no target of this tool'] / said: Please explicitly confirm the action and its target before I change anything. |
| 097 | travel_23_65e8cf8f4c7424fa062e54a3 | hard | PROPOSED_NOT_DISPATCHED | update_identity_doc proposed as [('update_identity_doc', {'doc_type': 'passport', 'doc_number': 'P1122'})] |
| 099 | travel_24_695bd157114f0d2317f88617 | hard | PROPOSED_NOT_DISPATCHED | update_identity_doc proposed as [('update_identity_doc', {'doc_type': 'visa', 'doc_number': 'V-Victor-4-4'})] |
