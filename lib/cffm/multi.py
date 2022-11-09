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

    def __build_custom__(self) -> Config:
        merged_cfg = self.__build_merged__()

        with unfrozen(self.__config_cls__()) as config:
            for path, field in recurse_fields(config):
                if isinstance(field, DataField):
                    if (value := self.__merged_config__[path]) != merged_cfg[path]:
                        config[path] = value

        return config

    def __getattr__(self, key: str) -> Any:
        return getattr(self.__merged_config__, key)

    def __setattr__(self, key: str, value: Any):
        if key.startswith('__'):
            super().__setattr__(key, value)
        elif (custom := self.__configs__.get('custom')) is not None:
            setattr(custom, key, value)
            self.__merged_config__ = self.__build_merged__()
        else:
            raise TypeError("Configuration is read-only")

    def __delattr__(self, key: str):
        if key.startswith('__'):
            super().__delattr__(key)
        elif (custom := self.__configs__.get('custom')) is not None:
            delattr(custom, key)
            self.__merged_config__ = self.__build_merged__()
        else:
            raise TypeError("Configuration is read-only")

    def __getitem__(self, field_or_path: Field | FieldPath) -> Any:
        return self.__merged_config__[field_or_path]

    def __setitem__(self, field_or_path: Field | FieldPath, value: Any):
        self.__merged_config__[field_or_path] = value

    def __delitem__(self, field_or_path: Field | FieldPath):
        del self.__merged_config__[field_or_path]