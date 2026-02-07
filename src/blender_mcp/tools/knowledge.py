import json
from pathlib import Path
from mcp.server.fastmcp import Context
from ..connect import mcp, logger
from ..experiment_logger import get_experiment_logger

# パス設定
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RULES_FILE = PROJECT_ROOT / "json_data" / "rules.json"

def _load_rules():
    """ルールファイルを読み込む"""
    if not RULES_FILE.exists():
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        return []
    try:
        with open(RULES_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content: return []
            return json.loads(content)
    except Exception as e:
        logger.error(f"Failed to load rules: {e}")
        return []

def _save_rules(rules):
    """ルールファイルを保存する"""
    try:
        with open(RULES_FILE, 'w', encoding='utf-8') as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save rules: {e}")
        return False

@mcp.tool()
def get_architectural_rules(ctx: Context, query: str = None, target_object: str = None) -> str:
    """
    過去に学習した建築ルール(rules.json)を検索します。

    Parameters:
    - query: 検索キーワード (例: "高さ", "配置", "クリアランス")
    - target_object: 適用対象でフィルタリング (例: "Window", "Door")
    """
    rules = _load_rules()

    # 1. まずターゲットでフィルタリング (Window, Doorなど)
    candidates = rules
    if target_object:
        t_obj = target_object.lower()
        # targetに指定文字列が含まれる、または target="All" のルールを候補にする
        candidates = [
            r for r in rules
            if t_obj in r.get("target", "").lower() or "all" in r.get("target", "").lower()
        ]

    # 2. クエリがある場合、さらに絞り込み
    matched = candidates
    if query:
        q = query.lower()
        matched = []
        for r in candidates:
            # 検索対象: 説明文、アクション名、トリガー名
            full_text = (
                r.get("description", "") + " " +
                r.get("action", "") + " " +
                r.get("trigger", "")
            ).lower()

            if q in full_text:
                matched.append(r)

    # 3. 結果の返却ロジック (ここを改善)
    if matched:
        return json.dumps(matched, indent=2, ensure_ascii=False)

    # ★改善ポイント: クエリでヒットしなくても、ターゲットの候補があればそれを返す（フォールバック）
    if not matched and candidates and query:
        return (
            f"キーワード '{query}' に完全一致するルールはありませんでしたが、"
            f"対象 '{target_object}' に関連するルールが見つかりました。\n"
            f"これらを確認してください:\n"
            f"{json.dumps(candidates, indent=2, ensure_ascii=False)}"
        )

    # 完全に該当なし
    msg = "条件に一致するルールは見つかりませんでした。"
    if target_object: msg += f"(Target={target_object})"
    if query: msg += f"(Query={query})"

    return msg

@mcp.tool()
def add_architectural_rule(
    ctx: Context,
    description: str,
    trigger: str = "ALWAYS",
    target: str = "General",
    action: str = "CHECK_GENERAL",
    severity: str = "WARNING"
) -> str:
    """
    新しい知見を「構造化されたルール」として保存します。

    Parameters:
    - description: 具体的なルール内容 (例: "窓の上端は壁の上辺-0.1m以下にする")
    - trigger: 適用タイミング ('ON_CREATE', 'ON_TRANSFORM', 'ALWAYS')
    - target: 適用対象 ('Window', 'Door', 'Wall', 'All')
    - action: ルールの種類 ('CHECK_BOUNDS', 'CHECK_POSITION', 'CHECK_COLLISION', 'CHECK_DIMENSION')
    - severity: 違反時の深刻度 ('ERROR': 必須, 'WARNING': 推奨)
    """
    exp_logger = get_experiment_logger()
    rules = _load_rules()

    # 重複チェック（内容が完全に一致する場合）
    for r in rules:
        if r["description"] == description and r["target"] == target:
            return "既に同じ内容のルールが存在するため、保存をスキップしました。"

    # ID生成 (数値連番)
    existing_ids = [int(r.get("id", 0)) for r in rules if isinstance(r.get("id"), int)]
    new_id = (max(existing_ids) if existing_ids else 0) + 1

    new_rule = {
        "id": new_id,
        "trigger": trigger,
        "target": target,
        "action": action,
        "severity": severity,
        "description": description
    }

    rules.append(new_rule)

    if _save_rules(rules):
        msg = f"✅ ルールを追加しました (ID: {new_id}): [{target}] {description}"
        if exp_logger:
            exp_logger.log_tool_call("add_architectural_rule", {"new_rule": new_rule}, {"success": True})
        return msg
    else:
        return "❌ ルールの保存に失敗しました。"
