"""Sessions at every stage of the flow, built with the real use case and in-memory fakes."""

from datetime import date, datetime
from decimal import Decimal

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.domain.plan_builder import ConstantSource
from pricor.domain.roles import ColumnRole as R
from pricor.ports.plan_advisor import (
    Evidence,
    ParameterHypothesis,
    ParameterId,
    PlanProposal,
    PlanQuestion,
    QuestionOption,
)

from ..application.fakes import FakeAdvisor, FakeClassifier, FakeReader

HEADER = ("Codigo", "Descripcion", "Precio lista", "IVA")
ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Precio lista": (R.COST_PRICE, 0.9),
    "IVA": (R.VAT_RATE, 0.9),
}
ROWS = (
    ("LISTA OCTUBRE", None, None, None),
    HEADER,
    ("00123", "Tornillo", "1.210,00", "21%"),
    ("A2", "Tuerca", Decimal("855.00"), "21%"),
    ("A3", "Arandela", Decimal("0.1"), "21%"),
    ("A4", "Clavo", 60, "21%"),
    ("A5", "Taco", "1.815,00", "21%"),
    ("A6", "Brida", "abc", "21%"),
    (None, None, None, None),
    ("TOTAL", None, "4.174,50", None),
    ("A7", datetime(2026, 10, 1, 8, 30), date(2026, 10, 2), "21%"),
)

PROPOSAL = PlanProposal(
    hypotheses=(
        ParameterHypothesis(
            ParameterId.PRICE_INCLUDES_VAT, True, 0.8, (Evidence(3, "21%"),)
        ),
        ParameterHypothesis(ParameterId.CURRENCY, ConstantSource("ARS"), 0.7),
    ),
    questions=(
        PlanQuestion(
            ParameterId.CURRENCY,
            "Which currency?",
            (QuestionOption("ARS", ConstantSource("ARS")),),
            (Evidence(2, "1.210,00"),),
        ),
    ),
    latency_seconds=1.5,
)


class Flow:
    """Drives one supplier file through the use case against a given repository."""

    def __init__(self, repository=None, rows=ROWS, supplier="Ferreteria Ejemplo", **kwargs):
        self.repository = repository or InMemoryImportSessionRepository()
        self.use_case = ImportFirstTime(
            FakeReader(rows),
            self.repository,
            [ClassifierStage("heuristics", FakeClassifier(ROLES))],
            FakeAdvisor(PROPOSAL),
            **kwargs,
        )
        self.supplier = supplier

    def start(self):
        return self.use_case.start("lista.xlsx", self.supplier)

    def ready(self):
        session = self.start()
        self.use_case.answer(session.id, "number_format", "decimal_comma")
        self.use_case.answer(session.id, "price_includes_vat", "yes")
        self.use_case.answer(session.id, "currency", "ARS")
        return self.use_case.get(session.id)

    def approved(self):
        return self.use_case.approve(self.ready().id)

    def headerless(self):
        reader = FakeReader([("A1", "Tornillo", "10,50"), ("A2", "Tuerca", "11,50")])
        use_case = ImportFirstTime(
            reader, self.repository, [ClassifierStage("heuristics", FakeClassifier())]
        )
        return use_case.start("x.csv", "Otro")
