# 河浦计量资料湖

站务员登记站日读数和勘误，供数值班员冻结交班件，异地实收员据来件结算。报表员断开供数仓后仍能从报表库核对日报、升数合计及逐行出处。

## 一天的交班

1. 打开供数库并初始化站日。再次开日复用原站日，保留用户已登记的勘误。
2. 按具名请求登记原读。原读追加一个带整数升数和出处的源修订。
3. 对已登记的键追加勘误或撤销。勘误也可以恢复已撤销的键。按旧截点仍能读回旧值。
4. 按既有源提交号冻结请求区间，或补发一笔确切的单键修订。发行登记绑定原请求和冻结件。
5. 传送中断时按原件号复发。发行登记可以在供数库离线时独立复发原内容。
6. 在异地报表库实收。实收登记、结算证据和可见账同次提交。
7. 按源提交号和覆盖范围裁决每个键，汇总可见读数。
8. 重开报表库，按区间领取日报和该次读视图下的逐行出处。

## 运行

需要 Python 3.11 标准库与其 SQLite 支持。报表库使用 WAL。以下命令在项目根目录运行。

```text
python3 -B check_project.py
python3 -B -m samples.demo
```

完整回归入口由控制台提供。五个测试模块也可以直接用 `python3 -B -m unittest discover -s tests -t .` 执行。演示读取 `samples/source-day.json` 和 `samples/dispatch.json`，在临时目录建立独立的源库、发行登记和报表库。演示先收到 9 号点件、8 号盘点，再重开并补收 7 号点件。区间 [10,20) 只计键 12 的 13 L，出处为 `orig12`、来件为 `P9`。继续实收空盘点、界外读数及恢复件后，区间 [10,21) 的明细为 13、17、5、19 L，总计 54 L。

日常 CLI 示例使用项目目录下的业务文件。

```sh
python3 -B -m source.ingest source.sqlite HP 2026-11-25 init
python3 -B -m source.ingest source.sqlite HP 2026-11-25 apply morning reading 12 orig12 7
python3 -B -m source.ingest source.sqlite HP 2026-11-25 apply corrected correction 12 verified12 11
python3 -B -m source.ingest source.sqlite HP 2026-11-25 at 1 10 20
python3 -B -m issue.requests issue.sqlite stocktake source.sqlite HP 2026-11-25 S1 1 10 20 > S1.json
python3 -B -m issue.requests issue.sqlite reissue S1 > S1-resend.json
python3 -B -m intake.accept report.sqlite S1-resend.json
python3 -B -m reports.reconcile report.sqlite HP 2026-11-25 10 20
```

点件子命令为 `point SOURCE STATION DAY ARTIFACT_ID CUT KEY`。源侧 `apply` 的 `withdrawal` 种类省略末尾的升数参数。业务拒绝由 CLI 返回非零状态。

## Python 接口

| 操作 | 入口和结果 |
| --- | --- |
| 开日和追加 | `source.day.StationDay(station, day)` 由两个非空标识组成。`initialize_day(store, day)` 返回是否首次建立。`source.ingest.apply(store, day, request_id, change)` 返回 `SourceRevision`，含 `cut`、`key`、`kind`、`litres` 和 `origin`。用 `PointChange('reading', key, litres, origin)`、`make_correction` 或 `make_withdrawal` 构造变动。 |
| 核对源历史 | `source.history.source_at(store, day, cut, lower, upper)` 返回排序后的原行。`source_change_at(store, day, cut, key)` 返回该截点的确切单键修订，含撤销。开日给出空的 0 号截点，之后每次新请求追加一个正整数提交号。 |
| 发行和复发 | `issue.requests.issue(store, registry, artifact_id, day, cut, bounds=(lower, upper))` 发行盘点。用 `key=key` 发行点件。`issue.reissue.reissue(registry, artifact_id)` 返回原字节串，未知件号返回 `None`。 |
| 异地实收 | `intake.accept.accept(connection, payload)` 返回 `Receipt(number, artifact_id, payload)`。调用使用 `balance.store.open_report_database(path)` 打开并初始化独立报表库，在连接没有活动事务时办理。`intake.receipts.lookup_receipt(connection, artifact_id)` 可按件号查实收。 |
| 日报与查源 | `reports.daybook.daybook(path, day, lower, upper)` 领取 `Daybook`。`reports.provenance.trace(path, day, key)` 领取当前在册键的 `Provenance`，缺席时返回 `None`。`reports.reconcile.reconcile_range(path, day, lower, upper)` 一次领取日报与全部逐行出处。 |

用 `source.store.open_source(path)` 打开源仓，`issue.registry.open_issue_registry(path)` 打开发行登记。源仓、登记和报表写连接由调用者关闭，可用 `contextlib.closing` 管理。日报与查源自行打开已有报表库的读视图。`reconcile_range` 可用 `after_daybook` 回调在日账选定后安排交班操作，逐行出处仍在原读视图内查询。

## 计量和交接约定

- 源请求身份在同站日内唯一，发行及实收件号在各自登记内唯一。标识和出处是非空 UTF-8 字符串。源请求同参复领原提交，同号异参触发 `ValueError`。已撤销键可勘误恢复，继续撤销或对从未登记的键发勘误与撤销会被拒绝。
- 键、提交号、区间端点和升数使用整数。浮点数、布尔值和数字字符串不能充当 Python API 或来件中的整数。区间包含左端、排除右端，反向区间拒绝，等端点查询为空。升数按 L 原值累计，0 L 可以在册。日报不含缺席行，空账为 0 L。
- 传送件使用 UTF-8 JSON。V1 外层字段是 `version`、`kind`、`artifact_id`、`station`、`day`、`cut`、`bounds`、`rows`。行字段为 `key`、`litres`、`origin`。`stocktake` 的 `bounds` 是完整的两端点，`rows` 按键递增且可以为空。`point` 的 `bounds` 是 `null`，仅有一个行项，其 `litres` 为 `null` 时表示撤销。空正文盘点仍证明请求范围内缺席。完整内容相同的来件可重投，JSON 空白和对象字段顺序不影响身份。
- 报表库只根据收到的材料解释日账。每个键以涵盖它的最高源提交号为准，整段盘点未列出的键和点撤销均给出缺席。在册盘点行的有效提交号是盘点截点，出处来自冻结行。等价的同截点实收证据按件号排序选取出处。件号对应原实收登记。分开调用的查询各自读取当时视图。
- 非法输入、未知源截点和身份冲突触发 `ValueError`。SQLite 写入或提交失败随数据库错误返回，原可见账和实收保持。撤去故障后可重投，成功后复领同一笔实收。报告仓的读取与供数库和发行登记相互独立。
