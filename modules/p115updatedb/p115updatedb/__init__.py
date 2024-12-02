#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 1)
__all__ = ["updatedb", "updatedb_one", "updatedb_tree"]
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

import logging

from collections import defaultdict, deque
from collections.abc import Collection, Generator, Iterator, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from errno import EBUSY
from itertools import takewhile
from math import isnan, isinf
from posixpath import splitext
from sqlite3 import connect, Connection, Cursor
from string import digits
from time import perf_counter
from typing import cast, Final

from p115client import check_response, P115Client
from p115client.const import CLASS_TO_TYPE, SUFFIX_TO_TYPE
from p115client.exception import BusyOSError, DataError
from p115client.tool.edit import update_desc, update_star
from p115client.tool.iterdir import filter_na_ids, get_id_to_path, iter_stared_dirs
from sqlitetools import execute, find, query, transact, upsert_items, AutoCloseConnection


# NOTE: 目录的 id 到它的上级目录 id
CID_TO_PID: Final[dict[int, int]] = {}
# NOTE: 初始化日志对象
logger = logging.Logger("115-updatedb", level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) "
    "\x1b[0m\x1b[1;35m%(name)s\x1b[0m \x1b[5;31m➜\x1b[0m %(message)s"
))
logger.addHandler(handler)

ZERO_DICT = type("", (dict,), {
    "__setitem__": staticmethod(lambda k, v, /: None), 
    "setdefault": staticmethod(lambda k, v, /: None), 
    "update": staticmethod(lambda *a, **k: None), 
})()


def initdb(con: Connection | Cursor, /) -> Cursor:
    """初始化数据库，会尝试创建一些表、索引、触发器等，并把表的 "journal_mode" 改为 WAL (write-ahead-log)

    :param con: 数据库连接或游标

    :return: 游标
    """
    return con.executescript("""\
-- 修改日志模式为 WAL (write-ahead-log)
PRAGMA journal_mode = WAL;

-- data 表
CREATE TABLE IF NOT EXISTS data (
    id INTEGER NOT NULL PRIMARY KEY,   -- 文件或目录的 id
    parent_id INTEGER NOT NULL,        -- 上级目录的 id
    pickcode TEXT NOT NULL DEFAULT '', -- 提取码，下载时需要用到
    sha1 TEXT NOT NULL DEFAULT '',     -- 文件的 sha1 散列值
    name TEXT NOT NULL,                -- 名字
    size INTEGER NOT NULL DEFAULT 0,   -- 文件大小
    is_dir INTEGER NOT NULL CHECK(is_dir IN (0, 1)), -- 是否目录
    type INTEGER NOT NULL DEFAULT 0,   -- 文件类型，目录的 type 总是 0
    ctime INTEGER NOT NULL DEFAULT 0,  -- 创建时间戳，一旦设置就不会更新
    mtime INTEGER NOT NULL DEFAULT 0,  -- 更新时间戳，如果名字、备注被设置（即使值没变），或者（如果自己是目录）进出回收站或增删直接子节点或设置封面，会更新此值，但移动并不更新
    is_collect INTEGER NOT NULL DEFAULT 0 CHECK(is_collect IN (0, 1)), -- 是否已被标记为违规
    is_alive INTEGER NOT NULL DEFAULT 1 CHECK(is_alive IN (0, 1)),   -- 是否存在中（未被删除）
    updated_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+08:00', 'now', '+8 hours')) -- 最近一次更新时间
);

-- dir 表，用来存储所有看到的目录数据
CREATE TABLE IF NOT EXISTS dir (
    id INTEGER NOT NULL PRIMARY KEY,   -- 目录的 id
    parent_id INTEGER NOT NULL,        -- 上级目录的 id
    name TEXT NOT NULL,                -- 名字
    mtime INTEGER NOT NULL DEFAULT 0   -- 更新时间戳，如果名字、备注被设置（即使值没变），或者进出回收站，或者增删直接子节点，或者设置封面，会更新此值，但移动并不更新
);

-- 触发器，记录 data 表数据的更新时间
CREATE TRIGGER IF NOT EXISTS trg_data_update
AFTER UPDATE ON data 
FOR EACH ROW
BEGIN
    UPDATE data SET updated_at = strftime('%Y-%m-%dT%H:%M:%f+08:00', 'now', '+8 hours') WHERE id = NEW.id;
END;

-- 索引
CREATE INDEX IF NOT EXISTS idx_data_pid ON data(parent_id);
CREATE INDEX IF NOT EXISTS idx_data_pc ON data(pickcode);
CREATE INDEX IF NOT EXISTS idx_data_sha1 ON data(sha1);
CREATE INDEX IF NOT EXISTS idx_data_name ON data(name);
CREATE INDEX IF NOT EXISTS idx_data_utime ON data(updated_at);
CREATE INDEX IF NOT EXISTS idx_dir_mtime ON dir(mtime);
""")


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


