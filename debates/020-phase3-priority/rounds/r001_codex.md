1. 顺序：A→B→C→D，但 A 先做“契约校对版”，不是大而全。

2. ROI：A 最高，Phase 5 adapter 立刻受益；但它不是纯文档活，现有 drift 已有：`create_server()` 还写 origin=`compiled`，schema/model 却是 `compost`。写 A 很可能顺手要修文案/测试。B 次高，能补运行时审计，但主防线其实已在 schema CHECK；它更像防 SQLite 直写和遗留脏数据。

3. 隐藏坑 / 第 5 选项：B 里“`compost_insight_sources` 孤儿”不能天真查；obsolete memory 的映射当前被 `invalidate_compost_fact` 用来保幂等，误报风险高。另若把“insight 必须是 compost”写进 lint，会改变当前语义。更好的第 5 选项是 A-lite + drift fix：先统一契约/命名/CLI 文案，并补 1-2 个 invariant tests。

4. 估时：A 半天偏乐观，像 0.5-1 天；B 若只做审计型 lint 可 1 天，若要先澄清规则和输出语义，更像 1.5 天。C/D 现在都没真实触发数据，ROI 最低。
