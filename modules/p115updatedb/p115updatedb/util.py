#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["ZERO_DICT", "bfs_gen"]

from collections import deque
from collections.abc import Generator


ZERO_DICT = type("", (dict,), {
    "__setitem__": staticmethod(lambda k, v, /: None), 
    "setdefault": staticmethod(lambda k, v, /: None), 
    "update": staticmethod(lambda *a, **k: None), 
})()


def bfs_gen[T](initial: T, /) -> Generator[T, None | T, None]:
    """辅助函数，返回生成器，用来简化广度优先遍历
    """
    dq: deque = deque()
    push, pop = dq.append, dq.popleft
    push(initial)
    while dq:
        args: None | T = yield pop()
        while args is not None:
            push(args)
            args = yield args

