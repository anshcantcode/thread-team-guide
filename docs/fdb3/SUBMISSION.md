# FDB-v3 submission entry point

Start with the [submission index](../submission/README.md), [setup](../SETUP.md), [architecture](../ARCHITECTURE.md), [results](../submission/RESULTS.md) and [organizer requirements](../submission/REQUIREMENTS.md).

The custom LiveKit agent is `scripts/fdb3_agent.py`. The complete Linux entry point is `bash scripts/reproduce_fdb3_linux.sh`, after the declared external prerequisites. It verifies the released corpus and pinned model assets, prepares the runtime and evaluators, then runs fresh inference and evaluation. See [reproduction](REPRODUCE.md).

Root `submission.yaml` retains the older queue-kit's valid module/class schema and now identifies team ReflexAi. The updated FDB-v3 guide does not use that queue manifest as its launch contract. No undocumented YAML field is substituted for the required executable LiveKit pipeline.

Tag `PRISM_GENAI_HACKATHON_Y2026` names the packaged source. Human disclosure signature and organizer-form submission remain separate. Historical measurements retain their original source identities.
