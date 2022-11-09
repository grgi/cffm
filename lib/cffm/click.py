""" Support for Click options

>>> import click
>>> from cffm import config
>>> from cffm.click import ClickSource

>>> click_src = ClickSource()

>>> @config
>>> class FooConfig:
...     foo: int = field(3, "The Foo parameter")

>>> @click.command()
... @click_src.option('--foo', FooConfig.foo)
... def command():
...     cfg = click_src.load(FooConfig)
...     click.echo(cfg.foo)

"""

from collections.abc import Sequence, Callable, Container
from typing import Any

import click

from cffm.config import Config, unfrozen, recurse_fields
from cffm.field import Field, DataField
from cffm import MISSING
from cffm.source import Source


class ConfigOption(click.Option):
    field: Field

    def __init__(self, *args, field: Field, **kwargs):
        super().__init__(*args, **kwargs)
        self.field = field


class ClickSource(Source):
    __slots__ = ('_data',)

    _data: dict[Field, Any]

    def __init__(self, name: str = 'CLI'):
        super().__init__(name)
        self._data = {}

    def load(self, config_cls: type[Config]) -> Config:
        with unfrozen(config_cls()) as config:
            for path, field in recurse_fields(config):
                if field in self._data:
                    config[path] = self._data[field]

        return config

    def validate(self, config_cls: type[Config], strict: bool = False):
        pass

    def _callback(self, field: DataField) \
            -> Callable[[click.Context, click.Parameter, Any], Any]:
        def callback(ctx: click.Context, param: click.Parameter, value: Any) -> Any:
            self._data[field] = value
            return value
        return callback

    def option(self, *param_decls: Sequence[str], field: DataField) -> Callable:
        return click.option(*param_decls,
                            default=None if field.__default__ is MISSING else field.__default__,
                            callback=self._callback(field), expose_value=False,
                            help=field.__description__, cls=ConfigOption, field=field
                            )

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
