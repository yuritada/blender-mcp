import json
from pathlib import Path
from mcp.server.fastmcp import Context
from ..connect import get_blender_connection, mcp, logger
from ..experiment_logger import get_experiment_logger

# 基準ファイルのパス設定
PROJECT_ROOT = Path(__file__).resolve().parents[3]
STANDARDS_FILE = PROJECT_ROOT / "json_data" / "building_standards.json"

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

def _find_scene_floor_area(blender):
    """
    シーン内の床オブジェクトを簡易探索して総面積を計算する
    """
    try:
        # シーン情報を取得
        scene_info = blender.send_command("get_scene_info")
        objects = scene_info.get("objects", [])

        total_area = 0.0
        found_any = False

        # 床とみなすキーワード
        floor_keywords = ["floor", "yuka", "room", "slab", "ground", "tatami", "base"]

        for obj in objects:
            name = obj["name"].lower()
            if any(k in name for k in floor_keywords):
                # 詳細情報を取得して寸法を確認
                details = blender.send_command("get_object_info", {"name": obj["name"]})
                if "dimensions" in details:
                    d = details["dimensions"]
                    # X * Y を面積とする (Zは高さと仮定)
                    area = d[0] * d[1]
                    if area > 0.1: # 小さすぎるゴミオブジェクトは無視
                        total_area += area
                        found_any = True

        return total_area if found_any else None
    except Exception as e:
        logger.warning(f"Floor search failed: {e}")
        return None

def _extract_parameters(obj_info, context_values=None):
    """
    Blenderのオブジェクト情報から検証用パラメータ辞書を作成する
    """
    dims = obj_info.get("dimensions", [0, 0, 0])
    location = obj_info.get("location", [0, 0, 0])

    # 底面位置の計算
    pos_z_bottom = location[2]
    bbox = obj_info.get("world_bounding_box")
    if bbox:
        pos_z_bottom = bbox[0][2]
    elif dims[2] > 0:
        pos_z_bottom = location[2] - (dims[2] / 2)

    params = {
        # 基本寸法
        "height_z": dims[2],
        "width_x": dims[0],
        "depth_y": dims[1],

        # 位置情報
        "position_z_bottom": pos_z_bottom,

        # エイリアス
        "effective_width": dims[0],
        "min_clear_width": dims[0],
        "clear_opening_width": dims[0],
        "riser_height": dims[2],
        "tread_depth_effective": dims[1],

        # 窓などの面積計算用
        "openable_window_area": dims[0] * dims[2],
        "effective_lighting_area": dims[0] * dims[2]
    }

    # 外部コンテキスト（床面積など）があればマージ
    if context_values:
        params.update(context_values)

    # 床面積が未設定の場合の安全策
    if "floor_area" not in params:
        params["floor_area"] = None

    return params

