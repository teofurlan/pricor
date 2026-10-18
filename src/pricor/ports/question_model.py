"""Value objects that describe one question for the user.

They live at the ports level because the stored import session holds its open
questions; building the questions stays in `application.questions`.
"""

from dataclasses import dataclass, field

from .plan_advisor import Evidence, ParameterId


@dataclass(frozen=True)
class LocalizedText:
    en: str
    es: str

    def as_dict(self) -> dict[str, str]:
        return {"en": self.en, "es": self.es}


@dataclass(frozen=True)
class Option:
    token: str
    label: LocalizedText


@dataclass(frozen=True)
class Suggestion:
    """A model hypothesis offered as a default. The user still has to answer."""

    option: str
    confidence: float  # as reported by the model
    evidence: tuple[Evidence, ...] = ()
    suggested_by: str = "model"
    calibrated: bool = False
    memory_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Question:
    id: ParameterId
    text: LocalizedText
    options: tuple[Option, ...]
    reason: str  # why the builder needs it (English, from the builder)
    allows_custom: bool = False  # also accepts any valid `constant:<number>` token
    suggestion: Suggestion | None = None
    model_phrasing: str | None = None
