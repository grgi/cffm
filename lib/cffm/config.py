import types
from collections.abc import Callable, Iterator
from importlib.metadata import entry_points
import inspect
from typing import overload, Any, ClassVar

__all__ = ('config', 'section', 'Config', 'Section',
           'sections_from_entrypoints', 'freeze', 'unfreeze')

from cffm import MISSING
from cffm.field import _MissingObject, Field, DataField, SectionField

_marker = object()


class ConfigDef(type):

    __fields__: dict[str, Field]
    __sections__: "dict[str, Config]"

    @staticmethod
    def freeze(cfg: "Config"):
        cfg.__frozen__ = True
        for name in cfg.__sections__:
            Config.freeze(getattr(cfg, name))

    @staticmethod
    def unfreeze(cfg: "Config"):
        cfg.__frozen__ = False
        for name in cfg.__sections__:
            Config.unfreeze(getattr(cfg, name))


class Config:
    # __slots__ = ('__frozen__',)

    __defaults__: ClassVar[dict[str, Any]] = {}
    __fields__: ClassVar[dict[str, Field]]
    __sections__: "ClassVar[dict[str, Config]]"
    __strict__: ClassVar[bool] = False

    __frozen__: bool

    def __init__(self, **kwargs):
        for name, field in self.__fields__.items():
            value = kwargs.pop(name, MISSING)
            setattr(self, name, value)

        self.__frozen__ = self.__defaults__.get('frozen', True)

        if self.__strict__ and kwargs:
            name = next(iter(kwargs))
            raise TypeError(
                f"{type(self).__name__}.__init__() got "
                f"an unexpected keyword argument '{name}'")

    def __repr__(self) -> str:
        def gen() -> str:
            for name, field in self.__fields__.items():
                field_type = getattr(field.type, '__name__', str(field.type))
                if (value := getattr(self, name, MISSING)) is not MISSING:
                    yield f"{name}: {field_type} = {value!r}"
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

    def __freeze__(self, inverse: bool = False) -> None:
        self.__frozen__ = not inverse
        for name in self.__sections__:
            getattr(self, name).__freeze__(inverse=inverse)


def freeze(cfg: Config) -> None:
    cfg.__freeze__()


def unfreeze(cfg: Config):
    cfg.__freeze__(inverse=True)


class Section(Config):
    # __slots__ = ('__parent__',)

    __section_name__: ClassVar[str]
    __parent_cls__: ClassVar[type[Config]]

    __parent__: Config


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
                    yield name, DataField(name=name, type=field_type)
                case Field() as f:
                    yield name, f.update(name=name, type=field_type)
                case _ as v:
                    yield name, DataField(default=v, name=name, type=field_type)

        for name, attr in cls_vars.items():
            if name not in sections and isinstance(attr, type) \
                    and issubclass(attr, Section):
                name = attr.__section_name__
                sections[name] = attr
                annotations[name] = attr
                yield name, SectionField(attr)
            else:
                ns[name] = attr

        for section_cls in additional_sections:
            name = section_cls.__section_name__
            if name in sections:
                raise TypeError(f"Duplicate section: {name}")
            sections[name] = section_cls
            annotations[name] = section_cls
            yield name, SectionField(section_cls)

    fields |= dict(gen_fields())

    ns.update(
        __annotations__=annotations,
        __fields__=fields,
        __sections__=sections,
        # __slots__=tuple(fields),
        __match_args__=tuple(fields),
        **fields
    )
    return ns


@overload
def config(cls: type, /) -> type:
    ...


@overload
def config(*, frozen: bool = True, strict: bool = False):
    ...


def config(maybe_cls=None, /, *, frozen: bool = True, strict: bool = False,
           add_sections: dict[str, type[Config]] = {}) \
        -> type[Config] | Callable[[type], type[Config]]:
    options = dict(frozen=frozen)
    add_sections = (section_cls
                    if name == getattr(section_cls, '__section_name__', _marker)
                    else _section_from_config(section_cls, name=name)
                    for name, section_cls in add_sections.items())
    def deco(cls: type) -> type[Config]:
        config_cls = type(cls.__name__, (Config,),
                          _process_def(cls, *add_sections) |
                          dict(__strict__=strict, __defaults__=options))
        for section_cls in config_cls.__sections__.values():
            section_cls.__parent_cls__ = config_cls
        return config_cls

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
        section_cls = type(cls.__name__, (Section,),
                          _process_def(cls, *additional_sections) |
                          dict(__section_name__=name, __defaults__=options))
        for subsection_cls in section_cls.__sections__.values():
            subsection_cls.__parent_cls__ = section_cls
        return section_cls

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