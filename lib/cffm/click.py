""" Support for Click options

>>> import click
>>> from cffm import config
>>> from cffm.click import ClickSource

>>> cli_src = ClickSource()

>>> @config
>>> class FooConfig:
...     foo: int = field(3, "The Foo parameter")
...     bar: str = field('Bar', "The Bar option")

>>> @click.command()
... @click.option('--foo', field=FooConfig.foo, cls=cli_src.Option)
... @cli_src.option('--bar', field=FooConfig.bar)
... def command():
...     cfg = cli_src.load(FooConfig)
...     click.echo(cfg.foo)

"""
import types
from enum import Enum
import functools
from collections.abc import Sequence, Callable, Container
from typing import Any, get_args

import click

from cffm.config import Config, unfrozen, recurse_fields
from cffm.field import Field, DataField
from cffm import MISSING
from cffm.source import Source

try:
    from click import EnumChoice
except ImportError:

    class EnumChoice(click.Choice):
        def __init__(self, enum_type: type[Enum], case_sensitive: bool = True):
            super().__init__(
                choices=[element.name for element in enum_type],
                case_sensitive=case_sensitive,
            )
            self.enum_type = enum_type

        def convert(
                self, value: Any, param: click.Parameter | None, ctx: click.Context | None
        ) -> Any:
            value = super().convert(value=value, param=param, ctx=ctx)
            if value is None:
                return None
            return self.enum_type[value]


class ConfigOption(click.Option):
    field: Field

    def __init__(self, param_decl: Sequence[str] | None = None, *,
                 field: DataField,
                 type: click.types.ParamType | Any | None = None,
                 default: Any | Callable[[], Any] | None = None,
                 is_flag: bool = False,
                 expose_value: bool = False,
                 envvar: Sequence[str] | str | None = None,
                 show_default: bool = True,
                 help: str | None = None,
                 **kwargs):

        if default is None:
            if (field_default := field.__default__()) is not MISSING:
                default = field_default

        if type is None:
            type = field.__type__

        if isinstance(type, types.UnionType):
            type = get_args(type)[0]

        if type is bool:
            is_flag = True
            show_default = False

        if issubclass(type, Enum):
            if isinstance(default, type):
                default = default.name
            type=EnumChoice(type, case_sensitive=False)

        super().__init__(
            param_decl, type=type, default=default, expose_value=expose_value,
            envvar=envvar if envvar is not None or field.__env__ is MISSING else field.__env__,
            help=field.__description__ if help is None else help, is_flag=is_flag,
            show_default=show_default,
            **kwargs
        )
        self.field = field


class ClickSource(Source):
    __slots__ = ('_data', '_handlers')

    _data: dict[Field, Any]
    _handlers: list[Callable[[Source, Field, Any], None]]

    def __init__(self, name: str = 'CLI'):
        super().__init__(name)
        self._data = {}
        self._handlers = []

    def load(self, config_cls: type[Config]) -> Config:
        with unfrozen(config_cls()) as config:
            for path, field in recurse_fields(config):
                if field in self._data:
                    config[path] = self._data[field]

        return config

    def validate(self, config_cls: type[Config], strict: bool = False):
        pass

    def notify(self, handler: Callable[[Source, Field, Any], None]):
        self._handlers.append(handler)

    def _callback(self, field: DataField) \
            -> Callable[[click.Context, click.Parameter, Any], Any]:
        def callback(_ctx: click.Context, _param: click.Parameter, value: Any) -> Any:
            self._data[field] = value
            for handler in self._handlers:
                handler(self, field, value)
            return value
        return callback

    def option(self, *param_decls: Sequence[str], field: DataField,
               callback: Callable[[click.Context, click.Parameter, Any], Any] | None = None,
               **kwargs) -> Callable:
        return click.option(*param_decls, field=field, cls=ConfigOption,
                            callback=self._callback(field) if callback is None else callback,
                            **kwargs)

    @property
    def Option(self):
        @functools.wraps(ConfigOption)
        def wrapper(*args, field: DataField, callback=None, **kwargs):
            return ConfigOption(
                *args, field=field,
                callback=self._callback(field) if callback is None else callback,
                **kwargs
            )
        return wrapper

    def add_options_from_section(self, section: type[Config], exclude_fields: Container[Field]):
        def wrapper(callback: Callable) -> Callable:
            for field in section.__fields__.values():
                if isinstance(field, DataField) and field not in exclude_fields:
                    callback = self.option(field=field)(callback)
            return callback
        return wrapper


def default_map_from_cfg(config: Config, command: click.Command) -> dict[str, Any]:
    return {
        param.name: value for param in command.params
        if isinstance(param, ConfigOption) and (value := config[param.field]) is not MISSING
    } | {
        name: default_map_from_cfg(config, command)
        for name, command in getattr(command, 'commands', {}).items()
    }