def _check_rule_logic(rule, current_values):
    """
    単一のルールと現在の値を比較検証するロジック
    """
    logic = rule.get("validation_logic", {})
    logic_type = logic.get("type", "simple_check") # デフォルトは通常チェック

    results = []
    failures = []

    # --- A. 比率計算 (Ratio Comparison) ---
    if logic_type == "ratio_comparison":
        num_key = logic.get("numerator")
        denom_key = logic.get("denominator")

        val_num = current_values.get(num_key)
        val_denom = current_values.get(denom_key)

        # ★重要修正: 分母（床面積）が不明な場合は「判定不能」としてPASSさせる
        # これにより無限ループを防ぐ
        if not val_denom or val_denom <= 0:
            msg = f"⚠️ {rule['id']}: 床面積などの基準({denom_key})が見つからないため、このルールの判定をスキップします。"
            results.append(msg)
            # failuresには追加しない -> 合格扱い
            return True, results, failures

        ratio = val_num / val_denom
        passed = _evaluate_condition(ratio, logic["operator"], logic["threshold"])

        status = "合格" if passed else "不合格"
        val_str = f"{ratio:.3f}"
        msg = f"- 比率 {num_key}/{denom_key}: 値={val_str} (基準 {logic['operator']} {logic['threshold']}) -> {status}"

        results.append(msg)
        if not passed:
            failures.append(f"比率要件未達 (現在: {val_str})")

        return passed, results, failures

    # --- B. 通常パラメータチェック (And Conditions / Single Parameter) ---
    conditions = []
    if "and_conditions" in logic:
        conditions = logic["and_conditions"]
    elif "parameter" in logic:
        conditions = [logic]

    for condition in conditions:
        if "parameter" not in condition: continue

        param_key = condition["parameter"]
        val = current_values.get(param_key)

        unit = condition.get("unit", "")
        threshold = condition.get("threshold")
        operator = condition.get("operator")

        if val is None:
            status = "判定不能"
            val_str = "N/A"
            passed = False # パラメータ不足は不合格扱いとするか要検討だが、基本はFalse
        else:
            passed = _evaluate_condition(val, operator, threshold)
            status = "合格" if passed else "不合格"
            val_str = f"{val:.3f}"

        msg = f"- {param_key}: 現在値={val_str}{unit} (基準 {operator} {threshold}) -> {status}"
        results.append(msg)

        if not passed:
            failures.append(f"{param_key}違反(値:{val_str})")

    # 条件チェックの結果
    # ratio_comparison以外の場合、resultsがあればそれに基づいて判定
    if not results and logic_type != "ratio_comparison":
        # 条件定義が空の場合は合格扱い
        return True, ["検証条件なし"], []

    is_all_passed = len(failures) == 0
    return is_all_passed, results, failures

@mcp.tool()
def get_building_standards(ctx: Context, category: str = None) -> str:
    """
    建築基準法データベース(building_standards.json)を検索します。
    """
    exp_logger = get_experiment_logger()
    data = _load_standards()
    rules = data.get("regulations", [])
    metadata = data.get("metadata", {})

    if category:
        query = category.lower()
        matched_rules = []
        for rule in rules:
            search_text = (
                rule.get("category", "").lower() + " " +
                rule.get("description", "").lower() + " " +
                rule.get("target_object", "").lower()
            ).strip()
            if query in search_text:
                matched_rules.append(rule)

        if not matched_rules:
            keywords = metadata.get("keywords", [])
            metadata_text = (metadata.get("title", "") + " " + metadata.get("description", "") + " " + " ".join(keywords)).lower()
            if query in metadata_text:
                matched_rules = rules

        if not matched_rules:
            available_categories = list(set([r.get("category", "") for r in rules if r.get("category")]))
            return f"指定されたカテゴリ '{category}' に該当する基準は見つかりませんでした。利用可能: {', '.join(available_categories)}"

        if exp_logger:
            exp_logger.log_tool_call("get_building_standards", {"category": category}, {"matched": len(matched_rules)})
        return json.dumps(matched_rules, indent=2, ensure_ascii=False)

    if exp_logger:
        exp_logger.log_tool_call("get_building_standards", {"category": None}, {"total": len(rules)})
    return json.dumps(rules, indent=2, ensure_ascii=False)

