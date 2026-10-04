# tools/zzz/

zzz 的维护用脚本，不进流水线。在仓库根用 `uv run python tools/zzz/<脚本>` 运行。

| 脚本 | 状态 | 用途 | 谁在引用 |
| --- | --- | --- | --- |
| `crosscheck.py` | 可用（未在本次重跑），要联网读玩家维基（`zenless-zone-zero.fandom.com`），维基改版式就可能失效 | 委托名、角色名与维基比对，场景类别与 FileCfg 资源路径比对；回答不了"有没有漏" | [docs/zzz/architecture.md](../../docs/zzz/architecture.md#交叉校验) |

```bash
uv run python tools/zzz/crosscheck.py
```
