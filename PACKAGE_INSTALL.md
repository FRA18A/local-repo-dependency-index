# Local Repo Dependency Index

本包提供一个纯本地、非 LLM 的仓库依赖索引与影响分析引擎。

## 安装

### 方式 1：在当前目录直接安装

```powershell
python -m pip install -e .
```

### 方式 2：复制到其他仓库后安装

把以下内容复制到目标仓库：

- `repo_tools/`
- `repo_index.py`
- `pyproject.toml`
- `skills/local-dependency-index/`
- `scripts/install_local_dep_engine.ps1`

然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_local_dep_engine.ps1
```

## 初始化

```powershell
repo-index init
repo-index index
repo-index risk-report
repo-index validate
```

## 常用命令

```powershell
repo-index impact OBJECT_ID
repo-index impact-set path\to\a.py path\to\b.py
repo-index revert-impact CHG-017
repo-index commit-impact HEAD~1
repo-index risk-report
repo-index graph OBJECT_ID --reverse
repo-index run-script script.py
```

## 说明

- Python 依赖来自 AST 静态分析。
- 文本对象引用来自正则扫描。
- 运行记录来自本地 manifest。
- `commit-impact` 需要当前目录是 git 仓库。
- 建议在代码变更后、提交前、或距离上次索引超过一天时重新执行 `repo-index index`。
- 每次重建索引后执行 `repo-index risk-report`。
- `graph` 需要本机安装 Graphviz `dot` 才能输出 SVG；否则会保留 DOT 文件。
