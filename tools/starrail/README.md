# tools/starrail/

starrail 的维护用脚本，不进流水线。在仓库根用 `uv run python tools/starrail/<脚本>` 运行。

| 脚本 | 状态 | 用途 | 谁在引用 |
| --- | --- | --- | --- |
| `p0_probe.py` | 可用（4.6.0 上实跑过） | 上游结构诊断：TextMap 分片与 `TextMapMain` 的关系、`Story/` 子目录、对话链路命中率、任务表规模、短信规模。换了上游快照、要核对文档里的实测数字时跑 | [docs/starrail/dev-guide.md](../../docs/starrail/dev-guide.md#改代码之后) |
| `crosscheck.py` | 可用（未在本次重跑），要联网：按需从 HuggingFace datasets-server 拉 `simon3000/starrail-voice` 的行 | 按文本内容与语音数据集比对，验 TextMap 解引用与说话人；验不了四语种对齐与"有没有漏" | [docs/starrail/architecture.md](../../docs/starrail/architecture.md#交叉校验) |

```bash
uv run python tools/starrail/p0_probe.py
uv run python tools/starrail/crosscheck.py --samples 3000
```
