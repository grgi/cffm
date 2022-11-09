"""
Config Sources

- default
- data
  - files
  - environment
  - custom (set)
"""
import io
import os
from abc import ABCMeta, abstractmethod
from collections.abc import Iterator, Callable
from pathlib import Path
from typing import Any

from cffm.config import Config, unfreeze, Section, unfrozen
from cffm.field import MISSING, _MissingObject


class Source(metaclass=ABCMeta):
    __slots__ = ('name', 'data')

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: '{self.name}'>"

    @abstractmethod
    def load(self, config_cls: type[Config]) -> Config:
        ...

    @abstractmethod
    def validate(self, config_cls: type[Config], strict: bool = False):
        ...

    def set(self, config: Config, name: str, value: Any) -> None:
        raise AttributeError(f"{self!r} is readonly")

    def delete(self, config: Config, name: str) -> None:
        raise AttributeError(f"{self!r} is readonly")


class DefaultSource(Source):
    __slots__ = ()

    def __init__(self, name: str = 'default'):
        super().__init__(name)

    def load(self, config_cls: type[Config]) -> Config:
        def apply_defaults(cfg: Config):
            for name, field in cfg.__fields__.items():
                match getattr(cfg, name, MISSING):
                    case Section() as section:
                        apply_defaults(section)
                    case _MissingObject():
                        setattr(cfg, name, field.__create_default__(cfg))
            return cfg

        with unfrozen(config_cls()) as config:
            apply_defaults(config)

        return config

    def validate(self, config_cls: type[Config], strict: bool = False) -> bool:
        """Usually Default sources validate unless strict=True
        and all entries have defaults.
        """


class DataSource(Source):
    __slots__ = ('_data',)

    _data: dict[str, Any]

    def __init__(self, name: str, data: dict[str, Any]):
        super().__init__(name)
        self._data = data

    def load(self, config_cls: type[Config]) -> Config:
        return config_cls(**self._data)

    def validate(self, config_cls: type[Config], strict: bool = False) -> bool:
        pass


class ConfigFileSource(Source):
    __slots__ = ('path', 'loader')

    path: Path
    loader: Callable[[io.BufferedReader], dict[str, Any]]

    def __init__(self, path: Path | str,
                 loader: Callable[[io.BufferedReader], dict[str, Any]],
                 name: str | None = None):
        if isinstance(path, str):
            path = Path(path)
        self.loader = loader
        if name is None:
            name = path.name
        self.path = path
        super().__init__(name)

    def load(self, config_cls: type[Config]) -> Config:
        with self.path.open('rb') as fp:
            return config_cls(**self.loader(fp))

    def validate(self, config_cls: type[Config], strict: bool = False) -> bool:
        pass


class CustomSource(DataSource):
    __slots__ = ()

    def __init__(self, name: str = 'custom', data: dict[str, Any] | None = None):
        super().__init__(name, {} if data is None else data)

    def load(self, config_cls: type[Config]) -> Config:
        config = super().load(config_cls)
        unfreeze(config)
        return config


class EnvironmentSource(Source):
    __slots__ = ('_environment', '_auto', '_case_sensitive',
                 '_prefix', '_separator')

    _environment: dict[str, str]
    _auto: bool
    _case_sensitive: bool
    _prefix: str
    _separator: str

    def __init__(self, name: str = 'environment', *,
                 auto: bool = False, case_sensitive: bool = False,
                 prefix: str = '', separator: str = '_',
                 environment: dict[str, str] = os.environ):
        super().__init__(name)
        self._auto = auto
        self._case_sensitive = case_sensitive
        self._prefix = prefix
        self._separator = separator
        self._environment = environment

    def load(self, config_cls: type[Config]) -> Config:
        def apply_envvars(cfg: Config):
            for name, field in cfg.__fields__.items():
                match getattr(cfg, name, MISSING):
                    case Section() as section:
                        apply_envvars(section)
                    case _MissingObject():
                        if isinstance(field.env, str):
                            setattr(cfg, name,
                                    self._environment.get(field.env, MISSING))

        with unfrozen(config_cls()) as config:
            apply_envvars(config)

        return config

    def validate(self, config_cls: type[Config], strict: bool = False):
        pass
