from contextlib import contextmanager
import types
from collections.abc import Callable, Iterator, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points, EntryPoint
import inspect
from typing import overload, Any, ClassVar


from cffm import MISSING
from cffm.field import Field, DataField, SectionField, FieldPath, PropertyField

_marker = object()


@dataclass(slots=True)
class ConfigOptions:
    frozen: bool = True
    strict: bool = False


class Config:
    __defaults__: ClassVar[ConfigOptions] = ConfigOptions()
    __fields__: ClassVar[dict[str, Field]]
    __sections__: "ClassVar[dict[str, Config]]"

    __options__: ConfigOptions
    __field_instance_mapping__: "dict[Field, Config]"

    def __init__(self, **kwargs):
        self._init_options()

        with unfrozen(self):
            self.__field_instance_mapping__ = {}

            for name, field in self.__fields__.items():
                setattr(self, name, kwargs.pop(name, MISSING))
                self.__field_instance_mapping__[field] = self
                if isinstance(field, SectionField):
                    self.__field_instance_mapping__ |= \
                        getattr(self, name).__field_instance_mapping__

        if self.__options__.strict and kwargs:
            name = next(iter(kwargs))
            raise TypeError(
                f"{type(self).__name__}.__init__() got "
                f"an unexpected keyword argument '{name}'")

    def _init_options(self):
        self.__options__ = ConfigOptions(
            frozen=self.__defaults__.frozen,
            strict=self.__defaults__.strict
        )

    def __repr__(self) -> str:
        def gen() -> str:
            for name, field in self.__fields__.items():
                field_type = getattr(field.__type__, '__name__', str(field.__type__))
                if (value := getattr(self, name, MISSING)) is not MISSING:
                    yield f"{name}: {field_type} = {value!r}"
        return f"{type(self).__name__}({', '.join(gen())})"

    def __eq__(self, other: Any) -> bool:
        return all(getattr(self, name) == getattr(other, name, _marker)
                   for name in self.__fields__)

    def __setattr__(self, name: str, value: Any):
        if (options := getattr(self, '__options__', None)) is not None \
                and options.frozen and name in self.__fields__:
            raise AttributeError("instance is read-only")
        return super().__setattr__(name, value)

    def __delattr__(self, name: str):
        if getattr(self, '__frozen__', False) and name in self.__fields__:
            raise AttributeError("instance is read-only")
        return super().__delattr__(name)

    def __freeze__(self, inverse: bool = False) -> None:
        self.__options__.frozen = not inverse

    def __class_getitem__(cls, field_path: FieldPath) -> Field:
        if isinstance(field_path, FieldPath):
            name, *sub = field_path
            if sub:
                return cls.__sections__[name][FieldPath(sub)]
            else:
                return cls.__fields__[name]
        elif isinstance(field_path, str):
            return cls[FieldPath(field_path)]

        raise KeyError(field_path)

    def __getitem__(self, field_or_path: Field | FieldPath) -> Any:
        if isinstance(field_or_path, Field):
            inst = self.__field_instance_mapping__[field_or_path]
            return getattr(inst, field_or_path.__field_name__)
        elif isinstance(field_or_path, FieldPath):
            name, *sub = field_or_path
            if sub:
                return self[name][FieldPath(sub)]
            else:
                return getattr(self, name)
        elif isinstance(field_or_path, str):
            return self[FieldPath(field_or_path)]
        else:
            raise KeyError(field_or_path)

    def __setitem__(self, field_or_path: Field | FieldPath, value: Any):
        if isinstance(field_or_path, Field):
            inst = self.__field_instance_mapping__[field_or_path]
            setattr(inst, field_or_path.__field_name__, value)
        elif isinstance(field_or_path, FieldPath):
            name, *sub = field_or_path
            if sub:
                getattr(self, name)[FieldPath(sub)] = value
            else:
                setattr(self, name, value)
        elif isinstance(field_or_path, str):
            self[FieldPath(field_or_path)] = value
        else:
            raise KeyError(field_or_path)

    def __delitem__(self, field_or_path: Field | FieldPath):
        if isinstance(field_or_path, Field):
            inst = self.__field_instance_mapping__[field_or_path]
            setattr(inst, field_or_path.__field_name__, MISSING)
        elif isinstance(field_or_path, FieldPath):
            name, *sub = field_or_path
            if sub:
                del getattr(self, name)[FieldPath(sub)]
            else:
                delattr(self, name)
        elif isinstance(field_or_path, str):
            del self[FieldPath(field_or_path)]
        else:
            raise KeyError(field_or_path)


class Section(Config):
    __section_name__: ClassVar[str]
    __parent_cls__: ClassVar[type[Config]]

    __parent__: Config

    def __init__(self, parent: Config, /, **kwargs):
        self.__parent__ = parent
        self.__options__ = parent.__options__
        super().__init__(**kwargs)

    def _init_options(self):
        # Do not initialise options on Sections
        pass


