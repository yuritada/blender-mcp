# src/blender_mcp/main.py

# 不要な import は削除し、以下のようにシンプルにします
from blender_mcp.connect import mcp, logger
from blender_mcp.experiment_logger import ExperimentLogger
import os
import sys

# 重要: 各モジュールを import することで、@mcp.tool デコレータが実行され、
# mcp オブジェクトにツールが登録されます。
import blender_mcp.tools.core
import blender_mcp.tools.assets.polyhaven
import blender_mcp.tools.assets.hyper3d
import blender_mcp.tools.assets.sketchfab
import blender_mcp.tools.assets.prompt
import blender_mcp.tools.rules
import blender_mcp.tools.knowledge
import blender_mcp.tools.standards

# グローバル実験ロガーインスタンス
experiment_logger = None

def initialize_experiment_logging():
    """実験用ログの初期化"""
    global experiment_logger
    
    # 環境変数でログ機能を有効化できるようにする
    if os.environ.get("BLENDER_MCP_EXPERIMENT_LOG", "false").lower() == "true":
        log_dir = os.environ.get("BLENDER_MCP_LOG_DIR", "logs")
        experiment_logger = ExperimentLogger(log_dir)
        logger.info(f"実験ログを有効化しました: {experiment_logger.get_log_file_path()}")
        return experiment_logger
    return None

# MCPツールの実行をインターセプトするためのラッパー
original_run_tool = None

def wrap_tool_execution():
    """ツール実行をラップしてログを記録"""
    global original_run_tool
    
    if not experiment_logger:
        return
    
    # MCPサーバーのツール実行メソッドを保存（実装詳細に依存）
    # 注: これは簡略化した例です。実際の実装は mcp.server の詳細に依存します
    try:
        # ツール実行のフックポイントを探す
        # 実際の実装では、mcp の内部構造に基づいて適切なフック方法を選択する必要があります
        logger.info("ツール実行のログ記録を設定中...")
    except Exception as e:
        logger.warning(f"ツール実行のフック設定に失敗: {e}")

def main():
    """Run the MCP server"""
    # 実験ログの初期化
    exp_logger = initialize_experiment_logging()
    
    if exp_logger:
        # 実験ログが有効な場合、開始メッセージを表示
        print(f"[実験モード] ログファイル: {exp_logger.get_log_file_path()}", file=sys.stderr)
        wrap_tool_execution()
    
    # 既に tools 内で登録が完了している mcp インスタンスを起動
    mcp.run()

if __name__ == "__main__":
    main()