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

    Parameters:
    - category: (Optional) 'Habitable Room', 'Stairs', 'Lighting' など。指定がない場合は全ルールを返します。
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

    Parameters:
    - object_name: 検証対象のBlenderオブジェクト名
    - rule_id: 適用するルールのID (例: 'RULE_01_CEILING')
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
    # パラメータのマッピング (簡易実装: Blenderの座標系に合わせる)
    # 実際の運用ではオブジェクトの回転などを考慮するか、bounding_boxを使う方が正確ですが、
    # ここでは概念実証としてdimensionsを使用します。
    current_values = {
        "height_z": dims[2],      # Z軸の高さ
        "width_x": dims[0],       # X軸の幅
        "depth_y": dims[1],       # Y軸の奥行き

        # 階段用: 単一オブジェクトの場合、全体の高さ/段数で推論する等の工夫が必要ですが
        # ここでは便宜上、LLMが別途計算した値を入れるか、bounding boxをそのままマッピングします
        # (階段一段ずつのオブジェクトならZ=riser_heightになります)
        "riser_height": dims[2],
        "tread_depth": dims[1]
    }

    logic = rule.get("validation_logic", {})
    results = []

    # 3. 検証ロジックの実行

    # 複合条件 (AND) の場合
    if "and_conditions" in logic:
        for condition in logic["and_conditions"]:
            param_key = condition["parameter"]
            val = current_values.get(param_key)
            passed = _evaluate_condition(val, condition["operator"], condition["threshold"])

            status = "合格" if passed else "不合格"
            results.append(f"- {param_key}: 現在値={val:.3f}{condition['unit']} (基準 {condition['operator']} {condition['threshold']}) -> {status}")

    # 単一条件の場合
    elif "parameter" in logic:
        param_key = logic["parameter"]
        val = current_values.get(param_key)
        passed = _evaluate_condition(val, logic["operator"], logic["threshold"])

        status = "合格" if passed else "不合格"
        results.append(f"- {param_key}: 現在値={val:.3f}{logic['unit']} (基準 {logic['operator']} {logic['threshold']}) -> {status}")

    # 比率比較 (窓など) - 高度なため今回は未実装の旨を返すか、簡易計算
    elif logic.get("type") == "ratio_comparison":
        return "このルールの自動検証には、対象オブジェクトと親オブジェクト(床)の両方の面積情報が必要です。現在は手動で確認してください。"

    # 4. 結果の返却
    is_all_passed = all("合格" in r for r in results)
    summary = "検証合格" if is_all_passed else "検証不合格"

    return f"""
検証レポート:
対象: {object_name}
ルール: {rule['description']}

結果: {summary}
詳細:
{chr(10).join(results)}

{'' if is_all_passed else f"修正提案: {rule['error_message']}"}
"""
