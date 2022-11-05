import inspect
from collections.abc import Iterator, Callable
from typing import overload, Any, ClassVar, Literal

from attrs import frozen, Attribute, NOTHING, field as attrs_field, Factory

from cffm.utils import iterate_to

__all__ = ('config', 'section', 'field', 'Config', 'Section', 'MISSING')


class _MissingObject:
    __slots__ = ()

    def __repr__(self) -> str:
        return '<MISSING>'


MISSING = _MissingObject()


def field(*, default: Any = NOTHING, description: str | None = None,
          env: str | None = None,
          converter: "Callable[[Field, Any], Any] | None" = None):
    metadata = {}
    if description:
        metadata.update(description=description)
    if env:
        metadata.update(env_varname=env)
    return attrs_field(default=default,
                       metadata=metadata,
                       converter=converter)


class Config:
    __slots__ = ()


class Section(Config):
    __slots__ = ()

    __section_name__: ClassVar[str]
    __parent__: ClassVar[type[Config]]


def _prepare_attributes(cls: type) -> Iterator[tuple[str, Any]]:
    """This fixes 2 things:
    * resolve annotations
    * wrap a `Section` in a field
    """
    annotations = inspect.get_annotations(cls, eval_str=True)
    for key, value in vars(cls).items():
        if key in ('__dict__', '__weakref__', '__annotations__'):
            continue

        if isinstance(value, type) and issubclass(value, Section):
            value.__parent__ = cls
            annotations[value.__section_name__] = value
            yield value.__section_name__, field(description=value.__doc__)
        else:
            yield key, value
    yield '__annotations__', annotations


@iterate_to(list)
def _process_attributes(_: type[Config], attributes: list[Attribute]) -> Iterator[Attribute]:
    for field_ in attributes:
        converter = field_.converter
        metadata = field_.metadata
        if issubclass(field_.type, Section):
            if converter is None:
                def converter(value: dict[str, Any] | field_.type,
                              _field_type: type = field_.type) -> field_.type:
                    if isinstance(value, _field_type):
                        return value
                    return _field_type(**value)
            default = Factory(field_.type)

        else:
            if converter is None:
                def converter(value: Any, _field_type: type = field_.type) \
                        -> field_.type | _MissingObject:
                    if value is MISSING:
                        return MISSING
                    return _field_type(value)
            if field_.default is not NOTHING:
                metadata = metadata.copy() | dict(default=field_.default)
            default = MISSING

        yield field_.evolve(converter=converter, default=default, metadata=metadata)


@overload
def config(cls: type, /) -> type:
    ...


@overload
def config(*, strict: bool = False):
    ...


def config(maybe_cls=None, /, *, strict=False) \
        -> type[Config] | Callable[[type], type[Config]]:
    def deco(cls: type) -> type[Config]:
        fixed_cls = type(cls.__name__, (Config,), dict(_prepare_attributes(cls)))
        return frozen(fixed_cls, kw_only=True, field_transformer=_process_attributes)

    if maybe_cls is None:
        return deco
    return deco(maybe_cls)


@overload
def section(cls: type, /) -> type:
    ...


@overload
def section(name: str, *, strict: bool = False):
    ...


def section(cls_or_name=None, *, strict=False) \
        -> type[Section] | Callable[[type], type[Section]]:
    def deco(cls: type) -> type[Section]:
        fixed_cls = type(cls.__name__, (Section,), dict(_prepare_attributes(cls)))
        fixed_cls.__section_name__ = cls_or_name \
            if isinstance(cls_or_name, str) else cls.__name__
        return frozen(fixed_cls, kw_only=True, field_transformer=_process_attributes)

    if isinstance(cls_or_name, type):
        return deco(cls_or_name)
    return deco
