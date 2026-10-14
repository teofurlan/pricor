"""Port that makes an approval all-or-nothing.

Approving an import writes the plan version, the price history and the session
state. They must land together or not at all, so the use case opens one
transaction and writes through the repositories it hands out.
"""

from contextlib import AbstractContextManager
from typing import Protocol

from pricor.ports.import_session_repository import ImportSessionRepository
from pricor.ports.plan_repository import PlanRepository
from pricor.ports.price_history import PriceHistory


class ApprovalTransaction(Protocol):
    plans: PlanRepository
    history: PriceHistory
    sessions: ImportSessionRepository


class ApprovalUnitOfWork(Protocol):
    def approval(self) -> AbstractContextManager[ApprovalTransaction]:
        """Commit on a normal exit, roll everything back if the block raises."""
        ...
