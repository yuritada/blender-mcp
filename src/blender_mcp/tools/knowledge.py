import json
import os
from mcp.server.fastmcp import Context
from ..connect import mcp, logger

# パスの構築: tools -> blender_mcp -> src -> project_root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
JSON_DIR = os.path.join(BASE_DIR, "json_data")
RULES_FILE = os.path.join(JSON_DIR, "rules.json")

# ディレクトリが存在しない場合は作成（安全策）
os.makedirs(JSON_DIR, exist_ok=True)

def _load_rules():
    if not os.path.exists(RULES_FILE):
        return []
    try:
        with open(RULES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load rules: {e}")
        return []

def _save_rules(rules):
    try:
        with open(RULES_FILE, 'w', encoding='utf-8') as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save rules: {e}")
        return False

@mcp.tool()
def get_architectural_rules(ctx: Context, category: str = None) -> str:
    """
    建築ルールブック（rules.json）を読み込みます。
    
    Parameters:
    - category: (Optional) 特定のカテゴリ（例: 'Door', 'Window'）のみフィルタリングして取得します。指定がない場合は全ルールを返します。
    """
    rules = _load_rules()
    
    if category:
        filtered_rules = [r for r in rules if r.get("category", "").lower() == category.lower()]
        if not filtered_rules:
            return f"カテゴリ '{category}' に関するルールは見つかりませんでした。"
        return json.dumps(filtered_rules, indent=2, ensure_ascii=False)
    
    return json.dumps(rules, indent=2, ensure_ascii=False)

@mcp.tool()
def add_architectural_rule(ctx: Context, category: str, description: str) -> str:
    """
    新しい建築ルールをルールブック（rules.json）に追加します。
    自律的な判断で、将来のために保存すべきルールを発見した場合に使用してください。
    
    Parameters:
    - category: ルールの対象（例: 'Roof', 'Wall'）
    - description: ルールの具体的な内容（例: '屋根の傾斜は30度以上が望ましい'）
    """
    rules = _load_rules()
    
    # 重複チェック（簡易的）
    for r in rules:
        if r["description"] == description:
            return "そのルールは既に存在します。"

    new_id = max([r.get("id", 0) for r in rules], default=0) + 1
    new_rule = {
        "id": new_id,
        "category": category,
        "description": description
    }
    
    rules.append(new_rule)
    
    if _save_rules(rules):
        return f"新しいルールを追加しました (ID: {new_id}): [{category}] {description}"
    else:
        return "ルールの保存に失敗しました。"