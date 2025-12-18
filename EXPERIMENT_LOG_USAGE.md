# 実験ログ機能の使用方法

## 概要

このプロジェクトには、AI実験のデータ収集用にログ機能が組み込まれています。ログ機能を有効にすると、ツール呼び出し、エラー、修正試行などの詳細な情報がJSONL形式で記録されます。

## ログ機能の有効化

### 方法1: .envファイルを使用（推奨）

プロジェクトルートの`.env`ファイルを編集してログ機能を制御します：

```bash
# .env ファイルの編集
BLENDER_MCP_EXPERIMENT_LOG=true    # ログ機能を有効化
BLENDER_MCP_LOG_DIR=logs           # ログファイルの保存先

# サーバー起動
python -m blender_mcp
```

実験を開始する前に：
```bash
# .envファイルでログを有効化
sed -i 's/BLENDER_MCP_EXPERIMENT_LOG=false/BLENDER_MCP_EXPERIMENT_LOG=true/' .env

# 実験終了後にログを無効化
sed -i 's/BLENDER_MCP_EXPERIMENT_LOG=true/BLENDER_MCP_EXPERIMENT_LOG=false/' .env
```

### 方法2: 環境変数で直接設定

```bash
# Windowsの場合 (PowerShell)
$env:BLENDER_MCP_EXPERIMENT_LOG = "true"
$env:BLENDER_MCP_LOG_DIR = "logs"  # オプション（デフォルト: logs）
python -m blender_mcp

# macOS/Linuxの場合
export BLENDER_MCP_EXPERIMENT_LOG=true
export BLENDER_MCP_LOG_DIR=logs  # オプション（デフォルト: logs）
python -m blender_mcp
```

## ログファイルの形式

ログファイルは以下の場所に保存されます：
- `logs/experiment_log_YYYYMMDD_HHMMSS.jsonl`

各行は以下のようなJSON形式です：

```json
{
  "timestamp": "2025-12-18T10:30:45.123456",
  "session_id": "20251218_103045",
  "event": "TOOL_CALL",
  "details": {
    "tool": "get_building_standards",
    "arguments": {"category": "residential"},
    "result": "...",
    "success": true
  }
}
```

## イベントタイプ

- `SESSION_START`: 実験セッション開始
- `TOOL_CALL`: ツール呼び出し
- `ERROR`: エラー発生
- `FIX_ATTEMPT`: 修正試行
- `VALIDATION_RESULT`: 検証結果

## ログデータの分析

ログファイルから統計情報を抽出するPythonスクリプトの例：

```python
import json
from collections import Counter

def analyze_log(log_file):
    events = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    
    # イベントタイプの集計
    event_types = Counter(e['event'] for e in events)
    
    # エラー回数
    error_count = sum(1 for e in events if e['event'] == 'ERROR')
    
    # 修正試行回数
    fix_attempts = sum(1 for e in events if e['event'] == 'FIX_ATTEMPT')
    
    print(f"総イベント数: {len(events)}")
    print(f"イベントタイプ別: {dict(event_types)}")
    print(f"エラー数: {error_count}")
    print(f"修正試行数: {fix_attempts}")

# 使用例
analyze_log('logs/experiment_log_20251218_103045.jsonl')
```

## 設定値の詳細

### BLENDER_MCP_EXPERIMENT_LOG

ログ機能の有効/無効を制御します。以下の値で `true` と判定されます：

- `true`, `True`, `TRUE`
- `1`
- `yes`, `Yes`, `YES`
- `on`, `On`, `ON`

その他の値（`false`, `0`, `no`, `off`, 空文字など）は `false` として扱われます。

### BLENDER_MCP_LOG_DIR

ログファイルの保存先ディレクトリを指定します。

- **デフォルト**: `logs`
- **相対パス**: プロジェクトルートからの相対パス
- **絶対パス**: システム上の任意の場所

## 注意事項

- ログ機能は開発・実験用です。本番環境では無効化することを推奨します。
- ログファイルは自動的に削除されないため、定期的に手動で管理してください。
- ログにはBlenderシーンの詳細情報が含まれる可能性があります。
- `.env`ファイルの変更後は、サーバーを再起動する必要があります。