def iter_files_with_id_mtime(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    max_depth: int = 0, 
) -> Iterator[tuple[int, int]]:
    """获取某个目录之下的所有文件节点的 id 和 mtime 数据的元组

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id
    :param max_depth: 最大递归深度，如果小于 0，则无限

    :return: 迭代器，产生 id 和 mtime 的元组
    """
    sql = "SELECT id, mtime, is_dir FROM data WHERE parent_id=? AND is_alive"
    gen = bfs_gen((parent_id, max_depth))
    send = gen.send
    for parent_id, depth in gen:
        if depth > 0:
            depth -= 1
        for id, mtime, is_dir in query(con, sql, parent_id):
            if is_dir:
                if depth:
                    send((id, depth))
            else:
                yield id, mtime


def select_mtime_groups(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    tree: bool = False, 
) -> dict[int, set[int]]:
    """获取某个目录之下的节点（不含此节点本身），按 mtime 进行分组，相同 mtime 的 id 归入同一组

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id
    :param tree: 是否拉取目录树，如果为 True，则拉取全部后代的文件节点（不含目录节点），如果为 False，则只拉取子节点（含目录节点）

    :return: 字典，表示相同 mtime 的 id 的集合，所以 key 是 mtime，value 是一组 id 的集合
    """
    if tree:
        it = iter_files_with_id_mtime(con, parent_id, max_depth=-1)
    else:
        it = query(con, "SELECT id, mtime FROM data WHERE parent_id=? AND is_alive", parent_id)
    d: dict[int, set[int]] = defaultdict(set)
    for id, mtime in it:
        d[mtime].add(id)
    return d


def select_subdir_ids(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
) -> list[int]:
    """获取某个目录之下的所有子目录的 id

    :param con: 数据库连接或游标
    :param parent_id: 父目录的 id

    :return: 一组 id
    """
    sql = "SELECT id FROM data WHERE parent_id=? AND is_dir AND is_alive"
    return [row[0] for row in query(con, sql, parent_id)]


def load_dir_ids(
    con: Connection | Cursor, 
    /, 
    min_mtime: int = 0, 
):
    """从 dir 表加载 id 数据到全局变量 `CID_TO_PID` 中

    :param con: 数据库连接或游标
    :param min_mtime: 忽略 mtime 小于这个值的数据
    """
    sql = "SELECT id, parent_id FROM dir WHERE mtime >= ?"
    CID_TO_PID.update(query(con, sql, min_mtime))


def insert_dir_items(con, items, commit: bool = False):
    upsert_items(
        con, 
        items, 
        table="dir", 
        fields=("id", "parent_id", "name", "mtime"), 
        commit=commit, 
    )


def kill_items(
    con: Connection | Cursor, 
    ids: int | Iterable[int], 
    /, 
    commit: bool = False, 
) -> Cursor:
    """使用 id 去筛选和删除一组数据

    :param con: 数据库连接或游标
    :param ids: 一组 id，会被删除
    :param commit: 是否提交

    :return: 游标
    """
    if isinstance(ids, int):
        cond = f"id = {ids:d}"
    else:
        cond = "id IN (%s)" % (",".join(map(str, ids)) or "NULL")
    sql = "UPDATE data SET is_alive=0 WHERE " + cond
    return execute(con, sql, commit=commit)


