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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cffm.config import Config, unfreeze, unfrozen, recurse_fields
from cffm.field import MISSING, DataField


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
        with unfrozen(config_cls()) as config:
            for path, field in recurse_fields(config):
                if isinstance(field, DataField):
                    config[path] = field.__create_default__(
                        config.__field_instance_mapping__[field])
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
        with unfrozen(config_cls()) as config:
            for path, field in recurse_fields(config):
                if isinstance(field, DataField) and isinstance(field.__env__, str):
                    config[path] = self._environment.get(field.__env__, MISSING)

        return config

    def validate(self, config_cls: type[Config], strict: bool = False):
        pass
