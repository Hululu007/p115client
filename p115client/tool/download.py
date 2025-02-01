#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "MakeStrmLog", "reduce_image_url_layers", "batch_get_url", "iter_url_batches", 
    "iter_files_with_url", "iter_images_with_url", "iter_subtitles_with_url", 
    "iter_subtitle_batches", "make_strm", "make_strm_by_export_dir", 
    "iter_download_nodes", "iter_download_files", 
]
__doc__ = "这个模块提供了一些和下载有关的函数"

from asyncio import to_thread, Queue as AsyncQueue, Semaphore, TaskGroup
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from errno import ENOENT, ENOTDIR
from functools import partial
from glob import iglob
from inspect import isawaitable
from itertools import chain, count, cycle, islice
from mimetypes import guess_type
from os import fsdecode, makedirs, remove, PathLike
from os.path import dirname, join as joinpath, normpath, splitext
from queue import SimpleQueue
from threading import Lock
from time import perf_counter
from typing import overload, Any, Final, Literal, TypedDict
from urllib.parse import quote, urlsplit
from uuid import uuid4
from warnings import warn

from asynctools import async_chain_from_iterable
from concurrenttools import run_as_async, run_as_thread
from encode_uri import encode_uri_component_loose
from iterutils import chunked, run_gen_step, run_gen_step_iter, with_iter_next, Yield, YieldFrom
from p115client import check_response, normalize_attr, P115Client, P115URL
from p115client.exception import P115Warning
from posixpatht import escape

from .export_dir import export_dir_parse_iter
from .iterdir import get_path_to_cid, iterdir, iter_files, iter_files_raw, DirNode, ID_TO_DIRNODE_CACHE


def reduce_image_url_layers(url: str, /, size: str | int = "") -> str:
    """从图片的缩略图链接中提取信息，以减少一次 302 访问
    """
    if not url.startswith(("http://thumb.115.com/", "https://thumb.115.com/")):
        return url
    urlp = urlsplit(url)
    sha1, _, size0 = urlp.path.rsplit("/")[-1].partition("_")
    if size == "":
        size = size0 or "0"
    return f"https://imgjump.115.com/?sha1={sha1}&{urlp.query}&size={size}"


class MakeStrmResult(TypedDict):
    """用来展示 `make_strm` 函数的执行结果
    """
    total: int
    success: int
    failed: int
    skipped: int
    removed: int
    elapsed: float


class MakeStrmLog(str):
    """用来表示 `make_strm` 增删 strm 后的消息
    """
    def __new__(cls, msg: str = "", /, *args, **kwds):
        return super().__new__(cls, msg)

    def __init__(self, msg: str = "", /, *args, **kwds):
        self.__dict__.update(*args, **kwds)

    def __getattr__(self, attr: str, /):
        try:
            return self.__dict__[attr]
        except KeyError as e:
            raise AttributeError(attr) from e

    def __getitem__(self, key: str, /): # type: ignore
        if isinstance(key, str):
            return self.__dict__[key]
        return super().__getitem__(key)

    def __repr__(self, /) -> str:
        cls = type(self)
        if (module := cls.__module__) == "__main__":
            name = cls.__qualname__
        else:
            name = f"{module}.{cls.__qualname__}"
        return f"{name}({str(self)!r}, {self.__dict__!r})"

    @property
    def mapping(self, /) -> dict[str, Any]:
        return self.__dict__

    def get(self, key, /, default=None):
        return self.__dict__.get(key, default)

    def items(self, /):
        return self.__dict__.items()

    def keys(self, /):
        return self.__dict__.keys()

    def values(self, /):
        return self.__dict__.values()