@mcp.tool()
def validate_object_compliance(ctx: Context, object_name: str, rule_id: str) -> str:
    """
    指定されたBlenderオブジェクトが、特定の建築基準(rule_id)を満たしているか検証します。
    """
    exp_logger = get_experiment_logger()

    # 1. ルールの取得
    data = _load_standards()
    regulations = data.get("regulations", [])
    rule = next((r for r in regulations if r.get("id") == rule_id), None)

    if not rule:
        valid_ids = [r.get("id", "") for r in regulations]
        return f"エラー: ルールID '{rule_id}' が見つかりません。有効ID: {', '.join(valid_ids)}"

    # 2. オブジェクト情報の取得
    blender = get_blender_connection()
    obj_info = blender.send_command("get_object_info", {"name": object_name})
    if "error" in obj_info:
        return f"エラー: オブジェクト情報の取得失敗 ({obj_info['error']})"

    # 3. コンテキスト情報の取得（床面積などが必要な場合のため）
    context_values = {}
    floor_area = _find_scene_floor_area(blender)
    if floor_area:
        context_values["floor_area"] = floor_area

    # 4. パラメータ抽出と検証
    current_values = _extract_parameters(obj_info, context_values)
    is_all_passed, results, failures = _check_rule_logic(rule, current_values)

    summary = "✅ 検証合格" if is_all_passed else "❌ 検証不合格"

    suggestion = ""
    if not is_all_passed:
        base_msg = rule.get('error_message', '基準を満たすように修正してください。')
        specific_errors = ", ".join(failures)
        suggestion = f"修正提案: {base_msg}\n(違反要因: {specific_errors})"

    if exp_logger:
        exp_logger.log_validation_result(object_name, rule_id, is_all_passed, f"{summary} - {suggestion}")

    return f"""
検証レポート:
対象: {object_name}
ルール: {rule['description']}

結果: {summary}
詳細:
{chr(10).join(results)}

{suggestion}
"""

@mcp.tool()
def validate_scene_rules(ctx: Context) -> str:
    """
    シーン内のすべてのオブジェクトに対して、該当するすべての建築基準を一括チェックします。
    """
    exp_logger = get_experiment_logger()
    blender = get_blender_connection()

    try:
        # 1. シーン情報の取得と床面積の計算
        scene_info = blender.send_command("get_scene_info")
        objects = scene_info.get("objects", [])

        # 床面積を一括計算（コンテキストとして使用）
        context_values = {}
        floor_area = _find_scene_floor_area(blender)
        if floor_area:
            context_values["floor_area"] = floor_area

        data = _load_standards()
        all_rules = data.get("regulations", [])

        report = []
        violation_count = 0
        checked_count = 0

        # 2. オブジェクトごとに該当ルールを探索して適用
        for obj in objects:
            obj_name = obj["name"]

            # 詳細情報を取得
            full_obj_info = blender.send_command("get_object_info", {"name": obj_name})
            if "error" in full_obj_info:
                continue

            current_values = _extract_parameters(full_obj_info, context_values)

            # 適用可能なルールをフィルタリング
            applicable_rules = []
            for rule in all_rules:
                target = rule.get("target_object", "").lower()
                category = rule.get("category", "").lower()

                # マッチングロジック
                if (target and target in obj_name.lower()) or \
                   (category and category in obj_name.lower()):
                    applicable_rules.append(rule)

            if not applicable_rules:
                continue

            checked_count += 1
            obj_violations = []

            # 3. 該当した全ルールを適用
            for rule in applicable_rules:
                is_passed, _, failures = _check_rule_logic(rule, current_values)

                if not is_passed:
                    error_detail = ", ".join(failures)
                    obj_violations.append(f"  - [{rule['id']}] {rule.get('description', '')[:30]}... -> 違反: {error_detail}")

            if obj_violations:
                violation_count += 1
                report.append(f"❌ オブジェクト '{obj_name}' の違反:")
                report.extend(obj_violations)

        if exp_logger:
            exp_logger.log_tool_call("validate_scene_rules",
                {"total_objects": len(objects), "checked": checked_count},
                {"violations": violation_count}
            )

        if not report:
            if checked_count == 0:
                return "⚠️ 検証可能なオブジェクトが見つかりませんでした（名前が基準カテゴリと一致しません）。"
            return f"✅ 全数検査合格: チェック対象 {checked_count} 個のオブジェクトに違反は見つかりませんでした。"
        else:
            return f"⚠️ {violation_count} 個のオブジェクトで違反が見つかりました:\n" + "\n".join(report)

    except Exception as e:
        import traceback
        return f"シーン検証エラー: {str(e)}\n{traceback.format_exc()}"
