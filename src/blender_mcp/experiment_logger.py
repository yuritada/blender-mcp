"""
実験データ記録用ロガー
実験の各ステップ、エラー、修正試行を構造化されたJSONL形式で記録
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

class ExperimentLogger:
    """実験データを記録する専用ロガー"""
    
    def __init__(self, log_dir: str = "logs"):
        """
        ログディレクトリを初期化し、タイムスタンプ付きログファイルを作成
        
        Args:
            log_dir: ログファイルを保存するディレクトリ
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # タイムスタンプ付きファイル名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"experiment_log_{timestamp}.jsonl"
        
        # セッション情報の記録
        self.session_id = timestamp
        self._log_session_start()
    
    def _log_session_start(self):
        """実験セッション開始の記録"""
        self.log_event("SESSION_START", {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat()
        })
    
    def log_event(self, event_type: str, details: Dict[str, Any]):
        """
        イベントをJSONL形式で記録
        
        Args:
            event_type: イベントタイプ (TOOL_CALL, ERROR, LLM_RESPONSE, FIX_ATTEMPT等)
            details: イベントの詳細情報
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "event": event_type,
            "details": details
        }
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # ロギング失敗時は標準エラー出力に記録
            import sys
            print(f"[ExperimentLogger] Failed to write log: {e}", file=sys.stderr)
    
    def log_tool_call(self, tool_name: str, args: Dict[str, Any], result: Any):
        """ツール呼び出しの記録"""
        self.log_event("TOOL_CALL", {
            "tool": tool_name,
            "arguments": args,
            "result": str(result) if result else None,
            "success": "error" not in str(result).lower() if result else True
        })
    
    def log_error(self, error_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """エラーの記録"""
        details = {
            "error_type": error_type,
            "message": message
        }
        if context:
            details["context"] = context
        self.log_event("ERROR", details)
    
    def log_fix_attempt(self, target: str, action: str, success: bool):
        """修正試行の記録"""
        self.log_event("FIX_ATTEMPT", {
            "target": target,
            "action": action,
            "success": success
        })
    
    def log_validation_result(self, object_name: str, rule_id: str, passed: bool, details: str):
        """検証結果の記録"""
        self.log_event("VALIDATION_RESULT", {
            "object": object_name,
            "rule_id": rule_id,
            "passed": passed,
            "details": details
        })
    
    def get_log_file_path(self) -> Path:
        """現在のログファイルパスを取得"""
        return self.log_file
    
    def get_session_stats(self) -> Dict[str, int]:
        """
        現在のセッションの統計情報を取得
        
        Returns:
            各イベントタイプのカウント
        """
        stats = {
            "total_events": 0,
            "tool_calls": 0,
            "errors": 0,
            "fix_attempts": 0,
            "validations": 0
        }
        
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("session_id") == self.session_id:
                        stats["total_events"] += 1
                        event_type = entry.get("event", "")
                        if event_type == "TOOL_CALL":
                            stats["tool_calls"] += 1
                        elif event_type == "ERROR":
                            stats["errors"] += 1
                        elif event_type == "FIX_ATTEMPT":
                            stats["fix_attempts"] += 1
                        elif event_type == "VALIDATION_RESULT":
                            stats["validations"] += 1
        except Exception:
            pass
        
        return stats


# グローバルなシングルトンインスタンス
_global_logger = None

def get_experiment_logger(log_dir: str = "logs") -> Optional[ExperimentLogger]:
    """
    アプリケーション全体で共有されるロガーインスタンスを取得または作成する
    ※ main.py で初期化された後は、引数なしで呼べば同じインスタンスが返ります
    """
    global _global_logger
    if _global_logger is None:
        # まだ作成されていない場合は新規作成（環境変数をチェック）
        import os
        # .envファイルからの設定を優先的にチェック
        experiment_log_enabled = os.environ.get("BLENDER_MCP_EXPERIMENT_LOG", "false").lower()
        if experiment_log_enabled not in ["true", "1", "yes", "on"]:
            return None
        
        # ログディレクトリも環境変数から取得
        actual_log_dir = os.environ.get("BLENDER_MCP_LOG_DIR", log_dir)
        
        try:
            _global_logger = ExperimentLogger(actual_log_dir)
        except Exception as e:
            print(f"Warning: Failed to initialize ExperimentLogger: {e}")
            return None
    return _global_logger

def set_global_logger(logger: Optional[ExperimentLogger]):
    """main.pyから呼ばれる：グローバルロガーを設定"""
    global _global_logger
    _global_logger = logger