def update_stared_dirs(
    con: Connection | Cursor, 
    /, 
    client: P115Client, 
) -> list[dict]:
    """从网上增量拉取目录数据，并更新到 `dir` 表和全局变量 `CID_TO_PID` 中

    :param con: 数据库连接或游标
    :param client: 115 网盘客户端对象
    """
    mtime = find(con, "SELECT COALESCE(MAX(mtime), 0) FROM dir")
    data: list[dict] = list(takewhile(
        lambda attr: attr["mtime"] > mtime or attr["id"] not in CID_TO_PID, 
        iter_stared_dirs(
            client, 
            order="user_utime", 
            asc=0, 
            first_page_size=64, 
            id_to_dirnode=ZERO_DICT, 
            normalize_attr=normalize_attr, 
            app="android", 
        ), 
    ))
    if data:
        with transact(con):
            insert_dir_items(con, data)
            upsert_items(con, data)
        CID_TO_PID.update((a["id"], a["parent_id"]) for a in data)
    return data


def iterdir(
    client: P115Client, 
    cid: int = 0, 
    /, 
    first_page_size: int = 0, 
    page_size: int = 10_000, 
    payload: dict = {}, 
) -> tuple[int, list[dict], set[int], Iterator[dict]]:
    """拉取一个目录中的文件或目录的数据

    :param client: 115 网盘客户端对象
    :param cid: 目录的 id
    :param first_page_size: 首次拉取的分页大小，如果为 None 或者 <= 0，自动确定
    :param page_size: 分页大小
    :param payload: 其它查询参数

    :return: 4 元组，分别是

        1. 总数
        2. 祖先节点的简略信息（不含根目录）
        3. 已经拉取的文件或目录的 id 的集合
        4. 迭代器，用来获取数据
    """
    if page_size <= 0:
        page_size = 10_000
    if first_page_size <= 0:
        first_page_size = page_size
    payload = {
        "asc": 0, "cid": cid, "custom_order": 1, "fc_mix": 1, "o": "user_utime", "offset": 0, 
        "limit": first_page_size, "show_dir": 1, **payload, 
    }
    fs_files = client.fs_files_app
    def get_files(*a, **k):
        while True:
            try:
                return check_response(fs_files(*a, **k))
            except DataError:
                if payload["limit"] <= 1150:
                    raise
                payload["limit"] -= 1_000
                if payload["limit"] < 1150:
                    payload["limit"] = 1150
    resp = get_files(payload)
    if cid and int(resp["path"][-1]["cid"]) != cid:
        raise NotADirectoryError(cid)
    count = resp["count"]
    ancestors = [
        {"id": a["cid"], "parent_id": a["pid"], "name": a["name"]} 
        for a in resp["path"][1:]
    ]
    seen: set[int] = set()
    seen_add = seen.add
    payload["limit"] = page_size
    def iterate():
        nonlocal resp
        offset = int(payload["offset"])
        payload["limit"] = page_size
        while True:
            for attr in map(normalize_attr, resp["data"]):
                fid = cast(int, attr["id"])
                if fid in seen:
                    raise BusyOSError(
                        EBUSY, 
                        f"duplicate id found, means that some unpulled items have been updated: cid={cid}", 
                    )
                seen_add(fid)
                yield attr
            offset += len(resp["data"])
            if offset >= count:
                break
            payload["offset"] = offset
            resp = get_files(payload)
            if cid and int(resp["path"][-1]["cid"]) != cid:
                raise FileNotFoundError(cid)
            ancestors[:] = (
                {"id": a["cid"], "parent_id": a["pid"], "name": a["name"]} 
                for a in resp["path"][1:]
            )
            if count != resp["count"]:
                raise BusyOSError(f"count changes during iteration: {cid}")
    return count, ancestors, seen, iterate()


