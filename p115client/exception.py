#!/usr/bin/env python3
# encoding: utf-8

__all__ = [
    "P115Warning", "P115OSError", "AuthenticationError", "BusyOSError", "DataError", 
    "LoginError", "MultipartUploadAbort", "NotSupportedError", "OperationalError", 
]

import warnings

from itertools import count
from collections.abc import Mapping
from functools import cached_property

from .type import MultipartResumeData


class P115Warning(UserWarning):
    """本模块的最基础警示类
    """


_count = count(1).__next__
warnings.filterwarnings("always", category=UserWarning)
warnings.formatwarning = lambda message, category, filename, lineno, line=None: f"\r\x1b[K\x1b[1;31;43m{category.__qualname__}\x1b[0m(\x1b[32m{_count()}\x1b[0m) @ \x1b[3;4;34m{filename}\x1b[0m:\x1b[36m{lineno}\x1b[0m \x1b[5;31m➜\x1b[0m \x1b[1m{message}\x1b[0m\n"


class P115OSError(OSError):
    """本模块的最基础异常类
    """
    def __init__(self, /, *args):
        super().__init__(*args)

    def __getattr__(self, attr, /):
        message = self.message
        try:
            if isinstance(message, Mapping):
                return message[attr]
        except KeyError as e:
            raise AttributeError(attr) from e
        raise AttributeError(attr)

    def __getitem__(self, key, /):
        message = self.message
        if isinstance(message, Mapping):
            return message[key]
        return message

    @cached_property
    def message(self, /):
        args = self.args
        if len(args) >= 2:
            if not isinstance(args[0], int):
                return args[1]
        if args:
            return args[0]


class AuthenticationError(P115OSError):
    """当登录状态无效时抛出
    """


class BusyOSError(P115OSError):
    """当操作繁忙时抛出（115 网盘的复制、移动、删除、还原只允许最多一个操作进行中）
    """


class DataError(P115OSError):
    """当响应数据解析失败时抛出
    """


class LoginError(AuthenticationError):
    """当登录失败时抛出
    """


class MultipartUploadAbort(P115OSError):
    """当分块上传失败时抛出，有个 ticket 属性，下次可用以继续任务
    """
    def __init__(self, ticket: MultipartResumeData, /):
        super().__init__(ticket)
        self.ticket = ticket

    def __repr__(self, /) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}({self.ticket})"


class NotSupportedError(P115OSError):
    """当调用不存在的接口时抛出
    """


class OperationalError(P115OSError):
    """当接口使用方法错误时抛出，例如参数错误、空间不足、超出允许数量范围等
    """

