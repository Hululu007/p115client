#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["ZERO_DICT", "bfs_gen"]

from collections import deque
from collections.abc import Generator, Iterator
from typing import overload, Literal


ZERO_DICT = type("", (dict,), {
    "__setitem__": staticmethod(lambda k, v, /: None), 
    "setdefault": staticmethod(lambda k, v, /: None), 
    "update": staticmethod(lambda *a, **k: None), 
})()


@overload
def bfs_gen[T](
    initial: T, 
    /, 
    unpack_iterator: Literal[False] = False, 
) -> Generator[T, T | None, None]:
    ...
@overload
def bfs_gen[T](
    initial: T | Iterator[T], 
    /, 
    unpack_iterator: Literal[True], 
) -> Generator[T, T | None, None]:
    ...
def bfs_gen[T](
    initial: T | Iterator[T], 
    /, 
    unpack_iterator: bool = False, 
) -> Generator[T, T | None, None]:
    """辅助函数，返回生成器，用来简化广度优先遍历
    """
    dq: deque = deque()
    push, pushmany, pop = dq.append, dq.extend, dq.popleft
    if isinstance(initial, Iterator) and unpack_iterator:
        pushmany(initial)
    else:
        push(initial)
    while dq:
        args: None | T = yield (val := pop())
        if unpack_iterator:
            while args is not None:
                if isinstance(args, Iterator):
                    pushmany(args)
                else:
                    push(args)
                args = yield val
        else:
            while args is not None:
                push(args)
                args = yield val