@overload
def batch_get_url(
    client: str | P115Client, 
    id_or_pickcode: int | str | Iterable[int | str], 
    user_agent: str = "", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> dict[int, P115URL]:
    ...
@overload
def batch_get_url(
    client: str | P115Client, 
    id_or_pickcode: int | str | Iterable[int | str], 
    user_agent: str = "", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, dict[int, P115URL]]:
    ...
def batch_get_url(
    client: str | P115Client, 
    id_or_pickcode: int | str | Iterable[int | str], 
    user_agent: str = "", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> dict[int, P115URL] | Coroutine[Any, Any, dict[int, P115URL]]:
    """批量获取下载链接

    .. attention::
        请确保所有的 pickcode 都是有效的，要么是现在存在的，要么是以前存在过被删除的。

        如果有目录的 pickcode 混在其中，则会自动排除。

    :param client: 115 客户端或 cookies
    :param id_or_pickcode: 如果是 int，视为 id，如果是 str，视为 pickcode
    :param user_agent: "User-Agent" 请求头的值
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 字典，key 是文件 id，value 是下载链接，自动忽略所有无效项目
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if headers := request_kwargs.get("headers"):
        request_kwargs["headers"] = dict(headers, **{"User-Agent": user_agent})
    else:
        request_kwargs["headers"] = {"User-Agent": user_agent}
    def gen_step():
        if isinstance(id_or_pickcode, int):
            resp = yield client.fs_file_skim(
                id_or_pickcode, 
                async_=async_, 
                **request_kwargs, 
            )
            if not resp or not resp["state"]:
                return {}
            pickcode = resp["data"][0]["pick_code"]
        elif isinstance(id_or_pickcode, str):
            pickcode = id_or_pickcode
            if not (len(pickcode) == 17 and pickcode.isalnum()):
                return {}
        else:
            ids: list[int] = []
            pickcodes: list[str] = []
            for val in id_or_pickcode:
                if isinstance(val, int):
                    ids.append(val)
                elif len(val) == 17 and val.isalnum():
                    pickcodes.append(val)
            if ids:
                resp = yield client.fs_file_skim(
                    ids, 
                    method="POST", 
                    async_=async_, 
                    **request_kwargs, 
                )
                if resp and resp["state"]:
                    pickcodes.extend(info["pick_code"] for info in resp["data"])
            if not pickcodes:
                return {}
            pickcode = ",".join(pickcodes)
        resp = yield client.download_url_app(pickcode, async_=async_, **request_kwargs)
        if not resp["state"]:
            if resp.get("errno") != 50003:
                check_response(resp)
            return {}
        headers = resp["headers"]
        return {
            int(id): P115URL(
                info["url"]["url"], 
                id=int(id), 
                pickcode=info["pick_code"], 
                name=info["file_name"], 
                size=int(info["file_size"]), 
                sha1=info["sha1"], 
                is_directory=False,
                headers=headers, 
            )
            for id, info in resp["data"].items()
            if info["url"]
        }
    return run_gen_step(gen_step, async_=async_)


@overload
def iter_url_batches(
    client: str | P115Client, 
    pickcodes: Iterator[str], 
    user_agent: str = "", 
    batch_size: int = 10, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[P115URL]:
    ...
@overload
def iter_url_batches(
    client: str | P115Client, 
    pickcodes: Iterator[str], 
    user_agent: str = "", 
    batch_size: int = 10, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[P115URL]:
    ...
def iter_url_batches(
    client: str | P115Client, 
    pickcodes: Iterator[str], 
    user_agent: str = "", 
    batch_size: int = 10, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[P115URL] | AsyncIterator[P115URL]:
    """批量获取下载链接

    .. attention::
        请确保所有的 pickcode 都是有效的，要么是现在存在的，要么是以前存在过被删除的。

        如果有目录的 pickcode 混在其中，则会自动排除。

    :param client: 115 客户端或 cookies
    :param pickcodes: 一个迭代器，产生提取码 pickcode
    :param user_agent: "User-Agent" 请求头的值
    :param batch_size: 每一个批次处理的个量
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 字典，key 是文件 id，value 是下载链接，自动忽略所有无效项目
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if headers := request_kwargs.get("headers"):
        request_kwargs["headers"] = dict(headers, **{"User-Agent": user_agent})
    else:
        request_kwargs["headers"] = {"User-Agent": user_agent}
    if batch_size <= 0:
        batch_size = 1
    def gen_step():
        it = iter(pickcodes)
        while pcs := ",".join(islice(it, batch_size)):
            resp = yield client.download_url_app(
                pcs, 
                async_=async_, 
                **request_kwargs, 
            )
            if not resp["state"]:
                if resp.get("errno") != 50003:
                    check_response(resp)
                continue
            headers = resp["headers"]
            for id, info in resp["data"].items():
                if url_info := info["url"]:
                    yield Yield(P115URL(
                        url_info["url"], 
                        id=int(id), 
                        pickcode=info["pick_code"], 
                        name=info["file_name"], 
                        size=int(info["file_size"]), 
                        sha1=info["sha1"], 
                        is_directory=False,
                        headers=headers, 
                    ), identity=True)
    return run_gen_step_iter(gen_step, async_=async_)


# TODO: 支持按批获取 url，以减少总的耗时
@overload
def iter_files_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    user_agent: str = "", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_files_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    user_agent: str = "", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_files_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    user_agent: str = "", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """获取文件信息和下载链接

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param suffixes: 扩展名，可以有多个，最前面的 "." 可以省略
    :param type: 文件类型

        - 1: 文档
        - 2: 图片
        - 3: 音频
        - 4: 视频
        - 5: 压缩包
        - 6: 应用
        - 7: 书籍
        - 99: 仅文件

    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param use_star: 获取目录信息时，是否允许使用星标 （如果为 None，则采用流处理，否则采用批处理）
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 `DirNode(name, parent_id)` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param user_agent: "User-Agent" 请求头的值
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件信息，并增加一个 "url" 作为下载链接
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    params = dict(
        cur=cur, 
        with_ancestors=with_ancestors, 
        with_path=with_path, 
        use_star=use_star, 
        escape=escape, 
        normalize_attr=normalize_attr, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        async_=async_, 
        **request_kwargs, 
    )
    def gen_step():
        if suffixes is None:
            it = iter_files(
                client, 
                cid, 
                type=type, 
                app=app, 
                **params, # type: ignore
            )
        elif isinstance(suffixes, str):
            it = iter_files(
                client, 
                cid, 
                suffix=suffixes, 
                app=app, 
                **params, # type: ignore
            )
        else:
            for suffix in suffixes:
                yield YieldFrom(
                    iter_files_with_url(
                        client, 
                        cid, 
                        suffixes=suffix, 
                        app=app, 
                        **params, # type: ignore
                    ), 
                    identity=True, 
                )
            return
        with with_iter_next(it) as get_next:
            while True:
                attr = yield get_next
                if attr.get("violated", False):
                    if attr["size"] < 1024 * 1024 * 115:
                        attr["url"] = yield partial(
                            client.download_url, 
                            attr["pickcode"], 
                            use_web_api=True, 
                            async_=async_, 
                            **request_kwargs, 
                        )
                    else:
                        warn(f"unable to get url for {attr!r}", category=P115Warning)
                else:
                    attr["url"] = yield partial(
                        client.download_url, 
                        attr["pickcode"], 
                        async_=async_, 
                        **request_kwargs, 
                    )
            yield Yield(attr, identity=True)
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_images_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_images_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_images_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """获取图片文件信息和下载链接

    .. attention::
        请不要把不能被 115 识别为图片的文件扩展名放在 `suffixes` 参数中传入，这只是浪费时间，最后也只能获得普通的下载链接

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param suffixes: 扩展名，可以有多个，最前面的 "." 可以省略（请确保扩展名确实能被 115 认为是图片，否则会因为不能批量获取到链接而浪费一些时间再去单独生成下载链接）；如果不传（默认），则会获取所有图片
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param use_star: 获取目录信息时，是否允许使用星标 （如果为 None，则采用流处理，否则采用批处理）
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 `DirNode(name, parent_id)` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件信息，并增加一个 "url" 作为下载链接
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    params = dict(
        cur=cur, 
        with_ancestors=with_ancestors, 
        with_path=with_path, 
        use_star=use_star, 
        escape=escape, 
        normalize_attr=normalize_attr, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        async_=async_, 
        **request_kwargs
    )
    def gen_step():
        if suffixes is None:
            it = iter_files(
                client, 
                cid, 
                type=2, 
                app=app, 
                **params, # type: ignore
            )
        elif isinstance(suffixes, str):
            it = iter_files(
                client, 
                cid, 
                suffix=suffixes, 
                app=app, 
                **params, # type: ignore
            )
        else:
            for suffix in suffixes:
                yield YieldFrom(
                    iter_images_with_url(
                        client, 
                        cid, 
                        suffixes=suffix, 
                        app=app, 
                        **params, # type: ignore
                    ), 
                    identity=True, 
                )
            return
        with with_iter_next(it) as get_next:
            while True:
                attr = yield get_next
                try:
                    attr["url"] = reduce_image_url_layers(attr["thumb"])
                except KeyError:
                    if attr.get("violated", False):
                        if attr["size"] < 1024 * 1024 * 115:
                            attr["url"] = yield partial(
                                client.download_url, 
                                attr["pickcode"], 
                                use_web_api=True, 
                                async_=async_, 
                                **request_kwargs, 
                            )
                        else:
                            warn(f"unable to get url for {attr!r}", category=P115Warning)
                    else:
                        attr["url"] = yield partial(
                            client.download_url, 
                            attr["pickcode"], 
                            async_=async_, 
                            **request_kwargs, 
                        )
            yield Yield(attr, identity=True)
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_subtitles_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: str | Iterable[str] = (".srt", ".ass", ".ssa"), 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_subtitles_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: str | Iterable[str] = (".srt", ".ass", ".ssa"), 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_subtitles_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: str | Iterable[str] = (".srt", ".ass", ".ssa"), 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    use_star: None | bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    app: str = "web", 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """获取字幕文件信息和下载链接

    .. caution::
        这个函数运行时，会把相关文件以 1,000 为一批，同一批次复制到同一个新建的目录，在批量获取链接后，自动把目录删除到回收站。

    .. attention::
        目前看来 115 只支持：".srt", ".ass", ".ssa"

        请不要把不能被 115 识别为字幕的文件扩展名放在 `suffixes` 参数中传入，这只是浪费时间，最后也只能获得普通的下载链接

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param suffixes: 扩展名，可以有多个，最前面的 "." 可以省略（请确保扩展名确实能被 115 认为是字幕，否则会因为不能批量获取到链接而浪费一些时间再去单独生成下载链接）
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param use_star: 获取目录信息时，是否允许使用星标 （如果为 None，则采用流处理，否则采用批处理）
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 `DirNode(name, parent_id)` 命名元组的字典
    :param app: 使用某个 app （设备）的接口
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件信息，并增加一个 "url" 作为下载链接
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        nonlocal suffixes
        if isinstance(suffixes, str):
            suffixes = suffixes,
        do_chain: Callable = async_chain_from_iterable if async_ else chain.from_iterable
        it = chunked(do_chain(
            iter_files(
                client, 
                cid, 
                suffix=suffix, 
                cur=cur, 
                with_ancestors=with_ancestors, 
                with_path=with_path, 
                use_star=use_star, 
                escape=escape, 
                normalize_attr=normalize_attr, 
                id_to_dirnode=id_to_dirnode, 
                app=app, 
                raise_for_changed_count=raise_for_changed_count, 
                async_=async_, # type: ignore
                **request_kwargs, 
            )
            for suffix in suffixes
        ), 1000)
        do_next = anext if async_ else next
        with with_iter_next(it) as get_next:
            while True:
                items: tuple[dict] = yield get_next
                resp = yield client.fs_mkdir(
                    f"subtitle-{uuid4()}", 
                    async_=async_, 
                    **request_kwargs, 
                )
                check_response(resp)
                try:
                    scid = resp["cid"]
                    resp = yield client.fs_copy(
                        (attr["id"] for attr in items), 
                        pid=scid, 
                        async_=async_, 
                        **request_kwargs, 
                    )
                    check_response(resp)
                    attr = yield do_next(iter_files_raw(
                        client, 
                        scid, 
                        first_page_size=1, 
                        base_url=True, 
                        async_=async_, # type: ignore
                        **request_kwargs, 
                    ))
                    resp = yield client.fs_video_subtitle(
                        attr["pc"], 
                        async_=async_, 
                        **request_kwargs, 
                    )
                    subtitles = {
                        info["sha1"]: info["url"]
                        for info in resp["data"]["list"] 
                        if info.get("file_id")
                    }
                finally:
                    yield client.fs_delete(scid, async_=async_, **request_kwargs)
            if subtitles:
                for attr in items:
                    attr["url"] = subtitles[attr["sha1"]]
                    yield Yield(attr, identity=True)
            else:
                for attr in items:
                    if attr.get("violated", False):
                        if attr["size"] < 1024 * 1024 * 115:
                            attr["url"] = yield partial(
                                client.download_url, 
                                attr["pickcode"], 
                                use_web_api=True, 
                                async_=async_, 
                                **request_kwargs, 
                            )
                        else:
                            warn(f"unable to get url for {attr!r}", category=P115Warning)
                    else:
                        attr["url"] = yield partial(
                            client.download_url, 
                            attr["pickcode"], 
                            async_=async_, 
                            **request_kwargs, 
                        )
                    yield Yield(attr, identity=True)
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def iter_subtitle_batches(
    client: str | P115Client, 
    file_ids: Iterable[int], 
    batch_size: int = 1_000, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_subtitle_batches(
    client: str | P115Client, 
    file_ids: Iterable[int], 
    batch_size: int = 1_000, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_subtitle_batches(
    client: str | P115Client, 
    file_ids: Iterable[int], 
    batch_size: int = 1_000, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """批量获取字幕文件的信息和下载链接

    .. caution::
        这个函数运行时，会把相关文件以 1,000 为一批，同一批次复制到同一个新建的目录，在批量获取链接后，自动把目录删除到回收站。

    .. attention::
        目前看来 115 只支持：".srt"、".ass"、".ssa"，如果不能被 115 识别为字幕，将会被自动略过

    :param client: 115 客户端或 cookies
    :param file_ids: 一组文件的 id（必须全是 115 所认为的字幕）
    :param batch_size: 每一个批次处理的个量
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件信息，并增加一个 "url" 作为下载链接，文件信息中的 file_id 是复制所得的文件信息，不是原来文件的 id
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if batch_size <= 0:
        batch_size = 1_000
    def gen_step():
        do_next: Callable = anext if async_ else next
        for ids in chunked(file_ids, batch_size):
            try:
                resp = yield client.fs_mkdir(
                    f"subtitle-{uuid4()}", 
                    async_=async_, 
                    **request_kwargs, 
                )
                check_response(resp)
                scid = resp["cid"]
                resp = yield client.fs_copy(
                    ids, 
                    pid=scid, 
                    async_=async_, 
                    **request_kwargs, 
                )
                check_response(resp)
                attr = yield do_next(iter_files_raw(
                    client, 
                    scid, 
                    first_page_size=1, 
                    base_url=True, 
                    async_=async_, 
                    **request_kwargs, 
                ))
                resp = yield client.fs_video_subtitle(
                    attr["pc"], 
                    async_=async_, 
                    **request_kwargs, 
                )
                check_response(resp)
                yield YieldFrom(
                    filter(lambda info: "file_id" in info, resp["data"]["list"]), 
                    identity=True, 
                )
            except (StopIteration, StopAsyncIteration):
                pass
            finally:
                yield client.fs_delete(scid, async_=async_, **request_kwargs)
    return run_gen_step_iter(gen_step, async_=async_)


@overload
def make_strm(
    client: str | P115Client, 
    cid: int = 0, 
    save_dir: bytes | str | PathLike = ".", 
    origin: str = "http://localhost:8000", 
    use_abspath: None | bool = True, 
    with_root: bool = True, 
    without_suffix: bool = True, 
    ensure_ascii: bool = False, 
    log: None | Callable[[MakeStrmLog], Any] = print, 
    max_workers: None | int = None, 
    update: bool = False, 
    discard: bool = True, 
    app: str = "web", 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> MakeStrmResult:
    ...
@overload
def make_strm(
    client: str | P115Client, 
    cid: int = 0, 
    save_dir: bytes | str | PathLike = ".", 
    origin: str = "http://localhost:8000", 
    use_abspath: None | bool = True, 
    with_root: bool = True, 
    without_suffix: bool = True, 
    ensure_ascii: bool = False, 
    log: None | Callable[[MakeStrmLog], Any] = print, 
    max_workers: None | int = None, 
    update: bool = False, 
    discard: bool = True, 
    app: str = "web", 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, MakeStrmResult]:
    ...
def make_strm(
    client: str | P115Client, 
    cid: int = 0, 
    save_dir: bytes | str | PathLike = ".", 
    origin: str = "http://localhost:8000", 
    use_abspath: None | bool = True, 
    with_root: bool = True, 
    without_suffix: bool = True, 
    ensure_ascii: bool = False, 
    log: None | Callable[[MakeStrmLog], Any] = print, 
    max_workers: None | int = None, 
    update: bool = False, 
    discard: bool = True, 
    app: str = "web", 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> MakeStrmResult | Coroutine[Any, Any, MakeStrmResult]:
    """生成 strm 保存到本地

    .. hint::
        函数在第 2 次处理同一个 id 时，速度会快一些，因为第 1 次时候需要全量拉取构建路径所需的数据

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param save_dir: 本地的保存目录，默认是当前工作目录
    :param origin: strm 文件的 `HTTP 源 <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin>`_
    :param use_abspath: 是否使用相对路径

        - 如果为 True，则使用 115 的完整路径
        - 如果为 False，则使用从 `cid` 的目录开始的相对路径
        - 如果为 None，则所有文件保存在到同一个目录内

    :param with_root: 如果为 True，则当 use_abspath 为 False 或 None 时，在 `save_dir` 下创建一个和 `cid` 目录名字相同的目录，作为实际的 `save_dir`
    :param without_suffix: 是否去除原来的扩展名。如果为 False，则直接用 ".strm" 拼接到原来的路径后面；如果为 True，则去掉原来的扩展名后再拼接
    :param ensure_ascii: strm 是否进行完全转码，确保 ascii 之外的字符都被 urlencode 转码
    :param log: 调用以收集事件，如果为 None，则忽略
    :param max_workers: 最大并发数，主要用于限制同时打开的文件数
    :param update: 是否更新 strm 文件，如果为 False，则跳过已存在的路径
    :param discard: 是否清理 strm 文件，如果为 True，则删除未取得的路径（不在本次的路径集合内）
    :param app: 使用某个 app （设备）的接口
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数
    """
    origin = origin.rstrip("/")
    savedir = fsdecode(save_dir)
    makedirs(savedir, exist_ok=True)
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    mode = "w" if update else "x"
    if discard:
        seen: set[str] = set()
        seen_add = seen.add
        existing: set[str] = set()
        def do_discard():
            removed = 0
            for path in existing - seen:
                path = joinpath(savedir, path)
                try:
                    remove(path)
                    if log is not None:
                        log(MakeStrmLog(
                            f"[DEL] path={path!r}", 
                            type="remove", 
                            path=path, 
                        ))
                    removed += 1
                except OSError:
                    pass
            return removed
    abspath_prefix_length = 1
    def normalize_path(attr: dict, /) -> str:
        if use_abspath is None:
            path = attr["name"]
        elif use_abspath:
            path = attr["path"][abspath_prefix_length:]
        else:
            dir_ = get_path_to_cid(
                client, 
                cid, 
                root_id=attr["parent_id"], 
                escape=None, 
                id_to_dirnode=id_to_dirnode, 
            )
            path = joinpath(dir_, attr["name"])
        if without_suffix:
            path = splitext(path)[0]
        relpath = normpath(path) + ".strm"
        if discard:
            seen_add(relpath)
        return joinpath(savedir, relpath)
    if async_:
        try:
            from aiofile import async_open
        except ImportError:
            from sys import executable
            from subprocess import run
            run([executable, "-m", "pip", "install", "-U", "aiofile"], check=True)
            from aiofile import async_open # type: ignore
        if max_workers is None or max_workers <= 0:
            sema = None
        else:
            sema = Semaphore(max_workers)
        async def request():
            nonlocal savedir, abspath_prefix_length
            if use_abspath:
                if cid:
                    root = await get_path_to_cid(
                        client, 
                        cid, 
                        escape=None, 
                        refresh=True, 
                        async_=True, 
                        **request_kwargs, 
                    )
                    savedir += root
                    abspath_prefix_length = len(root) + 1
            elif with_root:
                resp = await client.fs_file_skim(cid, async_=True, **request_kwargs)
                if not resp:
                    raise FileNotFoundError(ENOENT, cid)
                check_response(resp)
                savedir = joinpath(savedir, resp["data"][0]["file_name"])
            success = 0
            failed = 0
            skipped = 0
            removed = 0
            async def save(attr, /, sema=None):
                nonlocal success, failed, skipped
                if sema is not None:
                    async with sema:
                        return await save(attr)
                path = normalize_path(attr)
                url = f"{origin}/{encode_uri_component_loose(attr['name'], ensure_ascii=ensure_ascii)}?pickcode={attr['pickcode']}&id={attr['id']}&sha1={attr['sha1']}&size={attr['size']}"
                try:
                    try:
                        async with async_open(path, mode) as f:
                            await f.write(url)
                    except FileExistsError:
                        if log is not None:
                            ret = log(MakeStrmLog(
                                f"[SKIP] path={path!r} attr={attr!r}", 
                                type="ignore", 
                                path=path, 
                                attr=attr, 
                            ))
                            if isawaitable(ret):
                                await ret
                        skipped += 1
                        return
                    except FileNotFoundError:
                        makedirs(dirname(path), exist_ok=True)
                        async with async_open(path, "w") as f:
                            await f.write(url)
                    if log is not None:
                        ret = log(MakeStrmLog(
                            f"[OK] path={path!r} attr={attr!r}", 
                            type="write", 
                            path=path, 
                            attr=attr, 
                        ))
                        if isawaitable(ret):
                            await ret
                    success += 1
                except BaseException as e:
                    failed += 1
                    if log is not None:
                        ret =log(MakeStrmLog(
                            f"[ERROR] path={path!r} attr={attr!r} error={e!r}", 
                            type="error", 
                            path=path, 
                            attr=attr, 
                            error=e, 
                        ))
                        if isawaitable(ret):
                            await ret
                    if not isinstance(e, OSError):
                        raise
            start_t = perf_counter()
            async with TaskGroup() as group:
                create_task = group.create_task
                if discard:
                    create_task(to_thread(lambda: existing.update(iglob("**/*.strm", root_dir=savedir, recursive=True))))
                async for attr in iter_files(
                    client, 
                    cid, 
                    type=4, 
                    with_path=use_abspath is not None, 
                    escape=None, 
                    app=app, 
                    async_=True, 
                    **request_kwargs, 
                ):
                    create_task(save(attr, sema))
            if discard:
                removed = do_discard()
            return {
                "total": success + failed + skipped, 
                "success": success, 
                "failed": failed, 
                "skipped": skipped, 
                "removed": removed, 
                "elapsed": perf_counter() - start_t, 
            }
        return request()
    else:
        if use_abspath:
            if cid:
                root = get_path_to_cid(
                    client, 
                    cid, 
                    escape=None, 
                    refresh=True, 
                    **request_kwargs, 
                )
                savedir += root
                abspath_prefix_length = len(root) + 1
        elif with_root:
            resp = client.fs_file_skim(cid, **request_kwargs)
            if not resp:
                raise FileNotFoundError(ENOENT, cid)
            check_response(resp)
            savedir = joinpath(savedir, resp["data"][0]["file_name"])
        success = 0
        failed = 0
        skipped = 0
        removed = 0
        lock = Lock()
        def save(attr: dict, /):
            nonlocal success, failed, skipped
            path = normalize_path(attr)
            try:
                try:
                    f = open(path, mode)
                except FileExistsError:
                    if log is not None:
                        log(MakeStrmLog(
                            f"[SKIP] path={path!r} attr={attr!r}", 
                            type="ignore", 
                            path=path, 
                            attr=attr, 
                        ))
                    skipped += 1
                    return
                except FileNotFoundError:
                    makedirs(dirname(path), exist_ok=True)
                    f = open(path,  "w")
                f.write(f"{origin}/{encode_uri_component_loose(attr['name'], ensure_ascii=ensure_ascii)}?pickcode={attr['pickcode']}&id={attr['id']}&sha1={attr['sha1']}&size={attr['size']}")
                if log is not None:
                    log(MakeStrmLog(
                        f"[OK] path={path!r} attr={attr!r}", 
                        type="write", 
                        path=path, 
                        attr=attr, 
                    ))
                with lock:
                    success += 1
            except BaseException as e:
                with lock:
                    failed += 1
                if log is not None:
                    log(MakeStrmLog(
                        f"[ERROR] path={path!r} attr={attr!r} error={e!r}", 
                        type="error", 
                        path=path, 
                        attr=attr, 
                        error=e, 
                    ))
                if not isinstance(e, OSError):
                    raise
        if max_workers and max_workers <= 0:
            max_workers = None
        start_t = perf_counter()
        executor = ThreadPoolExecutor(max_workers)
        try:
            if discard:
                executor.submit(lambda: existing.update(iglob("**/*.strm", root_dir=savedir, recursive=True)))
            executor.map(save, iter_files(
                client, 
                cid, 
                type=4, 
                with_path=use_abspath is not None, 
                escape=None, 
                app=app, 
                **request_kwargs, 
            ))
            executor.shutdown(wait=True)
            if discard:
                removed = do_discard()
            return {
                "total": success + failed + skipped, 
                "success": success, 
                "failed": failed, 
                "skipped": skipped, 
                "removed": removed, 
                "elapsed": perf_counter() - start_t, 
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


@overload
def make_strm_by_export_dir(
    client: str | P115Client, 
    export_file_ids: int | str | Iterable[int | str], 
    save_dir: bytes | str | PathLike = ".", 
    origin: str = "http://localhost:8000", 
    without_suffix: bool = True, 
    ensure_ascii: bool = False, 
    log: None | Callable[[MakeStrmLog], Any] = print, 
    max_workers: None | int = None, 
    update: bool = False, 
    discard: bool = True, 
    layer_limit: int = 0, 
    timeout: None | int | float = None, 
    check_interval: int | float = 1, 
    show_clock: bool | Callable[[], Any] = True, 
    clock_interval: int | float = 0.05, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> MakeStrmResult:
    ...
@overload
def make_strm_by_export_dir(
    client: str | P115Client, 
    export_file_ids: int | str | Iterable[int | str], 
    save_dir: bytes | str | PathLike = ".", 
    origin: str = "http://localhost:8000", 
    without_suffix: bool = True, 
    ensure_ascii: bool = False, 
    log: None | Callable[[MakeStrmLog], Any] = print, 
    max_workers: None | int = None, 
    update: bool = False, 
    discard: bool = True, 
    layer_limit: int = 0, 
    timeout: None | int | float = None, 
    check_interval: int | float = 1, 
    show_clock: bool | Callable[[], Any] = True, 
    clock_interval: int | float = 0.05, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> Coroutine[Any, Any, MakeStrmResult]:
    ...
def make_strm_by_export_dir(
    client: str | P115Client, 
    export_file_ids: int | str | Iterable[int | str], 
    save_dir: bytes | str | PathLike = ".", 
    origin: str = "http://localhost:8000", 
    without_suffix: bool = True, 
    ensure_ascii: bool = False, 
    log: None | Callable[[MakeStrmLog], Any] = print, 
    max_workers: None | int = None, 
    update: bool = False, 
    discard: bool = True, 
    layer_limit: int = 0, 
    timeout: None | int | float = None, 
    check_interval: int | float = 1, 
    show_clock: bool | Callable[[], Any] = True, 
    clock_interval: int | float = 0.05, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> MakeStrmResult | Coroutine[Any, Any, MakeStrmResult]:
    """生成 strm 保存到本地（通过导出目录树 `export_dir`）

    .. hint::
        通过 `mimetypes.guess_type` 判断文件的 `mimetype <https://developer.mozilla.org/en-US/docs/Web/HTTP/MIME_types>`_，如果以 "video/" 开头，则会生成相应的 strm 文件

        有哪些扩展名会被系统识别为视频，在不同电脑是上是不同的，你可以使用 `mimetypes.add_type` 添加一些 mimetype 和 扩展名 的关系

        或者你可以安装这个模块，`mimetype_more <https://pypi.org/project/mimetype_more/>`_，我已经在其中添加了很多的 mimetype 和 扩展名 的关系，import 此模块后即会自行添加

        .. code:: console

            pip install -U mimetype_more

    :param client: 115 客户端或 cookies
    :param export_file_ids: 待导出的目录 id 或 路径（如果有多个，需传入可迭代对象）
    :param save_dir: 本地的保存目录，默认是当前工作目录
    :param origin: strm 文件的 `HTTP 源 <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin>`_
    :param without_suffix: 是否去除原来的扩展名。如果为 False，则直接用 ".strm" 拼接到原来的路径后面；如果为 True，则去掉原来的扩展名后再拼接
    :param ensure_ascii: strm 是否进行完全转码，确保 ascii 之外的字符都被 urlencode 转码
    :param log: 调用以收集事件，如果为 None，则忽略
    :param max_workers: 最大并发数，主要用于限制同时打开的文件数
    :param update: 是否更新 strm 文件，如果为 False，则跳过已存在的路径
    :param discard: 是否清理 strm 文件，如果为 True，则删除未取得的路径（不在本次的路径集合内）
    :param layer_limit: 层级深度，小于等于 0 时不限
    :param timeout: 导出任务的超时秒数，如果为 None 或 小于等于 0，则相当于 float("inf")，即永不超时
    :param check_interval: 导出任务的状态，两次轮询之间的等待秒数，如果 <= 0，则不等待
    :param show_clock: 是否在等待导出目录树时，显示时钟。如果为 True，则显示默认的时钟，如果为 Callable，则作为自定义时钟进行调用（无参数）
    :param clock_interval: 更新时钟的时间间隔
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数
    """
    origin = origin.rstrip("/")
    savedir = fsdecode(save_dir)
    makedirs(savedir, exist_ok=True)
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    mode = "w" if update else "x"
    if discard:
        seen: set[str] = set()
        seen_add = seen.add
        existing: set[str] = set()
        def do_discard():
            removed = 0
            for path in existing - seen:
                path = joinpath(savedir, path)
                try:
                    remove(path)
                    if log is not None:
                        log(MakeStrmLog(
                            f"[DEL] path={path!r}", 
                            type="remove", 
                            path=path, 
                        ))
                    removed += 1
                except OSError:
                    pass
            return removed
    def normalize_path(path: str, /) -> str:
        if without_suffix:
            path = splitext(path)[0]
        relpath = normpath(path[1:]) + ".strm"
        if discard:
            seen_add(relpath)
        return joinpath(savedir, relpath)
    if async_:
        try:
            from aiofile import async_open
        except ImportError:
            from sys import executable
            from subprocess import run
            run([executable, "-m", "pip", "install", "-U", "aiofile"], check=True)
            from aiofile import async_open
        if max_workers is None or max_workers <= 0:
            sema = None
        else:
            sema = Semaphore(max_workers)
        async def request():
            success = 0
            failed = 0
            skipped = 0
            removed = 0
            async def save(remote_path, /, sema=None):
                nonlocal success, failed, skipped
                if sema is not None:
                    async with sema:
                        return await save(remote_path)
                path = normalize_path(remote_path)
                url = f"{origin}/{encode_uri_component_loose(remote_path, ensure_ascii=ensure_ascii)}"
                try:
                    try:
                        async with async_open(path, mode) as f:
                            await f.write(url)
                    except FileExistsError:
                        if log is not None:
                            ret = log(MakeStrmLog(
                                f"[SKIP] path={path!r} remote_path={remote_path!r}", 
                                type="ignore", 
                                path=path, 
                                remote_path=remote_path, 
                            ))
                            if isawaitable(ret):
                                await ret
                        skipped += 1
                        return
                    except FileNotFoundError:
                        makedirs(dirname(path), exist_ok=True)
                        async with async_open(path, "w") as f:
                            await f.write(url)
                    if log is not None:
                        ret = log(MakeStrmLog(
                            f"[OK] path={path!r} remote_path={remote_path!r}", 
                            type="write", 
                            path=path, 
                            remote_path=remote_path, 
                        ))
                        if isawaitable(ret):
                            await ret
                    success += 1
                except BaseException as e:
                    failed += 1
                    if log is not None:
                        ret =log(MakeStrmLog(
                            f"[ERROR] path={path!r} remote_path={remote_path!r} error={e!r}", 
                            type="error", 
                            path=path, 
                            remote_path=remote_path, 
                            error=e, 
                        ))
                        if isawaitable(ret):
                            await ret
                    if not isinstance(e, OSError):
                        raise
            start_t = perf_counter()
            async with TaskGroup() as group:
                create_task = group.create_task
                if discard:
                    create_task(to_thread(lambda: existing.update(iglob("**/*.strm", root_dir=savedir, recursive=True))))
                async for remote_path in export_dir_parse_iter(
                    client, 
                    export_file_ids=export_file_ids, 
                    layer_limit=layer_limit, 
                    timeout=timeout, 
                    check_interval=check_interval, 
                    show_clock=show_clock, 
                    clock_interval=clock_interval, 
                    async_=async_, 
                    **request_kwargs, 
                ):
                    mime = guess_type(remote_path)[0]
                    if mime and mime.startswith("video/"):
                        create_task(save(remote_path, sema))
            if discard:
                removed = do_discard()
            return {
                "total": success + failed + skipped, 
                "success": success, 
                "failed": failed, 
                "skipped": skipped, 
                "removed": removed, 
                "elapsed": perf_counter() - start_t, 
            }
        return request()
    else:
        success = 0
        failed = 0
        skipped = 0
        removed = 0
        lock = Lock()
        def save(remote_path: str, /):
            nonlocal success, failed, skipped
            path = normalize_path(remote_path)
            try:
                try:
                    f = open(path, mode)
                except FileExistsError:
                    if log is not None:
                        log(MakeStrmLog(
                            f"[SKIP] path={path!r} remote_path={remote_path!r}", 
                            type="ignore", 
                            path=path, 
                            remote_path=remote_path, 
                        ))
                    skipped += 1
                    return
                except FileNotFoundError:
                    makedirs(dirname(path), exist_ok=True)
                    f = open(path,  "w")
                f.write(f"{origin}/{encode_uri_component_loose(remote_path, ensure_ascii=ensure_ascii)}")
                if log is not None:
                    log(MakeStrmLog(
                        f"[OK] path={path!r} remote_path={remote_path!r}", 
                        type="write", 
                        path=path, 
                        remote_path=remote_path, 
                    ))
                with lock:
                    success += 1
            except BaseException as e:
                with lock:
                    failed += 1
                if log is not None:
                    log(MakeStrmLog(
                        f"[ERROR] path={path!r} remote_path={remote_path!r} error={e!r}", 
                        type="error", 
                        path=path, 
                        remote_path=remote_path, 
                        error=e, 
                    ))
                if not isinstance(e, OSError):
                    raise
        if max_workers and max_workers <= 0:
            max_workers = None
        start_t = perf_counter()
        executor = ThreadPoolExecutor(max_workers)
        submit = executor.submit
        try:
            if discard:
                submit(lambda: existing.update(iglob("**/*.strm", root_dir=savedir, recursive=True)))
            for remote_path in export_dir_parse_iter(
                client, 
                export_file_ids=export_file_ids, 
                layer_limit=layer_limit, 
                timeout=timeout, 
                check_interval=check_interval, 
                show_clock=show_clock, 
                clock_interval=clock_interval, 
                **request_kwargs, 
            ):
                mime = guess_type(remote_path)[0]
                if mime and mime.startswith("video/"):
                    submit(save, remote_path)
            executor.shutdown(wait=True)
            if discard:
                removed = do_discard()
            return {
                "total": success + failed + skipped, 
                "success": success, 
                "failed": failed, 
                "skipped": skipped, 
                "removed": removed, 
                "elapsed": perf_counter() - start_t, 
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


@overload
def iter_download_nodes(
    client: str | P115Client, 
    pickcode: str, 
    files: bool = True, 
    max_workers: None | int = 1, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_download_nodes(
    client: str | P115Client, 
    pickcode: str, 
    files: bool = True, 
    max_workers: None | int = 1, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_download_nodes(
    client: str | P115Client, 
    pickcode: str, 
    files: bool = True, 
    max_workers: None | int = 1, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """获取一个目录内所有的文件或者目录的信息（简略）

    :param client: 115 客户端或 cookies
    :param pickcode: 目录的提取码
    :param files: 如果为 True，则只获取文件，否则只获取目录
    :param max_workers: 最大并发数，如果为 None 或 <= 0，则默认为 20
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件或者目录的简略信息
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if files:
        method = client.download_files
    else:
        method = client.download_folders
    request_kwargs.setdefault("base_url", cycle(("http://proapi.115.com", "https://proapi.115.com")).__next__)
    if max_workers == 1:
        def gen_step():
            for i in count(1):
                payload = {"pickcode": pickcode, "page": i}
                resp = yield method(payload, async_=async_, **request_kwargs)
                check_response(resp)
                data = resp["data"]
                yield YieldFrom(data["list"], identity=True)
                if not data["has_next_page"]:
                    break
    else:
        get_next_page = count(1).__next__
        if async_:
            q: Any = AsyncQueue()
        else:
            q = SimpleQueue()
        get, put = q.get, q.put_nowait
        max_page = 0
        def request():
            nonlocal max_page
            while True:
                page = get_next_page()
                if max_page and page > max_page:
                    return
                resp: dict = yield method(
                    {"pickcode": pickcode, "page": page}, 
                    async_=async_, # type: ignore
                    **request_kwargs, 
                )
                try:
                    check_response(resp)
                except BaseException as e:
                    put(e)
                    return
                data = resp["data"]
                put(data["list"])
                if not data["has_next_page"]:
                    max_page = page
        def gen_step():
            nonlocal max_workers
            if async_:
                if max_workers is None or max_workers <= 0:
                    max_workers = 20
                n = max_workers
                task_group = TaskGroup()
                yield task_group.__aenter__()
                create_task = task_group.create_task
                submit: Callable = lambda f, /, *a, **k: create_task(f(*a, **k))
                shutdown: Callable = lambda: task_group.__aexit__(None, None, None)
            else:
                if max_workers is not None and max_workers <= 0:
                    max_workers = None
                executor = ThreadPoolExecutor(max_workers)
                n = executor._max_workers
                submit = executor.submit
                shutdown = lambda: executor.shutdown(False, cancel_futures=True)
            try:
                sentinel = object()
                countdown: Callable
                if async_:
                    def countdown(_, /):
                        nonlocal n
                        n -= 1
                        if not n:
                            put(sentinel)
                else:
                    def countdown(_, /, lock=Lock()):
                        nonlocal n
                        with lock:
                            n -= 1
                            if not n:
                                put(sentinel)
                for i in range(n):
                    submit(run_gen_step, request, async_=async_).add_done_callback(countdown)
                while True:
                    ls = yield get
                    if ls is sentinel:
                        break
                    elif isinstance(ls, BaseException):
                        raise ls
                    yield YieldFrom(ls, identity=True)
            finally:
                yield shutdown
    return run_gen_step_iter(gen_step, async_=async_)


def iter_download_files(
    client: str | P115Client, 
    cid: int = 0, 
    id_to_dirnode: None | dict[int, tuple[str, int] | DirNode] = None, 
    max_workers: None | int = None, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
):
    """获取一个目录内所有的文件信息（简略），且包括 "dir_ancestors"、"dirname" 和 "posix_dirname"

    .. note::
        并不提供文件的 id 和 name，但有 pickcode，如果需要获得 name，你可以在之后获取下载链接，然后从下载链接中获取实际的名字

        如果要通过 pickcode 获取基本信息，请用 `P115Client.fs_supervision`

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param id_to_dirnode: 字典，保存 id 到对应文件的 `DirNode(name, parent_id)` 命名元组的字典
    :param max_workers: 最大并发数，如果为 None 或 <= 0，则默认为 20
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件的简略信息
    """
    if not isinstance(client, P115Client):
        client = P115Client(client, check_for_relogin=True)
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE_CACHE[client.user_id]
    else:
        id_to_dirnode = {}
    id_to_ancestors: dict[int, list[dict]] = {}
    def get_ancestors(id: int, attr: dict | tuple[str, int] | DirNode, /) -> list[dict]:
        if isinstance(attr, (DirNode, tuple)):
            name, pid = attr
        else:
            pid = attr["parent_id"]
            name = attr["name"]
        if pid == 0:
            ancestors = [{"id": 0, "parent_id": 0, "name": ""}]
        else:
            if pid not in id_to_ancestors:
                id_to_ancestors[pid] = get_ancestors(pid, id_to_dirnode[pid])
            ancestors = [*id_to_ancestors[pid]]
        ancestors.append({"id": id, "parent_id": pid, "name": name})
        return ancestors
    id_to_path: dict[int, str] = {}
    id_to_posixpath: dict[int, str] = {}
    def get_path(attr: dict | tuple[str, int] | DirNode, /) -> tuple[str, str]:
        if isinstance(attr, (DirNode, tuple)):
            name, pid = attr
        else:
            pid = attr["parent_id"]
            name = attr["name"]
        ename = name
        if escape is not None:
            ename = escape(ename)
        name = name.replace("/", "|")
        if pid == 0:
            return "/" + ename, "/" + name
        elif pid in id_to_path:
            return id_to_path[pid] + ename, id_to_posixpath[pid] + name
        else:
            dirname, posix_dirname = get_path(id_to_dirnode[pid])
            dirname += "/"
            posix_dirname += "/"
            id_to_path[pid], id_to_posixpath[pid] = dirname, posix_dirname
            return dirname + ename, posix_dirname + name
    def norm_attr(info: dict, /) -> dict:
        pid = int(info["pid"])
        attr = {"parent_id": pid, "pickcode": info["pc"], "size": info["fs"]}
        pnode = id_to_dirnode[pid]
        attr["dir_ancestors"] = get_ancestors(pid, pnode)
        attr["dirname"], attr["posix_dirname"] = get_path(pnode)
        return attr
    def gen_step(pickcode: str = ""):
        if not cid:
            defaults = {
                "dir_ancestors": [{"id": 0, "parent_id": 0, "name": ""}],
                "dirname": "/",
                "posix_dirname": "/", 
            }
            pickcodes: list[str] = []
            with with_iter_next(iterdir(
                client, 
                id_to_dirnode=id_to_dirnode, 
                app="android", 
                raise_for_changed_count=True, 
                async_=async_, # type: ignore
                **request_kwargs, 
            )) as get_next:
                while True:
                    attr = yield get_next
                    if attr["is_dir"]:
                        pickcodes.append(attr["pickcode"])
                    else:
                        yield Yield({
                            "parent_id": attr["parent_id"],
                            "pickcode": attr["pickcode"],
                            "size": attr["size"],
                            **defaults, 
                        }, identity=True)
            for pickcode in pickcodes:
                yield YieldFrom(run_gen_step_iter(gen_step(pickcode), async_=async_), identity=True)
            return
        if not pickcode:
            resp = yield client.fs_file_skim(cid, async_=async_, **request_kwargs)
            check_response(resp)
            info = resp["data"][0]
            if info["sha1"]:
                raise NotADirectoryError(ENOTDIR, info)
            pickcode = info["pick_code"]
        ancestors_loaded: None | bool = False
        def load_ancestors():
            nonlocal ancestors_loaded
            if cid:
                resp = yield client.fs_files(
                    {"cid": cid, "limit": 1}, 
                    async_=async_, 
                    **request_kwargs, 
                )
                check_response(resp)
                for info in resp["path"][1:]:
                    id_to_dirnode[int(info["cid"])] = DirNode(info["name"], int(info["pid"]))
            try:
                with with_iter_next(iter_download_nodes(
                    client, 
                    pickcode, 
                    files=False, 
                    max_workers=max_workers, 
                    async_=async_, 
                    **request_kwargs, 
                )) as get_next:
                    while True:
                        info = yield get_next
                        id_to_dirnode[int(info["fid"])] = DirNode(info["fn"], int(info["pid"]))
            finally:
                ancestors_loaded = True
        if async_:
            future: Any = run_as_async(run_gen_step, load_ancestors, async_=async_)
        else:
            future = run_as_thread(run_gen_step, load_ancestors, async_=async_)
        cache: list[dict] = []
        add_to_cache = cache.append
        with with_iter_next(iter_download_nodes(
            client, 
            pickcode, 
            files=True, 
            max_workers=max_workers, 
            async_=async_, # type: ignore
            **request_kwargs, 
        )) as get_next:
            while True:
                info = yield get_next
                if ancestors_loaded is None:
                    yield Yield(norm_attr(info), identity=True)
                elif ancestors_loaded:
                    yield YieldFrom(map(norm_attr, cache), identity=True)
                    cache.clear()
                    yield future.result()
                    ancestors_loaded = None
                else:
                    add_to_cache(info)
        if cache:
            yield future.result()
            yield YieldFrom(map(norm_attr, cache), identity=True)
    return run_gen_step_iter(gen_step, async_=async_)

