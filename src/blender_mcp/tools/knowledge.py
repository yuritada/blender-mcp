import json
from pathlib import Path
from mcp.server.fastmcp import Context
from ..connect import mcp, logger
from ..experiment_logger import get_experiment_logger

# パス設定 (pathlibを使用)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RULES_FILE = PROJECT_ROOT / "json_data" / "rules.json"

def _load_rules():
    """ルールファイルを読み込む"""
    if not RULES_FILE.exists():
        # 親ディレクトリごと作成
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
def get_architectural_rules(ctx: Context, query: str = None, category: str = None) -> str:
    """
    過去に学習した建築ルールや知見(rules.json)を検索します。

    Parameters:
    - query: (Optional) 検索したいキーワード（例: "階段", "高さ"）
    - category: (Optional) 特定のカテゴリでフィルタリング（例: "Window", "Door"）
    """
    rules = _load_rules()

    # フィルタリング処理
    matched = rules

    if category:
        matched = [r for r in matched if r.get("category", "").lower() == category.lower()]

    if query:
        q = query.lower()
        matched = [
            r for r in matched
            if q in r.get("description", "").lower()
            or q in r.get("trigger", "").lower()
            or q in r.get("category", "").lower()
        ]

    if not matched:
        return f"条件に一致するルールは見つかりませんでした。(Category={category}, Query={query})"

    return json.dumps(matched, indent=2, ensure_ascii=False)

@mcp.tool()
def add_architectural_rule(ctx: Context, description: str, category: str = "General", trigger: str = "Always") -> str:
    """
    新しい知見をルールブック(rules.json)に保存します。

    Parameters:
    - description: ルールの内容（例: "窓は床面積の1/7以上必要"）
    - category: 分類（例: "Window", "Safety", "Design"）
    - trigger: このルールをいつ思い出すべきか（例: "窓を作成するとき", "エラーが出たとき"）
    """
    exp_logger = get_experiment_logger()
    rules = _load_rules()

    # ID生成 (連番)
    # 既存IDが数値か文字列かで処理を分ける（安全策）
    existing_ids = []
    for r in rules:
        rid = r.get("id")
        if isinstance(rid, int): existing_ids.append(rid)
        elif isinstance(rid, str) and rid.isdigit(): existing_ids.append(int(rid))

    new_id_num = (max(existing_ids) if existing_ids else 0) + 1
    new_id = new_id_num # 数値IDで統一

    new_rule = {
        "id": new_id,
        "category": category,
        "trigger": trigger,
        "description": description,
        "created_at": "auto-generated"
    }

    rules.append(new_rule)

    if _save_rules(rules):
        msg = f"✅ ルールを追加しました (ID: {new_id}): [{category}] {description}"
        if exp_logger:
            exp_logger.log_tool_call("add_architectural_rule", {"new_rule": new_rule}, {"success": True})
        return msg
    else:
        return "❌ ルールの保存に失敗しました。"
