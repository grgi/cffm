from anytree import Node

from cffm import MultiSourceConfig
from cffm.config import Config, Section
from cffm.field import SectionField


def node_from_config(config: Config | MultiSourceConfig,
                     parent: Node | None = None) -> Node:
    if isinstance(config, MultiSourceConfig):
        config = config.__merged_config__

    if parent is None:
        node = Node(type(Config).__name__)
    else:
        config: Section
        node = Node(f"{config.__section_name__}", parent=parent)

    for name, field in config.__fields__.items():
        value = getattr(config, name)
        if isinstance(field, SectionField):
            node_from_config(value, parent=node)
        else:
            Node(name, parent=node, field=field, value=value)

    return node
