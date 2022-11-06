from typing import Any

from cffm.config import Config, Section, MISSING
from cffm.source import Source, CustomSource


class MultiSourceConfig:

    __config_cls__: type[Config]
    __sources__: list[Source]
    __configs__: dict[str, Config]
    __merged_config__: Config

    def __init__(self, config_def: type[Config], /, *sources: Source,
                 mutable: bool = True):
        self.__config_cls__ = config_def
        if mutable:
            sources = tuple((*sources, CustomSource()))
        self.__sources__ = list(sources)
        self.__configs__ = {source.name: source.load(config_def) for source in sources}
        self.__merged_config__ = self.__build_merged__()

    def __repr__(self) -> str:
        return f"[{', '.join(src.name for src in self.__sources__)}] -> {self.__merged_config__}"

    def __build_merged__(self) -> Config:
        def gen(config_cls: type[Config], configs: list[Config]):
            for name, field in config_cls.__fields__.items():
                if issubclass(field.type, Section):
                    value = field.type(**dict(gen(
                        field.type, [getattr(cfg, name) for cfg in configs])))
                else:
                    for cfg in configs:
                        if (value := getattr(cfg, name, MISSING)) is not MISSING:
                            break
                    else:
                        value = MISSING
                yield name, value

        return self.__config_cls__(**dict(
            gen(self.__config_cls__,
                [self.__configs__[src.name] for src in reversed(self.__sources__)])))

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
