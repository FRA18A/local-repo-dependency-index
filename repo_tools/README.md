# Local Dependency Index

`repo_tools/repo_index.py` 提供一个完全本地、非 LLM 的仓库依赖索引与影响分析 CLI。

核心命令：

```bash
python -m repo_tools.repo_index init
python -m repo_tools.repo_index index
python -m repo_tools.repo_index impact DATA-EXAMPLE-v01
python -m repo_tools.repo_index impact-set proj6\20.预测未来.py proj6\21.帕累托前沿.py
python -m repo_tools.repo_index commit-impact HEAD~1
python -m repo_tools.repo_index revert-impact CHG-001
python -m repo_tools.repo_index validate
```

说明：

- 对 Python 使用 AST 静态分析 `import`、I/O、config 加载和输出。
- 对 `md/yaml/txt/json/log/out` 进行对象 ID 引用扫描。
- 运行 `run-script` 会生成 `repo_tools/manifests/RUN-*.yaml`。
- Graphviz 图输出会优先尝试本地 `dot`，缺失时保留 `.dot` 文件。
- `registry/object_registry.yaml` 与 `registry/change_registry.yaml` 默认留空，避免模板对象污染校验结果。

对象注册示例：

```yaml
objects:
  - object_id: DATA-RelGap-grid-v02
    type: dataset
    path: data/rel_gap_grid_v02.parquet
    status: active
    summary: Relative accessibility gap grid dataset.
    dependencies: []
  - object_id: RESULT-HLM-ICC-v04
    type: result
    path: reports/hlm_icc_v04.csv
    status: active
    summary: HLM ICC model output.
    dependencies:
      - DATA-RelGap-grid-v02
```
