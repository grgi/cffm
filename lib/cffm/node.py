from anytree import Node

from cffm.config import Config, Section
from cffm.field import SectionField, MISSING


def node_from_config(config: Config, parent: Node | None = None, *,
                     include_type: bool = False) -> Node:
    if parent is None:
        node = Node(type(Config).__name__)
    else:
        config: Section
        node = Node(f"{config.__section_name__}", parent=parent)

    for name, field in config.__fields__.items():
        value = getattr(config, name)
        if isinstance(field, SectionField):
            node_from_config(value, parent=node, include_type=include_type)
        else:
            if include_type:
                field_type = getattr(field.__type__, '__name__', str(field.__type__))
                Node(f"{name} [{field_type}]: {value}", parent=node)
            else:
                Node(f"{name}: {value}", parent=node)

    return node
