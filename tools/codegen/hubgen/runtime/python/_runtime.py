"""Runtime support for the generated contract models (copied verbatim by the generator).

Decoding is tolerant where the protocol needs forward compatibility (unknown fields are kept in
``model_extra``, unknown enum values stay plain ``str``) and strict about JSON types. Everything
JSON Schema expresses beyond types (patterns, ranges, const, dependentRequired, ...) is checked
by ``contract_errors()``.
"""

from __future__ import annotations

import json
import math
import re
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, Strict, StrictBool

Number = Annotated[float, Strict()]
Boolish = Annotated[Union[StrictBool, Literal[0, 1]], Field(union_mode="left_to_right")]
"""SQLite boolean as delivered today: JSON boolean or integer 0/1 (known deviation D4 of the contract)."""

_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})\Z"
)
_IPV4 = re.compile(r"^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\Z")


def as_bool(value: bool | int | None) -> bool | None:
    """Normalizes a Boolish value."""
    return None if value is None else bool(value)


class ContractModel(BaseModel):
    """Base class of every generated model."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, protected_namespaces=())

    __fixed__: ClassVar[dict[str, str]] = {}
    __aliases__: ClassVar[dict[str, str]] = {}
    __closed__: ClassVar[bool] = False

    def model_post_init(self, context: Any, /) -> None:
        # discriminators (type/command) are always serialized, also when built in code
        self.__pydantic_fields_set__.update(self.__fixed__)

    # -- (de)serialization ----------------------------------------------------

    @classmethod
    def from_dict(cls, data: Any):
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, text: str | bytes):
        return cls.model_validate_json(text)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict: unset optional fields are omitted, explicit None stays null."""
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    # -- contract validation --------------------------------------------------

    def contract_errors(self) -> list[str]:
        """Violations of the JSON Schema beyond types; empty list = valid."""
        errors: list[str] = []
        self._check("", errors)
        return errors

    def _check(self, path: str, errors: list[str]) -> None:  # overridden
        pass

    def _present(self, json_name: str) -> bool:
        attr = self.__aliases__.get(json_name, json_name)
        if attr in type(self).model_fields:
            return attr in self.model_fields_set
        return json_name in (self.model_extra or {})

    def _check_object(self, path: str, errors: list[str], *, dependent: dict[str, list[str]] | None = None,
                      any_of: list[list[str]] | None = None, forbidden: list[str] | None = None,
                      conditionals: list[dict] | None = None,
                      max_properties: int | None = None, extra_check=None) -> None:
        for key, needed in (dependent or {}).items():
            if self._present(key):
                for n in needed:
                    if not self._present(n):
                        errors.append(f"{path or '/'}: '{n}' is required when '{key}' is present")
        if any_of and not any(all(self._present(n) for n in group) for group in any_of):
            errors.append(f"{path or '/'}: one of {any_of} is required")
        for n in forbidden or ():
            if self._present(n):
                errors.append(f"{path}/{n}: must not be present")
        for cond in conditionals or ():
            prop = cond["prop"]
            value = getattr(self, self.__aliases__.get(prop, prop), None)
            if self._present(prop):
                matched = value in cond["values"]
            else:
                # JSON Schema: an 'if' on an absent property holds (vacuous truth) unless it requires it
                matched = not cond["presence"]
            rule = cond["then"] if matched else cond["else"]
            for n in (rule or {}).get("required", ()):
                if not self._present(n):
                    errors.append(f"{path or '/'}: '{n}' is required when {prop} is {value!r}")
            for n in (rule or {}).get("forbidden", ()):
                if self._present(n):
                    errors.append(f"{path}/{n}: must not be present when {prop} is {value!r}")
            for n in (rule or {}).get("non_null", ()):
                if self._present(n) and getattr(self, self.__aliases__.get(n, n), None) is None:
                    errors.append(f"{path}/{n}: must not be null when {prop} is {value!r}")
            for n, const in (rule or {}).get("consts", {}).items():
                v = getattr(self, self.__aliases__.get(n, n), None)
                if self._present(n) and (v != const or (isinstance(const, bool) and not isinstance(v, bool))):
                    errors.append(f"{path}/{n}: must be {const!r} when {prop} is {value!r}")
        extra = self.model_extra or {}
        if self.__closed__ and extra:
            errors.append(f"{path or '/'}: unexpected properties {sorted(extra)}")
        if extra_check is not None:
            for k, v in sorted(extra.items()):
                extra_check(f"{path}/{k}", v)
        if max_properties is not None and len(self.model_fields_set) + len(extra) > max_properties:
            errors.append(f"{path or '/'}: more than {max_properties} properties")


