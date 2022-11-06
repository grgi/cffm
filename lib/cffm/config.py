import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass, KW_ONLY, replace
from typing import overload, Any, ClassVar

__all__ = ('MISSING', 'field', 'config', 'Config', 'Section')


_marker = object()


class _MissingObject:
    __slots__ = ()

    def __repr__(self) -> str:
        return '<MISSING>'


MISSING = _MissingObject()


@dataclass(slots=True, frozen=True)
class Field:
    def cast_field_type(self, value: Any) -> Any:
        if value is MISSING:
            return MISSING
        return self.type(value)

    def init_section(self, value: Any) -> "Config":
        match value:
            case self.type():
                return value
            case dict():
                return self.type(**value)
            case _MissingObject():
                return self.type()
            case _:
                return value

    default: Any | _MissingObject = MISSING
    description: str | None = None
    _: KW_ONLY = None
    env: str | None = None
    converter: "Callable[[Field, Any], Any] | None" = cast_field_type
    name: str | None = None
    type: type = None

    def convert(self, value: Any) -> Any:
        if self.converter is None:
            return value
        return self.converter(self, value)


def field(default: Any | _MissingObject = MISSING,
          description: str | None = None, *,
          env: str | None = None,
          converter: "Callable[[Any, Field], Any]" = Field.cast_field_type) -> Field:
    return Field(default, description, env=env, converter=converter)


class Config:
    __slots__ = ('__frozen__',)

    __defaults__: ClassVar[dict[str, Any]] = {}
    __fields__: ClassVar[dict[str, Field]]
    __sections__: "ClassVar[dict[str, Config]]"

    __frozen__: bool

    def __init__(self, **kwargs):
        for name, field in self.__fields__.items():
            value = kwargs.pop(name, MISSING)
            setattr(self, name, field.convert(value))

        self.__frozen__ = self.__defaults__.get('frozen', True)

        if kwargs:
            name = next(iter(kwargs))
            raise TypeError(
                f"{type(self).__name__}.__init__() got "
                f"an unexpected keyword argument '{name}'")

    def __repr__(self) -> str:
        def gen() -> str:
            for name, field in self.__fields__.items():
                yield f"{name}: {field.type.__name__} = {getattr(self, name, MISSING)!r}"
        return f"{type(self).__name__}({', '.join(gen())})"

    def __eq__(self, other: Any) -> bool:
        return all(getattr(self, name) == getattr(other, name, _marker)
                   for name in self.__fields__)

    def __setattr__(self, name: str, value: Any):
        if getattr(self, '__frozen__', False) and name in self.__fields__:
            raise AttributeError("instance is read-only")
        return super().__setattr__(name, value)

    def __delattr__(self, name: str):
        if getattr(self, '__frozen__', False) and name in self.__fields__:
            raise AttributeError("instance is read-only")
        return super().__delattr__(name)


class Section(Config):
    __slots__ = ()

    __section_name__: ClassVar[str]


def _process_def(config_def: type) -> dict[str, Any]:
    cls_vars = {k: v for k, v in vars(config_def).items()
                if k not in ('__annotations__', '__dict__', '__weakref__')}
    annotations = inspect.get_annotations(config_def, eval_str=True)
    ns = dict(__annotations__=annotations)

    sections = {}

    def gen_fields() -> Iterator[tuple[str, Field]]:
        for name, field_type in annotations.items():
            match cls_vars.pop(name, MISSING):
                case _MissingObject():
                    yield name, Field(name=name, type=field_type)
                case Field() as f:
                    yield name, replace(f, name=name, type=field_type)
                case _ as v:
                    yield name, Field(default=v, name=name, type=field_type)

        for name, attr in cls_vars.items():
            if isinstance(attr, type) and issubclass(attr, Section):
                name = attr.__section_name__
                sections[name] = attr
                annotations[name] = attr
                yield name, Field(description=section.__doc__,
                                  converter=Field.init_section,
                                  name=name, type=attr)
            else:
                ns[name] = attr

    fields = dict(gen_fields())

    ns.update(__fields__=fields,
              __sections__=sections,
              __slots__=tuple(fields),
              __match_args__=tuple(fields))
    return ns


@overload
def config(cls: type, /) -> type:
    ...


@overload
def config(*, strict: bool = False, frozen: bool = True):
    ...


def config(maybe_cls=None, /, *, frozen: bool = True) \
        -> type[Config] | Callable[[type], type[Config]]:
    options = dict(frozen=frozen)
    def deco(cls: type) -> type[Config]:
        return type(cls.__name__, (Config,),
                    _process_def(cls) | dict(__defaults__=options))

    if maybe_cls is None:
        return deco
    return deco(maybe_cls)


def section(name: str, *, frozen: bool = True) -> Callable[[type], type[Section]]:
    options = dict(frozen=frozen)
    def deco(cls: type) -> type[Section]:
        return type(cls.__name__, (Section,),
                    _process_def(cls) | dict(__section_name__=name,
                                             __defaults=options))

    return deco