def diff_dir(
    con: Connection | Cursor, 
    client: P115Client, 
    id: int = 0, 
    /, 
    tree: bool = False, 
) -> tuple[list[dict], list[int]]:
    """拉取数据，确定哪些记录需要删除或更替

    :param con: 数据库连接或游标
    :param client: 115 网盘客户端对象
    :param id: 目录的 id
    :param tree: 如果为 True，则比对目录树，但仅对文件，即叶子节点，如果为 False，则比对所有直接（1 级）子节点，包括文件和目录

    :return: 2 元组，1) 待更替的数据列表，2) 待删除的 id 列表
    """
    groups = select_mtime_groups(con, id, tree=tree)
    remains = sum(map(len, groups.values()))
    if tree:
        count, ancestors, seen, data_it = iterdir(client, id, first_page_size=64 if remains else 0, payload={"show_dir": 0})
    else:
        count, ancestors, seen, data_it = iterdir(client, id, first_page_size=16 if remains else 0)
    dirs: list[dict] = []
    upsert_list: list[dict] = []
    delete_list: list[int] = []
    dirs_add = dirs.append
    upsert_add = upsert_list.append
    delete_extend = delete_list.extend
    result = upsert_list, delete_list
    try:
        if remains:
            his_it = iter(sorted(groups.items(), reverse=True))
            his_mtime, his_ids = next(his_it)
        for n, attr in enumerate(data_it, 1):
            if attr["is_dir"]:
                dirs_add(attr)
            if remains:
                cur_id = attr["id"]
                cur_mtime = attr["mtime"]
                try:
                    while his_mtime > cur_mtime:
                        delete_extend(his_ids - seen)
                        remains -= len(his_ids)
                        his_mtime, his_ids = next(his_it)
                except StopIteration:
                    continue
                if his_mtime == cur_mtime and cur_id in his_ids:
                    remains -= 1
                    if n + remains == count:
                        return result
                    his_ids.remove(cur_id)
                    continue
            upsert_add(attr)
        if remains:
            delete_extend(his_ids - seen)
            for _, his_ids in his_it:
                delete_extend(his_ids - seen)
        return result
    finally:
        with transact(con):
            if ancestors:
                upsert_items(con, ancestors, extras={"is_alive": 1, "is_dir": 1})
                upsert_items(con, ancestors, table="dir")
                CID_TO_PID.update((a["id"], a["parent_id"]) for a in ancestors)
            if dirs:
                upsert_items(con, dirs, extras={"is_alive": 1})
                insert_dir_items(con, dirs)
                CID_TO_PID.update((a["id"], a["parent_id"]) for a in dirs)


def normalize_attr(info: Mapping, /) -> dict:
    """筛选和规范化数据的名字，以便插入 `data` 表

    :param info: 原始数据

    :return: 经过规范化后的数据
    """
    def typeof(attr):
        if attr["is_dir"]:
            return 0
        if int(info.get("iv", info.get("isv", 0))):
            return 4
        if "muc" in info:
            return 3
        if fclass := info.get("class", ""):
            if type := CLASS_TO_TYPE.get(fclass):
                return type
            else:
                return 99
        if type := SUFFIX_TO_TYPE.get(splitext(attr["name"])[1].lower()):
            return type
        elif "play_long" in info:
            return 4
        return 99
    if "fn" in info:
        is_dir = info["fc"] == "0"
        attr = {
            "id": int(info["fid"]), 
            "parent_id": int(info["pid"]), 
            "pickcode": info["pc"], 
            "sha1": info.get("sha1") or "", 
            "name": info["fn"], 
            "size": int(info.get("fs") or 0), 
            "is_dir": is_dir, 
            "ctime": int(info["uppt"]), 
            "mtime": int(info["upt"]), 
            "is_collect": int(info.get("ic") or 0), 
            "is_alive": 1, 
        }
    else:
        is_dir = "fid" not in info
        attr = {
            "id": int(info["cid" if is_dir else "fid"]), 
            "parent_id": int(info["pid" if is_dir else "cid"]), 
            "pickcode": info["pc"], 
            "sha1": info.get("sha") or "", 
            "name": info["n"], 
            "size": int(info.get("s") or 0), 
            "is_dir": is_dir, 
            "ctime": int(info.get("tp") or 0), 
            "mtime": int(info.get("te") or 0), 
            "is_collect": int(info.get("c") or 0), 
            "is_alive": 1, 
        }
    attr["type"] = typeof(attr)
    return attr


def _init_client(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
) -> tuple[P115Client, Connection | Cursor]:
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if not dbfile:
        dbfile = f"115-{client.user_id}.db"
    if isinstance(dbfile, (Connection, Cursor)):
        con = dbfile
    else:
        con = connect(dbfile, uri=dbfile.startswith("file:"), factory=AutoCloseConnection)
        initdb(con)
        load_dir_ids(con)
    return client, con


