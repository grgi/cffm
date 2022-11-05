
def iterate_to(type_: type, /): # -> Callable[Callable[[...], Iterator[_V]], _T[_V]]:
    def deco(gen): # Callable[[...], Iterator[_V]]) -> _T[_V]
        def wrapper(*args, **kwargs):
            return type_(gen(*args, **kwargs))
        return wrapper
    return deco
