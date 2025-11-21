import json
import datetime
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context, Image
from ..connect import get_blender_connection, mcp, logger

# 実験データ保存用のディレクトリ設定
# プロジェクト実行時のカレントディレクトリ直下に dataset フォルダを作ります
DATASET_DIR = Path("dataset")
IMAGES_DIR = DATASET_DIR / "images"
LOGS_DIR = DATASET_DIR / "logs"
LOG_FILE_PATH = LOGS_DIR / "experiment_log.jsonl"

# 読み込み時にディレクトリを作成
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

@mcp.tool()
def reset_scene(ctx: Context) -> str:
    """
    シーン内のすべてのメッシュ、カーブ、ライトなどを削除し、初期状態（空の状態）に戻します。
    カメラは残します。新しい実験タスクを開始する前に呼び出します。
    """
    reset_code = """
import bpy

# 編集モードならオブジェクトモードに戻す
if bpy.context.object and bpy.context.object.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')

# 全選択解除
bpy.ops.object.select_all(action='DESELECT')

# メッシュ、カーブ、サーフェス、メタ、テキスト、ボリューム、グリースペンシル、ライト、ライトプローブを選択
# カメラ(CAMERA)は実験記録用に残す
objs = [o for o in bpy.context.scene.objects if o.type in {
    'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'VOLUME', 'GPENCIL', 
    'LIGHT', 'LIGHT_PROBE'
}]

for o in objs:
    o.select_set(True)

# 削除実行
bpy.ops.object.delete()

# 孤立したデータブロック（マテリアルやメッシュデータ）を削除（メモリ掃除）
for block in bpy.data.meshes:
    if block.users == 0:
        bpy.data.meshes.remove(block)
for block in bpy.data.materials:
    if block.users == 0:
        bpy.data.materials.remove(block)
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("execute_code", {"code": reset_code})
        return f"Scene reset complete. {result.get('result', '')}"
    except Exception as e:
        logger.error(f"Error resetting scene: {str(e)}")
        return f"Error resetting scene: {str(e)}"

@mcp.tool()
def save_experiment_screenshot(ctx: Context, run_id: str) -> str:
    """
    実験記録用に現在のビューポートのスクリーンショットを保存します。
    
    Parameters:
    - run_id: 実験のID（例: "run_001"）。これがファイル名になります。
    """
    try:
        blender = get_blender_connection()
        
        # 保存先のパスを決定（絶対パスにするのが安全）
        filename = f"{run_id}.png"
        filepath = IMAGES_DIR / filename
        absolute_path = str(filepath.resolve())
        
        # Blenderに撮影命令を送る
        result = blender.send_command("get_viewport_screenshot", {
            "max_size": 1024, 
            "filepath": absolute_path,
            "format": "png"
        })
        
        if "error" in result:
            raise Exception(result["error"])
            
        return f"Screenshot saved to: {absolute_path}"
        
    except Exception as e:
        logger.error(f"Error saving experiment screenshot: {str(e)}")
        return f"Error saving screenshot: {str(e)}"

@mcp.tool()
def log_experiment_result(
    ctx: Context, 
    run_id: str, 
    prompt: str, 
    code: str, 
    status: str = "success"
) -> str:
    """
    実験の1試行の結果をJSONLファイルに記録します。
    
    Parameters:
    - run_id: 実験ID (例: "run_001")
    - prompt: 与えられたタスクの指示文
    - code: 生成・実行したPythonコード
    - status: 実行が成功したかどうか ("success" or "error")
    """
    try:
        # 画像パス
        image_path = str((IMAGES_DIR / f"{run_id}.png").resolve())
        
        log_entry = {
            "id": run_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "prompt": prompt,
            "generated_code": code,
            "execution_status": status,
            "image_path": image_path,
            "human_eval": {
                "score": None,
                "tags": [],
                "comment": ""
            }
        }
        
        # JSONLに追記
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            
        return f"Logged experiment {run_id} successfully to {LOG_FILE_PATH}"
        
    except Exception as e:
        logger.error(f"Error logging experiment: {str(e)}")
        return f"Error logging: {str(e)}"