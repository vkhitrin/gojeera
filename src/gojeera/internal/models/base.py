import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


def custom_as_dict_factory(data) -> dict:
    def convert_value(obj):
        if isinstance(obj, Enum):
            return obj.value
        return obj

    return {k: convert_value(v) for k, v in data}


def custom_as_json_dict_factory(data) -> dict:
    def convert_value(obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, Decimal):
            return str(obj)
        return obj

    return {k: convert_value(v) for k, v in data}


@dataclass
class BaseModel:
    def as_dict(self) -> dict:
        """Dumps dataclass into dictionary.

        Some objects may be dumped differently e.g. Decimal will be dumped to a string.
        """

        return dataclasses.asdict(self, dict_factory=custom_as_dict_factory)

    def as_json(self) -> dict:
        """Dumps dataclass into json dictionary.

        Some objects may be dumped differently eg. Decimal will be dumped to a string.
        """

        return dataclasses.asdict(self, dict_factory=custom_as_json_dict_factory)
