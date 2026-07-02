"""
checks — Individual validation check modules.

Each module exports a single function with the signature:
    def check_<name>(agent: AgentIndex) -> list[Finding]

Available checks:
    rich_media  Genesys carousel payload structure and link routing rules.
    category    Queue name (category parameter) against allowed values.
    last_page   lastPage parameter presence and filename alignment.
"""
