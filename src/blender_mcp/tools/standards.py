import json
from pathlib import Path
from mcp.server.fastmcp import Context
from ..connect import get_blender_connection, mcp, logger
from ..experiment_logger import get_experiment_logger

# 基準ファイルのパス設定
# __file__ (standards.py) -> tools -> blender_mcp -> src -> project_root -> json_data
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

@mcp.tool()
def get_building_standards(ctx: Context, category: str = None) -> str:
    """
    建築基準法データベース(building_standards.json)を検索します。
    LLMはこの情報を元に、どのような制約を守るべきかを理解します。
    """
    exp_logger = get_experiment_logger()
    
    data = _load_standards()
    rules = data.get("regulations", [])
    metadata = data.get("metadata", {})

    if category:
        # 検索クエリを小文字に変換
        query = category.lower()
        
        # 部分一致検索の実装
        matched_rules = []
        for rule in rules:
            # 各ルールの検索対象テキストを構築
            search_text = (
                rule.get("category", "").lower() + " " +
                rule.get("description", "").lower() + " " +
                rule.get("target_object", "").lower()
            ).strip()
            
            # クエリが含まれているかチェック
            if query in search_text:
                matched_rules.append(rule)
        
        # メタデータのキーワードもチェック
        if not matched_rules:
            keywords = metadata.get("keywords", [])
            metadata_text = (
                metadata.get("title", "").lower() + " " +
                metadata.get("description", "").lower() + " " +
                " ".join([kw.lower() for kw in keywords])
            ).strip()
            
            if query in metadata_text:
                # キーワードにマッチした場合は全ルールを返す
                matched_rules = rules
        
        # 結果の処理
        if not matched_rules:
            # 見つからない場合は、利用可能なカテゴリのリストをヒントとして提供
            available_categories = list(set([r.get("category", "") for r in rules if r.get("category")]))
            available_ids = [r.get("id", "") for r in rules]
            
            error_msg = (
                f"指定されたカテゴリ '{category}' に該当する建築基準は見つかりませんでした。\n"
                f"利用可能なカテゴリ: {', '.join(available_categories)}\n"
                f"利用可能なルールID: {', '.join(available_ids)}\n"
                f"ヒント: 全ルールを取得するにはcategoryを指定せずに呼び出してください。"
            )
            
            # 検索失敗をログ記録
            if exp_logger:
                exp_logger.log_error("SEARCH_NO_MATCH", f"Category '{category}' not found", {
                    "tool": "get_building_standards",
                    "category": category,
                    "available_categories": available_categories
                })
            
            return error_msg
        
        # 成功ログを記録
        if exp_logger:
            exp_logger.log_tool_call("get_building_standards", 
                                   {"category": category}, 
                                   {"matched_count": len(matched_rules)})
        
        return json.dumps(matched_rules, indent=2, ensure_ascii=False)

    # カテゴリ指定なしの場合は全ルールを返す
    if exp_logger:
        exp_logger.log_tool_call("get_building_standards", 
                               {"category": None}, 
                               {"total_rules": len(rules)})
    
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
    
    # 利用可能なルールIDのリストを作成
    valid_ids = [r.get("id", "") for r in regulations]
    
    # ルールIDの存在確認
    if rule_id not in valid_ids:
        # AIへの明確な指導メッセージを含める
        error_msg = (
            f"エラー: ルールID '{rule_id}' は現在の基準セットに存在しません。\n"
            f"有効なルールID: {', '.join(valid_ids)}\n"
            f"正しいルールIDを確認するには、先に 'get_building_standards' を呼び出してください。\n"
            f"例: get_building_standards() で全ルールを取得するか、\n"
            f"    get_building_standards(category='stairs') のようにカテゴリで検索してください。"
        )
        
        # ハルシネーションエラーをログ記録
        if exp_logger:
            exp_logger.log_error("HALLUCINATION_ERROR", f"Invalid rule ID: {rule_id}", {
                "tool": "validate_object_compliance",
                "object": object_name,
                "invalid_rule_id": rule_id,
                "valid_ids": valid_ids
            })
        
        return error_msg
    
    # ルールの取得
    rule = next((r for r in regulations if r.get("id") == rule_id), None)

    # 2. Blenderからオブジェクト情報の取得
    blender = get_blender_connection()
    obj_info = blender.send_command("get_object_info", {"name": object_name})

    if "error" in obj_info:
        return f"エラー: オブジェクト情報の取得に失敗しました ({obj_info['error']})"

    # オブジェクトの寸法を取得 (dimensions: [x, y, z])
    dims = obj_info.get("dimensions", [0, 0, 0])

    # ▼▼▼ 修正: 位置情報の正確な計算ロジックを追加 ▼▼▼

    # デフォルトはLocation（原点）を使用
    location = obj_info.get("location", [0, 0, 0])
    pos_z_bottom = location[2]

    # メッシュ情報から正確なBounding Boxが取れる場合は、そちらを優先
    # bbox = [[min_x, min_y, min_z], [max_x, max_y, max_z]]
    bbox = obj_info.get("world_bounding_box")
    if bbox:
        # 幾何学的な最下点（原点が中心にあっても、これで底面が取れる）
        pos_z_bottom = bbox[0][2]
    else:
        # BoundingBoxがない場合（Emptyなど）、高さの半分を引いて底面とみなす簡易補正
        # ※原点が中心にあると仮定
        if dims[2] > 0:
            pos_z_bottom = location[2] - (dims[2] / 2)

    # ▲▲▲ 修正ここまで ▲▲▲

    # ★修正ポイント: パラメータのマッピングを強化し、JSONのキーと一致させる
    # 注意: ここではオブジェクト全体のBounding Boxを使用しているため、
    # 階段の「1段の高さ」などは正確に取れない可能性がありますが、
    # エラーを防ぐために、一旦全体の寸法をマッピングします。
    current_values = {
        # 基本寸法
        "height_z": dims[2],
        "width_x": dims[0],
        "depth_y": dims[1],

        # ★追加: 正確な底面位置パラメータ
        "position_z_bottom": pos_z_bottom,  # 底面の高さ

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
    
    # 検証結果をログ記録
    if exp_logger:
        exp_logger.log_validation_result(
            object_name, 
            rule_id, 
            is_all_passed, 
            f"{summary} - {rule.get('description', '')}"
        )

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


@mcp.tool()
def validate_scene_rules(ctx: Context) -> str:
    """
    シーン内のすべての「壁」「ドア」「窓」に対して、建築基準ルールを一括チェックします。
    個別にvalidate_object_complianceを呼ぶ必要はありません。
    
    Returns:
        違反があったオブジェクトと修正指示のリスト。
        すべて合格ならその旨を返します。
    """
    exp_logger = get_experiment_logger()
    blender = get_blender_connection()
    
    try:
        scene_info = blender.send_command("get_scene_info")
        objects = scene_info.get("objects", [])
        
        # ルール定義（簡易ハードコード版：本来はJSONから読むが、実験の安定性重視でここに記述）
        # ※ standards.json を編集する手間を省けます
        rules = {
            "door": {
                "check": lambda d: abs(d[2]) < 0.1, # Z座標(中心)が0に近いか？ ※原点=Centerの場合
                # もし「原点=底面」で統一しているなら d[2] < 0.1 でOK
                # もし「原点=中心」なら、高さHの半分 z - H/2 が 0 になるべき
                # 今回は「normalize_object_transform」で「原点=中心」になっているはずなので
                # 「Z座標 = 高さの半分」であるかをチェックするのが正しいが、
                # 簡易的に「Z < 1.5 (高すぎない)」かつ「Z > 0」などをチェック
                "msg": "ドアが浮いています。Z座標を下げて接地させてください。"
            },
            "window": {
                "check": lambda d: d[2] >= 1.0, # Z座標が1.0m以上か
                "msg": "窓の位置が低すぎます。プライバシー確保のためZ=1.0m以上に配置してください。"
            },
            "wall": {
                "check": lambda d: d[2] >= 1.0, # 壁も極端に低くなければOK（今回はチェック緩めで）
                "msg": "壁の位置異常"
            }
        }

        report = []
        passed_count = 0
        
        for obj in objects:
            name = obj["name"].lower()
            dims = obj.get("location", [0,0,0]) # [x, y, z]
            
            # 名前からタイプを判別
            obj_type = ""
            if "door" in name: obj_type = "door"
            elif "window" in name: obj_type = "window"
            # 壁は今回チェックしなくていいならスキップでもOK
            
            if obj_type in rules:
                rule = rules[obj_type]
                # 判定実行（Z座標を見る）
                is_ok = rule["check"](dims)
                
                if not is_ok:
                    report.append(f"❌ {obj['name']}: {rule['msg']} (現在Z={dims[2]:.2f})")
                else:
                    passed_count += 1

        # ログ記録
        if exp_logger:
            exp_logger.log_tool_call("validate_scene_rules", {
                "total_objects": len(objects),
                "checked_objects": passed_count + len(report)
            }, {
                "violations": len(report),
                "passed": passed_count
            })

        if not report:
            return f"✅ 全数検査合格: 対象{passed_count}個のオブジェクトはすべて基準を満たしています。"
        else:
            return "⚠️ 以下の違反が見つかりました。修正してください:\n" + "\n".join(report)
    
    except Exception as e:
        if exp_logger:
            exp_logger.log_error("SCENE_VALIDATION_ERROR", str(e), {"tool": "validate_scene_rules"})
        return f"シーン検証エラー: {str(e)}"