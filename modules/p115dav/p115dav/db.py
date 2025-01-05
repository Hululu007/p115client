#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["get_id"]

from sqlite3 import Connection, Cursor

from sqlitetools import find


def get_id(
    con: Connection | Cursor, 
    /, 
    pickcode: str = "", 
    sha1: str = "", 
) -> None | int:
    if pickcode:
        return find(
            con, 
            "SELECT id FROM data WHERE pickcode=? LIMIT 1", 
            pickcode, 
        )
    elif sha1:
        return find(
            con, 
            "SELECT id FROM data WHERE sha1=? LIMIT 1", 
            sha1, 
        )
    return None


async def get_pickcode(
    con: Connection | Cursor, 
    /, 
    id: int = 0, 
    sha1: str = "", 
) -> str:
    if id:
        return find(
            con, 
            "SELECT pickcode FROM data WHERE id=? LIMIT 1", 
            id, 
            default="", 
        )
    elif sha1:
        return find(
            con, 
            "SELECT pickcode FROM data WHERE sha1=? LIMIT 1", 
            sha1, 
            default="", 
        )
    return ""


def get_sha1_from_db(id: int = 0, pickcode: str = "") -> str:
    if id:
        return await to_thread(query, "SELECT sha1 FROM data WHERE id=? LIMIT 1;", id, default="")
    elif pickcode:
        return await to_thread(query, "SELECT sha1 FROM data WHERE pickcode=? LIMIT 1;", pickcode, default="")
    return ""

async def get_share_parent_id_from_db(share_code, id: int = -1, sha1: str = "", path: str = ""):
    if id == 0:
        return 0
    pid: None | int = None
    if id > 0:
        pid = await to_thread(query, "SELECT parent_id FROM share_data WHERE share_code=? AND id=? LIMIT 1;", (share_code, id))
    if sha1:
        pid = await to_thread(query, "SELECT parent_id FROM share_data WHERE share_code=? AND sha1=? LIMIT 1;", (share_code, sha1))
    elif path:
        pid = await to_thread(query, "SELECT parent_id FROM share_data WHERE share_code=? AND path=? LIMIT 1;", (share_code, path))
    if pid is None:
        if await to_thread(query, "SELECT loaded FROM share_list_loaded WHERE share_code=?", share_code, default=False):
            raise FileNotFoundError({"share_code": share_code, "id": id, "sha1": sha1, "path": path})
    return pid

async def get_share_id_from_db(share_code: str, sha1: str = "", path: str = "") -> None | int:
    fid: None | int = None
    if sha1:
        fid = await to_thread(query, "SELECT id FROM share_data WHERE share_code=? AND sha1=? LIMIT 1;", (share_code, sha1))
    elif path:
        fid = await to_thread(query, "SELECT id FROM share_data WHERE share_code=? AND path=? LIMIT 1;", (share_code, path))
    if fid is None:
        if await to_thread(query, "SELECT loaded FROM share_list_loaded WHERE share_code=?", share_code, default=False):
            raise FileNotFoundError({"share_code": share_code, "sha1": sha1, "path": path})
    return fid

async def get_share_sha1_from_db(share_code: str, id: int = 0, path: str = "") -> str:
    sha1: None | str
    if id:
        sha1 = await to_thread(query, "SELECT sha1 FROM share_data WHERE share_code=? AND id=? LIMIT 1;", (share_code, id))
    elif sha1:
        sha1 = await to_thread(query, "SELECT sha1 FROM share_data WHERE share_code=? AND path=? LIMIT 1;", (share_code, path))
    else:
        sha1 = ""
    if sha1 is None:
        if await to_thread(query, "SELECT loaded FROM share_list_loaded WHERE share_code=?", share_code, default=False):
            raise FileNotFoundError({"share_code": share_code, "id": id, "path": path})
    return sha1 or ""

async def get_share_path_from_db(share_code: str, id: int = -1, sha1: str = "") -> str:
    if id == 0:
        return "/"
    path: None | str
    if id > 0:
        path = await to_thread(query, "SELECT path FROM share_data WHERE share_code=? AND id=? LIMIT 1;", (share_code, id))
    elif sha1:
        path = await to_thread(query, "SELECT path FROM share_data WHERE share_code=? AND sha1=? LIMIT 1;", (share_code, sha1))
    else:
        path = ""
    if path is None:
        if await to_thread(query, "SELECT loaded FROM share_list_loaded WHERE share_code=?", share_code, default=False):
            raise FileNotFoundError({"share_code": share_code, "id": id, "sha1": sha1})
    return path or ""

async def get_ancestors_from_db(id: int = 0) -> list[dict]:
    ancestors = [{"id": "0", "parent_id": "0", "name": ""}]
    ls = await to_thread(query_all, """\
WITH RECURSIVE t AS (
SELECT id, parent_id, name FROM data WHERE id = ?
UNION ALL
SELECT data.id, data.parent_id, data.name FROM t JOIN data ON (t.parent_id = data.id)
)
SELECT * FROM t;""", id)
    if ls:
        ancestors.extend(dict(zip(("id", "parent_id", "name"), map(str, record))) for record in reversed(ls))
    return ancestors

async def get_children_from_db(id: int = 0) -> None | list[AttrDict]:
    children = await to_thread(query, "SELECT data FROM list WHERE id=? LIMIT 1", id)
    if children:
        for i, attr in enumerate(children):
            children[i] = AttrDict(attr)
    return children

async def get_share_list_from_db(share_code: str, id: int = 0):
    share_list = await to_thread(query, "SELECT data FROM share_list WHERE share_code=? AND id=? LIMIT 1", (share_code, id))
    if share_list is None:
        if await to_thread(query, "SELECT loaded FROM share_list_loaded WHERE share_code=?", share_code, default=False):
            raise FileNotFoundError({"share_code": share_code, "id": id})
    else:
        children = share_list["children"]
        if children:
            for i, attr in enumerate(children):
                children[i] = AttrDict(attr)
    return share_list
