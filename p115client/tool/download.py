#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["batch_get_url", "iter_images_with_url", "iter_subtitles_with_url"]
__doc__ = "这个模块提供了一些和下载有关的函数"

from collections.abc import AsyncIterator, Callable, Coroutine, Iterable, Iterator
from functools import partial
from itertools import chain
from typing import overload, Any, Literal
from uuid import uuid4
from warnings import warn

from asynctools import async_chain_from_iterable
from iterutils import run_gen_step, run_gen_step_iter, Yield, YieldFrom
from p115client import P115Client, P115URL, normalize_attr
from p115client.exception import P115Warning
from posixpatht import escape

from .iterdir import iter_files, iter_files_raw, DirNode, DirNodeTuple


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
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        if isinstance(id_or_pickcode, int):
            resp = yield client.fs_file_skim(id_or_pickcode, async_=async_, **request_kwargs)
            if not resp or not resp["state"]:
                return {}
            pickcode = resp["data"][0]["pick_code"]
        elif isinstance(id_or_pickcode, str):
            pickcode = id_or_pickcode
        else:
            ids: list[int] = []
            pickcodes: list[str] = []
            for val in id_or_pickcode:
                if isinstance(val, int):
                    ids.append(val)
                else:
                    pickcodes.append(val)
            if ids:
                resp = yield client.fs_file_skim(ids, async_=async_, **request_kwargs)
                if resp and resp["state"]:
                    pickcodes.extend(info["pick_code"] for info in resp["data"])
            if not pickcodes:
                return {}
            pickcode = ",".join(pickcodes)
        headers = request_kwargs["headers"] = {"User-Agent": user_agent}
        resp = yield client.download_url_app(pickcode, async_=async_, **request_kwargs)
        if not resp["state"]:
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
def iter_images_with_url(
    client: str | P115Client, 
    cid: int = 0, 
    suffixes: None | str | Iterable[str] = None, 
    cur: Literal[0, 1] = 0, 
    with_ancestors: bool = False, 
    with_path: bool = False, 
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
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
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
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
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
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
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件信息，并增加一个 "url" 作为下载链接
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    params = dict(
        cur=cur, 
        with_ancestors=with_ancestors, 
        with_path=with_path, 
        escape=escape, 
        normalize_attr=normalize_attr, 
        id_to_dirnode=id_to_dirnode, 
        raise_for_changed_count=raise_for_changed_count, 
        async_=async_, 
    )
    def gen_step():
        if suffixes is None:
            it = iter_files(client, cid, type=2, **params, **request_kwargs) # type: ignore
        elif isinstance(suffixes, str):
            it = iter_files(client, cid, suffix=suffixes, **params, **request_kwargs) # type: ignore
        else:
            for suffix in suffixes:
                yield YieldFrom(
                    iter_images_with_url(client, cid, suffixes=suffix, **params, **request_kwargs), # type: ignore
                    identity=True, 
                )
            return
        do_next: Callable = anext if async_ else next
        while True:
            try:
                attr = yield partial(do_next, it)
                attr["url"] = attr["thumb"].replace("_100?", "_0?")
            except (StopIteration, StopAsyncIteration):
                break
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
                    attr["url"] = partial(
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
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
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
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
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
    escape: None | Callable[[str], str] = escape, 
    normalize_attr: Callable[[dict], dict] = normalize_attr, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
    raise_for_changed_count: bool = False, 
    *, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """获取字幕文件信息和下载链接

    .. caution::
        这个函数运行时，会把相关文件以 1_000 为一批，同一批次复制到同一个新建的目录，在批量获取链接后，自动把目录删除到回收站。

    .. attention::
        请不要把不能被 115 识别为字幕的文件扩展名放在 `suffixes` 参数中传入，这只是浪费时间，最后也只能获得普通的下载链接

    :param client: 115 客户端或 cookies
    :param cid: 目录 id
    :param suffixes: 扩展名，可以有多个，最前面的 "." 可以省略（请确保扩展名确实能被 115 认为是字幕，否则会因为不能批量获取到链接而浪费一些时间再去单独生成下载链接）
    :param cur: 仅当前目录。0: 否（将遍历子目录树上所有叶子节点），1: 是
    :param with_ancestors: 文件信息中是否要包含 "ancestors"
    :param with_path: 文件信息中是否要包含 "path"
    :param escape: 对文件名进行转义的函数。如果为 None，则不处理；否则，这个函数用来对文件名中某些符号进行转义，例如 "/" 等
    :param normalize_attr: 把数据进行转换处理，使之便于阅读
    :param id_to_dirnode: 字典，保存 id 到对应文件的 ``DirNode(name, parent_id)`` 命名元组的字典
    :param raise_for_changed_count: 分批拉取时，发现总数发生变化后，是否报错
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生文件信息，并增加一个 "url" 作为下载链接
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    def gen_step():
        nonlocal suffixes
        if isinstance(suffixes, str):
            suffixes = (suffixes,)
        do_chain: Callable = async_chain_from_iterable if async_ else chain.from_iterable
        do_next: Callable = anext if async_ else next
        it = do_chain(
            iter_files(
                client, 
                cid, 
                suffix=suffix, 
                cur=cur, 
                with_ancestors=with_ancestors, 
                with_path=with_path, 
                escape=escape, 
                normalize_attr=normalize_attr, 
                id_to_dirnode=id_to_dirnode, 
                raise_for_changed_count=raise_for_changed_count, 
                async_=async_, 
                **request_kwargs, 
            )
            for suffix in suffixes
        )
        attr: dict
        while True:
            items: list[dict] = []
            try:
                for i in range(1_000):
                    attr = yield partial(do_next, it)
                    items.append(attr)
            except (StopIteration, StopAsyncIteration):
                pass
            if not items:
                break
            try:
                resp = yield client.fs_mkdir(
                    f"subtitle-{uuid4()}", 
                    async_=async_, 
                    **request_kwargs, 
                )
                scid = resp["cid"]
                yield client.fs_copy(
                    (attr["id"] for attr in items), 
                    pid=scid, 
                    async_=async_, 
                    **request_kwargs, 
                )
                attr = yield do_next(iter_files_raw(
                    client, 
                    scid, 
                    first_page_size=1, 
                    async_=async_, 
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
                        attr["url"] = partial(
                            client.download_url, 
                            attr["pickcode"], 
                            async_=async_, 
                            **request_kwargs, 
                        )
                    yield Yield(attr, identity=True)
    return run_gen_step_iter(gen_step, async_=async_)

