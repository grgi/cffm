import inspect
import types
from abc import ABCMeta, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, get_args, Callable, TYPE_CHECKING, overload

if TYPE_CHECKING:
    from cffm.config import Config, Section


class _MissingObject:
    __slots__ = ()

    def __repr__(self) -> str:
        return '<MISSING>'


MISSING = _MissingObject()


class FieldPath(str):
    __slots__ = ('components',)
    __match_args__ = ('components',)

    components: tuple[str]

    def __new__(cls, str_or_tuple: str | Iterable[str] = ()):
        if isinstance(value := str_or_tuple, str):
            components = value.split('.') if value else ()
        elif isinstance(components := str_or_tuple, Iterable):
            value = '.'.join(components)
        else:
            raise ValueError(f"Value is not a FieldPath: {str_or_tuple}")

        path = super().__new__(cls, value)
        path.components = tuple(components)
        return path

    def __len__(self) -> int:
        return len(self.components)

    def __getitem__(self, index_or_slice):
        return FieldPath(self.components[index_or_slice])

    def __iter__(self) -> Iterator[str]:
        return iter(self.components)

    def upper(self) -> "FieldPath":
        return FieldPath(super().upper())

    def lower(self) -> "FieldPath":
        return FieldPath(super().lower())


@dataclass(frozen=True, repr=False, slots=True)
class Field(metaclass=ABCMeta):
    __field_name__: str | None = None
    __config_cls__: "type[Config] | None" = None
    __description__: str | None = None
    __type__: type | None = None

    def __set_name__(self, owner: "type[Config]", name: str) -> None:
        object.__setattr__(self, '__field_name__', name)
        object.__setattr__(self, '__config_cls__', owner)

    def __repr__(self) -> str:
        field_type = getattr(self.__type__, '__name__', str(self.__type__))
        if self.__config_cls__ is None:
            return f"<Unbound Field: {field_type}>"
        return f"<Field {self.__config_cls__.__name__}.{self.__field_name__}: {field_type}>"

    def __update__(self, **kwargs) -> "Field":
        return replace(self, **kwargs)

    @abstractmethod
    def __create_default__(self, instance: "Config") -> Any:
        ...

    @abstractmethod
    def __convert__(self, value: Any) -> Any:
        ...

    def __get__(self, instance: "Config | None", owner: "type[Config]") \
            -> "SectionField | Any":
        if instance is None:
            return self

        return vars(instance)[self.__field_name__]

    def __set__(self, instance: "Config", value: Any) -> None:
        data = vars(instance)

        # Allow initialisation but no further modification if instance is frozen
        if self.__field_name__ in data and instance.__options__.frozen:
            raise TypeError(
                f"{self.__config_cls__.__name__} is frozen: cannot replace {self.__field_name__}"
            )

        data[self.__field_name__] = self.__convert__(value)

    def __delete__(self, instance: "Config") -> None:
        if instance.__options.__frozen:
            raise TypeError(
                f"{self.__config_cls__.__name__} is frozen: cannot delete {self.__field_name__}"
            )

        try:
            del vars(instance)[self.__field_name__]
        except KeyError:
            raise AttributeError(self.__field_name__) from None