def updatedb_one(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    id: int = 0, 
    /, 
):
    """更新一个目录
    """
    client, con = _init_client(client, dbfile)
    to_upsert, to_delete = diff_dir(con, client, id)
    with transact(con):
        if to_upsert:
            upsert_items(con, to_upsert)
        if to_delete:
            kill_items(con, to_delete)
    return to_upsert, to_delete


def updatedb_tree(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    id: int = 0, 
    /, 
    no_dir_moved: bool = True, 
):
    """更新一个目录树
    """
    client, con = _init_client(client, dbfile)
    to_upsert, to_delete = diff_dir(con, client, id, tree=True)
    custom_no_dir_moved = no_dir_moved
    if to_delete:
        all_pids: set[int] = set()
        pids: Collection[int] = to_delete
        while pids := {pid for pid in (CID_TO_PID.get(pid, 0) for pid in pids) if pid and pid not in all_pids}:
            all_pids.update(pids)
        if all_pids:
            if not custom_no_dir_moved:
                update_desc(client, all_pids)
                no_dir_moved = False
            to_delete.extend(filter_na_ids(client, all_pids))
    if to_upsert:
        all_pids = set()
        pids = {ppid for attr in to_upsert if (ppid := attr["parent_id"])}
        while pids:
            all_pids.update(pids)
            if find_ids := pids - CID_TO_PID.keys():
                update_star(client, find_ids)
                if custom_no_dir_moved:
                    update_desc(client, find_ids)
                else:
                    update_desc(client, pids)
                update_stared_dirs(con, client)
                no_dir_moved = True
            elif not custom_no_dir_moved:
                update_desc(client, pids)
                no_dir_moved = False
            pids = {pid for pid in (CID_TO_PID.get(pid, 0) for pid in pids) if pid and pid not in all_pids}
    if not no_dir_moved:
        update_stared_dirs(con, client)
    with transact(con):
        if to_delete:
            kill_items(con, to_delete)
        if to_upsert:
            upsert_items(con, to_upsert)
    return to_upsert, to_delete


