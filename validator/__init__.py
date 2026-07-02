"""
validator — Dialogflow CX agent validation package.

Modules:
    config      Valid queue names and URL routing constants (loaded from config/).
    loader      Walk and index all files from an exported agent folder.
    extractor   Recursive JSON traversal utilities (parameters, payloads).
    checks      Individual check modules:
                  rich_media  — Genesys carousel payload structure and link routing.
                  category    — Queue name validation against allowed values.
                  last_page   — lastPage parameter presence and correctness.
    reporter    HTML report and console output generation.
"""
