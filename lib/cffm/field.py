import types
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass, KW_ONLY, field as dc_field, replace
from typing import Any, get_args, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from cffm.config import Config, Section


class _MissingObject:
    __slots__ = ()

    def __repr__(self) -> str:
        return '<MISSING>'


MISSING = _MissingObject()


@dataclass(frozen=True, repr=False, slots=True)
class Field(metaclass=ABCMeta):
    _: KW_ONLY
    name: str | None = None
    config_cls: "type[Config] | None" = None
    description: str | None = None
    type: "type | _MissingObject" = dc_field(default=MISSING)

    def __set_name__(self, owner: "type[Config]", name: str) -> None:
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'config_cls', owner)

    def __repr__(self) -> str:
        field_type = getattr(self.type, '__name__', str(self.type))
        if self.config_cls is None:
            return f"<Unbound Field: {field_type}>"
        return f"<Field {self.config_cls.__name__}.{self.name}: {field_type}>"

    def update(self, **kwargs) -> "Field":
        return replace(self, **kwargs)

    @abstractmethod
    def create_default(self, instance: "Config") -> Any:
        ...

    @abstractmethod
    def convert(self, value: Any) -> Any:
        ...

    def __get__(self, instance: "Config | None", owner: "type[Config]") \
            -> "SectionField | Any":
        if instance is None:
            return self

        return vars(instance)[self.name]

    def __set__(self, instance: "Config", value: Any) -> None:
        data = vars(instance)

        # Allow initialisation but no further modification if instance is frozen
        if self.name in data and instance.__options__.frozen:
            raise TypeError(
                f"{self.config_cls.__name__} is frozen: cannot replace {self.name}"
            )

        data[self.name] = self.convert(value)

    def __delete__(self, instance: "Config") -> None:
        if instance.__options.__frozen:
            raise TypeError(
                f"{self.config_cls.__name__} is frozen: cannot delete {self.name}"
            )

        try:
            del vars(instance)[self.name]
        except KeyError:
            raise AttributeError(self.name) from None


@dataclass(frozen=True, repr=False, slots=True)
class DataField(Field):
    default: Any = MISSING
    _: KW_ONLY = KW_ONLY
    ref: "Callable[[Field, Config]], Any] | None" = None
    env: str | None = None
    converter: "Callable[[Field, Any], Any] | None" = None

    def create_default(self, instance: "Config") -> Any:
        if self.default is MISSING and self.ref is not None:
            return self.ref(self, instance)
        return self.default

    def convert(self, value: Any) -> Any:
        if value is MISSING:
            return MISSING

        if self.converter is not None:
            return self.converter(self, value)

        match self.type:
            case type():
                return self.type(value)
            case types.UnionType():
                for t in get_args(self.type):
                    if isinstance(value, t):
                        return value
                return get_args(self.type)[0](value)


class SectionField(Field):
    __slots__ = ()

    def __init__(self, section_cls: "type[Section]",
                 description: str | None = None, *,
                 name: str | None = None,
                 config_cls: "type[Config] | None" = None) -> None:
        super().__init__(
            type=section_cls,
            description=section_cls.__doc__ if description is None else description,
            name=name, config_cls=config_cls
        )

    def __repr__(self) -> str:
        if self.config_cls is None:
            return f"<Unbound Section: {self.type.__name__}>"
        return f"<Section {self.config_cls.__name__}.{self.name}: {self.type.__name__}>"

    def create_default(self, instance: "Config") -> Any:
        return self.type(instance)

    def convert(self, value: Any) -> Any:
        pass

    def __set__(self, instance: "Config", value: Any) -> None:
        data = vars(instance)

        # Allow initialisation but no further modification
        if self.name in data:
            raise TypeError(
                f"Section {self.config_cls.__name__}.{self.name} cannot be replaced"
            )

        if value is MISSING:
            value = self.type(instance)
        elif isinstance(value, dict):
            value = self.type(instance, **value)
        elif not isinstance(value, self.type):
            raise TypeError(f"Cannot set Section: {value} has invalid type")

        data[self.name] = value

    def __delete__(self, instance: "Config") -> None:
        raise TypeError(
            f"Section {self.config_cls.__name__}.{self.name} cannot be deleted"
        )

    def __getattr__(self, name: str) -> Field:
        return getattr(self.type, name)


def field(default: Any | _MissingObject = MISSING,
          description: str | None = None, *,
          env: str | None = None,
          converter: "Callable[[Any, Field], Any]" = None) -> Field:
    return DataField(default, description=description, env=env, converter=converter)