def updatedb(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    top_dirs: int | str | Iterable[int | str] = 0, 
    auto_splitting_threshold: int = 100_000, 
    auto_splitting_statistics_timeout: None | float = 3, 
    no_dir_moved: bool = True, 
    recursive: bool = True, 
):
    """批量执行一组任务，任务为更新单个目录或者目录树的文件信息
    """
    from httpx import ReadTimeout

    client, con = _init_client(client, dbfile)
    id_to_dirnode: dict = {}
    def parse_top_iter(top: int | str | Iterable[int | str], /) -> Iterator[int]:
        if isinstance(top, int):
            yield top
        elif isinstance(top, str):
            if top in ("", "0", ".", "..", "/"):
                yield 0
            elif not (top.startswith("0") or top.strip(digits)):
                yield int(top)
            else:
                try:
                    yield get_id_to_path(
                        client, 
                        top, 
                        ensure_file=False, 
                        app="android", 
                        id_to_dirnode=id_to_dirnode, 
                    )
                except FileNotFoundError:
                    logger.exception("[\x1b[1;31mFAIL\x1b[0m] directory not found: %r", top)
        else:
            for top_ in top:
                yield from parse_top_iter(top_)
    if not (top_ids := set(parse_top_iter(top_dirs))):
        return
    if (auto_splitting_statistics_timeout is None or 
        isnan(auto_splitting_statistics_timeout) or 
        isinf(auto_splitting_statistics_timeout) or 
        auto_splitting_statistics_timeout <= 0
    ):
        auto_splitting_statistics_timeout = None
    seen: set[int] = set()
    seen_add = seen.add
    dq: deque[int] = deque()
    push, pushmany, pop = dq.append, dq.extend, dq.popleft
    need_calc_size = recursive and auto_splitting_threshold > 0
    if need_calc_size:
        executor = ThreadPoolExecutor(max_workers=1)
        submit = executor.submit
        cache_futures: dict[int, Future] = {}
        def get_dir_size(cid: int = 0, /) -> int | float:
            if cid == 0:
                resp = check_response(client.fs_space_summury())
                if not resp["type_summury"]:
                    return float("inf")
                return sum(v["count"] for k, v in resp["type_summury"].items() if k.isupper())
            else:
                try:
                    resp = client.fs_category_get_app(cid, timeout=auto_splitting_statistics_timeout)
                    if not resp:
                        return 0
                    check_response(resp)
                    return int(resp["count"])
                except ReadTimeout:
                    logger.info("[\x1b[1;37;43mSTAT\x1b[0m] \x1b[1m%d\x1b[0m, too big, since statistics timeout, consider the size as \x1b[1;3minf\x1b[0m", id)
                    return float("inf")
    try:
        pushmany(top_ids)
        if need_calc_size:
            for cid in top_ids:
                if cid not in cache_futures:
                    cache_futures[cid] = submit(get_dir_size, cid)
        while dq:
            id = pop()
            if id in seen:
                logger.warning("[\x1b[1;33mSKIP\x1b[0m] already processed: %s", id)
                continue
            if auto_splitting_threshold == 0:
                need_to_split_tasks = True
            elif auto_splitting_threshold < 0:
                need_to_split_tasks = False
            elif recursive:
                count = cache_futures[id].result()
                if count <= 0:
                    seen_add(id)
                    continue
                need_to_split_tasks = count > auto_splitting_threshold
                if need_to_split_tasks:
                    logger.info(f"[\x1b[1;37;41mTELL\x1b[0m] \x1b[1m{id}\x1b[0m, \x1b[1;31mbig\x1b[0m ({count:,.0f} > {auto_splitting_threshold:,d}), will be pulled in \x1b[1;4;5;31mmulti batches\x1b[0m")
                else:
                    logger.info(f"[\x1b[1;37;42mTELL\x1b[0m] \x1b[1m{id}\x1b[0m, \x1b[1;32mfit\x1b[0m ({count:,.0f} <= {auto_splitting_threshold:,d}), will be pulled in \x1b[1;4;5;32mone batch\x1b[0m")
            else:
                need_to_split_tasks = True
            try:
                start = perf_counter()
                if need_to_split_tasks or not recursive:
                    to_upsert, to_delete = updatedb_one(client, con, id)
                else:
                    if not no_dir_moved:
                        update_stared_dirs(con, client)
                        no_dir_moved = True
                    to_upsert, to_delete = updatedb_tree(client, con, id)
            except FileNotFoundError:
                kill_items(con, id, commit=True)
                logger.warning("[\x1b[1;33mSKIP\x1b[0m] not found: %s", id)
            except NotADirectoryError:
                logger.warning("[\x1b[1;33mSKIP\x1b[0m] not a directory: %s", id)
            except BusyOSError:
                logger.warning("[\x1b[1;35mREDO\x1b[0m] directory is busy updating: %s", id)
                push(id)
            except:
                logger.exception("[\x1b[1;31mFAIL\x1b[0m] %s", id)
                raise
            else:
                logger.info(
                    "[\x1b[1;32mGOOD\x1b[0m] \x1b[1m%s\x1b[0m, upsert: %d, delete: %d, cost: %.6f s", 
                    id, 
                    len(to_upsert), 
                    len(to_delete), 
                    perf_counter() - start, 
                )
                seen_add(id)
                if recursive and need_to_split_tasks and (ids := select_subdir_ids(con, id)):
                    pushmany(ids)
                    if need_calc_size:
                        for cid in ids:
                            if cid not in cache_futures:
                                cache_futures[cid] = submit(get_dir_size, cid)
    finally:
        if need_calc_size:
            executor.shutdown(wait=False, cancel_futures=True)

# TODO: 如果 http 请求超时，则需要进行重试
# TODO: 支持从 115 事件中获取数据
# TODO: 如果一个文件夹被移动，那么它的更新时间不会变，只是它的上级 id 的更新时间会变，因此必要时，还是需要结合 115 更新事件
# TODO: 增加一个选项，允许对数据进行全量而不是增量更新，这样可以避免一些问题
# TODO: 为数据库插入弄单独一个线程，就不需要等待数据库插入完成，就可以开始下一批数据拉取
# TODO: 先拉取一次 115 的更新事件，这个事件从数据库中最新一条数据的更新事件开始，如果没有数据，则为当前（不需要立即拉一次），以后轮到下一个任务时，只需要在最近一次拉取时间之后进行拉取，如果事件发生时间在当前记录的更新时间之前，则忽略此事件