def freeze(cfg: Config) -> None:
    cfg.__options__.frozen = True


def unfreeze(cfg: Config):
    cfg.__options__.frozen = False


def recurse_fields(cfg: Config | type[Config]) -> Iterator[tuple[FieldPath, Field]]:
    for name, field in cfg.__fields__.items():
        yield FieldPath(name), field
        if isinstance(field, SectionField):
            for path, section_field in recurse_fields(cfg.__sections__[name]):
                yield FieldPath((name, *path)), section_field


@contextmanager
def unfrozen(cfg: Config):
    was_frozen = cfg.__options__.frozen
    try:
        unfreeze(cfg)
        yield cfg
    finally:
        cfg.__options__.frozen = was_frozen


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

    for name, field_type in annotations.items():
        if name in fields:
            continue
        if (cls_attr := cls_vars.pop(name, MISSING)) is MISSING:
            fields[name] = DataField(__field_name__=name, __type__=field_type)
        elif isinstance(cls_attr, Field):
            fields[name] = cls_attr.__update__(__field_name__=name, __type__=field_type)
        else:
            fields[name] = DataField(__default__=cls_attr,
                                     __field_name__=name,
                                     __type__=field_type)

    for name, attr in cls_vars.items():
        if isinstance(attr, PropertyField):
            fields[name] = attr
        elif name not in sections and isinstance(attr, type) \
                and issubclass(attr, Section):
            name = attr.__section_name__
            sections[name] = attr
            annotations[name] = attr
            fields[name] = SectionField(attr)
        else:
            ns[name] = attr

    for section_cls in additional_sections:
        name = section_cls.__section_name__
        if name in sections:
            raise TypeError(f"Duplicate section: {name}")
        sections[name] = section_cls
        annotations[name] = section_cls
        fields[name] = SectionField(section_cls)

    ns.update(
        __annotations__=annotations,
        __fields__=fields,
        __sections__=sections,
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
    options = ConfigOptions(frozen=frozen, strict=strict)
    add_sections = (section_cls
                    if name == getattr(section_cls, '__section_name__', _marker)
                    else _section_from_config(section_cls, name=name)
                    for name, section_cls in add_sections.items())

    def deco(cls: type) -> type[Config]:
        config_cls = type(
            cls.__name__, (Config,),
            _process_def(cls, *add_sections) | dict(__defaults__=options)
        )
        for section_cls in config_cls.__sections__.values():
            section_cls.__parent_cls__ = config_cls
        return config_cls

    if maybe_cls is None:
        return deco
    return deco(maybe_cls)


def section(name: str, *,
            add_sections: dict[str, type[Config]] = {}) -> Callable[[type], type[Section]]:
    additional_sections = tuple(
        section_cls if name == getattr(section_cls, '__section_name__', _marker)
        else _section_from_config(section_cls, name=name)
        for name, section_cls in add_sections.items())

    def deco(cls: type) -> type[Section]:
        section_cls = type(cls.__name__, (Section,),
                          _process_def(cls, *additional_sections) |
                          dict(__section_name__=name))
        for subsection_cls in section_cls.__sections__.values():
            subsection_cls.__parent_cls__ = section_cls
        return section_cls

    return deco


@overload
def sections_from_entrypoints(name: str) -> dict[str, type[Section]]:
    ...


@overload
def sections_from_entrypoints(config_entry_points: Iterable[EntryPoint]) \
        -> dict[str, type[Section]]:
    ...


@overload
def sections_from_entrypoints(configs: Iterable[tuple[str, type[Config]]]) \
        -> dict[str, type[Section]]:
    ...


def sections_from_entrypoints(name_or_entrypoints) -> dict[str, type[Section]]:
    if isinstance(name_or_entrypoints, str):
        name_or_entrypoints = entry_points(group=name_or_entrypoints)

    def gen():
        for item in name_or_entrypoints:
            if isinstance(ep := item, EntryPoint):
                yield ep.name, ep.load()
            else:
                yield item

    cfg_mapping = {tuple(name.split('.')): cfg_cls for name, cfg_cls in gen()}
    for path, cfg_def in sorted(cfg_mapping.items(),
                                key=lambda item: len(item[0]), reverse=True):
        depth = len(path)
        sections = {p[-1]: cfg_mapping.pop(p) for p in tuple(cfg_mapping)
                    if len(p) == depth+1 and p[:depth] == path}
        cfg_mapping[path] = section(path[-1], add_sections=sections)(cfg_def)
    return {name[0]: config_cls for name, config_cls in cfg_mapping.items()}


def asdict(cfg: Config) -> dict[str, Any]:
    def gen():
        for name, field in cfg.__fields__.items():
            value = getattr(cfg, name, MISSING)
            if isinstance(field, DataField):
                if value is not MISSING:
                    yield name, value
            elif isinstance(field, SectionField):
                yield name, asdict(value)

    return dict(gen())