@dataclass(frozen=True, repr=False, slots=True)
class DataField(Field):
    __default__: Any = MISSING
    __ref__: "Callable[[Field, Config]], Any] | None" = None
    __env__: str | None = None
    __converter__: "Callable[[Field, Any], Any] | None" = None

    def __create_default__(self, instance: "Config") -> Any:
        if self.__default__ is MISSING and self.__ref__ is not None:
            return self.__ref__(self, instance)
        return self.__default__

    def __convert__(self, value: Any) -> Any:
        if value is MISSING:
            return MISSING

        if self.__converter__ is not None:
            return self.__converter__(self, value)

        if isinstance(self.__type__, type):
            if issubclass(self.__type__, Enum):
                try:
                    return self.__type__[value]
                except KeyError:
                    return self.__type__(value)
            elif self.__type__ is bool:
                if isinstance(value, str):
                    return value.lower() in ('yes', 'y', 't', 'true', '1')
                return bool(value)
            return self.__type__(value)
        elif isinstance(self.__type__, types.UnionType):
            for t in get_args(self.__type__):
                if isinstance(value, t):
                    return value
            return get_args(self.__type__)[0](value)

    @staticmethod
    def __serialize__(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.name
        return value


def field(default: Any | _MissingObject = MISSING,
          description: str | None = None, *,
          env: str | None = None,
          converter: "Callable[[Any, Field], Any]" = None) -> Field:
    return DataField(__default__=default, __description__=description,
                     __env__=env, __converter__=converter)


class SectionField(Field):
    __slots__ = ()

    def __init__(self, section_cls: "type[Section]",
                 description: str | None = None, *,
                 name: str | None = None,
                 config_cls: "type[Config] | None" = None) -> None:
        super().__init__(
            __type__=section_cls,
            __description__=section_cls.__doc__ if description is None else description,
            __field_name__=name, __config_cls__=config_cls
        )

    def __repr__(self) -> str:
        if self.__config_cls__ is None:
            return f"<Unbound Section: {self.__type__.__name__}>"
        return f"<Section {self.__config_cls__.__name__}.{self.__field_name__}: {self.__type__.__name__}>"

    def __create_default__(self, instance: "Config") -> Any:
        return self.__type__(instance)

    def __convert__(self, value: Any) -> Any:
        pass

    def __set__(self, instance: "Config", value: Any) -> None:
        data = vars(instance)

        # Allow initialisation but no further modification
        if self.__field_name__ in data:
            raise TypeError(
                f"Section {self.__config_cls__.__name__}.{self.__field_name__} cannot be replaced"
            )

        if value is MISSING:
            value = self.__type__(instance)
        elif isinstance(value, dict):
            value = self.__type__(instance, **value)
        elif not isinstance(value, self.__type__):
            raise TypeError(f"Cannot set Section: {value} has invalid type")

        data[self.__field_name__] = value

    def __delete__(self, instance: "Config") -> None:
        raise TypeError(
            f"Section {self.__config_cls__.__name__}.{self.__field_name__} cannot be deleted"
        )

    def __getattr__(self, name: str) -> Field:
        return getattr(self.__type__, name)

    def __dir__(self) -> Iterable[str]:
        yield from super().__dir__()
        yield from self.__type__.__fields__


@dataclass(frozen=True, repr=False, slots=True)
class PropertyField(Field):
    __getter__: "Callable[[Config], Any] | None" = None
    __setter__: "Callable[[Config, Any], None] | None" = None
    __deleter__: "Callable[[Config], None] | None" = None
    __env__: str | None = None

    def __create_default__(self, instance: "Config") -> Any:
        return self.__getter__(instance)

    def __convert__(self, value: Any) -> Any:
        return value

    def __call__(self, getter: "Callable[[Config], Any]") -> "PropertyField":
        object.__setattr__(self, '__getter__', getter)
        if self.__description__ is None:
            object.__setattr__(self, '__description__', getter.__doc__)
        if self.__field_name__ is None:
            object.__setattr__(self, '__field_name__', getter.__name__)
        object.__setattr__(self, '__type__', inspect.get_annotations(getter).get('return'))
        return self

    def setter(self, setter: "Callable[[Config, Any], None]") -> "PropertyField":
        object.__setattr__(self, '__setter__', setter)
        return self

    def deleter(self, deleter: "Callable[[Config], None]") -> "PropertyField":
        object.__setattr__(self, '__deleter__', deleter)
        return self

    def __get__(self, instance: "Config | None", owner: "type[Config]") \
            -> "SectionField | Any":
        if instance is None:
            return self
        return self.__getter__(instance)

    def __set__(self, instance: "Config", value: Any) -> None:
        if value is MISSING:
            return

        if self.__setter__ is None:
            raise AttributeError(f"Cannot set readonly field {self.__field_name__}")

        return self.__setter__(instance, self.__convert__(value))

    def __delete__(self, instance: "Config") -> None:
        if self.__deleter__ is None:
            raise AttributeError(f"Cannot delete readonly field {self.__field_name__}")

        if instance.__options.__frozen:
            raise TypeError(
                f"{self.__config_cls__.__name__} is frozen: cannot delete {self.__field_name__}"
            )

        return self.__deleter__(instance)


def property_field(getter: "Callable[[Config], Any] | None" = None, /, *,
                   env: str | None = None) -> PropertyField:
    if getter is None:
        return PropertyField(__env__=env)
    return PropertyField(__env__=env)(getter)
