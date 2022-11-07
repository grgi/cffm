import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass, KW_ONLY, replace
from importlib.metadata import entry_points
import inspect
from typing import overload, Any, ClassVar, get_args

__all__ = ('MISSING', 'field', 'config', 'section', 'Config', 'Section',
           'sections_from_entrypoints')


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
        match self.type:
            case type():
                return self.type(value)
            case types.UnionType():
                for t in get_args(self.type):
                    if isinstance(value, t):
                        return value
                return get_args(self.type)[0](value)

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


def section_field(section_cls: "type[Section]") -> Field:
    return Field(description=section_cls.__doc__, converter=Field.init_section,
                 name=section_cls.__section_name__, type=section_cls)


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
                field_type = getattr(field.type, '__name__', str(field.type))
                yield f"{name}: {field_type} = {getattr(self, name, MISSING)!r}"
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


def _section_from_config(config_cls: type[Config], name: str) -> type[Section]:
    ns = {k: v for k, v in vars(config_cls).items()
          if k not in ('__dict__', '__weakref__')
          and not isinstance(v, types.MemberDescriptorType)}
    return type(config_cls.__name__, (Section,), ns | dict(__section_name__=name))


def _process_def(config_def: type, *additional_sections: type[Section]) \
        -> dict[str, Any]:
    cls_vars = {k: v for k, v in vars(config_def).items()
                if k not in ('__annotations__', '__dict__', '__weakref__')
                and not isinstance(v, types.MemberDescriptorType)}
    annotations = inspect.get_annotations(config_def, eval_str=True)
    ns = {}

    fields = getattr(config_def, '__fields__', {}).copy()
    sections = getattr(config_def, '__sections__', {}).copy()

    def gen_fields() -> Iterator[tuple[str, Field]]:
        for name, field_type in annotations.items():
            if name in fields:
                continue
            match cls_vars.pop(name, MISSING):
                case _MissingObject():
                    yield name, Field(name=name, type=field_type)
                case Field() as f:
                    yield name, replace(f, name=name, type=field_type)
                case _ as v:
                    yield name, Field(default=v, name=name, type=field_type)

        for name, attr in cls_vars.items():
            if name not in sections and isinstance(attr, type) \
                    and issubclass(attr, Section):
                name = attr.__section_name__
                sections[name] = attr
                annotations[name] = attr
                yield name, section_field(attr)
            else:
                ns[name] = attr

        for section_cls in additional_sections:
            name = section_cls.__section_name__
            if name in sections:
                raise TypeError(f"Duplicate section: {name}")
            sections[name] = section_cls
            annotations[name] = section_cls
            yield name, section_field(section_cls)

    fields |= dict(gen_fields())

    ns.update(
        __annotations__=annotations,
        __fields__=fields,
        __sections__=sections,
        __slots__=tuple(fields),
        __match_args__=tuple(fields)
    )
    return ns


@overload
def config(cls: type, /) -> type:
    ...


@overload
def config(*, strict: bool = False, frozen: bool = True):
    ...


def config(maybe_cls=None, /, *, frozen: bool = True,
           add_sections: dict[str, type[Config]] = {}) \
        -> type[Config] | Callable[[type], type[Config]]:
    options = dict(frozen=frozen)
    add_sections = (section_cls
                    if name == getattr(section_cls, '__section_name__', _marker)
                    else _section_from_config(section_cls, name=name)
                    for name, section_cls in add_sections.items())
    def deco(cls: type) -> type[Config]:
        return type(cls.__name__, (Config,),
                    _process_def(cls, *add_sections) | dict(__defaults__=options))

    if maybe_cls is None:
        return deco
    return deco(maybe_cls)


def section(name: str, *, frozen: bool = True,
            add_sections: dict[str, type[Config]] = {}) -> Callable[[type], type[Section]]:
    options = dict(frozen=frozen)
    additional_sections = tuple(
        section_cls if name == getattr(section_cls, '__section_name__', _marker)
        else _section_from_config(section_cls, name=name)
        for name, section_cls in add_sections.items())
    def deco(cls: type) -> type[Section]:
        return type(cls.__name__, (Section,),
                    _process_def(cls, *additional_sections) |
                    dict(__section_name__=name, __defaults__=options))

    return deco


def sections_from_entrypoints(name: str) -> dict[str, type[Section]]:
    cfg_mapping = {tuple(ep.name.split('.')): ep.load() for ep in entry_points(group=name)}
    for path, cfg_def in sorted(cfg_mapping.items(),
                                key=lambda item: len(item[0]), reverse=True):
        depth = len(path)
        sections = {p[-1]: cfg_mapping.pop(p) for p in tuple(cfg_mapping)
                    if len(p) == depth+1 and p[:depth] == path}
        cfg_mapping[path] = section(path[-1], add_sections=sections)(cfg_def)
    return {name[0]: config_cls for name, config_cls in cfg_mapping.items()}