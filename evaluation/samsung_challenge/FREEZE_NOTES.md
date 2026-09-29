# Freeze metadata clarification, revision 1

The original `frozen/FREEZE.json` is preserved unchanged, including its field named `production_answers_exposed_before_freeze`. That name is too broad. Its intended and correct scope is **holdout answer rows exposed to production owners before freeze: false**.

Three **development** examples were shared to agree the adapter and continuation interface before freeze: a simple read, a pending-read cancellation, and an authorized shipping chain. The acceptance lane ran those examples and reported the shipping-chain false rejection before the corpus freeze. Production owners therefore had development expectations, as intended. No holdout answer rows were sent to them. This distinction is also stated in README.md and the original handoff.

This is a metadata-scope clarification only. It changes no case, stimulus, expected answer, oracle, hash, partition, or reported outcome. The first attempt and original manifest remain intact. Treat the held-out set as author-independent, template-sharing, procedurally isolated data; do not infer cryptographic secrecy or statistical independence from the original flag.
