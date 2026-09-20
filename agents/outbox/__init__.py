"""
The outbox — durable, unique-constrained send state.

Pass 1 of the production-send-pipeline plan: the ledger only. Provider,
pacer, webhooks and footer are later passes and are not imported here.
"""

from agents.outbox.ledger import Ledger

__all__ = ["Ledger"]
