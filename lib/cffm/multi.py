from collections.abc import Iterable
from typing import Any

from cffm.config import Config, Section, unfrozen, recurse_fields
from cffm.field import MISSING, _MissingObject, Field, FieldPath, DataField
from cffm.source import Source, CustomSource


class MultiSourceConfig:

    __config_cls__: type[Config]
    __sources__: list[Source]
    __configs__: dict[str, Config]
    __merged_config__: Config

    def __init__(self, config_def: type[Config], /, *sources: Source,
                 mutable: bool = True):
        self.__config_cls__ = config_def
        self.__sources__ = list(sources)
        self.__configs__ = {source.name: source.load(config_def) for source in sources}
        self.__merged_config__ = self.__build_merged__()
        self.__merged_config__.__freeze__(inverse=mutable)

    def __repr__(self) -> str:
        return f"[{', '.join(src.name for src in self.__sources__)}] -> {self.__merged_config__}"

    def __build_merged__(self) -> Config:
        with unfrozen(self.__config_cls__()) as config:
            for path, field in recurse_fields(config):
                if isinstance(field, DataField):
                    for cfg in reversed(self.__configs__.values()):
                        if (value := cfg[path]) is not MISSING:
                            config[path] = value
                            break
        return config

    def __update_merged__(self):
        frozen = self.__merged_config__.__options__.frozen
        self.__merged_config__ = self.__build_merged__()
        self.__merged_config__.__options__.frozen = frozen

    def __build_custom__(self) -> Config:
        merged_cfg = self.__build_merged__()

        with unfrozen(self.__config_cls__()) as config:
            for path, field in recurse_fields(config):
                if isinstance(field, DataField):
                    if (value := self.__merged_config__[path]) != merged_cfg[path]:
                        config[path] = value

        return config

    def __update_attribute__(self, field_or_path: Field | FieldPath, *sources: str):
        for src in self.__sources__:
            if not sources or src.name in sources:
                with unfrozen(self.__configs__[src.name]) as cfg:
                    cfg[field_or_path] = src.get(field_or_path)

        with unfrozen(self.__merged_config__) as merged_config:
            for cfg in reversed(self.__configs__.values()):
                if (value := cfg[field_or_path]) is not MISSING:
                    merged_config[field_or_path] = value
                    break
            else:
                merged_config[field_or_path] = MISSING

    def __getattr__(self, key: str) -> Any:
        return getattr(self.__merged_config__, key)

    def __setattr__(self, key: str, value: Any):
        if key.startswith('__'):
            super().__setattr__(key, value)
        else:
            setattr(self.__merged_config__, key, value)

    def __delattr__(self, key: str):
        if key.startswith('__'):
            super().__delattr__(key)
        else:
            delattr(self.__merged_config__, key)

    def __getitem__(self, field_or_path: Field | FieldPath) -> Any:
        return self.__merged_config__[field_or_path]

    def __setitem__(self, field_or_path: Field | FieldPath, value: Any):
        self.__merged_config__[field_or_path] = value

    def __delitem__(self, field_or_path: Field | FieldPath):
        del self.__merged_config__[field_or_path]

    def __add_source__(self, source: Source, index: int | None = None):
        if source.name in (src.name for src in self.__sources__):
            raise ValueError(f"Source '{source.name}' is already defined")

        if index is None:
            self.__sources__.append(source)
        else:
            self.__sources__.insert(index, source)

        self.__configs__ = {
            src.name: src.load(self.__config_cls__)
            if (cfg := self.__configs__.get(src.name, None)) is None
            else cfg
            for src in self.__sources__
        }
        self.__update_merged__()

    def __del_source__(self, name: str):
        for i, source in enumerate(self.__sources__):
            if source.name == name:
                del self.__sources__[i]
                break
        else:
            raise ValueError(f"No source with name '{name}'")

        del self.__configs__[name]
        self.__update_merged__()

    def __dir__(self) -> Iterable[str]:
        yield from super().__dir__()
        yield from dir(self.__merged_config__)
