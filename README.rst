.. These are examples of badges you might want to add to your README:
   please update the URLs accordingly

    .. image:: https://readthedocs.org/projects/cffm/badge/?version=latest
        :alt: ReadTheDocs
        :target: https://cffm.readthedocs.io/en/stable/
    .. image:: https://img.shields.io/coveralls/github/<USER>/cffm/main.svg
        :alt: Coveralls
        :target: https://coveralls.io/r/<USER>/cffm
    .. image:: https://img.shields.io/pypi/v/cffm.svg
        :alt: PyPI-Server
        :target: https://pypi.org/project/cffm/
    .. image:: https://pepy.tech/badge/cffm/month
        :alt: Monthly Downloads
        :target: https://pepy.tech/project/cffm

.. image:: https://img.shields.io/badge/-PyScaffold-005CA0?logo=pyscaffold
    :alt: Project generated with PyScaffold
    :target: https://pyscaffold.org/

|

====
cffm
====

   Configuratio ex Fontibus Multis - Configuration from many sources

The purpose of this library is to provide a flexible framework for
an application's/library's configuration:

* [x] **Multiple sources** with precedence, e.g. default values < config files < environmental variables
* [x] Static typing with documentation
* [x] Extension via **Sections**
* [ ] Source validation
* [ ] Autogenerate example config files



Example
=======

>>> from cffm import config, field, section
>>> @config
... class AppConfig:
...     loglevel: int = field(1, description="Loglevel")
...     @section('bar')
...     class BarConfig:
...          foo: int
...          baz: bool = False
