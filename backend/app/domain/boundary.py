"""Base class for boundary (contract) models: the tolerant reader.

A contract crosses a component boundary, so its producer will evolve independently of C3.
Unknown fields are therefore ignored and logged as ``UNKNOWN_FIELD_IGNORED`` instead of being
rejected. Internal C3 models are the opposite (``extra="forbid"``): there an unknown field is
our own typo.
"""

import logging
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, ConfigDict, StringConstraints, model_validator

logger = logging.getLogger(__name__)

UNKNOWN_FIELD_IGNORED = "UNKNOWN_FIELD_IGNORED"

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @classmethod
    def _accepted_keys(cls) -> frozenset[str]:
        keys: set[str] = set()
        for name, field in cls.model_fields.items():
            keys.add(name)
            if field.alias is not None:
                keys.add(field.alias)
            if isinstance(field.validation_alias, AliasChoices):
                keys.update(c for c in field.validation_alias.choices if isinstance(c, str))
        return frozenset(keys)

    @model_validator(mode="before")
    @classmethod
    def _log_unknown_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            accepted = cls._accepted_keys()
            for key in sorted(k for k in data if isinstance(k, str) and k not in accepted):
                logger.warning(
                    UNKNOWN_FIELD_IGNORED,
                    extra={"reason": UNKNOWN_FIELD_IGNORED, "model": cls.__name__, "field": key},
                )
        return data
