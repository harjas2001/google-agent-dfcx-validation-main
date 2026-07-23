"""
validator — Dialogflow CX agent validation package.

Modules:
    config      Queue names, URL routing constants, severity policy and NLU
                thresholds.
    loader      Walk and index every resource in an exported agent folder:
                flows, pages, intents (+ training phrases), entity types,
                route groups, test cases and agent-level settings.
    graph       Normalise flow, page and route-group routing into one
                navigable conversation graph. Shared by the routing checks
                and the journey tracer.
    extractor   Recursive JSON traversal utilities (parameters, payloads,
                customer-visible text, form parameters).
    checks      Individual check modules:
                  rich_media    — Genesys carousel payload structure and links.
                  category      — Queue name validation against allowed values.
                  last_page     — lastPage parameter presence and correctness.
                  routing       — Intent coverage, reference integrity,
                                  page reachability.
                  nlu           — Training phrase quality and collisions.
                  page_hygiene  — Page structure and content quality.
                  agent_config  — Agent settings and shared-resource integrity.
    journeys    Per-head-intent journey context extraction and export.
    reporter    HTML report and console output generation.
"""
