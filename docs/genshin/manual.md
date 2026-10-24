# 使用说明：产出的语料

`uv run gametext genshin all` 产出的东西长什么样、各字段什么意思。怎么跑见 [README](README.md#快速开始)。

每个字段的类型、能否为 null、取值范围以内容契约 [`src/gametext/genshin/contract.py`](../../src/gametext/genshin/contract.py) 为准（规则见根架构说明的[内容契约](../architecture.md#内容契约)），本文讲各表的来历与取舍。

## 输出

```
corpus/genshin/
├── quests_chs.jsonl.zst    各语种行数相同、逐行 id 相同（--compress none 出 .jsonl）
├── quests_en.jsonl.zst
├── quests_jp.jsonl.zst
├── reminders_{chs,en,jp}.jsonl.zst   语音字幕链（见[语音字幕](#语音字幕-reminders_)）
├── terms_{chs,en,jp}.jsonl.zst       短名词对照表（见[短名词](#短名词-terms_)）
├── pronouns_{chs,en,jp}.jsonl.zst    称谓表（见[称谓](#称谓-pronouns_)）
├── readables_{chs,en,jp}.jsonl.zst   阅读面板长文本（见[阅读面板长文本](#阅读面板长文本-readables_)）
├── report.json         完整性报告
└── manifest.json       清单：文件、行数、哈希与指纹（产物包协议，见根[架构说明](../architecture.md#产物包协议gtd-bundle1)）
```

`uv run gametext genshin bundle` 把 `corpus/genshin/` 打成一个包放进仓库根的 `out/`（emit 结束时已写好清单，`manifest` 子命令只重算清单）；发布用 `release`，先把这份语料记进 `releases/genshin/fingerprints.tsv`（规则见根架构说明的[指纹表与 rev](../architecture.md#指纹表与-rev)）。

## 任务 `quests_*`

`$HIDDEN` / `(test)` / `$UNRELEASED` 这类废弃或内部任务**不删**，留不留交给下游：可按 `name` 里的这些标记、`tag`、`steps[].fail_cond`（`QUEST_HIDDEN`）过滤。

语言代码沿用上游命名（**JP / KR**，不是 ja / ko）。真实的一条（`q_2001`，steps 与 dialog 各截取一项）：

```json
{
  "id": 2001,
  "name": "南十字武斗会",
  "description": "在了解了参赛者的状况之后，你预计这是一次很轻松的比赛。但比赛结果事关前往稻妻的船票，所以万不可掉以轻心。",
  "chapter_id": 1201,
  "chapter_title": null,
  "chapter_num": null,
  "series": 1201,
  "tag": null,
  "steps": [
    {
      "sub_id": 200101,
      "order": 1,
      "desc": "与负责报名的珠函交谈",
      "fail_cond": null
    }
  ],
  "dialog": [
    {
      "talk_id": 200103,
      "attribution": "explicit",
      "dialog_id": 20010301,
      "role": {
        "type": "TALK_ROLE_NPC",
        "id": "1031"
      },
      "speaker": null,
      "text": "哈哈哈，不愧是我看好的种子选手！",
      "next": [
        20010302
      ],
      "source": "Quest/200103.json",
      "voice": "voiced"
    }
  ],
  "upstream": {
    "commit": "792978e5503ecfba73dcb3562ed44a0d35a2abe2",
    "version": "7.1.0"
  }
}
```

`speaker` 只在上游给了独立人名字段时才有值（覆盖约 4% 的节点），多数情况下说话人要靠 `role.id` 去 `NpcExcelConfigData` 反查 —— 不做，见[架构说明的「记录在案，不做」](architecture.md#记录在案不做)。

设计上的几点取舍：

- `dialog` 是**扁平节点 + `next` 边**，不预先拍平成线性剧本 —— 分支剧情不该在提取阶段被破坏。要线性视图另写下游脚本。
- 文本保留上游原样，含 `{NICKNAME}`、`{F#她}{M#他}`、`<color=...>` 等占位与富文本标记。是否清洗交给下游。
- 查不到文本写 `null` 而不是空字符串 —— 两者语义不同，且都计入报告。
- `attribution` 区分**显式归属**（任务文件明确引用了这个 talk）与**推测归属**（按编号前缀推出来的）。下游可自行过滤。

### 任务对话配音

`dialog[].voice` 从 `BinOutput/Voice/Items` 与 `Lut` 的 `Dialog` 触发映射按 `dialog_id` 补标：
命中为 `voiced`，未命中仍为 `unknown`。Items 必须有 `.wem` 资源路径；Lut 本身是事件映射。
缺映射不是没有配音的证据，不按说话人类型推测 `unvoiced`，也不推测 `generic`。
同一 id 的标记跨语种一致，表示映射存在，不表示已验证每种语言的音频文件。

## 语音字幕 `reminders_*`

边走边说的对白——派蒙在路上的吐槽、比赛里队友的喊话、战斗喊话——**不在任何 Talk 里**，
但就在屏幕下方的字幕带上（带名牌）。它们在 `ExcelBinOutput/ReminderExcelConfigData.json`，
每行一句，`nextReminderId` 串成一段。一条链一行：

```json
{"id": 1110274, "lines": [
  {"reminder_id": 1110274, "speaker": "パイモン", "text": "やっと出れた…あの洞窟と部屋、もう完全に浸水しちゃったみたいだな。",
   "style": "Normal", "show_time": 4, "delay": 0, "voice": "unvoiced"},
  {"reminder_id": 1110275, "speaker": "パイモン", "text": "どうして水の下にあんな場所があったんだろう…不思議だなぁ…", …}]}
```

- 说话人与正文是两个混淆的 hash 字段，照"标题 vs 描述"的办法**按文本长度中位数区分**
  （正文中位 20 字、说话人 2 字）；否决规则是正文中位数至少是说话人的 3 倍，否则整张表判失败。
  说话人字段的命中率只有 83%——系统提示（`容器がいっぱいだ…`）本来就没有说话人，`speaker` 为 `null`。
- `style` 原样给（`Normal` 13 802 行、`Banner` 1 681、`CombatChat` 802…），上屏位置不同，
  下游自己挑。
- **配音标记 `voice`**（四态，和 starrail 同名同值域：`voiced` / `generic` / `unvoiced` / `unknown`）：
  优先用 Voice 的 `DungeonReminder` 映射按 `reminder_id` 补 `voiced`；未命中再依 `hasAudio`：
  `true` → `voiced`、`false` → `unvoiced`、缺字段 → `unknown`
  （7.0.0 表里 4284 / 14 048 / 0）。7.1.0 起这张表省略默认值，`false` 一条都不写了：整张表找不到
  显式默认值时，缺字段按默认值补（`hasAudio` 补 `false`，`style` / `delay` / `show_time` 同理），
  7.1.0 单看 `hasAudio` 是 4461 / 14 080 / 0；映射另补 238 行为 `voiced`。`generic`（有语音但是泛用短语、对不上本句）**判不了**：
  带资源名 `soundEffect` 的只有 10 条且互不重复，看不出"一段语音被多句共用"。
- 链的三种上游毛病都计数上报、一条不丢：两条链汇进同一段尾巴（32 处，各自带上尾巴，
  所以行数 18 396 多于表的 18 332 行）、`next` 指向自己（4 条，当链尾）、两条互指成环
  没有链头（1 对，从小的 id 起走一圈，行上标 `cyclic: true`）。悬空 `next` 13 个。
- **`reminder_id` 在产物里不唯一**：汇合的几条链各带一份共用的尾巴，同一个 `reminder_id` 会出现在
  几条链里。要唯一标识一行用 `(链的 id, reminder_id)`；按 `reminder_id` 建表的下游要么去重、要么知道自己在去重。
- **不挂到任务上**：触发它的是任务 / 关卡脚本，没解析；id 空间很小（`1003` 这种），
  按数值去 Quest 里撞只会撞出假关联。

为什么补它：拿游戏直播录像（下游项目 flowocr 的原神素材）量过，任务对话之外的屏幕文字大半是 UI
（成就、材料、加载提示、教程…），**对白形态**的里面最大的一块在这张表里（3h20m 的一场里
约 83 条 OCR 文本落在它上面；不归属任务的那 1.67 万个 talk 只认出 2 条）。

## 短名词 `terms_*`

TextMap 里"像名词"的短串逐条照搬，一个 TextMapHash 一行：`{"id": 3396555736, "text": "シュラム"}`（中文那份是「施拉姆」）。
给下游按屏幕上的字查译名用——名牌上的人名、称号、任务目标这类短文本，常常不在任何对话节点的说话人字段里。

- **只按形状收**（`emit.is_term`，只看 CHS 那份，所以各语种的行集合天然相同）：CHS ≤ 16 字
  （依据：任务对话里去重后的说话人中文名 P99 = 15 字）、含汉字或假名、不带句读 / 换行 / 占位与富文本标记 / `test`。
  上游没有"这条是人名"的标记，而画面上的人名可以只被一张无关的表引用（7.0.0 的「施拉姆」只出现在
  `DreamBookPhotoAvatarExcelConfigData` 里，任务和对话数据都不引用它），所以不按"被哪张表引用"去筛。
- **出处**就是 `id`（TextMapHash），配上清单里的上游 commit 可以回查；行上不重复带 `upstream`。
- **不去重、不消歧**：同一个日文串常对应几个 hash，中文也不一定相同（`旅人` → 旅行者 7 条 / 旅人 6 条 / …）。
  日文键怎么归一、歧义取哪个是下游的事，这里原样给全。
- 本语种查不到写 `null`，计进报告的 `terms_missing`（7.0.0：EN 1097 / JP 1107，CHS 恒为 0）。
- 为什么补它：下游 flowocr 的名牌层按屏幕上的名字查剧本说话人，原神直播录像 gi-s2 里的「シュラム」
  （NPC 名字隐藏、对话节点只挂了头衔「傭兵」）在任务数据里查不到，只在 TextMap 里有。

## 称谓 `pronouns_*`

台词里有一类按性别取的称谓：`{PLAYERAVATAR#SEXPRO[INFO_MALE_PRONOUN_HE|INFO_FEMALE_PRONOUN_SHE]}`（旅行者）、
`{MATEAVATAR#SEXPRO[…]}`（另一位双子），游戏按那个角色的性别选方括号里的一个键，再按键查文本。这张表就是键 → 文本：
`{"id": "INFO_MALE_PRONOUN_HE", "text": "他"}`（日文那份是「彼」），按 id 排序。7.1.0 共 78 个键：称谓 `INFO_*_PRONOUN_*` 62 个，
外加日文台词里按性别变的句尾 `INFO_*_PLAYER_END01`–`08` 16 个（`…だめ{MATEAVATAR#SEXPRO[INFO_MALE_PLAYER_END02|INFO_FEMALE_PLAYER_END01]}`）。

- **方括号里第一个键是那个角色为男时用的，第二个为女时**，和键名里的 MALE / FEMALE 无关：
  `我的{PLAYERAVATAR#SEXPRO[INFO_MALE_PRONOUN_SISTER|INFO_FEMALE_PRONOUN_BROTHER]}` 是男主说「妹妹」。
  7.1.0 任务对话里中文 775 处、日文 982 处、英文 3 处，引用的键全在表里；中文按位置读全部说得通。台词原样保留占位，选哪个、填什么是下游的事。
- **出处**：`ExcelBinOutput/ManualTextMapConfigData.json`（键名 → TextMapHash 的对照，四万多条），只取键名以 `INFO_MALE_` / `INFO_FEMALE_` 开头的那些；文本在 TextMap 的 Medium 那张表里。两个字段都按结构认（键字段是取值匹配这个形状的字符串字段，
  文本字段是这些行上 TextMap 命中率最高的整数字段），认不出就整张表判失败、写空表，记进 `build/unparsed.jsonl`。
- 本语种查不到写 `null`，计进报告的 `pronoun_unresolved`（7.1.0：三语种都是 0）。
- 有几条是上游的开发占位文本，不是真句尾：中文的 16 个 `INFO_*_PLAYER_END0x` 是「女主角句尾1」这类，日文的 END06 / END08 是
  「女性主人公の句末6」这类。7.1.0 的台词没有引用它们（中文不用句尾键，日文只用 END01–05）；以后版本引用到时下游会把这串字原样填进去，照原样给、不在这里改。
- 为什么补它：下游 flowocr 按视频认出主角性别后把称谓换成文字；没有这张表时只能把占位删掉，「神秘的{…}也曾到过水下堡垒」成了「神秘的也曾到过」。

## 阅读面板长文本 `readables_*`

书籍、信件、说明这类阅读界面上的长文本，一行一篇全文：

```json
{"id": 200101, "source": "Readable/", "text": "在台阶之上，石铸的卫士守护着碎石下的宝藏。\n<image name=UI_Dailytask_1/>"}
{"id": 78, "source": "MailExcelConfigData", "text": "亲爱的旅行者：\n「追想练行」活动玩法即将结束，欢迎旅行者及时参与活动，获取活动奖励~"}
```

- **收什么**（7.1.0，共 6636 条）：上游 `Readable/` 目录（书籍、武器 / 圣遗物故事、衣装与风之翼的说明、角色写的信件和告示，1878 条），
  加阅读界面配置表引用的正文：邮箱信件 `MailExcelConfigData`（323）、教程说明页 `TutorialDetailExcelConfigData`（3456）、
  活动来信 `AlchemySimLetterExcelConfigData`（6）、角色资料里的角色故事 `FetterStoryExcelConfigData`（973）。不按长度收：最短的十几条不到 10 字（`测试`、`？？？` 这类上游占位也照原样在）。
- **出处**：`source` 是 `Readable/` 或配置表名；`id` 在 `Readable/` 时是 `LocalizationExcelConfigData` 的行 id（阅读界面
  `DocumentExcelConfigData` 引用的就是它，那一行给出各语种的文件名），否则是那张配置表的行 id（角色故事是 `fetterId`）。不同 `source` 的 id 会撞，
  **唯一标识一行用 `(source, id)`**。
- **全文、不切段**：段落之间是真换行（TextMap 里的字面量 `\n` 换成了换行，`Readable/` 文件的 `\r\n` 换成 `\n`），首尾空白去掉；
  占位、富文本与 `<image name=…/>` 这类插图标记原样保留。切段、清洗是下游的事。
- **已经在台词里的不收**：中文全文与任务对话或语音字幕里某一句整段相同的（7.1.0：19 条，多是 `？？？`、`test` 这类占位，
  也有书里那句话就是台词的），免得下游叠加时两张表抢同一段字。行集合只看中文，所以各语种逐行 id 相同。
- **同一段文本出现多次照收**（出处不同）：7.1.0 有 240 行与表内前面某行中文全文相同，多是教程里重复的怪物说明、同模板的邮件，以及两位旅行者共用的角色故事（含 `暂未开放` 占位）。
- 中文没有文本的不收（7.1.0：本地化记录指向的文件不存在 8、文件为空 17、TextMap 查不到 189）；其余语种缺文本写 `null`，
  计进报告的 `readables_missing`（7.1.0：EN、JP 各 67）。`Readable/` 里另有 6 篇没有本地化记录指向（5 把新武器的故事、1 本书），
  没有 id、对不齐别的语种，不收、只计数。角色故事的变体版本（7.1.0 有 8 篇，剧情推进后替换原文）没有自己的行 id，也不收。上游的这些缺口见 [data-source.md 的 Readable 一节](data-source.md#readable阅读面板的正文)。

## 语种与压缩

默认出**中英日三语**、产物 **zstd 压缩**：

```bash
uv run gametext genshin all --langs chs,en,jp --compress zstd   # 这就是默认
uv run gametext genshin all --langs chs                  # 只要中文
uv run gametext genshin all --compress none              # 出原始 .jsonl
```

- 语种同时决定 `snapshot` **下载什么**：TextMap 里装着全部语种，只取需要的
  从 1235 MB 降到 219 MB。**收窄只对下一次取数生效**，已有快照要重新克隆才变小。
- 产物是 JSONL（UTF-8，一行一个 JSON 对象）；压缩后 `*.jsonl.zst`，391 MB → **41 MB**。
  读端一律走 `jsonl.open_read`，先找 `.zst` 再找原始文件，对下游透明。
- 基准语种 CHS 永远在列 —— 少了它就分不开"上游缺译"和"上游根本没这条"。

依据与取舍（为什么是 zstd level 3、为什么 `corpus/genshin/` 里分文件压）见根架构说明的
[产物格式](../architecture.md#产物格式jsonl--zstd)。
