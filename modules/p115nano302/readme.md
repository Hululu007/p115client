# 极小型 115 302 后端

## 安装

你可以通过 [pypi](https://pypi.org/project/p115nano302/) 安装

```console
pip install -U p115nano302
```

## 用法

### 命令行使用

```console
$ p115nano302 -h
usage: p115nano302 [-h] [-c COOKIES] [-cp COOKIES_PATH] [-H HOST] [-P PORT] [-d] [-uc UVICORN_RUN_CONFIG_PATH] [-v] [-l]

            🚄 115 302 极小版 🚇

    ╭───────────────────────── Welcome to 115 nano 302 ────────────────────────────╮
    │                                                                              │
    │  maintained by ❤     ChenyangGao https://chenyanggao.github.io               │
    │                                                                              │
    │                      Github      https://github.com/ChenyangGao/p115client/  │
    │                                                                              │
    │                      licence     https://www.gnu.org/licenses/gpl-3.0.txt    │
    │                                                                              │
    │                      version     0.0.1                                       │
    │                                                                              │
    ╰──────────────────────────────────────────────────────────────────────────────╯

⏰ 仅支持用 pickcode 查询

🌰 查询示例：

    0. 查询 pickcode
        http://localhost:8000?ecjq9ichcb40lzlvx
        http://localhost:8000/ecjq9ichcb40lzlvx
        http://localhost:8000?pickcode=ecjq9ichcb40lzlvx
    1. 带（任意）名字查询 pickcode
        http://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?ecjq9ichcb40lzlvx
        http://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?pickcode=ecjq9ichcb40lzlvx

options:
  -h, --help            show this help message and exit
  -c COOKIES, --cookies COOKIES
                        cookies 字符串，优先级高于 -cp/--cookies-path
  -cp COOKIES_PATH, --cookies-path COOKIES_PATH
                        cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt
  -H HOST, --host HOST  ip 或 hostname，默认值：'0.0.0.0'
  -P PORT, --port PORT  端口号，默认值：8000，如果为 0 则自动确定
  -d, --debug           启用调试，会输出更详细信息
  -uc UVICORN_RUN_CONFIG_PATH, --uvicorn-run-config-path UVICORN_RUN_CONFIG_PATH
                        uvicorn 启动时的配置文件路径，会作为关键字参数传给 `uvicorn.run`，支持 JSON、YAML 或 TOML 格式，会根据扩展名确定，不能确定时视为 JSON
  -v, --version         输出版本号
  -l, --license         输出授权信息
```