# -- value checks (None = absent/null, handled by the type) --------------------


def check_str(errors: list[str], path: str, value: Any, *, pattern: re.Pattern | None = None,
              min_length: int | None = None, max_length: int | None = None, fmt: str | None = None,
              enum: tuple[str, ...] | None = None, const: str | None = None,
              alternatives: tuple[dict, ...] | None = None) -> None:
    if value is None:
        return
    if alternatives is not None:
        for alt in alternatives:
            sub: list[str] = []
            check_str(sub, path, value, **alt)
            if not sub:
                return
        errors.append(f"{path}: {value!r} matches none of the allowed forms")
        return
    if const is not None and value != const:
        errors.append(f"{path}: must be {const!r}")
    if enum is not None and value not in enum:
        errors.append(f"{path}: {value!r} is not one of {list(enum)}")
    if pattern is not None and not pattern.search(value):
        errors.append(f"{path}: {value!r} does not match {pattern.pattern!r}")
    if min_length is not None and len(value) < min_length:
        errors.append(f"{path}: shorter than {min_length}")
    if max_length is not None and len(value) > max_length:
        errors.append(f"{path}: longer than {max_length}")
    if fmt == "date-time" and not _DATE_TIME.match(value):
        errors.append(f"{path}: not an RFC 3339 date-time")
    if fmt == "ipv4" and not _IPV4.match(value):
        errors.append(f"{path}: not an IPv4 address")


def check_enum(errors: list[str], path: str, value: Any, enum_cls) -> None:
    if value is not None and not isinstance(value, enum_cls):
        errors.append(f"{path}: unknown value {value!r} (known: {[e.value for e in enum_cls]})")


def check_num(errors: list[str], path: str, value: Any, *, minimum=None, maximum=None, const=None,
              finite: bool = False) -> None:
    if value is None:
        return
    if finite and not math.isfinite(value):
        errors.append(f"{path}: must be a finite number")
    if const is not None and value != const:
        errors.append(f"{path}: must be {const!r}")
    if minimum is not None and value < minimum:
        errors.append(f"{path}: below minimum {minimum}")
    if maximum is not None and value > maximum:
        errors.append(f"{path}: above maximum {maximum}")


def check_bool(errors: list[str], path: str, value: Any, *, const: bool) -> None:
    if value is not None and value is not const:
        errors.append(f"{path}: must be {const!r}")


def check_items(errors: list[str], path: str, value: Any, *, min_items=None, max_items=None, unique=False) -> None:
    if value is None:
        return
    if min_items is not None and len(value) < min_items:
        errors.append(f"{path}: fewer than {min_items} items")
    if max_items is not None and len(value) > max_items:
        errors.append(f"{path}: more than {max_items} items")
    if unique and len({str(v) for v in value}) != len(value):
        errors.append(f"{path}: items must be unique")


def check_map(errors: list[str], path: str, value: Any, *, max_properties=None, required=None) -> None:
    if value is None:
        return
    if max_properties is not None and len(value) > max_properties:
        errors.append(f"{path}: more than {max_properties} properties")
    for key in required or ():
        if key not in value:
            errors.append(f"{path}: '{key}' is required")


def check_model(errors: list[str], path: str, value: Any) -> None:
    if value is not None:
        value._check(path, errors)


def extra_str_check(errors: list[str]):
    def check(path: str, value: Any) -> None:
        if not isinstance(value, str):
            errors.append(f"{path}: must be a string")
    return check


__all__ = [
    "Boolish", "ClassVar", "ContractModel", "Field", "Literal", "Number", "as_bool", "check_bool",
    "check_enum", "check_items", "check_map", "check_model", "check_num", "check_str", "extra_str_check",
]
