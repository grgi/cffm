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
import pickle
from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import Any, cast

from cffm.config import Config, unfreeze, unfrozen, recurse_fields, asdict
from cffm.field import MISSING, DataField, FieldPath, PropertyField


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
                if isinstance(field, DataField) or isinstance(field, PropertyField):
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


class SharedMemorySource(Source):
    __slots__ = ('_shm_name',)

    _shm_name: str | None

    def __init__(self, name: str = 'shm', shm_name: str | None = None):
        super().__init__(name)
        self._shm_name = shm_name

    def load(self, config_cls: type[Config]) -> Config:
        shm = SharedMemory(self._shm_name)
        config = config_cls(**pickle.loads(cast(bytes, shm.buf)))
        shm.close()
        return config

    def dump(self, config: Config) -> SharedMemory:
        data = pickle.dumps(asdict(config))
        shm = SharedMemory(self._shm_name, create=True, size=len(data))
        shm.buf[:] = bytearray(data)
        shm.close()
        return shm

    def validate(self, config_cls: type[Config], strict: bool = False) -> bool:
        pass


class ConfigFileSource(Source):
    __slots__ = ('path', 'loader', 'dumper')

    path: Path
    loader: Callable[[io.BufferedReader], dict[str, Any]]
    dumper: Callable[[io.BufferedReader, dict[str, Any]], None] | None

    def __init__(self, path: Path | str,
                 loader: Callable[[io.BufferedReader], dict[str, Any]],
                 dumper: Callable[[io.BufferedReader, dict[str, Any]], None] | None = None,
                 name: str | None = None):
        if isinstance(path, str):
            path = Path(path)
        self.loader = loader
        self.dumper = dumper
        if name is None:
            name = path.name
        self.path = path
        super().__init__(name)

    def load(self, config_cls: type[Config]) -> Config:
        with self.path.open('rb') as fp:
            return config_cls(**self.loader(fp))

    def save(self, config: Config):
        with self.path.open('wb') as fp:
            self.dumper(fp, asdict(config))

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

    def _path2env_name(self, path: FieldPath, field: DataField | PropertyField) -> str:
        if isinstance(field.__env__, str):
            return field.__env__
        elif self._auto:
            def gen():
                if self._prefix:
                    yield self._prefix
                yield from path.upper()

            return self._separator.join(gen())
        return ''

    def load(self, config_cls: type[Config]) -> Config:
        with unfrozen(config_cls()) as config:
            for path, field in recurse_fields(config):
                if isinstance(field, DataField) or isinstance(field, PropertyField):
                    config[path] = self._environment.get(
                        self._path2env_name(path, field), MISSING)
        return config

    def save(self, config: Config):
        """Stores the config into the environment"""
        for path, field in recurse_fields(config):
            if isinstance(field, DataField) and \
                    (env_name := self._path2env_name(path, field)):
                if (value := config[path]) is MISSING:
                    if env_name in self._environment:
                        del self._environment[env_name]
                else:
                    self._environment[env_name] = str(field.__serialize__(value))

    def validate(self, config_cls: type[Config], strict: bool = False):
        pass
