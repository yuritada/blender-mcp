import json
from pathlib import Path
from mcp.server.fastmcp import Context
from ..connect import get_blender_connection, mcp, logger

# 基準ファイルのパス設定
CURRENT_DIR = Path(__file__).parent.parent
STANDARDS_FILE = CURRENT_DIR / "building_standards.json"

def _load_standards():
    """JSONファイルを読み込むヘルパー関数"""
    if not STANDARDS_FILE.exists():
        logger.error(f"Standards file not found at {STANDARDS_FILE}")
        return {"regulations": []}
    try:
        with open(STANDARDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load standards: {e}")
        return {"regulations": []}

def _evaluate_condition(value, operator, threshold):
    """単純な数値比較を行うヘルパー関数"""
    if value is None:
        return False
    if operator == ">=":
        return value >= threshold
    elif operator == "<=":
        return value <= threshold
    elif operator == ">":
        return value > threshold
    elif operator == "<":
        return value < threshold
    elif operator == "==":
        return value == threshold
    return False

@mcp.tool()
def get_building_standards(ctx: Context, category: str = None) -> str:
    """
    建築基準法データベース(building_standards.json)を検索します。
    LLMはこの情報を元に、どのような制約を守るべきかを理解します。
    """
    data = _load_standards()
    rules = data.get("regulations", [])

    if category:
        filtered = [r for r in rules if r.get("category", "").lower() == category.lower()]
        if not filtered:
            return f"カテゴリ '{category}' に該当する建築基準は見つかりませんでした。"
        return json.dumps(filtered, indent=2, ensure_ascii=False)

    return json.dumps(rules, indent=2, ensure_ascii=False)

@mcp.tool()
def validate_object_compliance(ctx: Context, object_name: str, rule_id: str) -> str:
    """
    指定されたBlenderオブジェクトが、特定の建築基準(rule_id)を満たしているか検証します。
    """
    # 1. ルールの取得
    data = _load_standards()
    rule = next((r for r in data.get("regulations", []) if r["id"] == rule_id), None)
    if not rule:
        return f"エラー: ルールID '{rule_id}' は見つかりませんでした。"

    # 2. Blenderからオブジェクト情報の取得
    blender = get_blender_connection()
    obj_info = blender.send_command("get_object_info", {"name": object_name})

    if "error" in obj_info:
        return f"エラー: オブジェクト情報の取得に失敗しました ({obj_info['error']})"

    # オブジェクトの寸法を取得 (dimensions: [x, y, z])
    dims = obj_info.get("dimensions", [0, 0, 0])
    
    # ★修正ポイント: パラメータのマッピングを強化し、JSONのキーと一致させる
    # 注意: ここではオブジェクト全体のBounding Boxを使用しているため、
    # 階段の「1段の高さ」などは正確に取れない可能性がありますが、
    # エラーを防ぐために、一旦全体の寸法をマッピングします。
    current_values = {
        # 基本寸法
        "height_z": dims[2],
        "width_x": dims[0],
        "depth_y": dims[1],

        # 階段・廊下用エイリアス (JSONのパラメータ名に対応)
        "effective_width": dims[0],       # 幅 = 有効幅と仮定
        "min_clear_width": dims[0],       # 廊下幅
        "clear_opening_width": dims[0],   # ドア幅
        
        # ※注意: 階段全体を1つのオブジェクト(Emptyの親など)として測っている場合、
        # "riser_height"(蹴上げ) = 全高 となってしまい、不合格になる可能性が高いです。
        # 本来は子オブジェクトを解析すべきですが、まずはクラッシュを防ぎます。
        "riser_height": dims[2],          
        "tread_depth_effective": dims[1]  # JSONのキー "tread_depth_effective" に対応
    }

    logic = rule.get("validation_logic", {})
    results = []

    # 3. 検証ロジックの実行
    conditions = []
    if "and_conditions" in logic:
        conditions = logic["and_conditions"]
    elif "parameter" in logic:
        conditions = [logic] # 単一条件をリスト化

    for condition in conditions:
        if "parameter" not in condition: continue
        
        param_key = condition["parameter"]
        val = current_values.get(param_key)
        
        # 値が取得できなかった場合の安全策
        if val is None:
            status = "判定不能 (パラメータ取得失敗)"
            val_str = "N/A"
        else:
            passed = _evaluate_condition(val, condition["operator"], condition["threshold"])
            status = "合格" if passed else "不合格"
            val_str = f"{val:.3f}" # ★修正ポイント: Noneでない場合のみフォーマット

        # 単位の取得
        unit = condition.get("unit", "")
        
        results.append(f"- {param_key}: 現在値={val_str}{unit} (基準 {condition['operator']} {condition['threshold']}) -> {status}")

    # 4. 結果の返却
    is_all_passed = all("合格" in r and "不合格" not in r and "判定不能" not in r for r in results)
    
    summary = "✅ 検証合格" if is_all_passed else "❌ 検証不合格"

    return f"""
検証レポート:
対象: {object_name}
ルール: {rule['description']}

結果: {summary}
詳細:
{chr(10).join(results)}

{'' if is_all_passed else f"修正提案: {rule.get('error_message', '基準を満たすように修正してください。')}"}
(注: 階段などの複合オブジェクトの場合、親オブジェクト全体のサイズで判定されているため、個別の段差寸法とは異なる場合があります)
"""