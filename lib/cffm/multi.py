from typing import Any

from cffm.config import Config, Section, unfrozen
from cffm.field import MISSING, _MissingObject, Field, FieldPath
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
        def apply(cfg: Config, configs: list[Config]):
            for name, field in cfg.__fields__.items():
                match getattr(cfg, name, MISSING):
                    case Section() as section:
                        apply(section, [getattr(c, name, MISSING) for c in configs])
                    case _MissingObject():
                        for c in configs:
                            if (value := getattr(c, name, MISSING)) is not MISSING:
                                setattr(cfg, name, value)

        with unfrozen(self.__config_cls__()) as config:
            apply(config, [self.__configs__[src.name] for src in reversed(self.__sources__)])

        return config

    def __build_custom__(self) -> Config:
        def apply_diff(diff_cfg: Config, custom: Config, configs: list[Config]):
            for name, field in diff_cfg.__fields__.items():
                match getattr(diff_cfg, name, MISSING):
                    case Section() as section:
                        apply_diff(section, getattr(custom, name),
                                   [getattr(cfg, name) for cfg in configs])
                    case _MissingObject():
                        for cfg in configs:
                            if (value := getattr(cfg, name, MISSING)) is not MISSING:
                                break
                        else:
                            value = MISSING

                        if (custom_value := getattr(custom, name, MISSING)) != value:
                            setattr(diff_cfg, name, custom_value)

        with unfrozen(self.__config_cls__()) as config:
            apply_diff(config, self.__merged_config__,
            [self.__configs__[src.name] for src in reversed(self.__sources__)])

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